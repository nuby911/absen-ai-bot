from io import BytesIO
import logging
from pathlib import Path

from fastapi import FastAPI
import httpx
import numpy as np
from PIL import Image
import pytest
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEFAULT_JWT_SECRET, Settings, get_settings
from app.database import create_engine_and_session, get_db
from app.main import create_app
from app.models import FaceEmbedding, Parent, SchoolClass, Student, User
from app.providers.face_engine import (
    DeterministicFaceEngine,
    FaceExtractionResult,
    FaceValidationError,
    InsightFaceEngine,
    cosine_similarity,
    create_face_engine,
)
from app.routers.admin import get_active_face_threshold
from app.security import hash_secret


def _make_textured_png(seed: int = 1, size: tuple[int, int] = (128, 128)) -> bytes:
    """Create a deterministic high-contrast RGB PNG image for face-upload tests."""
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, size=(size[1], size[0], 3), dtype=np.uint8)
    buf = BytesIO()
    Image.fromarray(arr, mode="RGB").save(buf, format="PNG")
    return buf.getvalue()


def _make_blank_png(size: tuple[int, int] = (128, 128)) -> bytes:
    """Create a uniform low-contrast PNG image that must fail quality validation."""
    arr = np.full((size[1], size[0], 3), 128, dtype=np.uint8)
    buf = BytesIO()
    Image.fromarray(arr, mode="RGB").save(buf, format="PNG")
    return buf.getvalue()


def _make_app_client(
    db_session: AsyncSession,
    settings: Settings,
    face_engine: object | None = None,
) -> tuple[FastAPI, httpx.AsyncClient]:
    """Create an isolated FastAPI app + AsyncClient with custom settings/face engine."""
    app = create_app(settings=settings, face_engine=face_engine)

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_settings] = lambda: settings
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return app, client


async def test_admin_crud_master_data_and_parent_phone_normalization(
    client: httpx.AsyncClient,
    seeded_teacher: User,
    admin_headers: dict[str, str],
    teacher_headers: dict[str, str],
) -> None:
    # Teacher cannot mutate admin master data or access admin-only endpoints
    forbidden_class = await client.post(
        "/api/v1/classes",
        headers=teacher_headers,
        json={"name": "XI IPA 9"},
    )
    assert forbidden_class.status_code == 403

    forbidden_parents = await client.get("/api/v1/parents", headers=teacher_headers)
    assert forbidden_parents.status_code == 403

    # Teachers CAN read students (for General Gate manual attendance picker), but cannot mutate
    teacher_students_ok = await client.get("/api/v1/students", headers=teacher_headers)
    assert teacher_students_ok.status_code == 200

    forbidden_student_create = await client.post(
        "/api/v1/students",
        headers=teacher_headers,
        json={
            "nis": "9999",
            "name": "Blocked",
            "class_id": "any",
            "parent_name": "Parent",
            "parent_phone_wa": "081234567890",
        },
    )
    assert forbidden_student_create.status_code == 403

    # 1. Create & update class
    create_class_res = await client.post(
        "/api/v1/classes",
        headers=admin_headers,
        json={"name": "XI IPA 1", "homeroom_teacher_id": seeded_teacher.id},
    )
    assert create_class_res.status_code == 201
    class_data = create_class_res.json()
    assert class_data["name"] == "XI IPA 1"
    assert class_data["homeroom_teacher_id"] == seeded_teacher.id
    class_id = class_data["id"]

    # Teacher CAN read classes list for mobile class picker
    teacher_classes_res = await client.get("/api/v1/classes", headers=teacher_headers)
    assert teacher_classes_res.status_code == 200
    assert any(c["id"] == class_id for c in teacher_classes_res.json())

    update_class_res = await client.put(
        f"/api/v1/classes/{class_id}",
        headers=admin_headers,
        json={"name": "XI IPA 1 Unggulan"},
    )
    assert update_class_res.status_code == 200
    assert update_class_res.json()["name"] == "XI IPA 1 Unggulan"

    # 2. Create parent with hyphenated 08xx phone -> stored as 628...
    bad_parent_res = await client.post(
        "/api/v1/parents",
        headers=admin_headers,
        json={"name": "Ibu Invalid", "phone_wa": "abc-123"},
    )
    assert bad_parent_res.status_code == 422

    create_parent_res = await client.post(
        "/api/v1/parents",
        headers=admin_headers,
        json={"name": "Bapak Ahmad", "phone_wa": "0812-7900-1234"},
    )
    assert create_parent_res.status_code == 201
    parent_data = create_parent_res.json()
    assert parent_data["phone_wa"] == "6281279001234"
    parent_id = parent_data["id"]

    # Duplicate normalized WA number must return 409
    dup_parent_res = await client.post(
        "/api/v1/parents",
        headers=admin_headers,
        json={"name": "Duplikat WA", "phone_wa": "+62 812 7900 1234"},
    )
    assert dup_parent_res.status_code == 409

    update_parent_res = await client.put(
        f"/api/v1/parents/{parent_id}",
        headers=admin_headers,
        json={"name": "Bapak Ahmad Updated", "phone_wa": "0813-7900-5678"},
    )
    assert update_parent_res.status_code == 200
    assert update_parent_res.json()["phone_wa"] == "6281379005678"

    # Invalid phone on PUT -> 422; duplicate phone on PUT -> 409
    bad_put_parent = await client.put(
        f"/api/v1/parents/{parent_id}",
        headers=admin_headers,
        json={"phone_wa": "0812"},
    )
    assert bad_put_parent.status_code == 422

    other_parent = await client.post(
        "/api/v1/parents",
        headers=admin_headers,
        json={"name": "Ibu Lain", "phone_wa": "0815-1111-2222"},
    )
    assert other_parent.status_code == 201
    dup_put_parent = await client.put(
        f"/api/v1/parents/{other_parent.json()['id']}",
        headers=admin_headers,
        json={"phone_wa": "6281379005678"},
    )
    assert dup_put_parent.status_code == 409
    assert (
        await client.delete(
            f"/api/v1/parents/{other_parent.json()['id']}",
            headers=admin_headers,
        )
    ).status_code == 204

    # 3. Create, list (with ?class_id=), update student
    create_student_res = await client.post(
        "/api/v1/students",
        headers=admin_headers,
        json={
            "nis": "2026101",
            "name": "Rubby Pratama",
            "class_id": class_id,
            "parent_id": parent_id,
        },
    )
    assert create_student_res.status_code == 201
    student_data = create_student_res.json()
    assert student_data["class_name"] == "XI IPA 1 Unggulan"
    assert student_data["parent_name"] == "Bapak Ahmad Updated"
    assert student_data["parent_phone_wa"] == "6281379005678"
    assert student_data["face_count"] == 0
    student_id = student_data["id"]

    list_students_res = await client.get(
        f"/api/v1/students?class_id={class_id}",
        headers=admin_headers,
    )
    assert list_students_res.status_code == 200
    assert len(list_students_res.json()) == 1

    dup_nis_res = await client.post(
        "/api/v1/students",
        headers=admin_headers,
        json={
            "nis": "2026101",
            "name": "Siswa Duplikat",
            "class_id": class_id,
            "parent_id": parent_id,
        },
    )
    assert dup_nis_res.status_code == 409

    update_student_res = await client.put(
        f"/api/v1/students/{student_id}",
        headers=admin_headers,
        json={"name": "Rubby Pratama Putra", "is_active": True},
    )
    assert update_student_res.status_code == 200
    assert update_student_res.json()["name"] == "Rubby Pratama Putra"

    # 4. Create, filter, update schedule + verify teacher read access
    create_sched_res = await client.post(
        "/api/v1/schedules",
        headers=admin_headers,
        json={
            "class_id": class_id,
            "teacher_id": seeded_teacher.id,
            "subject_name": "Pemrograman Mobile",
            "day_of_week": 1,
            "start_time": "07:30:00",
            "end_time": "09:10:00",
            "late_tolerance_minutes": 15,
        },
    )
    assert create_sched_res.status_code == 201
    sched_id = create_sched_res.json()["id"]

    teacher_sched_res = await client.get(
        f"/api/v1/schedules?class_id={class_id}&teacher_id={seeded_teacher.id}&day_of_week=1",
        headers=teacher_headers,
    )
    assert teacher_sched_res.status_code == 200
    assert len(teacher_sched_res.json()) == 1
    assert teacher_sched_res.json()[0]["subject_name"] == "Pemrograman Mobile"

    update_sched_res = await client.put(
        f"/api/v1/schedules/{sched_id}",
        headers=admin_headers,
        json={"subject_name": "Pemrograman Mobile Lanjut", "late_tolerance_minutes": 10},
    )
    assert update_sched_res.status_code == 200
    assert update_sched_res.json()["subject_name"] == "Pemrograman Mobile Lanjut"
    assert update_sched_res.json()["late_tolerance_minutes"] == 10

    # 5. Deleting parent while student still references it -> 409
    blocked_parent_del = await client.delete(
        f"/api/v1/parents/{parent_id}",
        headers=admin_headers,
    )
    assert blocked_parent_del.status_code == 409

    # 6. Clean delete chain: schedule -> student -> parent -> class
    assert (await client.delete(f"/api/v1/schedules/{sched_id}", headers=admin_headers)).status_code == 204
    assert (await client.delete(f"/api/v1/students/{student_id}", headers=admin_headers)).status_code == 204
    assert (await client.delete(f"/api/v1/parents/{parent_id}", headers=admin_headers)).status_code == 204
    assert (await client.delete(f"/api/v1/classes/{class_id}", headers=admin_headers)).status_code == 204


async def test_face_registration_validates_single_face_and_rejects_bad_images(
    db_session: AsyncSession,
    admin_headers: dict[str, str],
    teacher_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    school_class = SchoolClass(name="XII IPA 1")
    parent = Parent(name="Ibu Sari", phone_wa="6281200001111")
    db_session.add_all([school_class, parent])
    await db_session.flush()

    student = Student(
        nis="2026201",
        name="Septi Rahmawati",
        class_id=school_class.id,
        parent_id=parent.id,
    )
    db_session.add(student)
    await db_session.commit()

    upload_dir = tmp_path / "uploads"
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret="test-jwt-secret-key-for-smart-school-2026",
        face_engine_mode="deterministic",
        whatsapp_provider_mode="mock",
        llm_provider_mode="fallback",
        upload_dir=str(upload_dir),
    )

    _, local_client = _make_app_client(db_session, settings, face_engine=DeterministicFaceEngine())
    try:
        # Teacher forbidden on face registration
        teacher_forbidden = await local_client.post(
            f"/api/v1/students/{student.id}/faces",
            headers=teacher_headers,
            files={"file": ("face1.png", _make_textured_png(seed=1), "image/png")},
        )
        assert teacher_forbidden.status_code == 403

        # Valid textured PNG -> 201, 512 floats persisted, quality_score >= 0.5, file written
        res1 = await local_client.post(
            f"/api/v1/students/{student.id}/faces",
            headers=admin_headers,
            files={"file": ("face1.png", _make_textured_png(seed=1), "image/png")},
        )
        assert res1.status_code == 201
        face1_data = res1.json()
        assert face1_data["quality_score"] >= 0.5
        saved_file = upload_dir / face1_data["image_path"]
        assert saved_file.exists()

        persisted_rows = (
            await db_session.scalars(
                select(FaceEmbedding).where(FaceEmbedding.student_id == student.id)
            )
        ).all()
        assert len(persisted_rows) == 1
        assert len(persisted_rows[0].embedding) == 512
        assert all(isinstance(v, float) for v in persisted_rows[0].embedding)

        # Corrupt non-image bytes -> 422, DB count unchanged
        corrupt_res = await local_client.post(
            f"/api/v1/students/{student.id}/faces",
            headers=admin_headers,
            files={"file": ("corrupt.jpg", b"not-an-image-at-all", "image/jpeg")},
        )
        assert corrupt_res.status_code == 422

        # Uniform blank image (low std-dev < 5.0) -> 422, DB count unchanged
        blank_res = await local_client.post(
            f"/api/v1/students/{student.id}/faces",
            headers=admin_headers,
            files={"file": ("blank.png", _make_blank_png(), "image/png")},
        )
        assert blank_res.status_code == 422

        # Too small (< 64x64) -> 422
        tiny_res = await local_client.post(
            f"/api/v1/students/{student.id}/faces",
            headers=admin_headers,
            files={"file": ("tiny.png", _make_textured_png(seed=2, size=(32, 32)), "image/png")},
        )
        assert tiny_res.status_code == 422

        count_after_rejects = len(
            (
                await db_session.scalars(
                    select(FaceEmbedding).where(FaceEmbedding.student_id == student.id)
                )
            ).all()
        )
        assert count_after_rejects == 1

        # Upload 4 more valid faces (total 5) then verify 6th is rejected with 400
        for idx in range(2, 6):
            ok_res = await local_client.post(
                f"/api/v1/students/{student.id}/faces",
                headers=admin_headers,
                files={"file": (f"face{idx}.png", _make_textured_png(seed=idx), "image/png")},
            )
            assert ok_res.status_code == 201

        sixth_res = await local_client.post(
            f"/api/v1/students/{student.id}/faces",
            headers=admin_headers,
            files={"file": ("face6.png", _make_textured_png(seed=6), "image/png")},
        )
        assert sixth_res.status_code == 400

        list_faces_res = await local_client.get(
            f"/api/v1/students/{student.id}/faces",
            headers=admin_headers,
        )
        assert list_faces_res.status_code == 200
        assert len(list_faces_res.json()) == 5

        # Delete first face -> 204, DB count decrements and file removed from disk
        del_res = await local_client.delete(
            f"/api/v1/students/{student.id}/faces/{face1_data['id']}",
            headers=admin_headers,
        )
        assert del_res.status_code == 204
        assert not saved_file.exists()

        remaining_faces = (
            await db_session.scalars(
                select(FaceEmbedding).where(FaceEmbedding.student_id == student.id)
            )
        ).all()
        assert len(remaining_faces) == 4
    finally:
        await local_client.aclose()

    # Custom mock engine returning face_count=0, face_count=2, or low quality_score -> 422
    class _FixedResultEngine:
        def __init__(self, face_count: int, quality_score: float = 0.92) -> None:
            self.face_count = face_count
            self.quality_score = quality_score

        def extract_single_face(self, image_bytes: bytes) -> FaceExtractionResult:
            return FaceExtractionResult(
                embedding=[0.01] * 512,
                quality_score=self.quality_score,
                face_count=self.face_count,
            )

    for invalid_count, invalid_quality in ((0, 0.92), (2, 0.92), (1, 0.35)):
        _, mock_client = _make_app_client(
            db_session,
            settings,
            face_engine=_FixedResultEngine(invalid_count, invalid_quality),
        )
        try:
            res = await mock_client.post(
                f"/api/v1/students/{student.id}/faces",
                headers=admin_headers,
                files={"file": ("mock.png", _make_textured_png(seed=9), "image/png")},
            )
            assert res.status_code == 422
        finally:
            await mock_client.aclose()

    final_rows = (
        await db_session.scalars(
            select(FaceEmbedding).where(FaceEmbedding.student_id == student.id)
        )
    ).all()
    assert len(final_rows) == 4


async def test_face_threshold_setting_default_and_update(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin_headers: dict[str, str],
    teacher_headers: dict[str, str],
) -> None:
    forbidden = await client.get("/api/v1/settings/face-threshold", headers=teacher_headers)
    assert forbidden.status_code == 403

    get_default = await client.get("/api/v1/settings/face-threshold", headers=admin_headers)
    assert get_default.status_code == 200
    assert get_default.json() == {"threshold": pytest.approx(0.55)}

    put_res = await client.put(
        "/api/v1/settings/face-threshold",
        headers=admin_headers,
        json={"threshold": 0.62},
    )
    assert put_res.status_code == 200
    assert put_res.json() == {"threshold": pytest.approx(0.62)}

    get_updated = await client.get("/api/v1/settings/face-threshold", headers=admin_headers)
    assert get_updated.status_code == 200
    assert get_updated.json() == {"threshold": pytest.approx(0.62)}
    assert await get_active_face_threshold(db_session) == pytest.approx(0.62)

    invalid_high = await client.put(
        "/api/v1/settings/face-threshold",
        headers=admin_headers,
        json={"threshold": 1.5},
    )
    assert invalid_high.status_code == 422

    invalid_low = await client.put(
        "/api/v1/settings/face-threshold",
        headers=admin_headers,
        json={"threshold": 0.1},
    )
    assert invalid_low.status_code == 422


def test_cosine_similarity_properties() -> None:
    vec = [1.0, 2.0, -3.0, 4.0]
    assert cosine_similarity(vec, vec) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]) == pytest.approx(0.0)
    assert cosine_similarity([0.0, 0.0, 0.0], [1.0, 2.0, 3.0]) == 0.0
    assert cosine_similarity([], []) == 0.0

    # DeterministicFaceEngine produces high similarity for same image and low for distinct
    engine = DeterministicFaceEngine()
    img_a = _make_textured_png(seed=11)
    img_b = _make_textured_png(seed=99)
    emb_a1 = engine.extract_single_face(img_a).embedding
    emb_a2 = engine.extract_single_face(img_a).embedding
    emb_b = engine.extract_single_face(img_b).embedding

    assert len(emb_a1) == 512
    assert cosine_similarity(emb_a1, emb_a2) == pytest.approx(1.0)
    assert cosine_similarity(emb_a1, emb_b) < 0.45

    with Image.open(BytesIO(img_a)) as pil_img:
        jpg_buf = BytesIO()
        pil_img.save(jpg_buf, format="JPEG", quality=85)
        img_a_jpg = jpg_buf.getvalue()
    emb_a_jpg = engine.extract_single_face(img_a_jpg).embedding
    assert cosine_similarity(emb_a1, emb_a_jpg) > 0.90


def test_face_engine_factory_and_insightface_validation(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.providers.face_engine as face_engine_mod

    det_settings = Settings(face_engine_mode="deterministic")
    assert isinstance(create_face_engine(det_settings), DeterministicFaceEngine)

    ins_settings = Settings(face_engine_mode="insightface")
    assert isinstance(create_face_engine(ins_settings), InsightFaceEngine)

    monkeypatch.setattr(face_engine_mod, "_insightface_available", lambda: False)
    with caplog.at_level(logging.WARNING, logger="app.providers.face_engine"):
        auto_engine = create_face_engine(Settings(face_engine_mode="auto"))
    assert isinstance(auto_engine, DeterministicFaceEngine)
    assert any("DeterministicFaceEngine" in record.message for record in caplog.records)

    with pytest.raises(ValueError):
        create_face_engine(Settings(face_engine_mode="invalid-mode"))

    class _FakeFace:
        def __init__(self, det_score: float, embedding: np.ndarray) -> None:
            self.det_score = det_score
            self.normed_embedding = embedding

    class _FakeApp:
        def __init__(self, faces: list[object]) -> None:
            self._faces = faces

        def get(self, _bgr: np.ndarray) -> list[object]:
            return self._faces

    sample_png = _make_textured_png(seed=5)
    raw_vec = np.ones(512, dtype=np.float32)

    eng_zero = InsightFaceEngine()
    eng_zero._face_app = _FakeApp([])
    with pytest.raises(FaceValidationError):
        eng_zero.extract_single_face(sample_png)

    eng_two = InsightFaceEngine()
    eng_two._face_app = _FakeApp([_FakeFace(0.9, raw_vec), _FakeFace(0.85, raw_vec)])
    with pytest.raises(FaceValidationError):
        eng_two.extract_single_face(sample_png)

    eng_low = InsightFaceEngine()
    eng_low._face_app = _FakeApp([_FakeFace(0.3, raw_vec)])
    with pytest.raises(FaceValidationError):
        eng_low.extract_single_face(sample_png)

    eng_ok = InsightFaceEngine()
    eng_ok._face_app = _FakeApp([_FakeFace(0.88, raw_vec)])
    result = eng_ok.extract_single_face(sample_png)
    assert result.face_count == 1
    assert result.quality_score == pytest.approx(0.88)
    assert len(result.embedding) == 512
    assert cosine_similarity(result.embedding, result.embedding) == pytest.approx(1.0)


async def test_uploads_static_mount_serves_registered_face(
    db_session: AsyncSession,
    admin_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    school_class = SchoolClass(name="X IPA 2")
    parent = Parent(name="Ibu Lina", phone_wa="6281233334444")
    db_session.add_all([school_class, parent])
    await db_session.flush()

    student = Student(
        nis="2026301",
        name="Dewi Lestari",
        class_id=school_class.id,
        parent_id=parent.id,
    )
    db_session.add(student)
    await db_session.commit()

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret="test-jwt-secret-key-for-smart-school-2026",
        face_engine_mode="deterministic",
        upload_dir=str(upload_dir),
    )
    _, local_client = _make_app_client(db_session, settings)
    try:
        img_bytes = _make_textured_png(seed=7)
        upload_res = await local_client.post(
            f"/api/v1/students/{student.id}/faces",
            headers=admin_headers,
            files={"file": ("face.png", img_bytes, "image/png")},
        )
        assert upload_res.status_code == 201
        image_url = upload_res.json()["image_url"]
        static_res = await local_client.get(image_url)
        assert static_res.status_code == 200
        assert static_res.content[:2] == b"\xff\xd8"
        with Image.open(BytesIO(static_res.content)) as stored_img:
            assert stored_img.format == "JPEG"
            assert stored_img.size == (128, 128)
            assert len(stored_img.getexif()) == 0
    finally:
        await local_client.aclose()


async def test_decompression_bomb_error_converted_to_validation_error_and_422(
    db_session: AsyncSession,
    admin_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DecompressionBombError from Pillow must raise FaceValidationError -> HTTP 422."""
    school_class = SchoolClass(name="XI IPA 3")
    parent = Parent(name="Bapak Bomb", phone_wa="6281299990001")
    db_session.add_all([school_class, parent])
    await db_session.flush()

    student = Student(
        nis="2026401",
        name="Uji Bom Piksel",
        class_id=school_class.id,
        parent_id=parent.id,
    )
    db_session.add(student)
    await db_session.commit()

    sample_png = _make_textured_png(seed=42, size=(128, 128))
    # 128 * 128 = 16,384 pixels > 2 * 100 triggers Pillow's DecompressionBombError directly
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    engine = DeterministicFaceEngine()
    with pytest.raises(FaceValidationError):
        engine.extract_single_face(sample_png)

    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret="test-jwt-secret-key-for-smart-school-2026",
        face_engine_mode="deterministic",
        upload_dir=str(tmp_path / "uploads_bomb"),
    )
    _, local_client = _make_app_client(db_session, settings, face_engine=engine)
    try:
        res = await local_client.post(
            f"/api/v1/students/{student.id}/faces",
            headers=admin_headers,
            files={"file": ("bomb.png", sample_png, "image/png")},
        )
        assert res.status_code == 422
    finally:
        await local_client.aclose()


async def test_list_teachers_endpoint_admin_only_and_ordered(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_admin: User,
    seeded_teacher: User,
    admin_headers: dict[str, str],
    teacher_headers: dict[str, str],
) -> None:
    """GET /api/v1/teachers returns only teachers sorted alphabetically for admins."""
    extra_teacher = User(
        name="Ani Kartika",
        email="ani@sekolah.sch.id",
        password_hash=hash_secret("guru123"),
        role="teacher",
        nip="198501012010012001",
        kiosk_pin_hash=hash_secret("1234"),
    )
    db_session.add(extra_teacher)
    await db_session.commit()

    unauth = await client.get("/api/v1/teachers")
    assert unauth.status_code == 401

    forbidden = await client.get("/api/v1/teachers", headers=teacher_headers)
    assert forbidden.status_code == 403

    res = await client.get("/api/v1/teachers", headers=admin_headers)
    assert res.status_code == 200
    teachers = res.json()
    assert [t["name"] for t in teachers] == ["Ani Kartika", seeded_teacher.name]
    assert all(t["role"] == "teacher" for t in teachers)
    assert all(t["id"] != seeded_admin.id for t in teachers)
    assert teachers[0]["has_kiosk_pin"] is True
    assert teachers[1]["has_kiosk_pin"] is False


async def test_fresh_startup_creates_uploads_tables_cors_and_warns_default_jwt(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Fresh app startup creates upload dir + DB tables, disables CORS credentials, and warns on default JWT."""
    fresh_uploads = tmp_path / "nested" / "uploads"
    fresh_db_path = tmp_path / "fresh_startup.db"
    assert not fresh_uploads.exists()

    default_jwt_settings = Settings(
        database_url=f"sqlite+aiosqlite:///{fresh_db_path.as_posix()}",
        jwt_secret=DEFAULT_JWT_SECRET,
        face_engine_mode="deterministic",
        whatsapp_provider_mode="mock",
        llm_provider_mode="fallback",
        upload_dir=str(fresh_uploads),
    )
    app_default = create_app(settings=default_jwt_settings)
    assert fresh_uploads.exists() and fresh_uploads.is_dir()

    with caplog.at_level(logging.WARNING, logger="app.main"):
        async with app_default.router.lifespan_context(app_default):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app_default),
                base_url="http://test",
            ) as async_client:
                cors_res = await async_client.get(
                    "/health",
                    headers={"Origin": "http://localhost:3001"},
                )
                assert cors_res.status_code == 200
                assert cors_res.headers.get("access-control-allow-origin") == "*"
                assert cors_res.headers.get("access-control-allow-credentials") is None

                # Verify app.state.session_factory is wired and DB-backed endpoints use fresh_startup.db
                assert app_default.state.session_factory is not None
                login_probe = await async_client.post(
                    "/api/v1/auth/login",
                    json={"identifier": "nobody@sekolah.sch.id", "password": "wrong"},
                )
                assert login_probe.status_code == 401

    assert app_default.state.engine is None
    assert app_default.state.session_factory is None
    assert any("JWT_SECRET" in record.message for record in caplog.records)

    # Verify tables were created by lifespan on the fresh SQLite DB file
    engine, _ = create_engine_and_session(default_jwt_settings.database_url)
    try:
        async with engine.connect() as conn:
            table_names = set(
                await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
            )
    finally:
        await engine.dispose()
    assert {"users", "classes", "students", "attendances", "leave_requests"}.issubset(table_names)

    # Custom strong JWT secret must NOT trigger default-secret warning
    caplog.clear()
    custom_jwt_settings = Settings(
        database_url=f"sqlite+aiosqlite:///{fresh_db_path.as_posix()}",
        jwt_secret="super-strong-production-secret-key-2026-xyz",
        face_engine_mode="deterministic",
        whatsapp_provider_mode="mock",
        llm_provider_mode="fallback",
        upload_dir=str(fresh_uploads),
    )
    app_custom = create_app(settings=custom_jwt_settings)
    with caplog.at_level(logging.WARNING, logger="app.main"):
        async with app_custom.router.lifespan_context(app_custom):
            pass
    assert not any("JWT_SECRET" in record.message for record in caplog.records)


async def test_inline_parent_creation_reuse_and_update_on_students(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """POST/PUT /students supports inline parent create, reuse by WA phone, and inline edit."""
    cls_res = await client.post(
        "/api/v1/classes",
        headers=admin_headers,
        json={"name": "XI IPA Inline", "homeroom_teacher_id": ""},
    )
    assert cls_res.status_code == 201
    class_id = cls_res.json()["id"]
    assert cls_res.json()["homeroom_teacher_id"] is None

    # Missing both parent_id and inline parent fields -> 422
    missing_parent = await client.post(
        "/api/v1/students",
        headers=admin_headers,
        json={"nis": "2026900", "name": "Tanpa Ortu", "class_id": class_id},
    )
    assert missing_parent.status_code == 422

    # 1. Create student with inline parent_name + parent_phone_wa -> creates Parent automatically
    stu1_res = await client.post(
        "/api/v1/students",
        headers=admin_headers,
        json={
            "nis": "2026901",
            "name": "Anak Pertama",
            "class_id": class_id,
            "parent_name": "Bapak Inline",
            "parent_phone_wa": "0812-8800-1111",
        },
    )
    assert stu1_res.status_code == 201
    stu1 = stu1_res.json()
    assert stu1["parent_name"] == "Bapak Inline"
    assert stu1["parent_phone_wa"] == "6281288001111"
    assert stu1["created_at"].endswith("Z")

    # 2. Second sibling with same WA phone (different formatting) reuses existing Parent
    stu2_res = await client.post(
        "/api/v1/students",
        headers=admin_headers,
        json={
            "nis": "2026902",
            "name": "Anak Kedua",
            "class_id": class_id,
            "parent_name": "Bapak Inline (Duplikat Nama)",
            "parent_phone_wa": "+62 812 8800 1111",
        },
    )
    assert stu2_res.status_code == 201
    stu2 = stu2_res.json()
    assert stu2["parent_id"] == stu1["parent_id"]
    assert stu2["parent_name"] == "Bapak Inline"

    # 3. PUT with update_linked_parent=True updates parent's contact inline
    upd_inline = await client.put(
        f"/api/v1/students/{stu1['id']}",
        headers=admin_headers,
        json={
            "parent_name": "Bapak Inline Baru",
            "parent_phone_wa": "0813-8800-2222",
            "update_linked_parent": True,
        },
    )
    assert upd_inline.status_code == 200
    assert upd_inline.json()["parent_id"] == stu1["parent_id"]
    assert upd_inline.json()["parent_name"] == "Bapak Inline Baru"
    assert upd_inline.json()["parent_phone_wa"] == "6281388002222"

    # 4. PUT with update_linked_parent=False + new phone creates & links a new Parent
    switch_parent = await client.put(
        f"/api/v1/students/{stu2['id']}",
        headers=admin_headers,
        json={
            "parent_name": "Ibu Wali Baru",
            "parent_phone_wa": "0815-8800-3333",
            "update_linked_parent": False,
        },
    )
    assert switch_parent.status_code == 200
    assert switch_parent.json()["parent_id"] != stu1["parent_id"]
    assert switch_parent.json()["parent_name"] == "Ibu Wali Baru"
    assert switch_parent.json()["parent_phone_wa"] == "6281588003333"

    # 5. PUT update_linked_parent=True with conflicting WA phone -> 409
    conflict_phone = await client.put(
        f"/api/v1/students/{stu1['id']}",
        headers=admin_headers,
        json={
            "parent_phone_wa": "0815-8800-3333",
            "update_linked_parent": True,
        },
    )
    assert conflict_phone.status_code == 409
    assert "whatsapp" in conflict_phone.json()["detail"].lower()


async def test_teacher_crud_and_class_schedule_integrity_guards(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    teacher_headers: dict[str, str],
) -> None:
    """Admin can create/update/delete teachers; classes & schedules enforce uniqueness/overlap."""
    # Teacher forbidden from creating teachers
    assert (
        await client.post(
            "/api/v1/teachers",
            headers=teacher_headers,
            json={
                "name": "Unauthorized",
                "email": "unauth@sekolah.sch.id",
                "password": "password123",
            },
        )
    ).status_code == 403

    # Create teacher with uppercase email & blank NIP -> normalized lowercase & None
    create_t = await client.post(
        "/api/v1/teachers",
        headers=admin_headers,
        json={
            "name": "Ibu Rina",
            "email": "RINA.SARI@Sekolah.SCH.ID",
            "password": "password123",
            "nip": "   ",
            "kiosk_pin": "2468",
        },
    )
    assert create_t.status_code == 201
    t_data = create_t.json()
    assert t_data["email"] == "rina.sari@sekolah.sch.id"
    assert t_data["nip"] is None
    assert t_data["has_kiosk_pin"] is True
    teacher_id = t_data["id"]

    # Duplicate email (case-insensitive) -> 409
    dup_email = await client.post(
        "/api/v1/teachers",
        headers=admin_headers,
        json={
            "name": "Dup Email",
            "email": "rina.sari@sekolah.sch.id",
            "password": "password123",
        },
    )
    assert dup_email.status_code == 409

    # Update teacher with NIP & reset_kiosk_pin
    upd_t = await client.put(
        f"/api/v1/teachers/{teacher_id}",
        headers=admin_headers,
        json={
            "name": "Ibu Rina Sari, S.Pd",
            "nip": "199101012018012009",
            "reset_kiosk_pin": True,
        },
    )
    assert upd_t.status_code == 200
    assert upd_t.json()["nip"] == "199101012018012009"
    assert upd_t.json()["has_kiosk_pin"] is False

    # Duplicate NIP -> 409
    dup_nip = await client.post(
        "/api/v1/teachers",
        headers=admin_headers,
        json={
            "name": "Dup NIP",
            "email": "dupnip@sekolah.sch.id",
            "password": "password123",
            "nip": "199101012018012009",
        },
    )
    assert dup_nip.status_code == 409

    # Assign teacher as homeroom of a class, also verify case-insensitive unique class name
    cls1 = (
        await client.post(
            "/api/v1/classes",
            headers=admin_headers,
            json={"name": "X IPA 9", "homeroom_teacher_id": teacher_id},
        )
    ).json()
    dup_cls = await client.post(
        "/api/v1/classes",
        headers=admin_headers,
        json={"name": "x ipa 9"},
    )
    assert dup_cls.status_code == 409

    cls2 = (
        await client.post(
            "/api/v1/classes",
            headers=admin_headers,
            json={"name": "X IPA 10"},
        )
    ).json()

    # Inactive student should NOT be counted in GET /classes student_count
    await client.post(
        "/api/v1/students",
        headers=admin_headers,
        json={
            "nis": "2026950",
            "name": "Aktif",
            "class_id": cls1["id"],
            "parent_name": "Ortu Aktif",
            "parent_phone_wa": "081299110001",
            "is_active": True,
        },
    )
    await client.post(
        "/api/v1/students",
        headers=admin_headers,
        json={
            "nis": "2026951",
            "name": "Nonaktif",
            "class_id": cls1["id"],
            "parent_name": "Ortu Nonaktif",
            "parent_phone_wa": "081299110002",
            "is_active": False,
        },
    )
    classes_list = (await client.get("/api/v1/classes", headers=admin_headers)).json()
    cls1_info = next(c for c in classes_list if c["id"] == cls1["id"])
    assert cls1_info["student_count"] == 1

    # Schedule overlap guard: same class overlap -> 409, same teacher overlap -> 409, back-to-back -> 201
    sched1 = await client.post(
        "/api/v1/schedules",
        headers=admin_headers,
        json={
            "class_id": cls1["id"],
            "teacher_id": teacher_id,
            "subject_name": "Fisika",
            "day_of_week": 2,
            "start_time": "08:00:00",
            "end_time": "09:30:00",
        },
    )
    assert sched1.status_code == 201
    sched1_id = sched1.json()["id"]

    overlap_teacher = await client.post(
        "/api/v1/schedules",
        headers=admin_headers,
        json={
            "class_id": cls2["id"],
            "teacher_id": teacher_id,
            "subject_name": "Kimia",
            "day_of_week": 2,
            "start_time": "09:00:00",
            "end_time": "10:30:00",
        },
    )
    assert overlap_teacher.status_code == 409

    back_to_back = await client.post(
        "/api/v1/schedules",
        headers=admin_headers,
        json={
            "class_id": cls1["id"],
            "teacher_id": teacher_id,
            "subject_name": "Biologi",
            "day_of_week": 2,
            "start_time": "09:30:00",
            "end_time": "11:00:00",
        },
    )
    assert back_to_back.status_code == 201
    sched2_id = back_to_back.json()["id"]

    # Deleting teacher while referenced by schedule -> 409
    blocked_del = await client.delete(f"/api/v1/teachers/{teacher_id}", headers=admin_headers)
    assert blocked_del.status_code == 409

    # Remove schedules -> deleting teacher succeeds & clears homeroom_teacher_id on cls1
    assert (await client.delete(f"/api/v1/schedules/{sched1_id}", headers=admin_headers)).status_code == 204
    assert (await client.delete(f"/api/v1/schedules/{sched2_id}", headers=admin_headers)).status_code == 204
    assert (await client.delete(f"/api/v1/teachers/{teacher_id}", headers=admin_headers)).status_code == 204

    classes_after = (await client.get("/api/v1/classes", headers=admin_headers)).json()
    cls1_after = next(c for c in classes_after if c["id"] == cls1["id"])
    assert cls1_after["homeroom_teacher_id"] is None


async def test_exif_transposition_disallowed_format_oversized_413_and_telemetry_delete(
    db_session: AsyncSession,
    admin_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify EXIF orientation transpose, format allowlist, 413 oversized upload, and safe deletes."""
    from app.models import ChatbotLog, FaceRecognitionLog
    from app.routers.admin import _delete_upload_file_if_exists

    # 1. EXIF orientation=6 (90° CW stored rotated) must produce same embedding as upright image
    rng = np.random.default_rng(77)
    upright_arr = rng.integers(0, 256, size=(120, 80, 3), dtype=np.uint8)
    # Add asymmetric gradient so 90° rotation changes image dramatically
    upright_arr[:60, :, 0] = 240
    upright_arr[60:, :, 2] = 240
    upright_img = Image.fromarray(upright_arr, mode="RGB")

    upright_buf = BytesIO()
    upright_img.save(upright_buf, format="JPEG", quality=95)
    upright_bytes = upright_buf.getvalue()

    # Rotate 90° CCW so applying EXIF Orientation=6 (rotate 90° CW) restores upright_img
    rotated_raw = upright_img.transpose(Image.Transpose.ROTATE_90)
    exif = Image.Exif()
    exif[274] = 6  # Orientation tag = Rotate 90 CW
    exif_buf = BytesIO()
    rotated_raw.save(exif_buf, format="JPEG", quality=95, exif=exif)
    exif_bytes = exif_buf.getvalue()

    engine = DeterministicFaceEngine()
    emb_upright = engine.extract_single_face(upright_bytes).embedding
    emb_exif = engine.extract_single_face(exif_bytes).embedding
    assert cosine_similarity(emb_upright, emb_exif) > 0.95

    # 2. Disallowed image format (BMP) -> FaceValidationError
    bmp_buf = BytesIO()
    upright_img.save(bmp_buf, format="BMP")
    with pytest.raises(FaceValidationError):
        engine.extract_single_face(bmp_buf.getvalue())

    # 3. Oversized upload (> MAX_FACE_IMAGE_BYTES) -> HTTP 413
    school_class = SchoolClass(name="XII Upload Test")
    parent = Parent(name="Ortu Upload", phone_wa="6281277001122")
    db_session.add_all([school_class, parent])
    await db_session.flush()
    student = Student(
        nis="2026888",
        name="Siswa Upload",
        class_id=school_class.id,
        parent_id=parent.id,
    )
    db_session.add(student)
    await db_session.flush()

    # Add telemetry logs referencing student and parent to verify delete still succeeds
    db_session.add(
        FaceRecognitionLog(
            predicted_student_id=student.id,
            actual_student_id=student.id,
            top_similarity_score=0.9,
            threshold_used=0.55,
            liveness_passed=True,
            is_match=True,
            latency_ms=50,
        )
    )
    db_session.add(
        ChatbotLog(
            parent_id=parent.id,
            phone_wa=parent.phone_wa,
            user_message="Halo",
            bot_response="Hai",
            is_in_domain=True,
            is_fallback=False,
            latency_ms=10,
        )
    )
    await db_session.commit()

    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret="test-jwt-secret-key-for-smart-school-2026",
        face_engine_mode="deterministic",
        upload_dir=str(tmp_path / "uploads_413"),
    )
    _, local_client = _make_app_client(db_session, settings, face_engine=engine)
    try:
        # Temporarily shrink max bytes in admin module to test streaming 413 quickly
        import app.routers.admin as admin_mod

        monkeypatch.setattr(admin_mod, "MAX_FACE_IMAGE_BYTES", 1024)
        oversized_res = await local_client.post(
            f"/api/v1/students/{student.id}/faces",
            headers=admin_headers,
            files={"file": ("big.jpg", b"x" * 2048, "image/jpeg")},
        )
        assert oversized_res.status_code == 413

        # Deleting student with FaceRecognitionLog telemetry must succeed (204)
        del_stu = await local_client.delete(
            f"/api/v1/students/{student.id}", headers=admin_headers
        )
        assert del_stu.status_code == 204

        # Deleting parent with ChatbotLog telemetry must succeed (204)
        del_par = await local_client.delete(
            f"/api/v1/parents/{parent.id}", headers=admin_headers
        )
        assert del_par.status_code == 204
    finally:
        await local_client.aclose()

    # 4. _delete_upload_file_if_exists rejects absolute paths & traversal outside upload_dir
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("keep-me", encoding="utf-8")
    _delete_upload_file_if_exists(str(tmp_path / "uploads_413"), str(outside_file))
    _delete_upload_file_if_exists(str(tmp_path / "uploads_413"), "../outside.txt")
    assert outside_file.exists()

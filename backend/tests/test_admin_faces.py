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

    forbidden_students = await client.get("/api/v1/students", headers=teacher_headers)
    assert forbidden_students.status_code == 403

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


def test_face_engine_factory_and_insightface_validation() -> None:
    det_settings = Settings(face_engine_mode="deterministic")
    assert isinstance(create_face_engine(det_settings), DeterministicFaceEngine)

    ins_settings = Settings(face_engine_mode="insightface")
    assert isinstance(create_face_engine(ins_settings), InsightFaceEngine)

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
        assert static_res.content == img_bytes
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

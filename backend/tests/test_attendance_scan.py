from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO

import httpx
import numpy as np
from PIL import Image
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.main import create_app
from app.models import (
    Attendance,
    AttendanceSession,
    FaceEmbedding,
    FaceRecognitionLog,
    LeaveRequest,
    Parent,
    Schedule,
    SchoolClass,
    Student,
    User,
)
from app.providers.face_engine import DeterministicFaceEngine
from app.providers.whatsapp import (
    MockWhatsAppProvider,
    WahaWhatsAppProvider,
    WhatsAppMessage,
    build_attendance_wa_message,
    create_whatsapp_provider,
)

WIB = timezone(timedelta(hours=7))


def _make_textured_png(seed: int, size: tuple[int, int] = (128, 128)) -> bytes:
    """Create a deterministic high-contrast RGB PNG for face recognition tests."""
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, size=(size[1], size[0], 3), dtype=np.uint8)
    buf = BytesIO()
    Image.fromarray(arr, mode="RGB").save(buf, format="PNG")
    return buf.getvalue()


def _to_jpeg(png_bytes: bytes, quality: int = 88) -> bytes:
    """Re-encode PNG bytes as JPEG to simulate live camera frame capture."""
    with Image.open(BytesIO(png_bytes)) as img:
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality)
        return buf.getvalue()


async def _seed_classroom_with_faces(
    db_session: AsyncSession,
) -> dict[str, object]:
    """Seed two classes, three parents, three students, and deterministic face embeddings."""
    engine = DeterministicFaceEngine()

    class_a = SchoolClass(name="XI IPA 1")
    class_b = SchoolClass(name="XI IPA 2")
    parent_a = Parent(name="Bapak Ahmad", phone_wa="6281279001111")
    parent_b = Parent(name="Ibu Siti", phone_wa="6281279002222")
    parent_c = Parent(name="Bapak Hendra", phone_wa="6281279003333")
    db_session.add_all([class_a, class_b, parent_a, parent_b, parent_c])
    await db_session.flush()

    student_a = Student(
        nis="2026101",
        name="Rubby Pratama",
        class_id=class_a.id,
        parent_id=parent_a.id,
        is_active=True,
    )
    student_b = Student(
        nis="2026102",
        name="Deni Saputra",
        class_id=class_a.id,
        parent_id=parent_b.id,
        is_active=True,
    )
    student_c = Student(
        nis="2026103",
        name="Septi Rahmawati",
        class_id=class_b.id,
        parent_id=parent_c.id,
        is_active=True,
    )
    db_session.add_all([student_a, student_b, student_c])
    await db_session.flush()

    png_a = _make_textured_png(seed=11)
    png_b = _make_textured_png(seed=22)
    png_c = _make_textured_png(seed=33)

    db_session.add_all(
        [
            FaceEmbedding(
                student_id=student_a.id,
                image_path="faces/a.jpg",
                embedding=engine.extract_single_face(png_a).embedding,
                quality_score=0.95,
            ),
            FaceEmbedding(
                student_id=student_b.id,
                image_path="faces/b.jpg",
                embedding=engine.extract_single_face(png_b).embedding,
                quality_score=0.95,
            ),
            FaceEmbedding(
                student_id=student_c.id,
                image_path="faces/c.jpg",
                embedding=engine.extract_single_face(png_c).embedding,
                quality_score=0.95,
            ),
        ]
    )
    await db_session.commit()

    return {
        "class_a": class_a,
        "class_b": class_b,
        "parent_a": parent_a,
        "parent_b": parent_b,
        "parent_c": parent_c,
        "student_a": student_a,
        "student_b": student_b,
        "student_c": student_c,
        "png_a": png_a,
        "png_b": png_b,
        "png_c": png_c,
    }


async def test_kiosk_scan_match_triggers_wa_and_prevents_duplicate_wa(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    teacher_headers: dict[str, str],
    admin_headers: dict[str, str],
    mock_wa: MockWhatsAppProvider,
) -> None:
    seeded = await _seed_classroom_with_faces(db_session)
    class_a: SchoolClass = seeded["class_a"]  # type: ignore[assignment]
    parent_a: Parent = seeded["parent_a"]  # type: ignore[assignment]
    student_a: Student = seeded["student_a"]  # type: ignore[assignment]
    png_a: bytes = seeded["png_a"]  # type: ignore[assignment]
    png_c: bytes = seeded["png_c"]  # type: ignore[assignment]

    # Admin is forbidden from teacher session/kiosk endpoints
    forbidden = await client.post(
        "/api/v1/sessions",
        headers=admin_headers,
        json={"class_id": class_a.id, "session_type": "subject"},
    )
    assert forbidden.status_code == 403

    # Open subject session for Class A (no expected_start_time -> present)
    open_res = await client.post(
        "/api/v1/sessions",
        headers=teacher_headers,
        json={"class_id": class_a.id, "session_type": "subject"},
    )
    assert open_res.status_code == 201
    session_id = open_res.json()["id"]
    assert open_res.json()["status"] == "open"

    # 1. First scan for Student A (JPEG re-encoded camera frame)
    scan1 = await client.post(
        "/api/v1/attendance/scan",
        headers=teacher_headers,
        data={
            "session_id": session_id,
            "liveness_passed": "true",
            "condition_note": "jarak_50cm_normal",
        },
        files={"file": ("kiosk.jpg", _to_jpeg(png_a), "image/jpeg")},
    )
    assert scan1.status_code == 200
    data1 = scan1.json()
    assert data1["matched"] is True
    assert data1["already_recorded"] is False
    assert data1["student_id"] == student_a.id
    assert data1["student_name"] == "Rubby Pratama"
    assert data1["nis"] == "2026101"
    assert data1["class_name"] == "XI IPA 1"
    assert data1["status"] == "present"
    assert data1["similarity_score"] >= 0.90
    assert data1["threshold_used"] == pytest.approx(0.55)
    assert data1["wa_status"] == "sent"
    assert data1["wa_queued"] is True

    assert len(mock_wa.sent) == 1
    assert isinstance(mock_wa.sent[0], WhatsAppMessage)
    assert mock_wa.sent[0].phone_wa == parent_a.phone_wa
    assert "Rubby Pratama" in mock_wa.sent[0].text
    assert "Hadir" in mock_wa.sent[0].text

    # 2. Second scan for Student A in the same session -> already_recorded=True, NO duplicate WA
    scan2 = await client.post(
        "/api/v1/attendance/scan",
        headers=teacher_headers,
        data={"session_id": session_id, "liveness_passed": "true"},
        files={"file": ("kiosk2.jpg", _to_jpeg(png_a), "image/jpeg")},
    )
    assert scan2.status_code == 200
    data2 = scan2.json()
    assert data2["matched"] is True
    assert data2["already_recorded"] is True
    assert data2["attendance_id"] == data1["attendance_id"]
    assert data2["wa_status"] == "sent"
    assert data2["wa_queued"] is False
    assert len(mock_wa.sent) == 1

    # 3. Student C from Class B must NOT match inside Class A's subject session
    cross_class_scan = await client.post(
        "/api/v1/attendance/scan",
        headers=teacher_headers,
        data={"session_id": session_id, "liveness_passed": "true"},
        files={"file": ("student_c.png", png_c, "image/png")},
    )
    assert cross_class_scan.status_code == 200
    assert cross_class_scan.json()["matched"] is False

    # 4. Late detection when expected_start_time + tolerance has passed
    # Close the first open session first so duplicate open session guard allows a new one
    assert (
        await client.post(f"/api/v1/sessions/{session_id}/close", headers=teacher_headers)
    ).status_code == 200

    now_wib = datetime.now(WIB)
    if now_wib.hour > 0 or now_wib.minute >= 20:
        past_start = (now_wib - timedelta(minutes=20)).time().replace(microsecond=0)
    else:
        past_start = time(0, 0)
    late_session_res = await client.post(
        "/api/v1/sessions",
        headers=teacher_headers,
        json={
            "class_id": class_a.id,
            "session_type": "subject",
            "expected_start_time": past_start.isoformat(),
            "late_tolerance_minutes": 5 if (now_wib.hour > 0 or now_wib.minute >= 20) else 0,
        },
    )
    assert late_session_res.status_code == 201
    late_scan = await client.post(
        "/api/v1/attendance/scan",
        headers=teacher_headers,
        data={"session_id": late_session_res.json()["id"], "liveness_passed": "true"},
        files={"file": ("late.png", png_a, "image/png")},
    )
    assert late_scan.status_code == 200
    assert late_scan.json()["matched"] is True
    assert late_scan.json()["status"] == "late"
    assert len(mock_wa.sent) == 2
    assert "Terlambat" in mock_wa.sent[1].text

    # 5. Gate session (class_id=None) matches active students across all classes and exposes full roster
    gate_res = await client.post(
        "/api/v1/sessions",
        headers=teacher_headers,
        json={"session_type": "gate_in"},
    )
    assert gate_res.status_code == 201
    gate_id = gate_res.json()["id"]
    assert gate_res.json()["total_students"] == 3
    assert gate_res.json()["unrecorded_count"] == 3

    gate_scan = await client.post(
        "/api/v1/attendance/scan",
        headers=teacher_headers,
        data={"session_id": gate_id, "liveness_passed": "true"},
        files={"file": ("student_c.png", png_c, "image/png")},
    )
    assert gate_scan.status_code == 200
    assert gate_scan.json()["matched"] is True
    assert gate_scan.json()["student_name"] == "Septi Rahmawati"
    assert gate_scan.json()["class_name"] == "XI IPA 2"

    gate_detail = await client.get(f"/api/v1/sessions/{gate_id}", headers=teacher_headers)
    assert gate_detail.status_code == 200
    assert gate_detail.json()["summary"]["total_students"] == 3
    assert gate_detail.json()["summary"]["recorded_count"] == 1
    assert gate_detail.json()["summary"]["unrecorded_count"] == 2
    assert len(gate_detail.json()["students"]) == 3

    gate_close = await client.post(f"/api/v1/sessions/{gate_id}/close", headers=teacher_headers)
    assert gate_close.status_code == 200
    assert gate_close.json()["status"] == "closed"
    assert gate_close.json()["summary"]["present_count"] == 1
    assert gate_close.json()["summary"]["absent_count"] == 2
    assert gate_close.json()["summary"]["unrecorded_count"] == 0


async def test_kiosk_scan_wa_failure_keeps_attendance_and_allows_resend(
    db_session: AsyncSession,
    test_settings: Settings,
    teacher_headers: dict[str, str],
    mock_wa: MockWhatsAppProvider,
    client: httpx.AsyncClient,
) -> None:
    seeded = await _seed_classroom_with_faces(db_session)
    class_a: SchoolClass = seeded["class_a"]  # type: ignore[assignment]
    parent_a: Parent = seeded["parent_a"]  # type: ignore[assignment]
    student_a: Student = seeded["student_a"]  # type: ignore[assignment]
    student_b: Student = seeded["student_b"]  # type: ignore[assignment]
    png_a: bytes = seeded["png_a"]  # type: ignore[assignment]
    png_b: bytes = seeded["png_b"]  # type: ignore[assignment]

    open_res = await client.post(
        "/api/v1/sessions",
        headers=teacher_headers,
        json={"class_id": class_a.id, "session_type": "subject"},
    )
    assert open_res.status_code == 201
    session_id = open_res.json()["id"]

    # Case 1: Provider returns False
    mock_wa.should_fail = True
    scan_fail_res = await client.post(
        "/api/v1/attendance/scan",
        headers=teacher_headers,
        data={"session_id": session_id, "liveness_passed": "true"},
        files={"file": ("a.png", png_a, "image/png")},
    )
    assert scan_fail_res.status_code == 200
    fail_data = scan_fail_res.json()
    assert fail_data["matched"] is True
    assert fail_data["already_recorded"] is False
    assert fail_data["wa_status"] == "failed"
    assert len(mock_wa.sent) == 0

    attendance_row = await db_session.scalar(
        select(Attendance).where(Attendance.id == fail_data["attendance_id"])
    )
    assert attendance_row is not None
    assert attendance_row.student_id == student_a.id
    assert attendance_row.wa_status == "failed"
    assert attendance_row.wa_notified_at is None

    # Resend when gateway recovers
    mock_wa.should_fail = False
    resend_res = await client.post(
        f"/api/v1/attendance/{attendance_row.id}/resend-wa",
        headers=teacher_headers,
    )
    assert resend_res.status_code == 200
    resend_data = resend_res.json()
    assert resend_data["wa_status"] == "sent"
    assert resend_data["wa_sent"] is True
    assert resend_data["wa_notified_at"] is not None
    assert len(mock_wa.sent) == 1
    assert mock_wa.sent[0].phone_wa == parent_a.phone_wa

    await db_session.refresh(attendance_row)
    assert attendance_row.wa_status == "sent"
    assert attendance_row.wa_notified_at is not None

    # Case 2: Provider raises an exception during scan -> 200 & wa_status=="failed"
    class _ExplodingWAProvider:
        async def send_message(self, phone_wa: str, text: str) -> bool:
            raise RuntimeError("WAHA gateway connection refused")

    exploding_app = create_app(
        settings=test_settings,
        whatsapp_provider=_ExplodingWAProvider(),
    )

    async def _override_get_db():
        yield db_session

    exploding_app.dependency_overrides[get_db] = _override_get_db
    exploding_app.dependency_overrides[get_settings] = lambda: test_settings

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=exploding_app),
        base_url="http://test",
    ) as exploding_client:
        scan_exc_res = await exploding_client.post(
            "/api/v1/attendance/scan",
            headers=teacher_headers,
            data={"session_id": session_id, "liveness_passed": "true"},
            files={"file": ("b.png", png_b, "image/png")},
        )
    assert scan_exc_res.status_code == 200
    exc_data = scan_exc_res.json()
    assert exc_data["matched"] is True
    assert exc_data["student_id"] == student_b.id
    assert exc_data["wa_status"] == "failed"

    att_b = await db_session.scalar(
        select(Attendance).where(Attendance.id == exc_data["attendance_id"])
    )
    assert att_b is not None
    assert att_b.wa_status == "failed"


async def test_kiosk_scan_rejects_failed_liveness_and_unrecognized_face(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    teacher_headers: dict[str, str],
    mock_wa: MockWhatsAppProvider,
) -> None:
    seeded = await _seed_classroom_with_faces(db_session)
    class_a: SchoolClass = seeded["class_a"]  # type: ignore[assignment]
    png_a: bytes = seeded["png_a"]  # type: ignore[assignment]

    open_res = await client.post(
        "/api/v1/sessions",
        headers=teacher_headers,
        json={"class_id": class_a.id, "session_type": "subject"},
    )
    session_id = open_res.json()["id"]

    # 1. Failed liveness check -> 400
    liveness_fail = await client.post(
        "/api/v1/attendance/scan",
        headers=teacher_headers,
        data={"session_id": session_id, "liveness_passed": "false"},
        files={"file": ("a.png", png_a, "image/png")},
    )
    assert liveness_fail.status_code == 400
    assert "liveness" in liveness_fail.json()["detail"].lower()

    # 2. Corrupt image -> 422
    corrupt_res = await client.post(
        "/api/v1/attendance/scan",
        headers=teacher_headers,
        data={"session_id": session_id, "liveness_passed": "true"},
        files={"file": ("bad.jpg", b"not-an-image", "image/jpeg")},
    )
    assert corrupt_res.status_code == 422

    # 3. Unrecognized face (distinct texture seed=99) -> 200 matched=False + FaceRecognitionLog
    unknown_png = _make_textured_png(seed=99)
    unrecognized_res = await client.post(
        "/api/v1/attendance/scan",
        headers=teacher_headers,
        data={
            "session_id": session_id,
            "liveness_passed": "true",
            "condition_note": "cahaya_redup",
        },
        files={"file": ("unknown.png", unknown_png, "image/png")},
    )
    assert unrecognized_res.status_code == 200
    unrec_data = unrecognized_res.json()
    assert unrec_data["matched"] is False
    assert unrec_data["already_recorded"] is False
    assert unrec_data["similarity_score"] < unrec_data["threshold_used"]
    assert len(mock_wa.sent) == 0

    logs = (
        await db_session.scalars(
            select(FaceRecognitionLog)
            .where(FaceRecognitionLog.session_id == session_id)
            .order_by(FaceRecognitionLog.created_at.asc(), FaceRecognitionLog.id.asc())
        )
    ).all()
    assert len(logs) == 2
    liveness_log = next(log for log in logs if log.liveness_passed is False)
    assert liveness_log.is_match is False
    assert liveness_log.top_similarity_score == 0.0

    unrec_log = next(log for log in logs if log.liveness_passed is True)
    assert unrec_log.is_match is False
    assert unrec_log.predicted_student_id is None
    assert unrec_log.condition_note == "cahaya_redup"
    assert unrec_log.latency_ms >= 0

    attendances = (
        await db_session.scalars(select(Attendance).where(Attendance.session_id == session_id))
    ).all()
    assert attendances == []

    # 4. Unknown session -> 404
    missing_res = await client.post(
        "/api/v1/attendance/scan",
        headers=teacher_headers,
        data={"session_id": "nonexistent-session-id", "liveness_passed": "true"},
        files={"file": ("a.png", png_a, "image/png")},
    )
    assert missing_res.status_code == 404


async def test_manual_attendance_requires_valid_pin_and_close_session_marks_absent(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    teacher_headers: dict[str, str],
    mock_wa: MockWhatsAppProvider,
) -> None:
    seeded = await _seed_classroom_with_faces(db_session)
    class_a: SchoolClass = seeded["class_a"]  # type: ignore[assignment]
    student_a: Student = seeded["student_a"]  # type: ignore[assignment]
    student_b: Student = seeded["student_b"]  # type: ignore[assignment]
    png_a: bytes = seeded["png_a"]  # type: ignore[assignment]

    open_res = await client.post(
        "/api/v1/sessions",
        headers=teacher_headers,
        json={"class_id": class_a.id, "session_type": "subject"},
    )
    assert open_res.status_code == 201
    session_id = open_res.json()["id"]

    # 1. Manual attendance rejected with 403 before PIN is configured
    no_pin_res = await client.post(
        "/api/v1/attendance/manual",
        headers=teacher_headers,
        json={
            "session_id": session_id,
            "student_id": student_a.id,
            "status": "present",
            "kiosk_pin": "1234",
            "notify_wa": True,
        },
    )
    assert no_pin_res.status_code == 403

    # Configure teacher PIN
    pin_res = await client.put(
        "/api/v1/auth/kiosk-pin",
        headers=teacher_headers,
        json={"pin": "1234"},
    )
    assert pin_res.status_code == 200

    # 2. Wrong PIN rejected with 403
    wrong_pin_res = await client.post(
        "/api/v1/attendance/manual",
        headers=teacher_headers,
        json={
            "session_id": session_id,
            "student_id": student_a.id,
            "status": "present",
            "kiosk_pin": "9999",
            "notify_wa": True,
        },
    )
    assert wrong_pin_res.status_code == 403

    # 3. Valid PIN records manual attendance & notifies WA
    manual_ok = await client.post(
        "/api/v1/attendance/manual",
        headers=teacher_headers,
        json={
            "session_id": session_id,
            "student_id": student_a.id,
            "status": "present",
            "kiosk_pin": "1234",
            "notify_wa": True,
        },
    )
    assert manual_ok.status_code == 201
    assert manual_ok.json()["status"] == "present"
    assert manual_ok.json()["verification_method"] == "manual_teacher"
    assert manual_ok.json()["wa_status"] == "sent"
    assert len(mock_wa.sent) == 1

    # Check session detail before close: Student A present, Student B unrecorded
    detail_before = await client.get(
        f"/api/v1/sessions/{session_id}",
        headers=teacher_headers,
    )
    assert detail_before.status_code == 200
    before_json = detail_before.json()
    assert before_json["summary"]["total_students"] == 2
    assert before_json["summary"]["present_count"] == 1
    assert before_json["summary"]["unrecorded_count"] == 1
    by_student_before = {row["student_id"]: row for row in before_json["students"]}
    assert by_student_before[student_a.id]["status"] == "present"
    assert by_student_before[student_b.id]["status"] == "unrecorded"

    # 4. Close session -> Student B automatically marked absent with wa_status="skipped"
    close_res = await client.post(
        f"/api/v1/sessions/{session_id}/close",
        headers=teacher_headers,
    )
    assert close_res.status_code == 200
    closed_json = close_res.json()
    assert closed_json["status"] == "closed"
    assert closed_json["closed_at"] is not None
    assert closed_json["summary"]["present_count"] == 1
    assert closed_json["summary"]["absent_count"] == 1
    assert closed_json["summary"]["unrecorded_count"] == 0

    by_student_after = {row["student_id"]: row for row in closed_json["students"]}
    assert by_student_after[student_b.id]["status"] == "absent"
    assert by_student_after[student_b.id]["verification_method"] == "manual_teacher"
    assert by_student_after[student_b.id]["wa_status"] == "skipped"
    assert len(mock_wa.sent) == 1

    # 5. Scanning on closed session -> 400; closing twice -> 400
    closed_scan = await client.post(
        "/api/v1/attendance/scan",
        headers=teacher_headers,
        data={"session_id": session_id, "liveness_passed": "true"},
        files={"file": ("a.png", png_a, "image/png")},
    )
    assert closed_scan.status_code == 400

    reclose_res = await client.post(
        f"/api/v1/sessions/{session_id}/close",
        headers=teacher_headers,
    )
    assert reclose_res.status_code == 400

    # 6. Manual attendance on closed session -> 400 with Indonesian error message
    closed_manual = await client.post(
        "/api/v1/attendance/manual",
        headers=teacher_headers,
        json={
            "session_id": session_id,
            "student_id": student_b.id,
            "status": "present",
            "kiosk_pin": "1234",
            "notify_wa": False,
        },
    )
    assert closed_manual.status_code == 400
    assert "ditutup" in closed_manual.json()["detail"].lower()


def test_resolve_scan_status_compares_against_session_date() -> None:
    """_resolve_scan_status must anchor the deadline on session_date, not scan_wib.date()."""
    from app.routers.attendance import _resolve_scan_status

    # Session opened on 2026-11-22 at 07:30 WIB (+15 min tolerance -> deadline 07:45 WIB)
    session_date = date(2026, 11, 22)
    expected_start = time(7, 30)

    # Scan on-time on 2026-11-22 07:45 WIB (00:45 UTC) -> present
    assert (
        _resolve_scan_status(
            session_date,
            expected_start,
            15,
            datetime(2026, 11, 22, 0, 45, tzinfo=timezone.utc),
        )
        == "present"
    )
    # Scan late on 2026-11-22 07:46 WIB (00:46 UTC) -> late
    assert (
        _resolve_scan_status(
            session_date,
            expected_start,
            15,
            datetime(2026, 11, 22, 0, 46, tzinfo=timezone.utc),
        )
        == "late"
    )
    # Scan next morning 2026-11-23 07:00 WIB (00:00 UTC) must STILL be late vs 2026-11-22!
    assert (
        _resolve_scan_status(
            session_date,
            expected_start,
            15,
            datetime(2026, 11, 23, 0, 0, tzinfo=timezone.utc),
        )
        == "late"
    )


async def test_dispatch_attendance_wa_survives_commit_rollback_without_expired_orm_reads(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    teacher_headers: dict[str, str],
    mock_wa: MockWhatsAppProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If DB commit fails inside _dispatch_attendance_wa, callers must not raise MissingGreenlet."""
    seeded = await _seed_classroom_with_faces(db_session)
    class_a: SchoolClass = seeded["class_a"]  # type: ignore[assignment]
    png_a: bytes = seeded["png_a"]  # type: ignore[assignment]

    open_res = await client.post(
        "/api/v1/sessions",
        headers=teacher_headers,
        json={"class_id": class_a.id, "session_type": "subject"},
    )
    assert open_res.status_code == 201
    session_id = open_res.json()["id"]

    # First commit inside scan_kiosk_face saves attendance; second commit inside _dispatch_attendance_wa fails
    original_commit = db_session.commit
    commit_calls = 0

    async def _flaky_commit() -> None:
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 2:
            raise RuntimeError("Simulated DB commit failure on wa_status update")
        await original_commit()

    monkeypatch.setattr(db_session, "commit", _flaky_commit)

    scan_res = await client.post(
        "/api/v1/attendance/scan",
        headers=teacher_headers,
        data={"session_id": session_id, "liveness_passed": "true"},
        files={"file": ("a.png", png_a, "image/png")},
    )
    assert scan_res.status_code == 200
    body = scan_res.json()
    assert body["matched"] is True
    assert body["student_name"] == "Rubby Pratama"
    assert body["wa_status"] == "sent"
    assert len(mock_wa.sent) == 1


async def test_teacher_dashboard_returns_today_sessions_and_stats(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_teacher: User,
    teacher_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    seeded = await _seed_classroom_with_faces(db_session)
    class_a: SchoolClass = seeded["class_a"]  # type: ignore[assignment]
    parent_a: Parent = seeded["parent_a"]  # type: ignore[assignment]
    parent_b: Parent = seeded["parent_b"]  # type: ignore[assignment]
    student_a: Student = seeded["student_a"]  # type: ignore[assignment]
    student_b: Student = seeded["student_b"]  # type: ignore[assignment]

    today = datetime.now(WIB).date()
    today_dow = today.isoweekday()
    other_dow = 1 if today_dow != 1 else 2

    sched_today = Schedule(
        class_id=class_a.id,
        teacher_id=seeded_teacher.id,
        subject_name="Pemrograman Mobile",
        day_of_week=today_dow,
        start_time=time(7, 30),
        end_time=time(9, 10),
        late_tolerance_minutes=15,
    )
    sched_other = Schedule(
        class_id=class_a.id,
        teacher_id=seeded_teacher.id,
        subject_name="Basis Data",
        day_of_week=other_dow,
        start_time=time(10, 0),
        end_time=time(11, 40),
        late_tolerance_minutes=15,
    )
    leave_pending = LeaveRequest(
        student_id=student_a.id,
        parent_id=parent_a.id,
        request_type="sick",
        start_date=today,
        end_date=today,
        reason="Demam",
        status="pending",
    )
    leave_approved = LeaveRequest(
        student_id=seeded["student_c"].id,  # type: ignore[union-attr]
        parent_id=seeded["parent_c"].id,  # type: ignore[union-attr]
        request_type="permit",
        start_date=today,
        end_date=today,
        reason="Lomba",
        status="approved",
    )
    db_session.add_all([sched_today, sched_other, leave_pending, leave_approved])
    await db_session.commit()

    # Open session linked to today's schedule
    session_res = await client.post(
        "/api/v1/sessions",
        headers=teacher_headers,
        json={"schedule_id": sched_today.id, "session_type": "subject"},
    )
    assert session_res.status_code == 201
    session_id = session_res.json()["id"]
    assert session_res.json()["class_id"] == class_a.id
    assert session_res.json()["subject_name"] == "Pemrograman Mobile"

    # Seed 1 present + 1 late in today's session
    db_session.add_all(
        [
            Attendance(
                session_id=session_id,
                student_id=student_a.id,
                status="present",
                verification_method="face_kiosk",
                wa_status="sent",
            ),
            Attendance(
                session_id=session_id,
                student_id=student_b.id,
                status="late",
                verification_method="face_kiosk",
                wa_status="sent",
            ),
        ]
    )
    await db_session.commit()

    forbidden = await client.get("/api/v1/teacher/dashboard", headers=admin_headers)
    assert forbidden.status_code == 403

    dash_res = await client.get("/api/v1/teacher/dashboard", headers=teacher_headers)
    assert dash_res.status_code == 200
    dash = dash_res.json()
    assert dash["teacher_name"] == seeded_teacher.name
    assert dash["today_date"] == today.isoformat()
    assert dash["stats"]["present_count"] == 1
    assert dash["stats"]["late_count"] == 1
    assert dash["stats"]["present_rate"] == pytest.approx(100.0)
    assert dash["stats"]["pending_leaves_count"] == 1

    assert len(dash["sessions"]) == 1
    assert dash["sessions"][0]["id"] == session_id
    assert dash["sessions"][0]["class_name"] == "XI IPA 1"
    assert dash["sessions"][0]["subject_name"] == "Pemrograman Mobile"

    assert len(dash["today_schedules"]) == 1
    assert dash["today_schedules"][0]["subject_name"] == "Pemrograman Mobile"


async def test_waha_provider_and_message_builder() -> None:
    captured: list[tuple[str, dict[str, str], bytes]] = []

    def _ok_handler(request: httpx.Request) -> httpx.Response:
        captured.append((str(request.url), dict(request.headers), request.content))
        return httpx.Response(201, json={"id": "msg-1"})

    transport_ok = httpx.MockTransport(_ok_handler)
    waha_ok = WahaWhatsAppProvider(
        base_url="http://waha.local:3000",
        api_key="secret-key",
        session="school",
        transport=transport_ok,
    )
    assert await waha_ok.send_message("6281234567890", "Halo orang tua") is True
    assert len(captured) == 1
    assert captured[0][0] == "http://waha.local:3000/api/sendText"
    assert captured[0][1]["x-api-key"] == "secret-key"

    def _err_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    waha_down = WahaWhatsAppProvider(
        base_url="http://waha.local:3000",
        api_key="",
        session="default",
        transport=httpx.MockTransport(_err_handler),
    )
    assert await waha_down.send_message("6281234567890", "Halo") is False

    waha_500 = WahaWhatsAppProvider(
        base_url="http://waha.local:3000",
        transport=httpx.MockTransport(lambda _req: httpx.Response(500, json={"error": "down"})),
    )
    assert await waha_500.send_message("6281234567890", "Halo") is False

    assert isinstance(create_whatsapp_provider(Settings(whatsapp_provider_mode="mock")), MockWhatsAppProvider)
    assert isinstance(create_whatsapp_provider(Settings(whatsapp_provider_mode="waha")), WahaWhatsAppProvider)
    with pytest.raises(ValueError):
        create_whatsapp_provider(Settings(whatsapp_provider_mode="unknown"))

    msg = build_attendance_wa_message(
        student_name="Rubby Pratama",
        class_name="XI IPA 1",
        status="present",
        scanned_at_str="07:15 WIB",
        session_label="Gerbang Masuk",
    )
    assert "Rubby Pratama" in msg
    assert "XI IPA 1" in msg
    assert "Hadir" in msg
    assert "07:15 WIB" in msg


async def test_preapproved_leave_synced_on_session_open_close_and_kiosk_upgrade(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    teacher_headers: dict[str, str],
    admin_headers: dict[str, str],
    mock_wa: MockWhatsAppProvider,
) -> None:
    """Approved leaves auto-populate on POST /sessions, survive close, and kiosk scan upgrades to present."""
    seeded = await _seed_classroom_with_faces(db_session)
    class_a: SchoolClass = seeded["class_a"]  # type: ignore[assignment]
    parent_a: Parent = seeded["parent_a"]  # type: ignore[assignment]
    student_a: Student = seeded["student_a"]  # type: ignore[assignment]
    student_b: Student = seeded["student_b"]  # type: ignore[assignment]
    png_a: bytes = seeded["png_a"]  # type: ignore[assignment]

    today = datetime.now(WIB).date()
    db_session.add(
        LeaveRequest(
            student_id=student_a.id,
            parent_id=parent_a.id,
            request_type="sick",
            start_date=today,
            end_date=today,
            reason="Demam ringan",
            status="approved",
        )
    )
    await db_session.commit()

    # 1. Opening session auto-populates approved sick leave for student_a
    open_res = await client.post(
        "/api/v1/sessions",
        headers=teacher_headers,
        json={"class_id": class_a.id, "session_type": "subject"},
    )
    assert open_res.status_code == 201
    opened = open_res.json()
    session_id = opened["id"]
    assert opened["total_students"] == 2
    assert opened["sick_count"] == 1
    assert opened["recorded_count"] == 1
    assert opened["unrecorded_count"] == 1
    assert opened["opened_at"].endswith("Z")

    # 2. Duplicate open session for same (date, type, class, schedule) -> 409 with existing session_id
    dup_res = await client.post(
        "/api/v1/sessions",
        headers=teacher_headers,
        json={"class_id": class_a.id, "session_type": "subject"},
    )
    assert dup_res.status_code == 409
    assert session_id in dup_res.json()["detail"]

    # 3. schedule_id rejected on non-subject session -> 422
    bad_sched_type = await client.post(
        "/api/v1/sessions",
        headers=teacher_headers,
        json={"schedule_id": "any-id", "session_type": "gate_in"},
    )
    assert bad_sched_type.status_code == 422

    # 4. Kiosk scan for student_a upgrades 'sick' -> 'present', notifies parent WA, already_recorded=False!
    upgrade_scan = await client.post(
        "/api/v1/attendance/scan",
        headers=teacher_headers,
        data={"session_id": session_id, "liveness_passed": "true"},
        files={"file": ("a.png", png_a, "image/png")},
    )
    assert upgrade_scan.status_code == 200
    up_data = upgrade_scan.json()
    assert up_data["matched"] is True
    assert up_data["already_recorded"] is False
    assert up_data["status"] == "present"
    assert up_data["wa_queued"] is True
    assert up_data["scanned_at"].endswith("Z")
    assert len(mock_wa.sent) == 1

    # 5. Admin can list GET /sessions, read GET /sessions/{id}, and call resend-wa
    admin_sessions = await client.get(
        "/api/v1/sessions",
        params={"status": "open", "class_id": class_a.id},
        headers=admin_headers,
    )
    assert admin_sessions.status_code == 200
    assert any(s["id"] == session_id for s in admin_sessions.json())

    admin_detail = await client.get(f"/api/v1/sessions/{session_id}", headers=admin_headers)
    assert admin_detail.status_code == 200

    admin_resend = await client.post(
        f"/api/v1/attendance/{up_data['attendance_id']}/resend-wa",
        headers=admin_headers,
    )
    assert admin_resend.status_code == 200
    assert admin_resend.json()["wa_sent"] is True

    # 6. Approve leave for student_b BEFORE close, then close session -> student_b gets permit (not absent!)
    db_session.add(
        LeaveRequest(
            student_id=student_b.id,
            parent_id=seeded["parent_b"].id,  # type: ignore[union-attr]
            request_type="permit",
            start_date=today,
            end_date=today,
            reason="Izin keluarga",
            status="approved",
        )
    )
    await db_session.commit()

    closed = (
        await client.post(f"/api/v1/sessions/{session_id}/close", headers=teacher_headers)
    ).json()
    assert closed["summary"]["present_count"] == 1
    assert closed["summary"]["permit_count"] == 1
    assert closed["summary"]["absent_count"] == 0
    assert closed["closed_at"].endswith("Z")


async def test_gate_out_zero_embeddings_prior_day_open_and_manual_scanned_at(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_teacher: User,
    teacher_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify gate_out behavior, 0-embedding non-pollution, prior-day open visibility, and manual scanned_at."""
    from app.routers.attendance import _resolve_scan_status

    # 1. gate_out never returns "late"
    assert (
        _resolve_scan_status(
            date(2026, 11, 22),
            time(7, 30),
            0,
            datetime(2026, 11, 22, 8, 0, tzinfo=timezone.utc),
            session_type="gate_out",
        )
        == "present"
    )

    # 2. Class with 0 face embeddings -> scan returns 200 matched=False without polluting FaceRecognitionLog
    empty_class = SchoolClass(name="X Kosong")
    parent = Parent(name="Ortu Kosong", phone_wa="6281277889900")
    db_session.add_all([empty_class, parent])
    await db_session.flush()
    stu = Student(
        nis="2026777",
        name="Siswa Tanpa Wajah",
        class_id=empty_class.id,
        parent_id=parent.id,
    )
    db_session.add(stu)
    await db_session.commit()

    sess_res = await client.post(
        "/api/v1/sessions",
        headers=teacher_headers,
        json={"class_id": empty_class.id, "session_type": "subject"},
    )
    assert sess_res.status_code == 201
    empty_sess_id = sess_res.json()["id"]

    zero_scan = await client.post(
        "/api/v1/attendance/scan",
        headers=teacher_headers,
        data={"session_id": empty_sess_id, "liveness_passed": "true"},
        files={"file": ("probe.png", _make_textured_png(seed=55), "image/png")},
    )
    assert zero_scan.status_code == 200
    assert zero_scan.json()["matched"] is False
    assert "belum ada dataset" in zero_scan.json()["message"].lower()

    logs = (
        await db_session.scalars(
            select(FaceRecognitionLog).where(FaceRecognitionLog.session_id == empty_sess_id)
        )
    ).all()
    assert logs == []

    # 3. Oversized kiosk scan (> MAX_FACE_IMAGE_BYTES) -> HTTP 413
    import app.routers.attendance as attendance_mod

    monkeypatch.setattr(attendance_mod, "MAX_FACE_IMAGE_BYTES", 1024)
    oversized_scan = await client.post(
        "/api/v1/attendance/scan",
        headers=teacher_headers,
        data={"session_id": empty_sess_id, "liveness_passed": "true"},
        files={"file": ("huge.jpg", b"z" * 2048, "image/jpeg")},
    )
    assert oversized_scan.status_code == 413

    # 4. Manual attendance: absent/sick/permit must have scanned_at=None
    await client.put("/api/v1/auth/kiosk-pin", headers=teacher_headers, json={"pin": "1234"})
    manual_sick = await client.post(
        "/api/v1/attendance/manual",
        headers=teacher_headers,
        json={
            "session_id": empty_sess_id,
            "student_id": stu.id,
            "status": "sick",
            "kiosk_pin": "1234",
            "notify_wa": False,
        },
    )
    assert manual_sick.status_code == 201
    assert manual_sick.json()["scanned_at"] is None

    # 4. gate_out close does NOT mark unrecorded students as absent
    gate_out_res = await client.post(
        "/api/v1/sessions",
        headers=teacher_headers,
        json={"session_type": "gate_out"},
    )
    assert gate_out_res.status_code == 201
    gate_out_id = gate_out_res.json()["id"]
    gate_out_closed = (
        await client.post(f"/api/v1/sessions/{gate_out_id}/close", headers=teacher_headers)
    ).json()
    assert gate_out_closed["status"] == "closed"
    assert gate_out_closed["summary"]["absent_count"] == 0

    # 5. Unclosed prior-day open session still appears in GET /teacher/dashboard
    yesterday = datetime.now(WIB).date() - timedelta(days=1)
    prior_open = AttendanceSession(
        class_id=empty_class.id,
        teacher_id=seeded_teacher.id,
        session_type="subject",
        session_date=yesterday,
        status="open",
    )
    db_session.add(prior_open)
    await db_session.commit()

    dash = (await client.get("/api/v1/teacher/dashboard", headers=teacher_headers)).json()
    session_ids_in_dash = {s["id"] for s in dash["sessions"]}
    assert prior_open.id in session_ids_in_dash
    assert empty_sess_id in session_ids_in_dash
    # present_rate is over total_students (0 present out of total_students -> 0.0)
    assert dash["stats"]["present_rate"] == pytest.approx(0.0)

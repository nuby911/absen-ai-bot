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

    # 5. Gate session (class_id=None) matches active students across all classes
    gate_res = await client.post(
        "/api/v1/sessions",
        headers=teacher_headers,
        json={"session_type": "gate_in"},
    )
    assert gate_res.status_code == 201
    gate_id = gate_res.json()["id"]

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
    assert gate_detail.json()["summary"]["recorded_count"] == 1
    assert len(gate_detail.json()["students"]) == 1

    gate_close = await client.post(f"/api/v1/sessions/{gate_id}/close", headers=teacher_headers)
    assert gate_close.status_code == 200
    assert gate_close.json()["status"] == "closed"


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
            select(FaceRecognitionLog).where(FaceRecognitionLog.session_id == session_id)
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].is_match is False
    assert logs[0].predicted_student_id is None
    assert logs[0].liveness_passed is True
    assert logs[0].condition_note == "cahaya_redup"
    assert logs[0].latency_ms >= 0

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
        student_id=student_b.id,
        parent_id=parent_b.id,
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

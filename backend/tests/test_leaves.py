from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database import get_db
from app.main import create_app
from app.models import (
    Attendance,
    AttendanceSession,
    LeaveRequest,
    Parent,
    SchoolClass,
    Student,
    User,
)
from app.providers.whatsapp import MockWhatsAppProvider


async def _seed_leave_fixtures(db_session: AsyncSession) -> dict[str, object]:
    """Seed two classes, two parents, and two students for leave workflow tests."""
    class_a = SchoolClass(name="XI IPA 1")
    class_b = SchoolClass(name="XI IPA 2")
    parent_a = Parent(name="Bapak Ahmad", phone_wa="6281279001111")
    parent_b = Parent(name="Ibu Siti", phone_wa="6281279002222")
    db_session.add_all([class_a, class_b, parent_a, parent_b])
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
        class_id=class_b.id,
        parent_id=parent_b.id,
        is_active=True,
    )
    db_session.add_all([student_a, student_b])
    await db_session.commit()

    for obj in (class_a, class_b, parent_a, parent_b, student_a, student_b):
        await db_session.refresh(obj)

    return {
        "class_a": class_a,
        "class_b": class_b,
        "parent_a": parent_a,
        "parent_b": parent_b,
        "student_a": student_a,
        "student_b": student_b,
    }


@pytest.mark.asyncio
async def test_list_leave_requests_filtered_by_status(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_teacher: User,
    teacher_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    """List leave requests with enriched fields and status/class filters."""
    data = await _seed_leave_fixtures(db_session)
    class_a: SchoolClass = data["class_a"]  # type: ignore[assignment]
    class_b: SchoolClass = data["class_b"]  # type: ignore[assignment]
    parent_a: Parent = data["parent_a"]  # type: ignore[assignment]
    parent_b: Parent = data["parent_b"]  # type: ignore[assignment]
    student_a: Student = data["student_a"]  # type: ignore[assignment]
    student_b: Student = data["student_b"]  # type: ignore[assignment]

    now = datetime.now(timezone.utc)
    leave_pending = LeaveRequest(
        student_id=student_a.id,
        parent_id=parent_a.id,
        request_type="sick",
        start_date=date(2026, 11, 24),
        end_date=date(2026, 11, 25),
        reason="Demam tinggi sejak semalam.",
        attachment_url="/uploads/leaves/surat-dokter.jpg",
        status="pending",
        created_at=now,
    )
    leave_approved = LeaveRequest(
        student_id=student_b.id,
        parent_id=parent_b.id,
        request_type="permit",
        start_date=date(2026, 11, 20),
        end_date=date(2026, 11, 20),
        reason="Acara keluarga di luar kota.",
        status="approved",
        verified_by=seeded_teacher.id,
        verified_at=now - timedelta(hours=1),
        created_at=now - timedelta(hours=2),
    )
    db_session.add_all([leave_pending, leave_approved])
    await db_session.commit()

    # Unauthenticated request rejected
    unauth = await client.get("/api/v1/leave-requests")
    assert unauth.status_code == 401

    # Teacher sees all ordered newest first
    res_all = await client.get("/api/v1/leave-requests", headers=teacher_headers)
    assert res_all.status_code == 200
    items_all = res_all.json()
    assert len(items_all) == 2
    assert items_all[0]["id"] == leave_pending.id
    assert items_all[1]["id"] == leave_approved.id

    # Admin can also read leave requests for Web Admin monitoring
    res_admin = await client.get("/api/v1/leave-requests", headers=admin_headers)
    assert res_admin.status_code == 200
    assert len(res_admin.json()) == 2

    # Filter status=pending returns enriched student/class/parent fields
    res_pending = await client.get(
        "/api/v1/leave-requests",
        params={"status": "pending"},
        headers=teacher_headers,
    )
    assert res_pending.status_code == 200
    pending_items = res_pending.json()
    assert len(pending_items) == 1
    first = pending_items[0]
    assert first["id"] == leave_pending.id
    assert first["student_id"] == student_a.id
    assert first["student_name"] == "Rubby Pratama"
    assert first["student_nis"] == "2026101"
    assert first["class_id"] == class_a.id
    assert first["class_name"] == "XI IPA 1"
    assert first["parent_id"] == parent_a.id
    assert first["parent_name"] == "Bapak Ahmad"
    assert first["parent_phone_wa"] == "6281279001111"
    assert first["request_type"] == "sick"
    assert first["start_date"] == "2026-11-24"
    assert first["end_date"] == "2026-11-25"
    assert first["reason"] == "Demam tinggi sejak semalam."
    assert first["attachment_url"] == "/uploads/leaves/surat-dokter.jpg"
    assert first["status"] == "pending"
    assert first["verified_by"] is None
    assert first["verified_by_name"] is None
    assert first["verified_at"] is None
    assert first["created_at"] is not None

    # Filter status=approved
    res_approved = await client.get(
        "/api/v1/leave-requests",
        params={"status": "approved"},
        headers=teacher_headers,
    )
    assert res_approved.status_code == 200
    approved_items = res_approved.json()
    assert len(approved_items) == 1
    assert approved_items[0]["id"] == leave_approved.id
    assert approved_items[0]["verified_by"] == seeded_teacher.id
    assert approved_items[0]["verified_by_name"] == seeded_teacher.name

    # Filter class_id
    res_class_b = await client.get(
        "/api/v1/leave-requests",
        params={"class_id": class_b.id},
        headers=teacher_headers,
    )
    assert res_class_b.status_code == 200
    assert len(res_class_b.json()) == 1
    assert res_class_b.json()[0]["student_id"] == student_b.id


@pytest.mark.asyncio
async def test_approve_leave_updates_or_creates_attendance_and_notifies_parent_wa(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_teacher: User,
    teacher_headers: dict[str, str],
    admin_headers: dict[str, str],
    mock_wa: MockWhatsAppProvider,
) -> None:
    """Approving a sick leave upserts matching sessions, notifies WA, and blocks re-verify."""
    data = await _seed_leave_fixtures(db_session)
    class_a: SchoolClass = data["class_a"]  # type: ignore[assignment]
    class_b: SchoolClass = data["class_b"]  # type: ignore[assignment]
    parent_a: Parent = data["parent_a"]  # type: ignore[assignment]
    student_a: Student = data["student_a"]  # type: ignore[assignment]

    leave = LeaveRequest(
        student_id=student_a.id,
        parent_id=parent_a.id,
        request_type="sick",
        start_date=date(2026, 11, 24),
        end_date=date(2026, 11, 25),
        reason="Sakit flu dan demam.",
        status="pending",
    )
    db_session.add(leave)

    # 1. Closed class session inside date range with existing 'absent' record -> should update to 'sick'
    session_existing_absent = AttendanceSession(
        class_id=class_a.id,
        teacher_id=seeded_teacher.id,
        session_type="subject",
        session_date=date(2026, 11, 24),
        status="closed",
    )
    # 2. Open gate session (no class_id) inside date range with no attendance yet -> should create 'sick'
    session_open_gate = AttendanceSession(
        class_id=None,
        teacher_id=seeded_teacher.id,
        session_type="gate_in",
        session_date=date(2026, 11, 25),
        status="open",
    )
    # 3. Other class session inside date range -> must NOT be synced
    session_other_class = AttendanceSession(
        class_id=class_b.id,
        teacher_id=seeded_teacher.id,
        session_type="subject",
        session_date=date(2026, 11, 24),
        status="open",
    )
    # 4. Same class session outside date range -> must NOT be synced
    session_outside_range = AttendanceSession(
        class_id=class_a.id,
        teacher_id=seeded_teacher.id,
        session_type="subject",
        session_date=date(2026, 11, 26),
        status="open",
    )
    db_session.add_all(
        [
            session_existing_absent,
            session_open_gate,
            session_other_class,
            session_outside_range,
        ]
    )
    await db_session.flush()

    existing_att = Attendance(
        session_id=session_existing_absent.id,
        student_id=student_a.id,
        status="absent",
        verification_method="manual_teacher",
        wa_status="skipped",
    )
    db_session.add(existing_att)
    await db_session.commit()

    # Admin cannot verify leave requests (teacher-only)
    forbidden = await client.patch(
        f"/api/v1/leave-requests/{leave.id}/verify",
        json={"decision": "approved"},
        headers=admin_headers,
    )
    assert forbidden.status_code == 403

    # Missing leave returns 404
    not_found = await client.patch(
        "/api/v1/leave-requests/nonexistent-id/verify",
        json={"decision": "approved"},
        headers=teacher_headers,
    )
    assert not_found.status_code == 404

    # Teacher approves leave
    res = await client.patch(
        f"/api/v1/leave-requests/{leave.id}/verify",
        json={"decision": "approved", "note": "Semoga lekas sembuh."},
        headers=teacher_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["synced_sessions_count"] == 2
    assert body["wa_sent"] is True
    assert body["leave"]["status"] == "approved"
    assert body["leave"]["verified_by"] == seeded_teacher.id
    assert body["leave"]["verified_by_name"] == seeded_teacher.name
    assert body["leave"]["verified_at"] is not None

    # Capture scalar identifiers before expiring session cache
    student_a_id = student_a.id
    parent_a_phone = parent_a.phone_wa
    teacher_name = seeded_teacher.name
    leave_id = leave.id
    existing_att_id = existing_att.id
    session_absent_id = session_existing_absent.id
    session_gate_id = session_open_gate.id
    session_other_id = session_other_class.id
    session_outside_id = session_outside_range.id

    # Verify DB attendance rows
    db_session.expire_all()
    att_rows = (
        await db_session.scalars(
            select(Attendance).where(Attendance.student_id == student_a_id)
        )
    ).all()
    assert len(att_rows) == 2
    att_by_session = {row.session_id: row for row in att_rows}

    assert session_absent_id in att_by_session
    updated_att = att_by_session[session_absent_id]
    assert updated_att.id == existing_att_id
    assert updated_att.status == "sick"
    assert updated_att.verification_method == "leave_approved"
    assert updated_att.wa_status == "sent"
    assert updated_att.wa_notified_at is not None

    assert session_gate_id in att_by_session
    created_att = att_by_session[session_gate_id]
    assert created_att.status == "sick"
    assert created_att.verification_method == "leave_approved"
    assert created_att.wa_status == "sent"
    assert created_att.wa_notified_at is not None

    assert session_other_id not in att_by_session
    assert session_outside_id not in att_by_session

    # Verify parent WA received Indonesian approval message with teacher name and "SAKIT"
    assert len(mock_wa.sent) == 1
    sent_msg = mock_wa.sent[0]
    assert sent_msg.phone_wa == parent_a_phone
    assert "SAKIT" in sent_msg.text
    assert teacher_name in sent_msg.text
    assert "Rubby Pratama" in sent_msg.text
    assert "Semoga lekas sembuh." in sent_msg.text

    # Re-verifying the same leave returns HTTP 400
    re_verify = await client.patch(
        f"/api/v1/leave-requests/{leave_id}/verify",
        json={"decision": "rejected"},
        headers=teacher_headers,
    )
    assert re_verify.status_code == 400
    assert "sudah diverifikasi" in re_verify.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reject_leave_does_not_overwrite_attendance_and_notifies_parent_wa(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_teacher: User,
    teacher_headers: dict[str, str],
    mock_wa: MockWhatsAppProvider,
) -> None:
    """Rejecting a leave leaves attendance unchanged and notifies parent with optional note."""
    data = await _seed_leave_fixtures(db_session)
    class_a: SchoolClass = data["class_a"]  # type: ignore[assignment]
    parent_a: Parent = data["parent_a"]  # type: ignore[assignment]
    student_a: Student = data["student_a"]  # type: ignore[assignment]

    leave = LeaveRequest(
        student_id=student_a.id,
        parent_id=parent_a.id,
        request_type="permit",
        start_date=date(2026, 11, 24),
        end_date=date(2026, 11, 24),
        reason="Izin menghadiri acara keluarga.",
        status="pending",
    )
    session_row = AttendanceSession(
        class_id=class_a.id,
        teacher_id=seeded_teacher.id,
        session_type="subject",
        session_date=date(2026, 11, 24),
        status="open",
    )
    db_session.add_all([leave, session_row])
    await db_session.flush()

    existing_att = Attendance(
        session_id=session_row.id,
        student_id=student_a.id,
        status="absent",
        verification_method="manual_teacher",
        wa_status="skipped",
    )
    db_session.add(existing_att)
    await db_session.commit()

    rejection_note = "Mohon melampirkan surat keterangan resmi dari orang tua."
    res = await client.patch(
        f"/api/v1/leave-requests/{leave.id}/verify",
        json={"decision": "rejected", "note": rejection_note},
        headers=teacher_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["synced_sessions_count"] == 0
    assert body["wa_sent"] is True
    assert body["leave"]["status"] == "rejected"
    assert body["leave"]["verified_by"] == seeded_teacher.id
    assert body["leave"]["verified_by_name"] == seeded_teacher.name

    existing_att_id = existing_att.id
    parent_a_phone = parent_a.phone_wa
    teacher_name = seeded_teacher.name

    # Attendance remains unchanged
    db_session.expire_all()
    att_after = await db_session.get(Attendance, existing_att_id)
    assert att_after is not None
    assert att_after.status == "absent"
    assert att_after.verification_method == "manual_teacher"

    # Parent WA receives polite Indonesian rejection message including optional note
    assert len(mock_wa.sent) == 1
    sent_msg = mock_wa.sent[0]
    assert sent_msg.phone_wa == parent_a_phone
    assert "IZIN" in sent_msg.text
    assert teacher_name in sent_msg.text
    assert rejection_note in sent_msg.text


@pytest.mark.asyncio
async def test_approve_leave_survives_wa_failure(
    db_session: AsyncSession,
    test_settings: Settings,
    seeded_teacher: User,
    teacher_headers: dict[str, str],
) -> None:
    """When WhatsAppProvider raises an error, approval & attendance sync still commit cleanly."""
    data = await _seed_leave_fixtures(db_session)
    class_a: SchoolClass = data["class_a"]  # type: ignore[assignment]
    parent_a: Parent = data["parent_a"]  # type: ignore[assignment]
    student_a: Student = data["student_a"]  # type: ignore[assignment]

    leave = LeaveRequest(
        student_id=student_a.id,
        parent_id=parent_a.id,
        request_type="permit",
        start_date=date(2026, 11, 24),
        end_date=date(2026, 11, 24),
        reason="Izin keperluan keluarga mendadak.",
        status="pending",
    )
    session_row = AttendanceSession(
        class_id=class_a.id,
        teacher_id=seeded_teacher.id,
        session_type="subject",
        session_date=date(2026, 11, 24),
        status="open",
    )
    db_session.add_all([leave, session_row])
    await db_session.commit()

    failing_wa = MockWhatsAppProvider(fail_exception=RuntimeError("WA gateway timeout"))
    app = create_app(settings=test_settings, whatsapp_provider=failing_wa)

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        res = await async_client.patch(
            f"/api/v1/leave-requests/{leave.id}/verify",
            json={"decision": "approved"},
            headers=teacher_headers,
        )

    assert res.status_code == 200
    body = res.json()
    assert body["wa_sent"] is False
    assert body["synced_sessions_count"] == 1
    assert body["leave"]["status"] == "approved"

    leave_id = leave.id
    teacher_id = seeded_teacher.id
    session_id = session_row.id
    student_id = student_a.id

    # Approval & synced attendance remain durably committed despite WA exception
    db_session.expire_all()
    leave_after = await db_session.get(LeaveRequest, leave_id)
    assert leave_after is not None
    assert leave_after.status == "approved"
    assert leave_after.verified_by == teacher_id

    att_after = await db_session.scalar(
        select(Attendance).where(
            Attendance.session_id == session_id,
            Attendance.student_id == student_id,
        )
    )
    assert att_after is not None
    assert att_after.status == "permit"
    assert att_after.verification_method == "leave_approved"
    assert att_after.wa_status == "failed"


@pytest.mark.asyncio
async def test_verify_leave_atomic_update_blocks_concurrent_race(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_teacher: User,
    teacher_headers: dict[str, str],
    mock_wa: MockWhatsAppProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Atomic UPDATE WHERE status='pending' rejects a concurrent double-verification race with 400."""
    data = await _seed_leave_fixtures(db_session)
    parent_a: Parent = data["parent_a"]  # type: ignore[assignment]
    student_a: Student = data["student_a"]  # type: ignore[assignment]

    leave = LeaveRequest(
        student_id=student_a.id,
        parent_id=parent_a.id,
        request_type="sick",
        start_date=date(2026, 11, 24),
        end_date=date(2026, 11, 24),
        reason="Demam.",
        status="pending",
    )
    db_session.add(leave)
    await db_session.commit()
    leave_id = leave.id

    original_execute = db_session.execute

    class _ZeroRowcountResult:
        rowcount = 0

    async def _race_execute(statement, *args, **kwargs):
        # Let the initial SELECT see status='pending', then simulate a rival worker winning the UPDATE
        if getattr(statement, "is_update", False):
            return _ZeroRowcountResult()
        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", _race_execute)

    res = await client.patch(
        f"/api/v1/leave-requests/{leave_id}/verify",
        json={"decision": "approved"},
        headers=teacher_headers,
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "Pengajuan izin ini sudah diverifikasi sebelumnya."
    assert len(mock_wa.sent) == 0

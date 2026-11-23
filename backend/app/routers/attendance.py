import asyncio
from datetime import date, datetime, time, timedelta, timezone
import logging
import time as time_perf

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
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
from app.providers.face_engine import (
    EMBEDDING_DIM,
    FaceEngine,
    FaceValidationError,
    cosine_similarity,
    get_face_engine,
)
from app.providers.whatsapp import (
    ATTENDANCE_STATUS_LABELS_ID,
    WhatsAppProvider,
    build_attendance_wa_message,
    get_whatsapp_provider,
)
from app.routers.admin import get_active_face_threshold
from app.schemas import (
    AttendanceScanResponse,
    AttendanceSessionCreate,
    AttendanceSessionDetailResponse,
    AttendanceSessionSummary,
    ManualAttendanceRequest,
    ManualAttendanceResponse,
    ResendWaResponse,
    ScheduleResponse,
    SessionStudentAttendanceItem,
    SessionSummaryCounters,
    TeacherDashboardResponse,
    TeacherDashboardStats,
)
from app.security import require_teacher, verify_secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["attendance"])

WIB = timezone(timedelta(hours=7))
MAX_FACE_IMAGE_BYTES = 10 * 1024 * 1024
_SESSION_TYPE_LABELS: dict[str, str] = {
    "gate_in": "Gerbang Masuk",
    "gate_out": "Gerbang Pulang",
    "subject": "Sesi Mata Pelajaran",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _wib_now() -> datetime:
    return datetime.now(WIB)


def _format_wib_timestamp(dt: datetime | None) -> str:
    target = dt or _utc_now()
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return target.astimezone(WIB).strftime("%d/%m/%Y %H:%M WIB")


def _build_session_label(session_type: str, subject_name: str | None) -> str:
    if subject_name:
        return f"Mata Pelajaran {subject_name}"
    return _SESSION_TYPE_LABELS.get(session_type, "Sesi Presensi")


def _resolve_scan_status(
    session_date: date,
    expected_start_time: time | None,
    late_tolerance_minutes: int,
    scan_dt_utc: datetime,
) -> str:
    if expected_start_time is None:
        return "present"
    target_dt = (
        scan_dt_utc
        if scan_dt_utc.tzinfo is not None
        else scan_dt_utc.replace(tzinfo=timezone.utc)
    )
    scan_wib = target_dt.astimezone(WIB)
    deadline = datetime.combine(
        session_date,
        expected_start_time,
        tzinfo=WIB,
    ) + timedelta(minutes=late_tolerance_minutes)
    return "late" if scan_wib > deadline else "present"


def _compute_counters(
    items: list[SessionStudentAttendanceItem],
    total_students: int | None = None,
) -> SessionSummaryCounters:
    counts: dict[str, int] = {
        "present": 0,
        "late": 0,
        "permit": 0,
        "sick": 0,
        "absent": 0,
        "unrecorded": 0,
    }
    for item in items:
        if item.status in counts:
            counts[item.status] += 1

    recorded = (
        counts["present"]
        + counts["late"]
        + counts["permit"]
        + counts["sick"]
        + counts["absent"]
    )
    resolved_total = len(items) if total_students is None else total_students
    return SessionSummaryCounters(
        total_students=resolved_total,
        present_count=counts["present"],
        late_count=counts["late"],
        permit_count=counts["permit"],
        sick_count=counts["sick"],
        absent_count=counts["absent"],
        unrecorded_count=counts["unrecorded"],
        recorded_count=recorded,
    )


async def _get_session_with_meta(
    db: AsyncSession,
    session_id: str,
) -> tuple[AttendanceSession, str | None, str | None, str | None]:
    stmt = (
        select(
            AttendanceSession,
            SchoolClass.name.label("class_name"),
            User.name.label("teacher_name"),
            Schedule.subject_name.label("subject_name"),
        )
        .join(User, AttendanceSession.teacher_id == User.id)
        .outerjoin(SchoolClass, AttendanceSession.class_id == SchoolClass.id)
        .outerjoin(Schedule, AttendanceSession.schedule_id == Schedule.id)
        .where(AttendanceSession.id == session_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sesi presensi tidak ditemukan.",
        )
    return row[0], row[1], row[2], row[3]


def _to_student_attendance_item(
    student: Student,
    class_name: str,
    parent_phone_wa: str,
    attendance: Attendance | None = None,
) -> SessionStudentAttendanceItem:
    return SessionStudentAttendanceItem(
        student_id=student.id,
        nis=student.nis,
        student_name=student.name,
        class_id=student.class_id,
        class_name=class_name,
        parent_phone_wa=parent_phone_wa,
        attendance_id=attendance.id if attendance is not None else None,
        status=attendance.status if attendance is not None else "unrecorded",
        verification_method=attendance.verification_method if attendance is not None else None,
        scanned_at=attendance.scanned_at if attendance is not None else None,
        similarity_score=attendance.similarity_score if attendance is not None else None,
        wa_status=attendance.wa_status if attendance is not None else None,
        wa_notified_at=attendance.wa_notified_at if attendance is not None else None,
    )


async def _build_session_detail(
    db: AsyncSession,
    session_id: str,
) -> AttendanceSessionDetailResponse:
    session_row, class_name, teacher_name, subject_name = await _get_session_with_meta(
        db, session_id
    )

    attendance_stmt = (
        select(
            Attendance,
            Student,
            SchoolClass.name.label("student_class_name"),
            Parent.phone_wa.label("parent_phone_wa"),
        )
        .join(Student, Attendance.student_id == Student.id)
        .join(SchoolClass, Student.class_id == SchoolClass.id)
        .join(Parent, Student.parent_id == Parent.id)
        .where(Attendance.session_id == session_row.id)
        .order_by(Student.name)
    )
    attendance_rows = (await db.execute(attendance_stmt)).all()
    attendance_by_student: dict[
        str, tuple[Attendance, Student, str, str]
    ] = {
        student.id: (attendance, student, s_class_name, phone_wa)
        for attendance, student, s_class_name, phone_wa in attendance_rows
    }

    items: list[SessionStudentAttendanceItem] = []
    if session_row.class_id is not None:
        roster_stmt = (
            select(
                Student,
                SchoolClass.name.label("student_class_name"),
                Parent.phone_wa.label("parent_phone_wa"),
            )
            .join(SchoolClass, Student.class_id == SchoolClass.id)
            .join(Parent, Student.parent_id == Parent.id)
            .where(
                Student.class_id == session_row.class_id,
                Student.is_active.is_(True),
            )
            .order_by(Student.name)
        )
        roster_rows = (await db.execute(roster_stmt)).all()
        seen_ids: set[str] = set()
        for student, s_class_name, phone_wa in roster_rows:
            seen_ids.add(student.id)
            rec = attendance_by_student.get(student.id)
            items.append(
                _to_student_attendance_item(
                    student,
                    s_class_name,
                    phone_wa,
                    attendance=rec[0] if rec is not None else None,
                )
            )

        # Include any already-recorded students even if moved or deactivated later
        for student_id, (att, student, s_class_name, phone_wa) in attendance_by_student.items():
            if student_id in seen_ids:
                continue
            items.append(
                _to_student_attendance_item(
                    student,
                    s_class_name,
                    phone_wa,
                    attendance=att,
                )
            )
    else:
        for att, student, s_class_name, phone_wa in attendance_rows:
            items.append(
                _to_student_attendance_item(
                    student,
                    s_class_name,
                    phone_wa,
                    attendance=att,
                )
            )

    summary = _compute_counters(items)
    return AttendanceSessionDetailResponse(
        id=session_row.id,
        class_id=session_row.class_id,
        class_name=class_name,
        teacher_id=session_row.teacher_id,
        teacher_name=teacher_name,
        schedule_id=session_row.schedule_id,
        subject_name=subject_name,
        session_type=session_row.session_type,
        session_date=session_row.session_date,
        expected_start_time=session_row.expected_start_time,
        late_tolerance_minutes=session_row.late_tolerance_minutes,
        opened_at=session_row.opened_at,
        closed_at=session_row.closed_at,
        status=session_row.status,
        total_students=summary.total_students,
        present_count=summary.present_count,
        late_count=summary.late_count,
        permit_count=summary.permit_count,
        sick_count=summary.sick_count,
        absent_count=summary.absent_count,
        unrecorded_count=summary.unrecorded_count,
        recorded_count=summary.recorded_count,
        summary=summary,
        students=items,
    )


async def _query_session_summaries(
    db: AsyncSession,
    teacher_id: str,
    session_date: date,
) -> list[AttendanceSessionSummary]:
    stmt = (
        select(
            AttendanceSession,
            SchoolClass.name.label("class_name"),
            User.name.label("teacher_name"),
            Schedule.subject_name.label("subject_name"),
        )
        .join(User, AttendanceSession.teacher_id == User.id)
        .outerjoin(SchoolClass, AttendanceSession.class_id == SchoolClass.id)
        .outerjoin(Schedule, AttendanceSession.schedule_id == Schedule.id)
        .where(
            AttendanceSession.teacher_id == teacher_id,
            AttendanceSession.session_date == session_date,
        )
        .order_by(AttendanceSession.opened_at.desc())
    )
    session_rows = (await db.execute(stmt)).all()
    if not session_rows:
        return []

    class_ids = {s.class_id for s, _, _, _ in session_rows if s.class_id is not None}
    class_student_counts: dict[str, int] = {}
    if class_ids:
        roster_counts = (
            await db.execute(
                select(Student.class_id, func.count(Student.id))
                .where(Student.class_id.in_(class_ids), Student.is_active.is_(True))
                .group_by(Student.class_id)
            )
        ).all()
        class_student_counts = {cid: int(cnt) for cid, cnt in roster_counts}

    session_ids = [s.id for s, _, _, _ in session_rows]
    status_counts_by_session: dict[str, dict[str, int]] = {sid: {} for sid in session_ids}
    att_counts = (
        await db.execute(
            select(Attendance.session_id, Attendance.status, func.count(Attendance.id))
            .where(Attendance.session_id.in_(session_ids))
            .group_by(Attendance.session_id, Attendance.status)
        )
    ).all()
    for sid, att_status, cnt in att_counts:
        status_counts_by_session[sid][att_status] = int(cnt)

    summaries: list[AttendanceSessionSummary] = []
    for session_row, class_name, teacher_name, subject_name in session_rows:
        sc = status_counts_by_session[session_row.id]
        present_cnt = sc.get("present", 0)
        late_cnt = sc.get("late", 0)
        permit_cnt = sc.get("permit", 0)
        sick_cnt = sc.get("sick", 0)
        absent_cnt = sc.get("absent", 0)
        recorded_cnt = present_cnt + late_cnt + permit_cnt + sick_cnt + absent_cnt
        total_cnt = (
            class_student_counts.get(session_row.class_id, 0)
            if session_row.class_id is not None
            else recorded_cnt
        )
        unrecorded_cnt = max(0, total_cnt - recorded_cnt)
        summaries.append(
            AttendanceSessionSummary(
                id=session_row.id,
                class_id=session_row.class_id,
                class_name=class_name,
                teacher_id=session_row.teacher_id,
                teacher_name=teacher_name,
                schedule_id=session_row.schedule_id,
                subject_name=subject_name,
                session_type=session_row.session_type,
                session_date=session_row.session_date,
                expected_start_time=session_row.expected_start_time,
                late_tolerance_minutes=session_row.late_tolerance_minutes,
                opened_at=session_row.opened_at,
                closed_at=session_row.closed_at,
                status=session_row.status,
                total_students=total_cnt,
                present_count=present_cnt,
                late_count=late_cnt,
                permit_count=permit_cnt,
                sick_count=sick_cnt,
                absent_count=absent_cnt,
                unrecorded_count=unrecorded_cnt,
                recorded_count=recorded_cnt,
            )
        )
    return summaries


async def _dispatch_attendance_wa(
    db: AsyncSession,
    whatsapp_provider: WhatsAppProvider,
    attendance: Attendance,
    student_name: str,
    class_name: str,
    parent_phone_wa: str,
    session_label: str,
) -> tuple[bool, str, datetime | None]:
    """Send WA notification safely and persist `wa_status` without expiring caller scalars."""
    attendance_id = attendance.id
    attendance_status = attendance.status
    scanned_at = attendance.scanned_at
    existing_wa_notified_at = attendance.wa_notified_at

    message_text = build_attendance_wa_message(
        student_name=student_name,
        class_name=class_name,
        status=attendance_status,
        scanned_at_str=_format_wib_timestamp(scanned_at),
        session_label=session_label,
    )
    sent = False
    try:
        sent = bool(await whatsapp_provider.send_message(parent_phone_wa, message_text))
    except Exception as exc:
        logger.warning(
            "Exception saat mengirim notifikasi WA untuk attendance %s: %s",
            attendance_id,
            exc,
        )
        sent = False

    resolved_wa_status = "sent" if sent else "failed"
    resolved_wa_notified_at = _utc_now() if sent else existing_wa_notified_at

    attendance.wa_status = resolved_wa_status
    if sent:
        attendance.wa_notified_at = resolved_wa_notified_at

    try:
        await db.commit()
        await db.refresh(attendance)
        resolved_wa_status = attendance.wa_status
        resolved_wa_notified_at = attendance.wa_notified_at
    except Exception as exc:
        logger.warning(
            "Gagal menyimpan status WA untuk attendance %s: %s",
            attendance_id,
            exc,
        )
        await db.rollback()
    return sent, resolved_wa_status, resolved_wa_notified_at


async def _match_best_student(
    db: AsyncSession,
    query_embedding: list[float],
    class_id: str | None,
) -> tuple[Student | None, SchoolClass | None, Parent | None, float]:
    stmt = (
        select(FaceEmbedding, Student, SchoolClass, Parent)
        .join(Student, FaceEmbedding.student_id == Student.id)
        .join(SchoolClass, Student.class_id == SchoolClass.id)
        .join(Parent, Student.parent_id == Parent.id)
        .where(Student.is_active.is_(True))
    )
    if class_id is not None:
        stmt = stmt.where(Student.class_id == class_id)

    candidates = (await db.execute(stmt)).all()
    if not candidates:
        return None, None, None, 0.0

    best_student: Student | None = None
    best_class: SchoolClass | None = None
    best_parent: Parent | None = None
    top_score = -1.0

    for face_row, student, school_class, parent in candidates:
        if len(face_row.embedding) != len(query_embedding):
            continue
        score = cosine_similarity(query_embedding, face_row.embedding)
        if score > top_score:
            top_score = score
            best_student = student
            best_class = school_class
            best_parent = parent

    if best_student is None:
        return None, None, None, 0.0
    return best_student, best_class, best_parent, max(0.0, top_score)


# ---------------------------------------------------------------------------
# Teacher Dashboard & Session Endpoints
# ---------------------------------------------------------------------------


@router.get("/teacher/dashboard", response_model=TeacherDashboardResponse)
async def get_teacher_dashboard(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> TeacherDashboardResponse:
    """Return today's stats, attendance sessions, and schedules for the authenticated teacher."""
    today = _wib_now().date()
    today_dow = today.isoweekday()

    sessions = await _query_session_summaries(db, current_user.id, today)

    present_count = sum(s.present_count for s in sessions)
    late_count = sum(s.late_count for s in sessions)
    total_recorded = sum(s.recorded_count for s in sessions)
    present_rate = (
        round((present_count + late_count) / total_recorded * 100.0, 2)
        if total_recorded > 0
        else 0.0
    )

    pending_leaves_count = (
        await db.scalar(
            select(func.count(LeaveRequest.id)).where(LeaveRequest.status == "pending")
        )
    ) or 0

    schedule_rows = (
        await db.execute(
            select(Schedule, SchoolClass.name.label("class_name"))
            .join(SchoolClass, Schedule.class_id == SchoolClass.id)
            .where(
                Schedule.teacher_id == current_user.id,
                Schedule.day_of_week == today_dow,
            )
            .order_by(Schedule.start_time)
        )
    ).all()
    today_schedules = [
        ScheduleResponse(
            id=sched.id,
            class_id=sched.class_id,
            class_name=c_name,
            teacher_id=sched.teacher_id,
            teacher_name=current_user.name,
            subject_name=sched.subject_name,
            day_of_week=sched.day_of_week,
            start_time=sched.start_time,
            end_time=sched.end_time,
            late_tolerance_minutes=sched.late_tolerance_minutes,
        )
        for sched, c_name in schedule_rows
    ]

    return TeacherDashboardResponse(
        teacher_name=current_user.name,
        today_date=today,
        stats=TeacherDashboardStats(
            present_rate=present_rate,
            present_count=present_count,
            late_count=late_count,
            pending_leaves_count=int(pending_leaves_count),
        ),
        sessions=sessions,
        today_schedules=today_schedules,
    )


@router.post(
    "/sessions",
    response_model=AttendanceSessionSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_attendance_session(
    payload: AttendanceSessionCreate,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> AttendanceSessionSummary:
    """Open a new gate or subject attendance session."""
    class_id = payload.class_id
    expected_start_time = payload.expected_start_time
    late_tolerance_minutes = payload.late_tolerance_minutes
    subject_name: str | None = None

    if payload.schedule_id is not None:
        schedule = await db.get(Schedule, payload.schedule_id)
        if schedule is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Jadwal pelajaran tidak ditemukan.",
            )
        if class_id is None:
            class_id = schedule.class_id
        elif class_id != schedule.class_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Kelas sesi tidak sesuai dengan jadwal pelajaran.",
            )
        if expected_start_time is None:
            expected_start_time = schedule.start_time
        if late_tolerance_minutes is None:
            late_tolerance_minutes = schedule.late_tolerance_minutes
        subject_name = schedule.subject_name

    if payload.session_type == "subject" and class_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Sesi mata pelajaran wajib memilih kelas atau jadwal.",
        )

    class_name: str | None = None
    total_students = 0
    if class_id is not None:
        school_class = await db.get(SchoolClass, class_id)
        if school_class is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Kelas tidak ditemukan.",
            )
        class_name = school_class.name
        total_students = int(
            (
                await db.scalar(
                    select(func.count(Student.id)).where(
                        Student.class_id == class_id,
                        Student.is_active.is_(True),
                    )
                )
            )
            or 0
        )

    session_row = AttendanceSession(
        class_id=class_id,
        teacher_id=current_user.id,
        schedule_id=payload.schedule_id,
        session_type=payload.session_type,
        session_date=payload.session_date or _wib_now().date(),
        expected_start_time=expected_start_time,
        late_tolerance_minutes=15 if late_tolerance_minutes is None else late_tolerance_minutes,
        status="open",
    )
    db.add(session_row)
    await db.commit()
    await db.refresh(session_row)

    return AttendanceSessionSummary(
        id=session_row.id,
        class_id=session_row.class_id,
        class_name=class_name,
        teacher_id=session_row.teacher_id,
        teacher_name=current_user.name,
        schedule_id=session_row.schedule_id,
        subject_name=subject_name,
        session_type=session_row.session_type,
        session_date=session_row.session_date,
        expected_start_time=session_row.expected_start_time,
        late_tolerance_minutes=session_row.late_tolerance_minutes,
        opened_at=session_row.opened_at,
        closed_at=session_row.closed_at,
        status=session_row.status,
        total_students=total_students,
        unrecorded_count=total_students,
    )


@router.get("/sessions/{session_id}", response_model=AttendanceSessionDetailResponse)
async def get_attendance_session_detail(
    session_id: str,
    _: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> AttendanceSessionDetailResponse:
    """Return session metadata, summary counters, and real-time per-student statuses."""
    return await _build_session_detail(db, session_id)


@router.post("/sessions/{session_id}/close", response_model=AttendanceSessionDetailResponse)
async def close_attendance_session(
    session_id: str,
    _: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> AttendanceSessionDetailResponse:
    """Close an open session and automatically mark unrecorded class students as absent."""
    session_row = await db.get(AttendanceSession, session_id)
    if session_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sesi presensi tidak ditemukan.",
        )
    if session_row.status == "closed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sesi presensi sudah ditutup sebelumnya.",
        )

    if session_row.class_id is not None:
        active_student_ids = (
            await db.scalars(
                select(Student.id).where(
                    Student.class_id == session_row.class_id,
                    Student.is_active.is_(True),
                )
            )
        ).all()
        recorded_student_ids = set(
            (
                await db.scalars(
                    select(Attendance.student_id).where(Attendance.session_id == session_row.id)
                )
            ).all()
        )
        for student_id in active_student_ids:
            if student_id not in recorded_student_ids:
                db.add(
                    Attendance(
                        session_id=session_row.id,
                        student_id=student_id,
                        status="absent",
                        verification_method="manual_teacher",
                        scanned_at=None,
                        similarity_score=None,
                        wa_status="skipped",
                        wa_notified_at=None,
                    )
                )

    session_row.status = "closed"
    session_row.closed_at = _utc_now()
    await db.commit()

    return await _build_session_detail(db, session_id)


# ---------------------------------------------------------------------------
# Kiosk Face Scan, Manual PIN Override & WA Resend
# ---------------------------------------------------------------------------


@router.post("/attendance/scan", response_model=AttendanceScanResponse)
async def scan_kiosk_face(
    session_id: str = Form(...),
    liveness_passed: bool = Form(...),
    file: UploadFile = File(...),
    condition_note: str | None = Form(default=None),
    _: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    face_engine: FaceEngine = Depends(get_face_engine),
    whatsapp_provider: WhatsAppProvider = Depends(get_whatsapp_provider),
) -> AttendanceScanResponse:
    """Process a kiosk face scan, record attendance, log telemetry, and notify parent WA."""
    session_row, _, _, subject_name = await _get_session_with_meta(db, session_id)
    if session_row.status != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sesi presensi sudah ditutup. Tidak dapat memindai wajah.",
        )

    if not liveness_passed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verifikasi keaktifan (liveness) gagal. Mohon berkedip saat memindai.",
        )

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="File foto wajah kosong.",
        )
    if len(image_bytes) > MAX_FACE_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Ukuran file foto melebihi batas maksimal 10 MB.",
        )

    normalized_note = condition_note.strip() or None if condition_note is not None else None
    started_at = time_perf.perf_counter()

    try:
        extraction = await asyncio.to_thread(face_engine.extract_single_face, image_bytes)
    except FaceValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.message,
        ) from exc

    if extraction.face_count != 1 or len(extraction.embedding) != EMBEDDING_DIM:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Foto harus menampilkan tepat satu wajah yang jelas.",
        )

    session_id_val = session_row.id
    session_type_val = session_row.session_type
    session_date_val = session_row.session_date
    expected_start_time_val = session_row.expected_start_time
    late_tolerance_minutes_val = session_row.late_tolerance_minutes

    best_student, best_class, best_parent, top_score = await _match_best_student(
        db, extraction.embedding, session_row.class_id
    )
    latency_ms = max(0, int(round((time_perf.perf_counter() - started_at) * 1000)))
    threshold = await get_active_face_threshold(db, default=settings.face_similarity_threshold)
    rounded_score = round(float(top_score), 4)

    if best_student is None or best_class is None or best_parent is None or top_score < threshold:
        db.add(
            FaceRecognitionLog(
                session_id=session_id_val,
                predicted_student_id=None,
                top_similarity_score=rounded_score,
                threshold_used=threshold,
                liveness_passed=True,
                is_match=False,
                latency_ms=latency_ms,
                condition_note=normalized_note,
            )
        )
        await db.commit()
        return AttendanceScanResponse(
            matched=False,
            already_recorded=False,
            similarity_score=rounded_score,
            threshold_used=threshold,
            wa_queued=False,
            message="Wajah tidak dikenali. Silakan posisikan ulang wajah Anda.",
        )

    best_student_id = best_student.id
    best_student_name = best_student.name
    best_student_nis = best_student.nis
    best_class_name = best_class.name
    best_parent_phone_wa = best_parent.phone_wa

    existing_attendance = await db.scalar(
        select(Attendance).where(
            Attendance.session_id == session_id_val,
            Attendance.student_id == best_student_id,
        )
    )
    if existing_attendance is not None:
        existing_att_id = existing_attendance.id
        existing_att_status = existing_attendance.status
        existing_att_scanned_at = existing_attendance.scanned_at
        existing_att_wa_status = existing_attendance.wa_status
        db.add(
            FaceRecognitionLog(
                session_id=session_id_val,
                predicted_student_id=best_student_id,
                top_similarity_score=rounded_score,
                threshold_used=threshold,
                liveness_passed=True,
                is_match=True,
                latency_ms=latency_ms,
                condition_note=normalized_note,
            )
        )
        await db.commit()
        return AttendanceScanResponse(
            matched=True,
            already_recorded=True,
            attendance_id=existing_att_id,
            student_id=best_student_id,
            student_name=best_student_name,
            nis=best_student_nis,
            class_name=best_class_name,
            status=existing_att_status,
            scanned_at=existing_att_scanned_at,
            similarity_score=rounded_score,
            threshold_used=threshold,
            wa_status=existing_att_wa_status,
            wa_queued=False,
            message=f"{best_student_name} sudah tercatat presensi pada sesi ini.",
        )

    scanned_at = _utc_now()
    attendance_status = _resolve_scan_status(
        session_date_val,
        expected_start_time_val,
        late_tolerance_minutes_val,
        scanned_at,
    )
    attendance = Attendance(
        session_id=session_id_val,
        student_id=best_student_id,
        status=attendance_status,
        verification_method="face_kiosk",
        scanned_at=scanned_at,
        similarity_score=rounded_score,
        wa_status="pending",
    )
    face_log = FaceRecognitionLog(
        session_id=session_id_val,
        predicted_student_id=best_student_id,
        top_similarity_score=rounded_score,
        threshold_used=threshold,
        liveness_passed=True,
        is_match=True,
        latency_ms=latency_ms,
        condition_note=normalized_note,
    )
    db.add_all([attendance, face_log])
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        concurrent_existing = await db.scalar(
            select(Attendance).where(
                Attendance.session_id == session_id_val,
                Attendance.student_id == best_student_id,
            )
        )
        if concurrent_existing is not None:
            concurrent_att_id = concurrent_existing.id
            concurrent_att_status = concurrent_existing.status
            concurrent_att_scanned_at = concurrent_existing.scanned_at
            concurrent_att_wa_status = concurrent_existing.wa_status
            db.add(
                FaceRecognitionLog(
                    session_id=session_id_val,
                    predicted_student_id=best_student_id,
                    top_similarity_score=rounded_score,
                    threshold_used=threshold,
                    liveness_passed=True,
                    is_match=True,
                    latency_ms=latency_ms,
                    condition_note=normalized_note,
                )
            )
            await db.commit()
            return AttendanceScanResponse(
                matched=True,
                already_recorded=True,
                attendance_id=concurrent_att_id,
                student_id=best_student_id,
                student_name=best_student_name,
                nis=best_student_nis,
                class_name=best_class_name,
                status=concurrent_att_status,
                scanned_at=concurrent_att_scanned_at,
                similarity_score=rounded_score,
                threshold_used=threshold,
                wa_status=concurrent_att_wa_status,
                wa_queued=False,
                message=f"{best_student_name} sudah tercatat presensi pada sesi ini.",
            )
        raise

    await db.refresh(attendance)
    attendance_id_val = attendance.id
    attendance_status_val = attendance.status
    attendance_scanned_at = attendance.scanned_at

    session_label = _build_session_label(session_type_val, subject_name)
    _, wa_status_val, _ = await _dispatch_attendance_wa(
        db=db,
        whatsapp_provider=whatsapp_provider,
        attendance=attendance,
        student_name=best_student_name,
        class_name=best_class_name,
        parent_phone_wa=best_parent_phone_wa,
        session_label=session_label,
    )

    status_label = ATTENDANCE_STATUS_LABELS_ID.get(attendance_status_val, attendance_status_val)
    return AttendanceScanResponse(
        matched=True,
        already_recorded=False,
        attendance_id=attendance_id_val,
        student_id=best_student_id,
        student_name=best_student_name,
        nis=best_student_nis,
        class_name=best_class_name,
        status=attendance_status_val,
        scanned_at=attendance_scanned_at,
        similarity_score=rounded_score,
        threshold_used=threshold,
        wa_status=wa_status_val,
        wa_queued=True,
        message=f"Presensi {best_student_name} berhasil dicatat ({status_label}).",
    )


@router.post(
    "/attendance/manual",
    response_model=ManualAttendanceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_manual_attendance(
    payload: ManualAttendanceRequest,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
    whatsapp_provider: WhatsAppProvider = Depends(get_whatsapp_provider),
) -> ManualAttendanceResponse:
    """Record or update manual teacher attendance after verifying the teacher's kiosk PIN."""
    if not current_user.kiosk_pin_hash:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PIN Kiosk belum diatur. Silakan atur PIN Kiosk terlebih dahulu.",
        )
    if not verify_secret(payload.kiosk_pin, current_user.kiosk_pin_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PIN Kiosk tidak valid.",
        )

    session_row, _, _, subject_name = await _get_session_with_meta(db, payload.session_id)
    if session_row.status != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sesi presensi sudah ditutup. Tidak dapat mencatat presensi manual.",
        )

    student_row = (
        await db.execute(
            select(Student, SchoolClass, Parent)
            .join(SchoolClass, Student.class_id == SchoolClass.id)
            .join(Parent, Student.parent_id == Parent.id)
            .where(Student.id == payload.student_id)
        )
    ).first()
    if student_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Siswa tidak ditemukan.",
        )
    student, school_class, parent = student_row

    if not student.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Siswa berstatus tidak aktif.",
        )

    if session_row.class_id is not None and student.class_id != session_row.class_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Siswa tidak terdaftar pada kelas sesi ini.",
        )

    session_id_val = session_row.id
    session_type_val = session_row.session_type
    student_id_val = student.id
    student_name_val = student.name
    student_nis_val = student.nis
    class_name_val = school_class.name
    parent_phone_wa_val = parent.phone_wa

    now_utc = _utc_now()
    attendance = await db.scalar(
        select(Attendance).where(
            Attendance.session_id == session_id_val,
            Attendance.student_id == student_id_val,
        )
    )
    if attendance is None:
        attendance = Attendance(
            session_id=session_id_val,
            student_id=student_id_val,
            status=payload.status,
            verification_method="manual_teacher",
            scanned_at=now_utc,
            similarity_score=None,
            wa_status="pending" if payload.notify_wa else "skipped",
        )
        db.add(attendance)
    else:
        attendance.status = payload.status
        attendance.verification_method = "manual_teacher"
        if attendance.scanned_at is None:
            attendance.scanned_at = now_utc
        if payload.notify_wa:
            attendance.wa_status = "pending"
        elif attendance.wa_status != "sent":
            attendance.wa_status = "skipped"

    await db.commit()
    await db.refresh(attendance)

    attendance_id_val = attendance.id
    attendance_session_id = attendance.session_id
    attendance_status_val = attendance.status
    attendance_method_val = attendance.verification_method
    attendance_scanned_at = attendance.scanned_at
    attendance_wa_status = attendance.wa_status
    attendance_wa_notified_at = attendance.wa_notified_at

    if payload.notify_wa:
        session_label = _build_session_label(session_type_val, subject_name)
        _, attendance_wa_status, attendance_wa_notified_at = await _dispatch_attendance_wa(
            db=db,
            whatsapp_provider=whatsapp_provider,
            attendance=attendance,
            student_name=student_name_val,
            class_name=class_name_val,
            parent_phone_wa=parent_phone_wa_val,
            session_label=session_label,
        )

    return ManualAttendanceResponse(
        attendance_id=attendance_id_val,
        session_id=attendance_session_id,
        student_id=student_id_val,
        student_name=student_name_val,
        nis=student_nis_val,
        class_name=class_name_val,
        status=attendance_status_val,
        verification_method=attendance_method_val,
        scanned_at=attendance_scanned_at,
        wa_status=attendance_wa_status,
        wa_notified_at=attendance_wa_notified_at,
        message=f"Presensi manual untuk {student_name_val} berhasil disimpan.",
    )


@router.post("/attendance/{attendance_id}/resend-wa", response_model=ResendWaResponse)
async def resend_attendance_wa(
    attendance_id: str,
    _: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
    whatsapp_provider: WhatsAppProvider = Depends(get_whatsapp_provider),
) -> ResendWaResponse:
    """Retry sending a parent WhatsApp notification for an existing attendance record."""
    row = (
        await db.execute(
            select(
                Attendance,
                AttendanceSession,
                Student,
                SchoolClass,
                Parent,
                Schedule.subject_name.label("subject_name"),
            )
            .join(AttendanceSession, Attendance.session_id == AttendanceSession.id)
            .join(Student, Attendance.student_id == Student.id)
            .join(SchoolClass, Student.class_id == SchoolClass.id)
            .join(Parent, Student.parent_id == Parent.id)
            .outerjoin(Schedule, AttendanceSession.schedule_id == Schedule.id)
            .where(Attendance.id == attendance_id)
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data presensi tidak ditemukan.",
        )

    attendance, session_row, student, school_class, parent, subject_name = row
    attendance_id_val = attendance.id
    student_name_val = student.name
    class_name_val = school_class.name
    parent_phone_wa_val = parent.phone_wa
    session_label = _build_session_label(session_row.session_type, subject_name)

    sent, wa_status_val, wa_notified_at_val = await _dispatch_attendance_wa(
        db=db,
        whatsapp_provider=whatsapp_provider,
        attendance=attendance,
        student_name=student_name_val,
        class_name=class_name_val,
        parent_phone_wa=parent_phone_wa_val,
        session_label=session_label,
    )

    return ResendWaResponse(
        attendance_id=attendance_id_val,
        wa_status=wa_status_val,
        wa_sent=sent,
        wa_notified_at=wa_notified_at_val,
        message=(
            "Notifikasi WhatsApp berhasil dikirim ulang ke orang tua siswa."
            if sent
            else "Gagal mengirim ulang notifikasi WhatsApp. Periksa koneksi gateway WA."
        ),
    )

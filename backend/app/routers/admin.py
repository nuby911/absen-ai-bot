import asyncio
import csv
from datetime import date, datetime, time, timedelta, timezone
import io
from pathlib import Path
from typing import Literal, TypeVar
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.models import (
    Attendance,
    AttendanceSession,
    ChatbotLog,
    FaceEmbedding,
    FaceRecognitionLog,
    LeaveRequest,
    Parent,
    Schedule,
    SchoolClass,
    Student,
    SystemSetting,
    User,
)
from app.providers.face_engine import (
    EMBEDDING_DIM,
    MAX_FACE_IMAGE_BYTES,
    FaceEngine,
    FaceValidationError,
    get_face_engine,
    read_upload_bytes_limited,
    reencode_clean_jpeg,
)
from app.providers.llm import LLMProvider, get_llm_provider
from app.providers.whatsapp import (
    ATTENDANCE_STATUS_LABELS_ID,
    WhatsAppProvider,
    get_whatsapp_provider,
)
from app.schemas import (
    ChatbotEvaluationMetrics,
    ChatbotLogItem,
    ChatbotSimulateRequest,
    ClassDailyRecap,
    EvaluationDashboardResponse,
    FaceEmbeddingResponse,
    FaceEvaluationMetrics,
    FaceLogLabelRequest,
    FaceRecognitionLogItem,
    FaceThresholdResponse,
    FaceThresholdUpdateRequest,
    PaginatedChatbotLogsResponse,
    PaginatedFaceLogsResponse,
    ParentCreate,
    ParentResponse,
    ParentUpdate,
    ScheduleCreate,
    ScheduleResponse,
    ScheduleUpdate,
    SchoolClassCreate,
    SchoolClassResponse,
    SchoolClassUpdate,
    StudentCreate,
    StudentResponse,
    StudentUpdate,
    TeacherCreate,
    TeacherUpdate,
    UserResponse,
    WhatsAppWebhookResponse,
)
from app.security import (
    get_current_user,
    hash_secret_async,
    require_admin,
    require_staff,
)
from app.services.chatbot import ChatbotOrchestrator

router = APIRouter(prefix="/api/v1", tags=["admin"])

WIB = timezone(timedelta(hours=7))
FACE_THRESHOLD_SETTING_KEY = "face_similarity_threshold"
MAX_FACES_PER_STUDENT = 5
MIN_FACE_QUALITY_SCORE = 0.5

_SESSION_TYPE_LABELS_ID: dict[str, str] = {
    "gate_in": "Gerbang Masuk",
    "gate_out": "Gerbang Pulang",
    "subject": "Sesi Mata Pelajaran",
}

_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

_VERIFICATION_METHOD_LABELS_ID: dict[str, str] = {
    "face_kiosk": "Scan Wajah Kiosk",
    "manual_teacher": "Input Manual Guru",
    "leave_approved": "Izin Disetujui Guru",
    "face_recognition": "Scan Wajah Kiosk",
    "chatbot_leave": "Izin Disetujui Guru",
}

_WA_STATUS_LABELS_ID: dict[str, str] = {
    "sent": "Terkirim",
    "failed": "Gagal",
    "pending": "Menunggu",
    "skipped": "Dilewati",
}

ModelT = TypeVar("ModelT")


async def get_active_face_threshold(db: AsyncSession, default: float = 0.55) -> float:
    """Load the active cosine similarity threshold from system_settings, or return default."""
    setting = await db.get(SystemSetting, FACE_THRESHOLD_SETTING_KEY)
    if setting is None:
        return default
    try:
        parsed = float(setting.value)
    except (TypeError, ValueError):
        return default
    if not (0.2 <= parsed <= 0.95):
        return default
    return parsed


async def _get_or_404(
    db: AsyncSession,
    model: type[ModelT],
    entity_id: str,
    not_found_detail: str,
) -> ModelT:
    row = await db.get(model, entity_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        )
    return row


async def _validate_teacher_user(
    db: AsyncSession,
    user_id: str,
    not_found_detail: str = "Guru tidak ditemukan.",
) -> User:
    teacher = await _get_or_404(db, User, user_id, not_found_detail)
    if teacher.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Pengguna yang dipilih harus memiliki peran guru.",
        )
    return teacher


async def _ensure_unique_parent_phone(
    db: AsyncSession,
    phone_wa: str,
    exclude_id: str | None = None,
) -> None:
    stmt = select(Parent.id).where(Parent.phone_wa == phone_wa)
    if exclude_id is not None:
        stmt = stmt.where(Parent.id != exclude_id)
    if (await db.scalar(stmt)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nomor WhatsApp orang tua sudah terdaftar.",
        )


async def _ensure_unique_student_nis(
    db: AsyncSession,
    nis: str,
    exclude_id: str | None = None,
) -> None:
    stmt = select(Student.id).where(Student.nis == nis)
    if exclude_id is not None:
        stmt = stmt.where(Student.id != exclude_id)
    if (await db.scalar(stmt)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="NIS siswa sudah terdaftar.",
        )


async def _ensure_unique_user_email(
    db: AsyncSession,
    email: str,
    exclude_id: str | None = None,
) -> None:
    stmt = select(User.id).where(func.lower(User.email) == email.lower())
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    if (await db.scalar(stmt)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email akun sudah terdaftar.",
        )


async def _ensure_unique_user_nip(
    db: AsyncSession,
    nip: str | None,
    exclude_id: str | None = None,
) -> None:
    if nip is None:
        return
    stmt = select(User.id).where(User.nip == nip)
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    if (await db.scalar(stmt)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="NIP guru sudah terdaftar.",
        )


async def _ensure_unique_class_name(
    db: AsyncSession,
    name: str,
    exclude_id: str | None = None,
) -> None:
    stmt = select(SchoolClass.id).where(func.lower(SchoolClass.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(SchoolClass.id != exclude_id)
    if (await db.scalar(stmt)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nama kelas sudah terdaftar.",
        )


async def _ensure_no_schedule_overlap(
    db: AsyncSession,
    *,
    class_id: str,
    teacher_id: str,
    day_of_week: int,
    start_time: time,
    end_time: time,
    exclude_id: str | None = None,
) -> None:
    class_stmt = select(Schedule.id).where(
        Schedule.class_id == class_id,
        Schedule.day_of_week == day_of_week,
        Schedule.start_time < end_time,
        Schedule.end_time > start_time,
    )
    if exclude_id is not None:
        class_stmt = class_stmt.where(Schedule.id != exclude_id)
    if (await db.scalar(class_stmt.limit(1))) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Jadwal bentrok dengan mata pelajaran lain di kelas yang sama.",
        )

    teacher_stmt = select(Schedule.id).where(
        Schedule.teacher_id == teacher_id,
        Schedule.day_of_week == day_of_week,
        Schedule.start_time < end_time,
        Schedule.end_time > start_time,
    )
    if exclude_id is not None:
        teacher_stmt = teacher_stmt.where(Schedule.id != exclude_id)
    if (await db.scalar(teacher_stmt.limit(1))) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Guru sudah memiliki jadwal mengajar yang bentrok pada hari dan jam tersebut.",
        )


def _raise_student_integrity_error(exc: IntegrityError) -> None:
    raw = str(getattr(exc, "orig", exc)).lower()
    if "phone_wa" in raw or "parents" in raw:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nomor WhatsApp orang tua sudah terdaftar.",
        ) from exc
    if "nis" in raw:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="NIS siswa sudah terdaftar.",
        ) from exc
    if "foreign key" in raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Referensi kelas atau orang tua tidak valid.",
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Data siswa konflik dengan data yang sudah terdaftar.",
    ) from exc


def _raise_teacher_integrity_error(exc: IntegrityError) -> None:
    raw = str(getattr(exc, "orig", exc)).lower()
    if "nip" in raw:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="NIP guru sudah terdaftar.",
        ) from exc
    if "email" in raw:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email akun sudah terdaftar.",
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Data guru konflik dengan akun yang sudah terdaftar.",
    ) from exc


def _delete_upload_file_if_exists(upload_dir: str, image_path: str) -> None:
    if not image_path or not image_path.strip():
        return
    raw_path = Path(image_path)
    if raw_path.is_absolute():
        return
    upload_root = Path(upload_dir).resolve()
    raw_candidate = Path(upload_dir) / raw_path
    if raw_candidate.is_symlink():
        return
    try:
        resolved_candidate = raw_candidate.resolve()
    except OSError:
        return
    if not resolved_candidate.is_relative_to(upload_root):
        return
    if resolved_candidate.exists() and resolved_candidate.is_file():
        resolved_candidate.unlink()


async def _query_classes(
    db: AsyncSession,
    class_id: str | None = None,
) -> list[SchoolClassResponse]:
    student_count_subq = (
        select(
            Student.class_id,
            func.count(Student.id).label("student_count"),
        )
        .where(Student.is_active.is_(True))
        .group_by(Student.class_id)
        .subquery()
    )
    stmt = (
        select(
            SchoolClass,
            User.name.label("homeroom_teacher_name"),
            func.coalesce(student_count_subq.c.student_count, 0).label("student_count"),
        )
        .outerjoin(User, SchoolClass.homeroom_teacher_id == User.id)
        .outerjoin(student_count_subq, SchoolClass.id == student_count_subq.c.class_id)
        .order_by(SchoolClass.name)
    )
    if class_id is not None:
        stmt = stmt.where(SchoolClass.id == class_id)

    rows = (await db.execute(stmt)).all()
    return [
        SchoolClassResponse(
            id=school_class.id,
            name=school_class.name,
            homeroom_teacher_id=school_class.homeroom_teacher_id,
            homeroom_teacher_name=teacher_name,
            student_count=int(student_count or 0),
            created_at=school_class.created_at,
        )
        for school_class, teacher_name, student_count in rows
    ]


async def _query_students(
    db: AsyncSession,
    class_id: str | None = None,
    student_id: str | None = None,
    is_active: bool | None = None,
) -> list[StudentResponse]:
    face_count_subq = (
        select(
            FaceEmbedding.student_id,
            func.count(FaceEmbedding.id).label("face_count"),
        )
        .group_by(FaceEmbedding.student_id)
        .subquery()
    )
    stmt = (
        select(
            Student,
            SchoolClass.name.label("class_name"),
            Parent.name.label("parent_name"),
            Parent.phone_wa.label("parent_phone_wa"),
            func.coalesce(face_count_subq.c.face_count, 0).label("face_count"),
        )
        .join(SchoolClass, Student.class_id == SchoolClass.id)
        .join(Parent, Student.parent_id == Parent.id)
        .outerjoin(face_count_subq, Student.id == face_count_subq.c.student_id)
        .order_by(Student.name)
    )
    if class_id is not None:
        stmt = stmt.where(Student.class_id == class_id)
    if student_id is not None:
        stmt = stmt.where(Student.id == student_id)
    if is_active is not None:
        stmt = stmt.where(Student.is_active.is_(is_active))

    rows = (await db.execute(stmt)).all()
    return [
        StudentResponse(
            id=student.id,
            nis=student.nis,
            name=student.name,
            class_id=student.class_id,
            class_name=class_name,
            parent_id=student.parent_id,
            parent_name=parent_name,
            parent_phone_wa=parent_phone_wa,
            is_active=student.is_active,
            face_count=int(face_count or 0),
            created_at=student.created_at,
        )
        for student, class_name, parent_name, parent_phone_wa, face_count in rows
    ]


async def _query_schedules(
    db: AsyncSession,
    class_id: str | None = None,
    teacher_id: str | None = None,
    day_of_week: int | None = None,
    schedule_id: str | None = None,
) -> list[ScheduleResponse]:
    stmt = (
        select(
            Schedule,
            SchoolClass.name.label("class_name"),
            User.name.label("teacher_name"),
        )
        .join(SchoolClass, Schedule.class_id == SchoolClass.id)
        .join(User, Schedule.teacher_id == User.id)
        .order_by(Schedule.day_of_week, Schedule.start_time)
    )
    if class_id is not None:
        stmt = stmt.where(Schedule.class_id == class_id)
    if teacher_id is not None:
        stmt = stmt.where(Schedule.teacher_id == teacher_id)
    if day_of_week is not None:
        stmt = stmt.where(Schedule.day_of_week == day_of_week)
    if schedule_id is not None:
        stmt = stmt.where(Schedule.id == schedule_id)

    rows = (await db.execute(stmt)).all()
    return [
        ScheduleResponse(
            id=schedule.id,
            class_id=schedule.class_id,
            class_name=class_name,
            teacher_id=schedule.teacher_id,
            teacher_name=teacher_name,
            subject_name=schedule.subject_name,
            day_of_week=schedule.day_of_week,
            start_time=schedule.start_time,
            end_time=schedule.end_time,
            late_tolerance_minutes=schedule.late_tolerance_minutes,
        )
        for schedule, class_name, teacher_name in rows
    ]


def _to_face_response(face: FaceEmbedding) -> FaceEmbeddingResponse:
    normalized_path = face.image_path.lstrip("/")
    return FaceEmbeddingResponse(
        id=face.id,
        student_id=face.student_id,
        image_path=face.image_path,
        image_url=f"/uploads/{normalized_path}",
        quality_score=face.quality_score,
        embedding_dim=len(face.embedding),
        created_at=face.created_at,
    )


# ---------------------------------------------------------------------------
# Teachers CRUD
# ---------------------------------------------------------------------------


@router.get("/teachers", response_model=list[UserResponse])
async def list_teachers(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[UserResponse]:
    """List all staff users with role 'teacher' ordered alphabetically by name."""
    teachers = (
        await db.scalars(
            select(User).where(User.role == "teacher").order_by(User.name)
        )
    ).all()
    return [UserResponse.from_user(teacher) for teacher in teachers]


@router.post("/teachers", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_teacher(
    payload: TeacherCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Create a new teacher account (admin only)."""
    await _ensure_unique_user_email(db, payload.email)
    await _ensure_unique_user_nip(db, payload.nip)

    password_hash = await hash_secret_async(payload.password)
    kiosk_pin_hash = (
        await hash_secret_async(payload.kiosk_pin) if payload.kiosk_pin is not None else None
    )

    teacher = User(
        name=payload.name,
        email=payload.email,
        password_hash=password_hash,
        role="teacher",
        nip=payload.nip,
        kiosk_pin_hash=kiosk_pin_hash,
    )
    db.add(teacher)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        _raise_teacher_integrity_error(exc)
    await db.refresh(teacher)
    return UserResponse.from_user(teacher)


@router.put("/teachers/{teacher_id}", response_model=UserResponse)
async def update_teacher(
    teacher_id: str,
    payload: TeacherUpdate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Update an existing teacher's profile, credentials, or kiosk PIN (admin only)."""
    teacher = await db.scalar(
        select(User).where(User.id == teacher_id, User.role == "teacher")
    )
    if teacher is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guru tidak ditemukan.",
        )

    if "name" in payload.model_fields_set and payload.name is not None:
        teacher.name = payload.name
    if "email" in payload.model_fields_set and payload.email is not None:
        await _ensure_unique_user_email(db, payload.email, exclude_id=teacher.id)
        teacher.email = payload.email
    if "nip" in payload.model_fields_set:
        await _ensure_unique_user_nip(db, payload.nip, exclude_id=teacher.id)
        teacher.nip = payload.nip
    if payload.password is not None:
        teacher.password_hash = await hash_secret_async(payload.password)
    if payload.reset_kiosk_pin:
        teacher.kiosk_pin_hash = None
    elif payload.kiosk_pin is not None:
        teacher.kiosk_pin_hash = await hash_secret_async(payload.kiosk_pin)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        _raise_teacher_integrity_error(exc)
    await db.refresh(teacher)
    return UserResponse.from_user(teacher)


@router.delete("/teachers/{teacher_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_teacher(
    teacher_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a teacher if no schedules or attendance sessions depend on them."""
    teacher = await db.scalar(
        select(User).where(User.id == teacher_id, User.role == "teacher")
    )
    if teacher is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guru tidak ditemukan.",
        )

    has_schedule = await db.scalar(
        select(Schedule.id).where(Schedule.teacher_id == teacher.id).limit(1)
    )
    has_session = await db.scalar(
        select(AttendanceSession.id).where(AttendanceSession.teacher_id == teacher.id).limit(1)
    )
    if has_schedule is not None or has_session is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Guru tidak dapat dihapus karena masih memiliki jadwal mengajar atau riwayat sesi presensi.",
        )

    try:
        await db.execute(
            update(SchoolClass)
            .where(SchoolClass.homeroom_teacher_id == teacher.id)
            .values(homeroom_teacher_id=None)
        )
        await db.execute(
            update(LeaveRequest)
            .where(LeaveRequest.verified_by == teacher.id)
            .values(verified_by=None)
        )
        await db.delete(teacher)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Guru tidak dapat dihapus karena masih terhubung dengan data lain.",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Classes CRUD
# ---------------------------------------------------------------------------


@router.get("/classes", response_model=list[SchoolClassResponse])
async def list_classes(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SchoolClassResponse]:
    """List all academic classes (accessible by admin and teachers)."""
    return await _query_classes(db)


@router.post("/classes", response_model=SchoolClassResponse, status_code=status.HTTP_201_CREATED)
async def create_class(
    payload: SchoolClassCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SchoolClassResponse:
    """Create a new academic class (admin only)."""
    await _ensure_unique_class_name(db, payload.name)
    if payload.homeroom_teacher_id is not None:
        await _validate_teacher_user(
            db,
            payload.homeroom_teacher_id,
            not_found_detail="Guru wali kelas tidak ditemukan.",
        )

    school_class = SchoolClass(
        name=payload.name,
        homeroom_teacher_id=payload.homeroom_teacher_id,
    )
    db.add(school_class)
    await db.commit()
    return (await _query_classes(db, class_id=school_class.id))[0]


@router.put("/classes/{class_id}", response_model=SchoolClassResponse)
async def update_class(
    class_id: str,
    payload: SchoolClassUpdate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SchoolClassResponse:
    """Update an existing academic class (admin only)."""
    school_class = await _get_or_404(db, SchoolClass, class_id, "Kelas tidak ditemukan.")

    if "name" in payload.model_fields_set and payload.name is not None:
        await _ensure_unique_class_name(db, payload.name, exclude_id=class_id)
        school_class.name = payload.name
    if "homeroom_teacher_id" in payload.model_fields_set:
        if payload.homeroom_teacher_id is not None:
            await _validate_teacher_user(
                db,
                payload.homeroom_teacher_id,
                not_found_detail="Guru wali kelas tidak ditemukan.",
            )
        school_class.homeroom_teacher_id = payload.homeroom_teacher_id

    await db.commit()
    return (await _query_classes(db, class_id=school_class.id))[0]


@router.delete("/classes/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_class(
    class_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete an academic class if no students, schedules, or sessions reference it."""
    school_class = await _get_or_404(db, SchoolClass, class_id, "Kelas tidak ditemukan.")
    try:
        await db.delete(school_class)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Kelas tidak dapat dihapus karena masih memiliki data siswa, jadwal, atau sesi absensi.",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Parents CRUD
# ---------------------------------------------------------------------------


@router.get("/parents", response_model=list[ParentResponse])
async def list_parents(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[ParentResponse]:
    """List all registered parents/guardians (admin only)."""
    parents = (await db.scalars(select(Parent).order_by(Parent.name))).all()
    return [
        ParentResponse(
            id=parent.id,
            name=parent.name,
            phone_wa=parent.phone_wa,
            created_at=parent.created_at,
        )
        for parent in parents
    ]


@router.post("/parents", response_model=ParentResponse, status_code=status.HTTP_201_CREATED)
async def create_parent(
    payload: ParentCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ParentResponse:
    """Register a parent with canonicalized WhatsApp phone number (admin only)."""
    await _ensure_unique_parent_phone(db, payload.phone_wa)

    parent = Parent(name=payload.name, phone_wa=payload.phone_wa)
    db.add(parent)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nomor WhatsApp orang tua sudah terdaftar.",
        ) from exc
    await db.refresh(parent)
    return ParentResponse(
        id=parent.id,
        name=parent.name,
        phone_wa=parent.phone_wa,
        created_at=parent.created_at,
    )


@router.put("/parents/{parent_id}", response_model=ParentResponse)
async def update_parent(
    parent_id: str,
    payload: ParentUpdate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ParentResponse:
    """Update parent details and re-normalize WhatsApp phone number (admin only)."""
    parent = await _get_or_404(db, Parent, parent_id, "Data orang tua tidak ditemukan.")

    if "name" in payload.model_fields_set and payload.name is not None:
        parent.name = payload.name
    if "phone_wa" in payload.model_fields_set and payload.phone_wa is not None:
        await _ensure_unique_parent_phone(db, payload.phone_wa, exclude_id=parent_id)
        parent.phone_wa = payload.phone_wa

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nomor WhatsApp orang tua sudah terdaftar.",
        ) from exc
    await db.refresh(parent)
    return ParentResponse(
        id=parent.id,
        name=parent.name,
        phone_wa=parent.phone_wa,
        created_at=parent.created_at,
    )


@router.delete("/parents/{parent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_parent(
    parent_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a parent if no student or leave request references them."""
    parent = await _get_or_404(db, Parent, parent_id, "Data orang tua tidak ditemukan.")
    try:
        await db.execute(
            update(ChatbotLog)
            .where(ChatbotLog.parent_id == parent.id)
            .values(parent_id=None)
        )
        await db.delete(parent)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Data orang tua tidak dapat dihapus karena masih terhubung dengan siswa atau izin.",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Students CRUD
# ---------------------------------------------------------------------------


@router.get("/students", response_model=list[StudentResponse])
async def list_students(
    class_id: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    _: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
) -> list[StudentResponse]:
    """List students with class name, parent WA info, and face count (admin & teachers)."""
    return await _query_students(db, class_id=class_id, is_active=is_active)


@router.post("/students", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
async def create_student(
    payload: StudentCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> StudentResponse:
    """Create a student, linking an existing parent or creating/reusing one inline by WA phone."""
    await _get_or_404(db, SchoolClass, payload.class_id, "Kelas tidak ditemukan.")
    await _ensure_unique_student_nis(db, payload.nis)

    if payload.parent_id is not None:
        await _get_or_404(db, Parent, payload.parent_id, "Data orang tua tidak ditemukan.")
        resolved_parent_id = payload.parent_id
    else:
        assert payload.parent_phone_wa is not None and payload.parent_name is not None
        existing_parent = await db.scalar(
            select(Parent).where(Parent.phone_wa == payload.parent_phone_wa)
        )
        if existing_parent is not None:
            resolved_parent_id = existing_parent.id
        else:
            new_parent = Parent(
                name=payload.parent_name,
                phone_wa=payload.parent_phone_wa,
            )
            db.add(new_parent)
            await db.flush()
            resolved_parent_id = new_parent.id

    student = Student(
        nis=payload.nis,
        name=payload.name,
        class_id=payload.class_id,
        parent_id=resolved_parent_id,
        is_active=payload.is_active,
    )
    db.add(student)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        _raise_student_integrity_error(exc)
    return (await _query_students(db, student_id=student.id))[0]


@router.put("/students/{student_id}", response_model=StudentResponse)
async def update_student(
    student_id: str,
    payload: StudentUpdate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> StudentResponse:
    """Update student profile, class assignment, active flag, or inline parent link/contact."""
    student = await _get_or_404(db, Student, student_id, "Siswa tidak ditemukan.")

    if "nis" in payload.model_fields_set and payload.nis is not None:
        await _ensure_unique_student_nis(db, payload.nis, exclude_id=student_id)
        student.nis = payload.nis
    if "name" in payload.model_fields_set and payload.name is not None:
        student.name = payload.name
    if "class_id" in payload.model_fields_set and payload.class_id is not None:
        await _get_or_404(db, SchoolClass, payload.class_id, "Kelas tidak ditemukan.")
        student.class_id = payload.class_id

    if payload.parent_phone_wa is not None:
        if payload.update_linked_parent:
            linked_parent = await _get_or_404(
                db, Parent, student.parent_id, "Data orang tua tidak ditemukan."
            )
            await _ensure_unique_parent_phone(
                db, payload.parent_phone_wa, exclude_id=linked_parent.id
            )
            linked_parent.phone_wa = payload.parent_phone_wa
            if payload.parent_name is not None:
                linked_parent.name = payload.parent_name
        else:
            existing_parent = await db.scalar(
                select(Parent).where(Parent.phone_wa == payload.parent_phone_wa)
            )
            if existing_parent is not None:
                student.parent_id = existing_parent.id
            else:
                if payload.parent_name is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail="Nama orang tua wajib diisi saat mendaftarkan nomor WhatsApp baru.",
                    )
                new_parent = Parent(
                    name=payload.parent_name,
                    phone_wa=payload.parent_phone_wa,
                )
                db.add(new_parent)
                await db.flush()
                student.parent_id = new_parent.id
    elif payload.update_linked_parent and payload.parent_name is not None:
        linked_parent = await _get_or_404(
            db, Parent, student.parent_id, "Data orang tua tidak ditemukan."
        )
        linked_parent.name = payload.parent_name
    elif "parent_id" in payload.model_fields_set and payload.parent_id is not None:
        await _get_or_404(db, Parent, payload.parent_id, "Data orang tua tidak ditemukan.")
        student.parent_id = payload.parent_id

    if "is_active" in payload.model_fields_set and payload.is_active is not None:
        student.is_active = payload.is_active

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        _raise_student_integrity_error(exc)
    return (await _query_students(db, student_id=student.id))[0]


@router.delete("/students/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student(
    student_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Delete a student without attendance/leave history and remove stored face files."""
    student = await _get_or_404(db, Student, student_id, "Siswa tidak ditemukan.")
    face_paths = (
        await db.scalars(
            select(FaceEmbedding.image_path).where(FaceEmbedding.student_id == student.id)
        )
    ).all()

    try:
        await db.execute(
            update(FaceRecognitionLog)
            .where(FaceRecognitionLog.predicted_student_id == student.id)
            .values(predicted_student_id=None)
        )
        await db.execute(
            update(FaceRecognitionLog)
            .where(FaceRecognitionLog.actual_student_id == student.id)
            .values(actual_student_id=None)
        )
        await db.delete(student)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Siswa tidak dapat dihapus karena sudah memiliki riwayat presensi atau pengajuan izin.",
        ) from exc

    for image_path in face_paths:
        _delete_upload_file_if_exists(settings.upload_dir, image_path)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Schedules CRUD
# ---------------------------------------------------------------------------


@router.get("/schedules", response_model=list[ScheduleResponse])
async def list_schedules(
    class_id: str | None = Query(default=None),
    teacher_id: str | None = Query(default=None),
    day_of_week: int | None = Query(default=None, ge=1, le=7),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ScheduleResponse]:
    """List weekly schedules with optional filters (accessible by admin and teachers)."""
    return await _query_schedules(
        db,
        class_id=class_id,
        teacher_id=teacher_id,
        day_of_week=day_of_week,
    )


@router.post("/schedules", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    payload: ScheduleCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    """Create a weekly teaching schedule (admin only) rejecting overlapping intervals."""
    await _get_or_404(db, SchoolClass, payload.class_id, "Kelas tidak ditemukan.")
    await _validate_teacher_user(db, payload.teacher_id)
    await _ensure_no_schedule_overlap(
        db,
        class_id=payload.class_id,
        teacher_id=payload.teacher_id,
        day_of_week=payload.day_of_week,
        start_time=payload.start_time,
        end_time=payload.end_time,
    )

    schedule = Schedule(
        class_id=payload.class_id,
        teacher_id=payload.teacher_id,
        subject_name=payload.subject_name,
        day_of_week=payload.day_of_week,
        start_time=payload.start_time,
        end_time=payload.end_time,
        late_tolerance_minutes=payload.late_tolerance_minutes,
    )
    db.add(schedule)
    await db.commit()
    return (await _query_schedules(db, schedule_id=schedule.id))[0]


@router.put("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: str,
    payload: ScheduleUpdate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    """Update an existing weekly teaching schedule (admin only) rejecting overlaps."""
    schedule = await _get_or_404(db, Schedule, schedule_id, "Jadwal pelajaran tidak ditemukan.")

    if "class_id" in payload.model_fields_set and payload.class_id is not None:
        await _get_or_404(db, SchoolClass, payload.class_id, "Kelas tidak ditemukan.")
        schedule.class_id = payload.class_id
    if "teacher_id" in payload.model_fields_set and payload.teacher_id is not None:
        await _validate_teacher_user(db, payload.teacher_id)
        schedule.teacher_id = payload.teacher_id
    if "subject_name" in payload.model_fields_set and payload.subject_name is not None:
        schedule.subject_name = payload.subject_name
    if "day_of_week" in payload.model_fields_set and payload.day_of_week is not None:
        schedule.day_of_week = payload.day_of_week
    if "start_time" in payload.model_fields_set and payload.start_time is not None:
        schedule.start_time = payload.start_time
    if "end_time" in payload.model_fields_set and payload.end_time is not None:
        schedule.end_time = payload.end_time
    if (
        "late_tolerance_minutes" in payload.model_fields_set
        and payload.late_tolerance_minutes is not None
    ):
        schedule.late_tolerance_minutes = payload.late_tolerance_minutes

    if schedule.end_time <= schedule.start_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Jam selesai harus lebih lambat dari jam mulai.",
        )

    await _ensure_no_schedule_overlap(
        db,
        class_id=schedule.class_id,
        teacher_id=schedule.teacher_id,
        day_of_week=schedule.day_of_week,
        start_time=schedule.start_time,
        end_time=schedule.end_time,
        exclude_id=schedule.id,
    )

    await db.commit()
    return (await _query_schedules(db, schedule_id=schedule.id))[0]


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a teaching schedule if no attendance sessions depend on it."""
    schedule = await _get_or_404(db, Schedule, schedule_id, "Jadwal pelajaran tidak ditemukan.")
    try:
        await db.delete(schedule)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Jadwal tidak dapat dihapus karena sudah digunakan pada sesi presensi.",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Face Dataset Registration (3-5 Samples per Student)
# ---------------------------------------------------------------------------


@router.get("/students/{student_id}/faces", response_model=list[FaceEmbeddingResponse])
async def list_student_faces(
    student_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[FaceEmbeddingResponse]:
    """List all registered face samples for a student (admin only)."""
    student = await _get_or_404(db, Student, student_id, "Siswa tidak ditemukan.")
    faces = (
        await db.scalars(
            select(FaceEmbedding)
            .where(FaceEmbedding.student_id == student.id)
            .order_by(FaceEmbedding.created_at)
        )
    ).all()
    return [_to_face_response(face) for face in faces]


@router.post(
    "/students/{student_id}/faces",
    response_model=FaceEmbeddingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_student_face(
    student_id: str,
    file: UploadFile = File(...),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    face_engine: FaceEngine = Depends(get_face_engine),
) -> FaceEmbeddingResponse:
    """Validate and register one face sample (up to 5 active samples per student)."""
    student = await _get_or_404(db, Student, student_id, "Siswa tidak ditemukan.")

    active_count = (
        await db.scalar(
            select(func.count(FaceEmbedding.id)).where(FaceEmbedding.student_id == student.id)
        )
    ) or 0
    if active_count >= MAX_FACES_PER_STUDENT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maksimal 5 sampel foto wajah aktif per siswa telah tercapai. "
            "Hapus salah satu sampel sebelum mengunggah foto baru.",
        )

    image_bytes = await read_upload_bytes_limited(file, MAX_FACE_IMAGE_BYTES)
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="File foto wajah kosong.",
        )

    try:
        result = await asyncio.to_thread(face_engine.extract_single_face, image_bytes)
    except FaceValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.message,
        ) from exc

    if result.face_count == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Wajah tidak terdeteksi pada foto. Pastikan wajah terlihat jelas.",
        )
    if result.face_count > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Terdeteksi lebih dari satu wajah pada foto. Gunakan foto dengan tepat satu wajah.",
        )
    if result.face_count != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Foto harus menampilkan tepat satu wajah.",
        )
    if result.quality_score < MIN_FACE_QUALITY_SCORE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Kualitas foto wajah terlalu rendah (< 0.5). Gunakan foto yang lebih jelas.",
        )
    if len(result.embedding) != EMBEDDING_DIM:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Hasil ekstraksi vektor wajah tidak valid.",
        )

    try:
        clean_jpeg_bytes = await asyncio.to_thread(reencode_clean_jpeg, image_bytes, 90)
    except FaceValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.message,
        ) from exc

    face_id = str(uuid.uuid4())
    relative_path = f"faces/{student.id}/{face_id}.jpg"
    target_path = Path(settings.upload_dir) / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(clean_jpeg_bytes)

    embedding_row = FaceEmbedding(
        id=face_id,
        student_id=student.id,
        image_path=relative_path,
        embedding=[float(v) for v in result.embedding],
        quality_score=float(result.quality_score),
    )
    db.add(embedding_row)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        if target_path.exists():
            target_path.unlink()
        raise

    await db.refresh(embedding_row)
    return _to_face_response(embedding_row)


@router.delete(
    "/students/{student_id}/faces/{face_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_student_face(
    student_id: str,
    face_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Delete a registered face sample from the database and disk."""
    student = await _get_or_404(db, Student, student_id, "Siswa tidak ditemukan.")
    face = await db.scalar(
        select(FaceEmbedding).where(
            FaceEmbedding.id == face_id,
            FaceEmbedding.student_id == student.id,
        )
    )
    if face is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sampel foto wajah tidak ditemukan.",
        )

    image_path = face.image_path
    await db.delete(face)
    await db.commit()
    _delete_upload_file_if_exists(settings.upload_dir, image_path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Face Recognition Threshold Settings
# ---------------------------------------------------------------------------


@router.get("/settings/face-threshold", response_model=FaceThresholdResponse)
async def get_face_threshold_setting(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FaceThresholdResponse:
    """Return the active cosine similarity threshold for face recognition."""
    threshold = await get_active_face_threshold(
        db,
        default=settings.face_similarity_threshold,
    )
    return FaceThresholdResponse(threshold=threshold)


@router.put("/settings/face-threshold", response_model=FaceThresholdResponse)
async def update_face_threshold_setting(
    payload: FaceThresholdUpdateRequest,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FaceThresholdResponse:
    """Persist a new cosine similarity threshold (0.20 to 0.95) in system_settings."""
    setting = await db.get(SystemSetting, FACE_THRESHOLD_SETTING_KEY)
    serialized = f"{payload.threshold:.4f}".rstrip("0").rstrip(".")
    if setting is None:
        setting = SystemSetting(key=FACE_THRESHOLD_SETTING_KEY, value=serialized)
        db.add(setting)
    else:
        setting.value = serialized

    await db.commit()
    return FaceThresholdResponse(threshold=payload.threshold)


# ---------------------------------------------------------------------------
# Scientific Evaluation Metrics, Lab Labeling & CSV Export (Task 7)
# ---------------------------------------------------------------------------


def _is_impostor_note(condition_note: str | None) -> bool:
    return bool(condition_note and condition_note.strip().lower().startswith("impostor"))


def _strip_impostor_prefix(condition_note: str | None) -> str | None:
    if condition_note is None:
        return None
    stripped = condition_note.strip()
    if not stripped:
        return None
    lowered = stripped.lower()
    if lowered == "impostor":
        return None
    if lowered.startswith("impostor:"):
        return stripped[len("impostor:") :].strip() or None
    return stripped


def _is_log_impostor(log: FaceRecognitionLog) -> bool:
    return bool(
        log.is_impostor
        or (log.actual_student_id is None and _is_impostor_note(log.condition_note))
    )


def _classify_face_log(log: FaceRecognitionLog) -> str:
    """Classify one face scan log into TP, FP, FN, TN, or unlabeled."""
    if log.actual_student_id is not None:
        if log.is_match and log.predicted_student_id == log.actual_student_id:
            return "TP"
        if log.is_match:
            return "FP"
        return "FN"

    if _is_log_impostor(log):
        return "FP" if log.is_match else "TN"
    return "unlabeled"


def _to_face_log_item(
    log: FaceRecognitionLog,
    student_names: dict[str, str],
) -> FaceRecognitionLogItem:
    return FaceRecognitionLogItem(
        id=log.id,
        session_id=log.session_id,
        predicted_student_id=log.predicted_student_id,
        predicted_student_name=(
            student_names.get(log.predicted_student_id)
            if log.predicted_student_id is not None
            else None
        ),
        actual_student_id=log.actual_student_id,
        actual_student_name=(
            student_names.get(log.actual_student_id)
            if log.actual_student_id is not None
            else None
        ),
        top_similarity_score=log.top_similarity_score,
        threshold_used=log.threshold_used,
        liveness_passed=log.liveness_passed,
        is_match=log.is_match,
        latency_ms=log.latency_ms,
        condition_note=log.condition_note,
        is_impostor=log.actual_student_id is None and _is_log_impostor(log),
        classification=_classify_face_log(log),
        created_at=log.created_at,
    )


def _to_chatbot_log_item(row: ChatbotLog) -> ChatbotLogItem:
    return ChatbotLogItem(
        id=row.id,
        created_at=row.created_at,
        phone_wa=row.phone_wa,
        user_message=row.user_message,
        bot_response=row.bot_response,
        detected_intent=row.detected_intent,
        tool_called=row.tool_called,
        is_in_domain=row.is_in_domain,
        is_fallback=row.is_fallback,
        latency_ms=row.latency_ms,
    )


def _format_wib_csv_timestamp(dt: datetime | None) -> str:
    if dt is None:
        return ""
    target = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    return target.astimezone(WIB).strftime("%d/%m/%Y %H:%M WIB")


def _sanitize_csv_cell(value: object) -> str:
    """Neutralize spreadsheet formula injection by prefixing risky leading characters with `'`."""
    text = "" if value is None else str(value)
    if text and (
        text[0] in _CSV_FORMULA_PREFIXES
        or text.lstrip()[0:1] in _CSV_FORMULA_PREFIXES
    ):
        return f"'{text}"
    return text


def _build_csv_session_label(session_type: str, subject_name: str | None) -> str:
    if subject_name:
        return f"Mata Pelajaran {subject_name}"
    return _SESSION_TYPE_LABELS_ID.get(session_type, "Sesi Presensi")


@router.get("/evaluation/metrics", response_model=EvaluationDashboardResponse)
async def get_evaluation_metrics(
    recap_date: date | None = Query(default=None),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> EvaluationDashboardResponse:
    """Return Confusion Matrix (FAR/FRR), chatbot metrics, and daily class recaps."""
    target_date = recap_date or datetime.now(WIB).date()

    face_logs = (
        await db.scalars(
            select(FaceRecognitionLog).order_by(
                FaceRecognitionLog.created_at.desc(),
                FaceRecognitionLog.id.desc(),
            )
        )
    ).all()

    student_rows = (await db.execute(select(Student.id, Student.name))).all()
    student_names = {student_id: name for student_id, name in student_rows}

    tp = fp = fn = tn = 0
    total_face_latency = 0
    for log in face_logs:
        total_face_latency += log.latency_ms
        label = _classify_face_log(log)
        if label == "TP":
            tp += 1
        elif label == "FP":
            fp += 1
        elif label == "FN":
            fn += 1
        elif label == "TN":
            tn += 1

    total_scans = len(face_logs)
    total_labeled = tp + fp + fn + tn
    accuracy = round((tp + tn) / total_labeled * 100.0, 2) if total_labeled > 0 else 0.0
    far = round(fp / (fp + tn) * 100.0, 2) if (fp + tn) > 0 else 0.0
    frr = round(fn / (fn + tp) * 100.0, 2) if (fn + tp) > 0 else 0.0
    avg_scan_latency_ms = (
        round(total_face_latency / total_scans, 2) if total_scans > 0 else 0.0
    )
    active_threshold = await get_active_face_threshold(
        db,
        default=settings.face_similarity_threshold,
    )

    face_metrics = FaceEvaluationMetrics(
        total_scans=total_scans,
        total_labeled=total_labeled,
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
        accuracy=accuracy,
        far=far,
        frr=frr,
        avg_scan_latency_ms=avg_scan_latency_ms,
        threshold=active_threshold,
    )

    chatbot_logs = (
        await db.scalars(
            select(ChatbotLog).order_by(
                ChatbotLog.created_at.desc(),
                ChatbotLog.id.desc(),
            )
        )
    ).all()
    total_messages = len(chatbot_logs)
    domain_eligible_logs = [
        row for row in chatbot_logs if row.detected_intent != "unregistered_parent"
    ]
    in_domain_count = sum(1 for row in domain_eligible_logs if row.is_in_domain)
    out_of_domain_count = sum(1 for row in domain_eligible_logs if not row.is_in_domain)
    domain_denominator = len(domain_eligible_logs)
    fallback_count = sum(1 for row in chatbot_logs if row.is_fallback)
    in_domain_rate = (
        round(in_domain_count / domain_denominator * 100.0, 2)
        if domain_denominator > 0
        else 0.0
    )
    fallback_rate = (
        round(fallback_count / total_messages * 100.0, 2) if total_messages > 0 else 0.0
    )
    avg_chatbot_latency_ms = (
        round(sum(row.latency_ms for row in chatbot_logs) / total_messages, 2)
        if total_messages > 0
        else 0.0
    )

    chatbot_metrics = ChatbotEvaluationMetrics(
        total_messages=total_messages,
        in_domain_count=in_domain_count,
        out_of_domain_count=out_of_domain_count,
        in_domain_rate=in_domain_rate,
        fallback_count=fallback_count,
        fallback_rate=fallback_rate,
        avg_latency_ms=avg_chatbot_latency_ms,
        recent_logs=[_to_chatbot_log_item(row) for row in chatbot_logs[:20]],
    )

    class_rows = (
        await db.execute(
            select(SchoolClass, User.name.label("homeroom_teacher_name"))
            .outerjoin(User, SchoolClass.homeroom_teacher_id == User.id)
            .order_by(SchoolClass.name)
        )
    ).all()

    recap_map: dict[str, ClassDailyRecap] = {
        school_class.id: ClassDailyRecap(
            class_id=school_class.id,
            class_name=school_class.name,
            homeroom_teacher_name=teacher_name,
        )
        for school_class, teacher_name in class_rows
    }
    session_ids_by_class: dict[str, set[str]] = {cid: set() for cid in recap_map}

    day_sessions = (
        await db.execute(
            select(AttendanceSession.id, AttendanceSession.class_id).where(
                AttendanceSession.session_date == target_date
            )
        )
    ).all()
    for sess_id, sess_class_id in day_sessions:
        if sess_class_id is not None and sess_class_id in session_ids_by_class:
            session_ids_by_class[sess_class_id].add(sess_id)

    attendance_rows = (
        await db.execute(
            select(
                Student.class_id,
                Attendance.session_id,
                Attendance.status,
                Attendance.wa_status,
            )
            .join(AttendanceSession, Attendance.session_id == AttendanceSession.id)
            .join(Student, Attendance.student_id == Student.id)
            .where(AttendanceSession.session_date == target_date)
        )
    ).all()

    for cls_id, sess_id, att_status, wa_status in attendance_rows:
        recap = recap_map.get(cls_id)
        if recap is None:
            continue
        session_ids_by_class[cls_id].add(sess_id)
        if att_status == "present":
            recap.present_count += 1
        elif att_status == "late":
            recap.late_count += 1
        elif att_status in ("permit", "sick"):
            recap.permit_or_sick_count += 1
        elif att_status == "absent":
            recap.absent_count += 1

        if wa_status != "skipped":
            recap.wa_total_count += 1
            if wa_status == "sent":
                recap.wa_sent_count += 1

    for cls_id, recap in recap_map.items():
        recap.session_count = len(session_ids_by_class[cls_id])

    return EvaluationDashboardResponse(
        recap_date=target_date,
        face_metrics=face_metrics,
        chatbot_metrics=chatbot_metrics,
        class_recaps=list(recap_map.values()),
        recent_face_logs=[_to_face_log_item(log, student_names) for log in face_logs[:20]],
    )


@router.get("/evaluation/face-logs", response_model=PaginatedFaceLogsResponse)
async def list_evaluation_face_logs(
    status_filter: Literal["all", "labeled", "unlabeled", "errors"] = Query(
        default="all", alias="status"
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PaginatedFaceLogsResponse:
    """List paginated kiosk face recognition logs filterable by labeling status or errors."""
    face_logs = (
        await db.scalars(
            select(FaceRecognitionLog).order_by(
                FaceRecognitionLog.created_at.desc(),
                FaceRecognitionLog.id.desc(),
            )
        )
    ).all()

    filtered: list[FaceRecognitionLog] = []
    for log in face_logs:
        cls_label = _classify_face_log(log)
        if status_filter == "all":
            filtered.append(log)
        elif status_filter == "labeled" and cls_label != "unlabeled":
            filtered.append(log)
        elif status_filter == "unlabeled" and cls_label == "unlabeled":
            filtered.append(log)
        elif status_filter == "errors" and cls_label in {"FP", "FN"}:
            filtered.append(log)

    page = filtered[offset : offset + limit]
    student_ids = {
        sid
        for log in page
        for sid in (log.predicted_student_id, log.actual_student_id)
        if sid is not None
    }
    student_names: dict[str, str] = {}
    if student_ids:
        rows = (
            await db.execute(
                select(Student.id, Student.name).where(Student.id.in_(student_ids))
            )
        ).all()
        student_names = {sid: name for sid, name in rows}

    return PaginatedFaceLogsResponse(
        items=[_to_face_log_item(log, student_names) for log in page],
        total=len(filtered),
        limit=limit,
        offset=offset,
    )


@router.get("/evaluation/chatbot-logs", response_model=PaginatedChatbotLogsResponse)
async def list_evaluation_chatbot_logs(
    in_domain: Literal["all", "true", "false"] = Query(default="all"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PaginatedChatbotLogsResponse:
    """List paginated WhatsApp AI chatbot logs with optional domain filtering."""
    base_stmt = select(ChatbotLog)
    count_stmt = select(func.count(ChatbotLog.id))
    if in_domain == "true":
        base_stmt = base_stmt.where(ChatbotLog.is_in_domain.is_(True))
        count_stmt = count_stmt.where(ChatbotLog.is_in_domain.is_(True))
    elif in_domain == "false":
        base_stmt = base_stmt.where(ChatbotLog.is_in_domain.is_(False))
        count_stmt = count_stmt.where(ChatbotLog.is_in_domain.is_(False))

    total = int((await db.scalar(count_stmt)) or 0)
    rows = (
        await db.scalars(
            base_stmt.order_by(ChatbotLog.created_at.desc(), ChatbotLog.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()

    return PaginatedChatbotLogsResponse(
        items=[_to_chatbot_log_item(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/evaluation/chatbot-simulate", response_model=WhatsAppWebhookResponse)
async def simulate_chatbot_message(
    payload: ChatbotSimulateRequest,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    llm_provider: LLMProvider = Depends(get_llm_provider),
    whatsapp_provider: WhatsAppProvider = Depends(get_whatsapp_provider),
) -> WhatsAppWebhookResponse:
    """Run an admin dry-run simulation against ChatbotOrchestrator without sending WAHA messages."""
    orchestrator = ChatbotOrchestrator(
        llm_provider=llm_provider,
        whatsapp_provider=whatsapp_provider,
    )
    return await orchestrator.handle_incoming_message(
        db=db,
        phone_wa_raw=payload.phone_wa,
        message_text=payload.message_text,
        media_url=payload.media_url,
        send_wa=False,
    )


@router.post(
    "/evaluation/face-logs/{log_id}/label",
    response_model=FaceRecognitionLogItem,
)
async def label_face_recognition_log(
    log_id: str,
    payload: FaceLogLabelRequest,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FaceRecognitionLogItem:
    """Assign or clear ground-truth student or impostor label on a face recognition log."""
    log = await _get_or_404(
        db,
        FaceRecognitionLog,
        log_id,
        "Log pengenalan wajah tidak ditemukan.",
    )

    if payload.is_impostor:
        log.is_impostor = True
        log.actual_student_id = None
        if "condition_note" in payload.model_fields_set:
            log.condition_note = _strip_impostor_prefix(payload.condition_note)
        else:
            log.condition_note = _strip_impostor_prefix(log.condition_note)
    elif payload.actual_student_id is not None:
        await _get_or_404(
            db,
            Student,
            payload.actual_student_id,
            "Siswa tidak ditemukan.",
        )
        log.is_impostor = False
        log.actual_student_id = payload.actual_student_id
        if "condition_note" in payload.model_fields_set:
            log.condition_note = _strip_impostor_prefix(payload.condition_note)
        else:
            log.condition_note = _strip_impostor_prefix(log.condition_note)
    else:
        # Cleanly unlabel the log
        log.is_impostor = False
        log.actual_student_id = None
        if "condition_note" in payload.model_fields_set:
            log.condition_note = _strip_impostor_prefix(payload.condition_note)
        else:
            log.condition_note = _strip_impostor_prefix(log.condition_note)

    await db.commit()
    await db.refresh(log)

    student_ids = {
        sid for sid in (log.predicted_student_id, log.actual_student_id) if sid is not None
    }
    student_names: dict[str, str] = {}
    if student_ids:
        rows = (
            await db.execute(
                select(Student.id, Student.name).where(Student.id.in_(student_ids))
            )
        ).all()
        student_names = {sid: name for sid, name in rows}

    return _to_face_log_item(log, student_names)


@router.get("/reports/attendance.csv")
async def export_attendance_csv(
    class_id: str | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export attendance records as a formula-safe downloadable UTF-8 CSV report."""
    if start_date is not None and end_date is not None and end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Tanggal akhir tidak boleh lebih awal dari tanggal mulai.",
        )

    stmt = (
        select(
            Attendance,
            AttendanceSession,
            Student,
            SchoolClass,
            Schedule.subject_name.label("subject_name"),
        )
        .join(AttendanceSession, Attendance.session_id == AttendanceSession.id)
        .join(Student, Attendance.student_id == Student.id)
        .join(SchoolClass, Student.class_id == SchoolClass.id)
        .outerjoin(Schedule, AttendanceSession.schedule_id == Schedule.id)
        .order_by(
            AttendanceSession.session_date.desc(),
            SchoolClass.name.asc(),
            Student.name.asc(),
        )
    )
    if class_id is not None:
        stmt = stmt.where(Student.class_id == class_id)
    if start_date is not None:
        stmt = stmt.where(AttendanceSession.session_date >= start_date)
    if end_date is not None:
        stmt = stmt.where(AttendanceSession.session_date <= end_date)

    rows = (await db.execute(stmt)).all()

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "Tanggal",
            "Sesi / Mata Pelajaran",
            "Kelas",
            "NIS",
            "Nama Siswa",
            "Status",
            "Metode Verifikasi",
            "Waktu Scan",
            "Status WA",
        ]
    )
    for att, session_row, student, school_class, subject_name in rows:
        raw_row = [
            session_row.session_date.isoformat(),
            _build_csv_session_label(session_row.session_type, subject_name),
            school_class.name,
            student.nis,
            student.name,
            ATTENDANCE_STATUS_LABELS_ID.get(att.status, att.status),
            _VERIFICATION_METHOD_LABELS_ID.get(
                att.verification_method, att.verification_method
            ),
            _format_wib_csv_timestamp(att.scanned_at),
            _WA_STATUS_LABELS_ID.get(att.wa_status, att.wa_status),
        ]
        writer.writerow([_sanitize_csv_cell(cell) for cell in raw_row])

    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="rekap-absensi.csv"'},
    )

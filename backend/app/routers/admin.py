import asyncio
import csv
from datetime import date, datetime, timedelta, timezone
import io
from pathlib import Path
from typing import TypeVar
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select
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
    Parent,
    Schedule,
    SchoolClass,
    Student,
    SystemSetting,
    User,
)
from app.providers.face_engine import (
    EMBEDDING_DIM,
    FaceEngine,
    FaceValidationError,
    get_face_engine,
)
from app.providers.whatsapp import ATTENDANCE_STATUS_LABELS_ID
from app.schemas import (
    ChatbotEvaluationMetrics,
    ChatbotLogItem,
    ClassDailyRecap,
    EvaluationDashboardResponse,
    FaceEmbeddingResponse,
    FaceEvaluationMetrics,
    FaceLogLabelRequest,
    FaceRecognitionLogItem,
    FaceThresholdResponse,
    FaceThresholdUpdateRequest,
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
    UserResponse,
)
from app.security import get_current_user, require_admin

router = APIRouter(prefix="/api/v1", tags=["admin"])

WIB = timezone(timedelta(hours=7))
FACE_THRESHOLD_SETTING_KEY = "face_similarity_threshold"
MAX_FACES_PER_STUDENT = 5
MIN_FACE_QUALITY_SCORE = 0.5
MAX_FACE_IMAGE_BYTES = 10 * 1024 * 1024

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


def _delete_upload_file_if_exists(upload_dir: str, image_path: str) -> None:
    candidate = Path(image_path)
    if not candidate.is_absolute():
        candidate = Path(upload_dir) / image_path
    if candidate.exists() and candidate.is_file():
        candidate.unlink()


async def _query_classes(
    db: AsyncSession,
    class_id: str | None = None,
) -> list[SchoolClassResponse]:
    student_count_subq = (
        select(
            Student.class_id,
            func.count(Student.id).label("student_count"),
        )
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
# Teachers Listing
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
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[StudentResponse]:
    """List students with class name, parent WA info, and registered face sample count."""
    return await _query_students(db, class_id=class_id)


@router.post("/students", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
async def create_student(
    payload: StudentCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> StudentResponse:
    """Create a new student record linked to an existing class and parent."""
    await _get_or_404(db, SchoolClass, payload.class_id, "Kelas tidak ditemukan.")
    await _get_or_404(db, Parent, payload.parent_id, "Data orang tua tidak ditemukan.")
    await _ensure_unique_student_nis(db, payload.nis)

    student = Student(
        nis=payload.nis,
        name=payload.name,
        class_id=payload.class_id,
        parent_id=payload.parent_id,
        is_active=payload.is_active,
    )
    db.add(student)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="NIS siswa sudah terdaftar.",
        ) from exc
    return (await _query_students(db, student_id=student.id))[0]


@router.put("/students/{student_id}", response_model=StudentResponse)
async def update_student(
    student_id: str,
    payload: StudentUpdate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> StudentResponse:
    """Update student profile, class assignment, parent link, or active flag."""
    student = await _get_or_404(db, Student, student_id, "Siswa tidak ditemukan.")

    if "nis" in payload.model_fields_set and payload.nis is not None:
        await _ensure_unique_student_nis(db, payload.nis, exclude_id=student_id)
        student.nis = payload.nis
    if "name" in payload.model_fields_set and payload.name is not None:
        student.name = payload.name
    if "class_id" in payload.model_fields_set and payload.class_id is not None:
        await _get_or_404(db, SchoolClass, payload.class_id, "Kelas tidak ditemukan.")
        student.class_id = payload.class_id
    if "parent_id" in payload.model_fields_set and payload.parent_id is not None:
        await _get_or_404(db, Parent, payload.parent_id, "Data orang tua tidak ditemukan.")
        student.parent_id = payload.parent_id
    if "is_active" in payload.model_fields_set and payload.is_active is not None:
        student.is_active = payload.is_active

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="NIS siswa sudah terdaftar.",
        ) from exc
    return (await _query_students(db, student_id=student.id))[0]


@router.delete("/students/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student(
    student_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Delete a student without attendance history and remove stored face files."""
    student = await _get_or_404(db, Student, student_id, "Siswa tidak ditemukan.")
    face_paths = (
        await db.scalars(
            select(FaceEmbedding.image_path).where(FaceEmbedding.student_id == student.id)
        )
    ).all()

    try:
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
    """Create a weekly teaching schedule (admin only)."""
    await _get_or_404(db, SchoolClass, payload.class_id, "Kelas tidak ditemukan.")
    await _validate_teacher_user(db, payload.teacher_id)

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
    """Update an existing weekly teaching schedule (admin only)."""
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

    face_id = str(uuid.uuid4())
    relative_path = f"faces/{student.id}/{face_id}.jpg"
    target_path = Path(settings.upload_dir) / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(image_bytes)

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


def _classify_face_log(log: FaceRecognitionLog) -> str:
    """Classify one face scan log into TP, FP, FN, TN, or unlabeled."""
    if log.actual_student_id is not None:
        if log.is_match and log.predicted_student_id == log.actual_student_id:
            return "TP"
        if log.is_match:
            return "FP"
        return "FN"

    if _is_impostor_note(log.condition_note):
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
        is_impostor=log.actual_student_id is None and _is_impostor_note(log.condition_note),
        classification=_classify_face_log(log),
        created_at=log.created_at,
    )


def _format_wib_csv_timestamp(dt: datetime | None) -> str:
    if dt is None:
        return "-"
    target = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    return target.astimezone(WIB).strftime("%d/%m/%Y %H:%M WIB")


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
    in_domain_count = sum(1 for row in chatbot_logs if row.is_in_domain)
    fallback_count = sum(1 for row in chatbot_logs if row.is_fallback)
    in_domain_rate = (
        round(in_domain_count / total_messages * 100.0, 2) if total_messages > 0 else 0.0
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
        in_domain_rate=in_domain_rate,
        fallback_count=fallback_count,
        fallback_rate=fallback_rate,
        avg_latency_ms=avg_chatbot_latency_ms,
        recent_logs=[
            ChatbotLogItem(
                id=row.id,
                created_at=row.created_at,
                phone_wa=row.phone_wa,
                user_message=row.user_message,
                detected_intent=row.detected_intent,
                tool_called=row.tool_called,
                is_in_domain=row.is_in_domain,
                is_fallback=row.is_fallback,
                latency_ms=row.latency_ms,
            )
            for row in chatbot_logs[:20]
        ],
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

    attendance_rows = (
        await db.execute(
            select(Student.class_id, Attendance.status, Attendance.wa_status)
            .join(AttendanceSession, Attendance.session_id == AttendanceSession.id)
            .join(Student, Attendance.student_id == Student.id)
            .where(AttendanceSession.session_date == target_date)
        )
    ).all()

    for cls_id, att_status, wa_status in attendance_rows:
        recap = recap_map.get(cls_id)
        if recap is None:
            continue
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

    return EvaluationDashboardResponse(
        recap_date=target_date,
        face_metrics=face_metrics,
        chatbot_metrics=chatbot_metrics,
        class_recaps=list(recap_map.values()),
        recent_face_logs=[_to_face_log_item(log, student_names) for log in face_logs[:20]],
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
    """Assign ground-truth student or impostor label to a face recognition log."""
    log = await _get_or_404(
        db,
        FaceRecognitionLog,
        log_id,
        "Log pengenalan wajah tidak ditemukan.",
    )

    if payload.is_impostor:
        log.actual_student_id = None
        note = payload.condition_note or ""
        if not note:
            log.condition_note = "impostor"
        elif _is_impostor_note(note):
            log.condition_note = note
        else:
            log.condition_note = f"impostor:{note}"
    else:
        if payload.actual_student_id is not None:
            await _get_or_404(
                db,
                Student,
                payload.actual_student_id,
                "Siswa tidak ditemukan.",
            )
        log.actual_student_id = payload.actual_student_id
        if "condition_note" in payload.model_fields_set:
            log.condition_note = payload.condition_note
        elif payload.actual_student_id is not None and _is_impostor_note(log.condition_note):
            log.condition_note = None

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
    """Export attendance records as a downloadable UTF-8 CSV report."""
    if start_date is not None and end_date is not None and end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Tanggal akhir tidak boleh lebih awal dari tanggal mulai.",
        )

    stmt = (
        select(Attendance, AttendanceSession, Student, SchoolClass)
        .join(AttendanceSession, Attendance.session_id == AttendanceSession.id)
        .join(Student, Attendance.student_id == Student.id)
        .join(SchoolClass, Student.class_id == SchoolClass.id)
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
            "Kelas",
            "NIS",
            "Nama Siswa",
            "Status",
            "Metode Verifikasi",
            "Waktu Scan",
            "Status WA",
        ]
    )
    for att, session_row, student, school_class in rows:
        writer.writerow(
            [
                session_row.session_date.isoformat(),
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
        )

    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="rekap-absensi.csv"'},
    )

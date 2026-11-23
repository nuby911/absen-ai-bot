from datetime import date, datetime, time
import math
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import User
from app.security import normalize_wa_phone


def _strip_required_text(value: str, field_label: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_label} wajib diisi.")
    return stripped


def _strip_optional_text(value: str | None, field_label: str) -> str | None:
    if value is None:
        return None
    return _strip_required_text(value, field_label)


class LoginRequest(BaseModel):
    """Credentials payload accepting either email or NIP as identifier."""

    identifier: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Email atau NIP wajib diisi.")
        return stripped


class UserResponse(BaseModel):
    """Public profile representation of an authenticated staff user."""

    id: str
    name: str
    email: str
    role: str
    nip: str | None
    has_kiosk_pin: bool

    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        return cls(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            nip=user.nip,
            has_kiosk_pin=bool(user.kiosk_pin_hash),
        )


class LoginResponse(BaseModel):
    """Bearer access token response alongside authenticated user metadata."""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class KioskPinUpdateRequest(BaseModel):
    """Payload for setting or updating a teacher's 4–6 digit numeric kiosk PIN."""

    pin: str

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4,6}", value):
            raise ValueError("PIN Kiosk harus terdiri dari 4 hingga 6 digit angka.")
        return value


class KioskPinUpdateResponse(BaseModel):
    """Confirmation returned after updating the kiosk PIN."""

    message: str
    has_kiosk_pin: bool = True


class VerifyPinRequest(BaseModel):
    """Payload for verifying a teacher's kiosk PIN."""

    pin: str = Field(..., min_length=1)


class VerifyPinResponse(BaseModel):
    """Result of kiosk PIN verification."""

    valid: bool


# ---------------------------------------------------------------------------
# Master Data & Face Dataset Schemas (Task 3)
# ---------------------------------------------------------------------------


class SchoolClassCreate(BaseModel):
    """Payload to create an academic class."""

    name: str = Field(..., min_length=1, max_length=100)
    homeroom_teacher_id: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _strip_required_text(value, "Nama kelas")


class SchoolClassUpdate(BaseModel):
    """Payload to update an academic class."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    homeroom_teacher_id: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return _strip_optional_text(value, "Nama kelas")


class SchoolClassResponse(BaseModel):
    """Academic class metadata returned by admin and teacher endpoints."""

    id: str
    name: str
    homeroom_teacher_id: str | None
    homeroom_teacher_name: str | None = None
    student_count: int = 0
    created_at: datetime


class ParentCreate(BaseModel):
    """Payload to register a student parent/guardian with normalized WhatsApp number."""

    name: str = Field(..., min_length=1, max_length=255)
    phone_wa: str = Field(..., min_length=1, max_length=50)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _strip_required_text(value, "Nama orang tua")

    @field_validator("phone_wa")
    @classmethod
    def validate_phone_wa(cls, value: str) -> str:
        return normalize_wa_phone(value)


class ParentUpdate(BaseModel):
    """Payload to update a parent/guardian record."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone_wa: str | None = Field(default=None, min_length=1, max_length=50)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return _strip_optional_text(value, "Nama orang tua")

    @field_validator("phone_wa")
    @classmethod
    def validate_phone_wa(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_wa_phone(value)


class ParentResponse(BaseModel):
    """Parent/guardian representation."""

    id: str
    name: str
    phone_wa: str
    created_at: datetime


class StudentCreate(BaseModel):
    """Payload to register a student linked to a class and parent."""

    nis: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    class_id: str = Field(..., min_length=1)
    parent_id: str = Field(..., min_length=1)
    is_active: bool = True

    @field_validator("nis")
    @classmethod
    def validate_nis(cls, value: str) -> str:
        return _strip_required_text(value, "NIS")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _strip_required_text(value, "Nama siswa")


class StudentUpdate(BaseModel):
    """Payload to update student details."""

    nis: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    class_id: str | None = None
    parent_id: str | None = None
    is_active: bool | None = None

    @field_validator("nis")
    @classmethod
    def validate_nis(cls, value: str | None) -> str | None:
        return _strip_optional_text(value, "NIS")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return _strip_optional_text(value, "Nama siswa")


class StudentResponse(BaseModel):
    """Student detail including class, parent WA info, and face sample count."""

    id: str
    nis: str
    name: str
    class_id: str
    class_name: str
    parent_id: str
    parent_name: str
    parent_phone_wa: str
    is_active: bool
    face_count: int
    created_at: datetime


class ScheduleCreate(BaseModel):
    """Payload to create a weekly subject schedule."""

    class_id: str = Field(..., min_length=1)
    teacher_id: str = Field(..., min_length=1)
    subject_name: str = Field(..., min_length=1, max_length=255)
    day_of_week: int = Field(..., ge=1, le=7)
    start_time: time
    end_time: time
    late_tolerance_minutes: int = Field(default=15, ge=0, le=120)

    @field_validator("subject_name")
    @classmethod
    def validate_subject(cls, value: str) -> str:
        return _strip_required_text(value, "Nama mata pelajaran")

    @model_validator(mode="after")
    def validate_time_range(self) -> "ScheduleCreate":
        if self.end_time <= self.start_time:
            raise ValueError("Jam selesai harus lebih lambat dari jam mulai.")
        return self


class ScheduleUpdate(BaseModel):
    """Payload to update an existing weekly subject schedule."""

    class_id: str | None = None
    teacher_id: str | None = None
    subject_name: str | None = Field(default=None, min_length=1, max_length=255)
    day_of_week: int | None = Field(default=None, ge=1, le=7)
    start_time: time | None = None
    end_time: time | None = None
    late_tolerance_minutes: int | None = Field(default=None, ge=0, le=120)

    @field_validator("subject_name")
    @classmethod
    def validate_subject(cls, value: str | None) -> str | None:
        return _strip_optional_text(value, "Nama mata pelajaran")


class ScheduleResponse(BaseModel):
    """Weekly schedule representation enriched with class and teacher names."""

    id: str
    class_id: str
    class_name: str
    teacher_id: str
    teacher_name: str
    subject_name: str
    day_of_week: int
    start_time: time
    end_time: time
    late_tolerance_minutes: int


class FaceEmbeddingResponse(BaseModel):
    """Registered face sample metadata returned by face dataset endpoints."""

    id: str
    student_id: str
    image_path: str
    image_url: str
    quality_score: float
    embedding_dim: int
    created_at: datetime


class FaceThresholdUpdateRequest(BaseModel):
    """Payload for updating the cosine similarity recognition threshold."""

    threshold: float

    @field_validator("threshold")
    @classmethod
    def validate_threshold(cls, value: float) -> float:
        if not math.isfinite(value) or not (0.2 <= value <= 0.95):
            raise ValueError("Ambang batas kemiripan wajah harus bernilai antara 0.20 dan 0.95.")
        return round(float(value), 4)


class FaceThresholdResponse(BaseModel):
    """Active cosine similarity threshold response."""

    threshold: float


# ---------------------------------------------------------------------------
# Attendance Sessions, Kiosk Scan & Manual Override Schemas (Task 4)
# ---------------------------------------------------------------------------


class AttendanceSessionCreate(BaseModel):
    """Payload to open a gate or subject attendance session."""

    class_id: str | None = None
    schedule_id: str | None = None
    session_type: Literal["gate_in", "gate_out", "subject"]
    session_date: date | None = None
    expected_start_time: time | None = None
    late_tolerance_minutes: int | None = Field(default=None, ge=0, le=120)


class SessionSummaryCounters(BaseModel):
    """Real-time attendance status counters for a session."""

    total_students: int = 0
    present_count: int = 0
    late_count: int = 0
    permit_count: int = 0
    sick_count: int = 0
    absent_count: int = 0
    unrecorded_count: int = 0
    recorded_count: int = 0


class AttendanceSessionSummary(BaseModel):
    """Summary metadata and counters for an attendance session."""

    id: str
    class_id: str | None = None
    class_name: str | None = None
    teacher_id: str
    teacher_name: str | None = None
    schedule_id: str | None = None
    subject_name: str | None = None
    session_type: str
    session_date: date
    expected_start_time: time | None = None
    late_tolerance_minutes: int
    opened_at: datetime
    closed_at: datetime | None = None
    status: str
    total_students: int = 0
    present_count: int = 0
    late_count: int = 0
    permit_count: int = 0
    sick_count: int = 0
    absent_count: int = 0
    unrecorded_count: int = 0
    recorded_count: int = 0


class SessionStudentAttendanceItem(BaseModel):
    """Per-student real-time attendance status within a session."""

    student_id: str
    nis: str
    student_name: str
    class_id: str
    class_name: str
    parent_phone_wa: str
    attendance_id: str | None = None
    status: str
    verification_method: str | None = None
    scanned_at: datetime | None = None
    similarity_score: float | None = None
    wa_status: str | None = None
    wa_notified_at: datetime | None = None


class AttendanceSessionDetailResponse(AttendanceSessionSummary):
    """Full attendance session detail with summary counters and student statuses."""

    summary: SessionSummaryCounters
    students: list[SessionStudentAttendanceItem]


class TeacherDashboardStats(BaseModel):
    """Aggregated teacher dashboard statistics for today."""

    present_rate: float
    present_count: int
    late_count: int
    pending_leaves_count: int


class TeacherDashboardResponse(BaseModel):
    """Teacher mobile home dashboard payload."""

    teacher_name: str
    today_date: date
    stats: TeacherDashboardStats
    sessions: list[AttendanceSessionSummary]
    today_schedules: list[ScheduleResponse]


class AttendanceScanResponse(BaseModel):
    """Structured response returned to the Kiosk scanner after face recognition."""

    matched: bool
    already_recorded: bool
    attendance_id: str | None = None
    student_id: str | None = None
    student_name: str | None = None
    nis: str | None = None
    class_name: str | None = None
    status: str | None = None
    scanned_at: datetime | None = None
    similarity_score: float
    threshold_used: float
    wa_status: str | None = None
    wa_queued: bool
    message: str


class ManualAttendanceRequest(BaseModel):
    """Teacher PIN-verified manual attendance override request."""

    session_id: str = Field(..., min_length=1)
    student_id: str = Field(..., min_length=1)
    status: Literal["present", "late", "permit", "sick", "absent"]
    kiosk_pin: str = Field(..., min_length=1)
    notify_wa: bool = True


class ManualAttendanceResponse(BaseModel):
    """Result of manual teacher attendance entry."""

    attendance_id: str
    session_id: str
    student_id: str
    student_name: str
    nis: str
    class_name: str
    status: str
    verification_method: str
    scanned_at: datetime | None = None
    wa_status: str
    wa_notified_at: datetime | None = None
    message: str


class ResendWaResponse(BaseModel):
    """Result of retrying a parent WhatsApp attendance notification."""

    attendance_id: str
    wa_status: str
    wa_sent: bool
    wa_notified_at: datetime | None = None
    message: str

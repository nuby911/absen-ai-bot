from datetime import date, datetime, time, timezone
import math
import re
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)

from app.models import User
from app.security import normalize_wa_phone

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _serialize_utc_datetime(value: datetime) -> str:
    """Serialize any naive or aware datetime as an explicit UTC ISO-8601 `Z` string."""
    dt_utc = (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )
    return dt_utc.isoformat().replace("+00:00", "Z")


UtcDateTime = Annotated[
    datetime,
    PlainSerializer(_serialize_utc_datetime, return_type=str, when_used="json"),
]


def _strip_required_text(value: str, field_label: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_label} wajib diisi.")
    return stripped


def _strip_optional_text(value: str | None, field_label: str) -> str | None:
    if value is None:
        return None
    return _strip_required_text(value, field_label)


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _validate_email_value(value: str) -> str:
    cleaned = value.strip().lower()
    if not cleaned or not _EMAIL_RE.fullmatch(cleaned):
        raise ValueError("Format email tidak valid.")
    return cleaned


def _validate_pin_format(value: str) -> str:
    if not re.fullmatch(r"\d{4,6}", value):
        raise ValueError("PIN Kiosk harus terdiri dari 4 hingga 6 digit angka.")
    return value


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
    current_pin: str | None = None

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, value: str) -> str:
        return _validate_pin_format(value)

    @field_validator("current_pin")
    @classmethod
    def normalize_current_pin(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


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
    has_kiosk_pin: bool


# ---------------------------------------------------------------------------
# Master Data & Face Dataset Schemas (Task 3)
# ---------------------------------------------------------------------------


class TeacherCreate(BaseModel):
    """Payload to create a teacher account (admin only)."""

    name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=6, max_length=128)
    nip: str | None = Field(default=None, max_length=50)
    kiosk_pin: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _strip_required_text(value, "Nama guru")

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validate_email_value(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not value.strip() or len(value) < 6:
            raise ValueError("Kata sandi minimal 6 karakter.")
        return value

    @field_validator("nip")
    @classmethod
    def normalize_nip(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("kiosk_pin")
    @classmethod
    def validate_kiosk_pin(cls, value: str | None) -> str | None:
        cleaned = _blank_to_none(value)
        if cleaned is None:
            return None
        return _validate_pin_format(cleaned)


class TeacherUpdate(BaseModel):
    """Payload to update an existing teacher account (admin only)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    nip: str | None = Field(default=None, max_length=50)
    password: str | None = Field(default=None, max_length=128)
    kiosk_pin: str | None = None
    reset_kiosk_pin: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return _strip_optional_text(value, "Nama guru")

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_email_value(value)

    @field_validator("nip")
    @classmethod
    def normalize_nip(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not value.strip() or len(value) < 6:
            raise ValueError("Kata sandi minimal 6 karakter.")
        return value

    @field_validator("kiosk_pin")
    @classmethod
    def validate_kiosk_pin(cls, value: str | None) -> str | None:
        cleaned = _blank_to_none(value)
        if cleaned is None:
            return None
        return _validate_pin_format(cleaned)


class SchoolClassCreate(BaseModel):
    """Payload to create an academic class."""

    name: str = Field(..., min_length=1, max_length=100)
    homeroom_teacher_id: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _strip_required_text(value, "Nama kelas")

    @field_validator("homeroom_teacher_id")
    @classmethod
    def normalize_homeroom_teacher_id(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class SchoolClassUpdate(BaseModel):
    """Payload to update an academic class."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    homeroom_teacher_id: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return _strip_optional_text(value, "Nama kelas")

    @field_validator("homeroom_teacher_id")
    @classmethod
    def normalize_homeroom_teacher_id(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class SchoolClassResponse(BaseModel):
    """Academic class metadata returned by admin and teacher endpoints."""

    id: str
    name: str
    homeroom_teacher_id: str | None
    homeroom_teacher_name: str | None = None
    student_count: int = 0
    created_at: UtcDateTime


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
    created_at: UtcDateTime


class StudentCreate(BaseModel):
    """Payload to register a student linked to an existing or inline-created parent."""

    nis: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    class_id: str = Field(..., min_length=1)
    parent_id: str | None = None
    parent_name: str | None = Field(default=None, max_length=255)
    parent_phone_wa: str | None = Field(default=None, max_length=50)
    is_active: bool = True

    @field_validator("nis")
    @classmethod
    def validate_nis(cls, value: str) -> str:
        return _strip_required_text(value, "NIS")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _strip_required_text(value, "Nama siswa")

    @field_validator("parent_id", "parent_name")
    @classmethod
    def normalize_optional_parent_fields(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("parent_phone_wa")
    @classmethod
    def validate_parent_phone_wa(cls, value: str | None) -> str | None:
        cleaned = _blank_to_none(value)
        if cleaned is None:
            return None
        return normalize_wa_phone(cleaned)

    @model_validator(mode="after")
    def validate_parent_reference(self) -> "StudentCreate":
        if self.parent_id is None and (
            self.parent_name is None or self.parent_phone_wa is None
        ):
            raise ValueError(
                "Wajib memilih orang tua (parent_id) atau mengisi nama dan nomor WhatsApp orang tua."
            )
        return self


class StudentUpdate(BaseModel):
    """Payload to update student details and optionally link/update parent inline."""

    nis: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    class_id: str | None = None
    parent_id: str | None = None
    parent_name: str | None = Field(default=None, max_length=255)
    parent_phone_wa: str | None = Field(default=None, max_length=50)
    update_linked_parent: bool = False
    is_active: bool | None = None

    @field_validator("nis")
    @classmethod
    def validate_nis(cls, value: str | None) -> str | None:
        return _strip_optional_text(value, "NIS")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return _strip_optional_text(value, "Nama siswa")

    @field_validator("class_id", "parent_id", "parent_name")
    @classmethod
    def normalize_optional_ids(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("parent_phone_wa")
    @classmethod
    def validate_parent_phone_wa(cls, value: str | None) -> str | None:
        cleaned = _blank_to_none(value)
        if cleaned is None:
            return None
        return normalize_wa_phone(cleaned)


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
    created_at: UtcDateTime


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
    created_at: UtcDateTime


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
    opened_at: UtcDateTime
    closed_at: UtcDateTime | None = None
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
    scanned_at: UtcDateTime | None = None
    similarity_score: float | None = None
    wa_status: str | None = None
    wa_notified_at: UtcDateTime | None = None


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
    scanned_at: UtcDateTime | None = None
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
    scanned_at: UtcDateTime | None = None
    wa_status: str
    wa_notified_at: UtcDateTime | None = None
    message: str


class ResendWaResponse(BaseModel):
    """Result of retrying a parent WhatsApp attendance notification."""

    attendance_id: str
    wa_status: str
    wa_sent: bool
    wa_notified_at: UtcDateTime | None = None
    message: str


# ---------------------------------------------------------------------------
# Leave Request Verification Schemas (Task 5)
# ---------------------------------------------------------------------------


class LeaveRequestResponse(BaseModel):
    """Enriched student leave request returned to teacher and admin dashboards."""

    id: str
    student_id: str
    student_name: str
    student_nis: str
    class_id: str
    class_name: str
    parent_id: str
    parent_name: str
    parent_phone_wa: str
    request_type: str
    start_date: date
    end_date: date
    reason: str
    attachment_url: str | None = None
    status: str
    verified_by: str | None = None
    verified_by_name: str | None = None
    verified_at: UtcDateTime | None = None
    verification_note: str | None = None
    created_at: UtcDateTime


class LeaveVerifyRequest(BaseModel):
    """Payload for a teacher to approve or reject a parent leave request."""

    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class LeaveVerifyResponse(BaseModel):
    """Result of verifying a leave request and syncing matching attendance sessions."""

    leave: LeaveRequestResponse
    synced_sessions_count: int
    wa_sent: bool
    message: str


# ---------------------------------------------------------------------------
# WhatsApp AI Chatbot Webhook Schemas (Task 6)
# ---------------------------------------------------------------------------


_IGNORED_WAHA_MESSAGE_TYPES = frozenset(
    {"sticker", "revoked", "e2e_notification", "protocol", "gp2", "call_log"}
)


class WahaMessagePayload(BaseModel):
    """Nested WAHA webhook message payload (`{from, body, mediaUrl?, fromMe?, type?}`)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    from_: str | None = Field(default=None, alias="from")
    body: str | None = ""
    media_url: str | None = Field(default=None, alias="mediaUrl")
    media: dict[str, Any] | None = None
    from_me: bool = Field(default=False, alias="fromMe")
    type: str | None = None


class WhatsAppWebhookRequest(BaseModel):
    """Incoming webhook payload supporting both standard and WAHA formats."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    phone_wa: str | None = None
    message_text: str | None = None
    media_url: str | None = None

    event: str | None = None
    payload: WahaMessagePayload | None = None

    @model_validator(mode="after")
    def validate_payload_shape(self) -> "WhatsAppWebhookRequest":
        phone_raw, msg_text, media, ignored = self.extract_normalized_fields()
        if not ignored:
            if not phone_raw or not phone_raw.strip():
                raise ValueError("Nomor WhatsApp pengirim wajib diisi.")
            normalize_wa_phone(phone_raw)
            if (not msg_text or not msg_text.strip()) and not (media and media.strip()):
                raise ValueError("Isi pesan WhatsApp wajib diisi.")
        return self

    def extract_normalized_fields(self) -> tuple[str | None, str | None, str | None, bool]:
        """Return `(phone_wa_raw, message_text, media_url, ignored)` for standard or WAHA input."""
        if self.payload is not None:
            if self.event is not None and self.event != "message":
                return None, None, None, True
            if self.payload.from_me:
                return None, None, None, True
            msg_type = (self.payload.type or "").strip().lower()
            if msg_type in _IGNORED_WAHA_MESSAGE_TYPES:
                return None, None, None, True
            sender_raw = (self.payload.from_ or "").strip()
            lowered_sender = sender_raw.lower()
            if (
                lowered_sender == "status@broadcast"
                or lowered_sender.endswith("@g.us")
                or lowered_sender.endswith("@newsletter")
                or lowered_sender.endswith("@broadcast")
            ):
                return None, None, None, True

            media_val = self.payload.media_url
            if not media_val and isinstance(self.payload.media, dict):
                raw_url = self.payload.media.get("url")
                if isinstance(raw_url, str) and raw_url.strip():
                    media_val = raw_url.strip()

            return sender_raw, (self.payload.body or ""), media_val, False

        if self.event is not None and self.event != "message":
            return None, None, None, True

        return self.phone_wa, self.message_text, self.media_url, False


class WhatsAppWebhookResponse(BaseModel):
    """Structured response returned by the WhatsApp AI chatbot webhook."""

    reply_text: str = ""
    is_in_domain: bool = True
    is_fallback: bool = False
    tool_called: str | None = None
    detected_intent: str | None = None
    latency_ms: int = 0
    wa_sent: bool = False
    ignored: bool = False


# ---------------------------------------------------------------------------
# Scientific Evaluation Metrics & Lab Labeling Schemas (Task 7)
# ---------------------------------------------------------------------------


class FaceLogLabelRequest(BaseModel):
    """Payload for labeling or unlabeling a kiosk face recognition log."""

    actual_student_id: str | None = None
    is_impostor: bool = False
    condition_note: str | None = Field(default=None, max_length=255)

    @field_validator("actual_student_id")
    @classmethod
    def normalize_actual_student_id(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("condition_note")
    @classmethod
    def normalize_condition_note(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def validate_impostor_xor_student(self) -> "FaceLogLabelRequest":
        if self.is_impostor and self.actual_student_id is not None:
            raise ValueError(
                "Tidak dapat menandai impostor sekaligus menetapkan actual_student_id."
            )
        return self


class FaceRecognitionLogItem(BaseModel):
    """Individual face recognition scan log with confusion matrix classification."""

    id: str
    session_id: str | None = None
    predicted_student_id: str | None = None
    predicted_student_name: str | None = None
    actual_student_id: str | None = None
    actual_student_name: str | None = None
    top_similarity_score: float
    threshold_used: float
    liveness_passed: bool
    is_match: bool
    latency_ms: int
    condition_note: str | None = None
    is_impostor: bool = False
    classification: str = "unlabeled"
    created_at: UtcDateTime


class PaginatedFaceLogsResponse(BaseModel):
    """Paginated face recognition evaluation logs."""

    items: list[FaceRecognitionLogItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0


class FaceEvaluationMetrics(BaseModel):
    """Face recognition confusion matrix metrics (TP/FP/FN/TN, FAR, FRR, latency)."""

    total_scans: int = 0
    total_labeled: int = 0
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    accuracy: float = 0.0
    far: float = 0.0
    frr: float = 0.0
    avg_scan_latency_ms: float = 0.0
    threshold: float = 0.55


class ChatbotLogItem(BaseModel):
    """Individual WhatsApp AI chatbot evaluation log item."""

    id: str
    created_at: UtcDateTime
    phone_wa: str
    user_message: str
    bot_response: str = ""
    detected_intent: str | None = None
    tool_called: str | None = None
    is_in_domain: bool
    is_fallback: bool
    latency_ms: int


class PaginatedChatbotLogsResponse(BaseModel):
    """Paginated WhatsApp AI chatbot evaluation logs."""

    items: list[ChatbotLogItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0


class ChatbotSimulateRequest(BaseModel):
    """Admin dry-run simulation request for the WhatsApp AI chatbot."""

    phone_wa: str = Field(..., min_length=1, max_length=50)
    message_text: str = Field(..., min_length=1, max_length=2000)
    media_url: str | None = None

    @field_validator("phone_wa")
    @classmethod
    def validate_phone_wa(cls, value: str) -> str:
        return normalize_wa_phone(value)

    @field_validator("message_text")
    @classmethod
    def validate_message_text(cls, value: str) -> str:
        return _strip_required_text(value, "Pesan simulasi")

    @field_validator("media_url")
    @classmethod
    def normalize_media_url(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class ChatbotEvaluationMetrics(BaseModel):
    """Aggregated WhatsApp AI chatbot domain accuracy, fallback rate, and latency."""

    total_messages: int = 0
    in_domain_count: int = 0
    out_of_domain_count: int = 0
    in_domain_rate: float = 0.0
    fallback_count: int = 0
    fallback_rate: float = 0.0
    avg_latency_ms: float = 0.0
    recent_logs: list[ChatbotLogItem] = Field(default_factory=list)


class ClassDailyRecap(BaseModel):
    """Daily attendance and WhatsApp notification recap for one academic class."""

    class_id: str
    class_name: str
    homeroom_teacher_name: str | None = None
    session_count: int = 0
    present_count: int = 0
    late_count: int = 0
    permit_or_sick_count: int = 0
    absent_count: int = 0
    wa_sent_count: int = 0
    wa_total_count: int = 0


class EvaluationDashboardResponse(BaseModel):
    """Combined scientific evaluation metrics and daily class recap for admin dashboard."""

    recap_date: date
    face_metrics: FaceEvaluationMetrics
    chatbot_metrics: ChatbotEvaluationMetrics
    class_recaps: list[ClassDailyRecap] = Field(default_factory=list)
    recent_face_logs: list[FaceRecognitionLogItem] = Field(default_factory=list)

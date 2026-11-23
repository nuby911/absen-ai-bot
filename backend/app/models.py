from datetime import date, datetime, time, timezone
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """School staff account (admin or teacher)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    nip: Mapped[str | None] = mapped_column(String(50), nullable=True)
    kiosk_pin_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )

    homeroom_classes: Mapped[list["SchoolClass"]] = relationship(
        "SchoolClass", back_populates="homeroom_teacher"
    )
    schedules: Mapped[list["Schedule"]] = relationship("Schedule", back_populates="teacher")
    sessions: Mapped[list["AttendanceSession"]] = relationship(
        "AttendanceSession", back_populates="teacher"
    )


class SchoolClass(Base):
    """Academic class group (e.g., XI IPA 1)."""

    __tablename__ = "classes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    homeroom_teacher_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )

    homeroom_teacher: Mapped["User | None"] = relationship(
        "User", back_populates="homeroom_classes"
    )
    students: Mapped[list["Student"]] = relationship(
        "Student", back_populates="school_class"
    )
    schedules: Mapped[list["Schedule"]] = relationship(
        "Schedule", back_populates="school_class"
    )


class Parent(Base):
    """Student parent/guardian registered for WhatsApp notifications and chatbot."""

    __tablename__ = "parents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_wa: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )

    students: Mapped[list["Student"]] = relationship("Student", back_populates="parent")
    leave_requests: Mapped[list["LeaveRequest"]] = relationship(
        "LeaveRequest", back_populates="parent"
    )


class Student(Base):
    """Enrolled student linked to a class and parent."""

    __tablename__ = "students"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    nis: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    class_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("classes.id"), nullable=False, index=True
    )
    parent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("parents.id"), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )

    school_class: Mapped["SchoolClass"] = relationship(
        "SchoolClass", back_populates="students"
    )
    parent: Mapped["Parent"] = relationship("Parent", back_populates="students")
    face_embeddings: Mapped[list["FaceEmbedding"]] = relationship(
        "FaceEmbedding",
        back_populates="student",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    attendances: Mapped[list["Attendance"]] = relationship(
        "Attendance", back_populates="student"
    )
    leave_requests: Mapped[list["LeaveRequest"]] = relationship(
        "LeaveRequest", back_populates="student"
    )


class Schedule(Base):
    """Weekly subject teaching schedule for a class."""

    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    class_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("classes.id"), nullable=False, index=True
    )
    teacher_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    subject_name: Mapped[str] = mapped_column(String(255), nullable=False)
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    late_tolerance_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)

    school_class: Mapped["SchoolClass"] = relationship(
        "SchoolClass", back_populates="schedules"
    )
    teacher: Mapped["User"] = relationship("User", back_populates="schedules")


class FaceEmbedding(Base):
    """Registered 512-dimensional face embedding sample for a student."""

    __tablename__ = "face_embeddings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    student_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )

    student: Mapped["Student"] = relationship("Student", back_populates="face_embeddings")


class AttendanceSession(Base):
    """Active or closed attendance session (gate or subject)."""

    __tablename__ = "attendance_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    class_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("classes.id"), nullable=True, index=True
    )
    teacher_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    schedule_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("schedules.id"), nullable=True
    )
    session_type: Mapped[str] = mapped_column(String(20), nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    expected_start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    late_tolerance_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)

    school_class: Mapped["SchoolClass | None"] = relationship("SchoolClass")
    teacher: Mapped["User"] = relationship("User", back_populates="sessions")
    schedule: Mapped["Schedule | None"] = relationship("Schedule")
    attendances: Mapped[list["Attendance"]] = relationship(
        "Attendance", back_populates="session"
    )


class Attendance(Base):
    """Per-student attendance record within a session."""

    __tablename__ = "attendances"
    __table_args__ = (
        UniqueConstraint("session_id", "student_id", name="uq_attendance_session_student"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("attendance_sessions.id"), nullable=False, index=True
    )
    student_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("students.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    verification_method: Mapped[str] = mapped_column(String(30), nullable=False)
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    wa_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    wa_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    session: Mapped["AttendanceSession"] = relationship(
        "AttendanceSession", back_populates="attendances"
    )
    student: Mapped["Student"] = relationship("Student", back_populates="attendances")


class LeaveRequest(Base):
    """Student permit or sick leave submitted by a parent via chatbot."""

    __tablename__ = "leave_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    student_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("students.id"), nullable=False, index=True
    )
    parent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("parents.id"), nullable=False, index=True
    )
    request_type: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    verified_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )

    student: Mapped["Student"] = relationship("Student", back_populates="leave_requests")
    parent: Mapped["Parent"] = relationship("Parent", back_populates="leave_requests")
    verifier: Mapped["User | None"] = relationship("User", foreign_keys=[verified_by])


class FaceRecognitionLog(Base):
    """Evaluation log for kiosk face scans (FAR/FRR confusion matrix & latency)."""

    __tablename__ = "face_recognition_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("attendance_sessions.id"), nullable=True, index=True
    )
    predicted_student_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("students.id"), nullable=True
    )
    actual_student_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("students.id"), nullable=True
    )
    top_similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_used: Mapped[float] = mapped_column(Float, nullable=False)
    liveness_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_match: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    condition_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )


class ChatbotLog(Base):
    """Evaluation log for WhatsApp AI chatbot interactions."""

    __tablename__ = "chatbot_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("parents.id"), nullable=True, index=True
    )
    phone_wa: Mapped[str] = mapped_column(String(30), nullable=False)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    detected_intent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_called: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bot_response: Mapped[str] = mapped_column(Text, nullable=False)
    is_in_domain: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )


class SystemSetting(Base):
    """Key-value runtime configuration persisted in database."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False
    )

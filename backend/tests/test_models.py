from datetime import date, datetime, time, timezone

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

import app.models  # noqa: F401
from app.config import get_settings
from app.database import Base, create_engine_and_session
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


def test_all_spec_tables_exist_in_metadata() -> None:
    expected_tables = {
        "users",
        "classes",
        "parents",
        "students",
        "schedules",
        "face_embeddings",
        "attendance_sessions",
        "attendances",
        "leave_requests",
        "face_recognition_logs",
        "chatbot_logs",
        "system_settings",
    }
    assert set(Base.metadata.tables.keys()) == expected_tables


def test_settings_defaults() -> None:
    settings = get_settings()
    assert settings.jwt_algorithm == "HS256"
    assert settings.access_token_expire_minutes == 480
    assert settings.face_similarity_threshold == 0.55
    assert settings.face_engine_mode == "auto"
    assert settings.whatsapp_provider_mode == "mock"
    assert settings.waha_base_url == "http://localhost:3000"
    assert settings.waha_session == "default"
    assert settings.llm_provider_mode == "fallback"
    assert settings.gemini_model == "gemini-2.0-flash"
    assert settings.upload_dir == "uploads"


async def test_create_session_student_and_attendance(db_session) -> None:
    teacher = User(
        name="Sari Wulandari",
        email="sari@sekolah.sch.id",
        password_hash="hashed-password",
        role="teacher",
        nip="198901012015012001",
    )
    school_class = SchoolClass(name="XI IPA 1")
    parent = Parent(name="Bapak Ahmad", phone_wa="6281279001234")
    db_session.add_all([teacher, school_class, parent])
    await db_session.flush()

    school_class.homeroom_teacher_id = teacher.id
    student = Student(
        nis="2026001",
        name="Rubby Pratama",
        class_id=school_class.id,
        parent_id=parent.id,
    )
    db_session.add(student)
    await db_session.flush()

    session_row = AttendanceSession(
        class_id=school_class.id,
        teacher_id=teacher.id,
        session_type="subject",
        session_date=date(2026, 11, 23),
        expected_start_time=time(7, 30),
    )
    db_session.add(session_row)
    await db_session.flush()

    attendance = Attendance(
        session_id=session_row.id,
        student_id=student.id,
        status="present",
        verification_method="face_kiosk",
        scanned_at=datetime.now(timezone.utc),
        similarity_score=0.81,
    )
    db_session.add(attendance)
    await db_session.commit()

    fetched = await db_session.scalar(
        select(Attendance).where(Attendance.id == attendance.id)
    )
    assert fetched is not None
    assert len(student.id) == 36
    assert student.is_active is True
    assert session_row.status == "open"
    assert session_row.late_tolerance_minutes == 15
    assert fetched.status == "present"
    assert fetched.wa_status == "pending"


async def test_duplicate_attendance_raises_integrity_error(db_session) -> None:
    teacher = User(
        name="Guru Piket",
        email="piket@sekolah.sch.id",
        password_hash="hashed",
        role="teacher",
    )
    school_class = SchoolClass(name="XI IPA 2")
    parent = Parent(name="Ibu Siti", phone_wa="6281279009999")
    db_session.add_all([teacher, school_class, parent])
    await db_session.flush()

    student = Student(
        nis="2026002",
        name="Deni Saputra",
        class_id=school_class.id,
        parent_id=parent.id,
    )
    session_row = AttendanceSession(
        class_id=school_class.id,
        teacher_id=teacher.id,
        session_type="gate_in",
        session_date=date(2026, 11, 23),
    )
    db_session.add_all([student, session_row])
    await db_session.flush()

    first = Attendance(
        session_id=session_row.id,
        student_id=student.id,
        status="present",
        verification_method="face_kiosk",
    )
    db_session.add(first)
    await db_session.commit()

    duplicate = Attendance(
        session_id=session_row.id,
        student_id=student.id,
        status="late",
        verification_method="manual_teacher",
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_delete_student_cascades_face_embeddings(db_session) -> None:
    pragma_fk = await db_session.scalar(text("PRAGMA foreign_keys"))
    assert pragma_fk == 1

    school_class = SchoolClass(name="XII IPS 1")
    parent = Parent(name="Ibu Rina", phone_wa="6281311112222")
    db_session.add_all([school_class, parent])
    await db_session.flush()

    student = Student(
        nis="2026003",
        name="Septi Rahmawati",
        class_id=school_class.id,
        parent_id=parent.id,
    )
    db_session.add(student)
    await db_session.flush()

    embeddings = [
        FaceEmbedding(
            student_id=student.id,
            image_path=f"uploads/faces/septi_{idx}.jpg",
            embedding=[0.01 * idx] * 512,
            quality_score=0.91,
        )
        for idx in range(2)
    ]
    db_session.add_all(embeddings)
    await db_session.commit()

    count_before = len(
        (await db_session.scalars(select(FaceEmbedding))).all()
    )
    assert count_before == 2

    await db_session.execute(delete(Student).where(Student.id == student.id))
    await db_session.commit()

    count_after = len(
        (await db_session.scalars(select(FaceEmbedding))).all()
    )
    assert count_after == 0


async def test_remaining_models_persist_cleanly(db_session) -> None:
    teacher = User(
        name="Pak Budi",
        email="budi@sekolah.sch.id",
        password_hash="hashed",
        role="teacher",
    )
    school_class = SchoolClass(name="X IPA 1")
    parent = Parent(name="Ibu Dewi", phone_wa="6281500001111")
    db_session.add_all([teacher, school_class, parent])
    await db_session.flush()

    student = Student(
        nis="2026004",
        name="Yoga Pratama",
        class_id=school_class.id,
        parent_id=parent.id,
    )
    db_session.add(student)
    await db_session.flush()

    schedule = Schedule(
        class_id=school_class.id,
        teacher_id=teacher.id,
        subject_name="Pemrograman Mobile",
        day_of_week=1,
        start_time=time(8, 0),
        end_time=time(9, 40),
    )
    leave_req = LeaveRequest(
        student_id=student.id,
        parent_id=parent.id,
        request_type="sick",
        start_date=date(2026, 11, 23),
        end_date=date(2026, 11, 24),
        reason="Demam tinggi",
    )
    face_log = FaceRecognitionLog(
        predicted_student_id=student.id,
        actual_student_id=student.id,
        top_similarity_score=0.78,
        threshold_used=0.55,
        liveness_passed=True,
        is_match=True,
        latency_ms=42,
        condition_note="jarak_50cm_normal",
    )
    chat_log = ChatbotLog(
        parent_id=parent.id,
        phone_wa="6281500001111",
        user_message="Apakah Yoga sudah absen hari ini?",
        detected_intent="check_today_attendance",
        tool_called="get_today_attendance",
        bot_response="Ananda Yoga tercatat hadir pukul 07:12 WIB.",
        is_in_domain=True,
        is_fallback=False,
        latency_ms=310,
    )
    setting = SystemSetting(key="face_similarity_threshold", value="0.55")

    db_session.add_all([schedule, leave_req, face_log, chat_log, setting])
    await db_session.commit()

    assert (await db_session.scalar(select(Schedule))).late_tolerance_minutes == 15
    assert (await db_session.scalar(select(LeaveRequest))).status == "pending"
    assert (await db_session.scalar(select(FaceRecognitionLog))).is_match is True
    assert (await db_session.scalar(select(ChatbotLog))).is_in_domain is True
    assert (await db_session.scalar(select(SystemSetting))).value == "0.55"


async def test_orm_delete_student_cascades_face_embeddings(db_session) -> None:
    school_class = SchoolClass(name="XII IPA 1")
    parent = Parent(name="Bapak Hadi", phone_wa="6281322223333")
    db_session.add_all([school_class, parent])
    await db_session.flush()

    student = Student(
        nis="2026005",
        name="Raka Wijaya",
        class_id=school_class.id,
        parent_id=parent.id,
    )
    db_session.add(student)
    await db_session.flush()

    embedding = FaceEmbedding(
        student_id=student.id,
        image_path="uploads/faces/raka_0.jpg",
        embedding=[0.05] * 512,
        quality_score=0.95,
    )
    db_session.add(embedding)
    await db_session.commit()

    await db_session.delete(student)
    await db_session.commit()

    remaining = (await db_session.scalars(select(FaceEmbedding))).all()
    assert remaining == []


async def test_postgres_engine_factory_initializes_cleanly() -> None:
    engine, session_factory = create_engine_and_session(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/smart_school_attendance"
    )
    try:
        assert engine.dialect.name == "postgresql"
        assert session_factory is not None
    finally:
        await engine.dispose()


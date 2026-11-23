import asyncio
from datetime import datetime, time, timedelta, timezone
import hashlib
import uuid

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401
from app.database import Base, create_engine_and_session
from app.config import get_settings
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
from app.providers.face_engine import EMBEDDING_DIM
from app.security import hash_secret, normalize_wa_phone

WIB = timezone(timedelta(hours=7))


def _seed_uuid(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"smart-school-attendance:{key}"))


def _deterministic_embedding(seed_key: str) -> list[float]:
    digest = hashlib.sha256(seed_key.encode("utf-8")).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
    vec = rng.standard_normal(EMBEDDING_DIM).astype(np.float64)
    norm = float(np.linalg.norm(vec))
    return (vec / norm).tolist() if norm > 0 else [0.0] * EMBEDDING_DIM


async def _get_or_create_user(
    db: AsyncSession,
    *,
    email: str,
    name: str,
    password: str,
    role: str,
    nip: str | None,
    kiosk_pin: str | None = None,
) -> User:
    existing = await db.scalar(select(User).where(User.email == email))
    if existing is not None:
        return existing
    user = User(
        name=name,
        email=email,
        password_hash=hash_secret(password),
        role=role,
        nip=nip,
        kiosk_pin_hash=hash_secret(kiosk_pin) if kiosk_pin else None,
    )
    db.add(user)
    await db.flush()
    return user


async def _get_or_create_class(
    db: AsyncSession,
    *,
    name: str,
    homeroom_teacher_id: str | None,
) -> SchoolClass:
    existing = await db.scalar(select(SchoolClass).where(SchoolClass.name == name))
    if existing is not None:
        return existing
    school_class = SchoolClass(
        name=name,
        homeroom_teacher_id=homeroom_teacher_id,
    )
    db.add(school_class)
    await db.flush()
    return school_class


async def _get_or_create_parent(
    db: AsyncSession,
    *,
    name: str,
    phone_wa: str,
) -> Parent:
    normalized = normalize_wa_phone(phone_wa)
    existing = await db.scalar(select(Parent).where(Parent.phone_wa == normalized))
    if existing is not None:
        return existing
    parent = Parent(name=name, phone_wa=normalized)
    db.add(parent)
    await db.flush()
    return parent


async def _get_or_create_student(
    db: AsyncSession,
    *,
    nis: str,
    name: str,
    class_id: str,
    parent_id: str,
) -> Student:
    existing = await db.scalar(select(Student).where(Student.nis == nis))
    if existing is not None:
        return existing
    student = Student(
        nis=nis,
        name=name,
        class_id=class_id,
        parent_id=parent_id,
        is_active=True,
    )
    db.add(student)
    await db.flush()
    return student


async def _get_or_create_schedule(
    db: AsyncSession,
    *,
    class_id: str,
    teacher_id: str,
    subject_name: str,
    day_of_week: int,
    start_time: time,
    end_time: time,
    late_tolerance_minutes: int = 15,
) -> Schedule:
    existing = await db.scalar(
        select(Schedule).where(
            Schedule.class_id == class_id,
            Schedule.teacher_id == teacher_id,
            Schedule.subject_name == subject_name,
            Schedule.day_of_week == day_of_week,
            Schedule.start_time == start_time,
        )
    )
    if existing is not None:
        return existing
    schedule = Schedule(
        class_id=class_id,
        teacher_id=teacher_id,
        subject_name=subject_name,
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time,
        late_tolerance_minutes=late_tolerance_minutes,
    )
    db.add(schedule)
    await db.flush()
    return schedule


async def seed_demo_data(db: AsyncSession) -> dict[str, int]:
    """Seed idempotent realistic demo data aligned with Figma mockups."""
    now_wib = datetime.now(WIB)
    today_wib = now_wib.date()
    today_dow = today_wib.isoweekday()
    now_utc = now_wib.astimezone(timezone.utc)

    # 1. Runtime setting for face threshold
    threshold_setting = await db.get(SystemSetting, "face_similarity_threshold")
    if threshold_setting is None:
        db.add(SystemSetting(key="face_similarity_threshold", value="0.55"))

    # 2. Admin & Teachers
    await _get_or_create_user(
        db,
        email="admin@sekolah.sch.id",
        name="Admin Sekolah",
        password="admin123",
        role="admin",
        nip="198001012010011001",
    )
    sari = await _get_or_create_user(
        db,
        email="sari.wulandari@sekolah.sch.id",
        name="Ibu Sari Wulandari, S.Pd",
        password="guru123",
        role="teacher",
        nip="198901012015032001",
        kiosk_pin="1234",
    )
    budi = await _get_or_create_user(
        db,
        email="budi.hartono@sekolah.sch.id",
        name="Bapak Budi Hartono, M.Pd",
        password="guru123",
        role="teacher",
        nip="198504122012011002",
        kiosk_pin="1234",
    )
    dewi = await _get_or_create_user(
        db,
        email="dewi.anggraini@sekolah.sch.id",
        name="Ibu Dewi Anggraini, S.Pd",
        password="guru123",
        role="teacher",
        nip="199008202016032003",
        kiosk_pin="1234",
    )
    dwi = await _get_or_create_user(
        db,
        email="dwi.handoko@sekolah.sch.id",
        name="Bapak Dwi Handoko, M.T.I",
        password="guru123",
        role="teacher",
        nip="198711052014021004",
        kiosk_pin="1234",
    )

    # 3. Classes
    xi_ipa_1 = await _get_or_create_class(db, name="XI IPA 1", homeroom_teacher_id=sari.id)
    xi_ipa_2 = await _get_or_create_class(db, name="XI IPA 2", homeroom_teacher_id=budi.id)
    xi_ips_1 = await _get_or_create_class(db, name="XI IPS 1", homeroom_teacher_id=dewi.id)
    xii_ipa_1 = await _get_or_create_class(db, name="XII IPA 1", homeroom_teacher_id=dwi.id)

    # 4. Parents & Students (matching Figma mockups + extra class coverage)
    parent_anantara = await _get_or_create_parent(
        db, name="Bapak Anantara", phone_wa="6281279001234"
    )
    parent_prawira = await _get_or_create_parent(
        db, name="Ibu Prawira", phone_wa="6281279001235"
    )
    parent_cahyo = await _get_or_create_parent(
        db, name="Bapak Cahyo", phone_wa="6281279001236"
    )
    parent_pasaribu = await _get_or_create_parent(
        db, name="Ibu Pasaribu", phone_wa="6281279001237"
    )
    parent_fauzi = await _get_or_create_parent(
        db, name="Bapak Fauzi", phone_wa="6281279001238"
    )
    parent_pratama = await _get_or_create_parent(
        db, name="Ibu Pratama", phone_wa="6281279001239"
    )
    parent_lestari = await _get_or_create_parent(
        db, name="Bapak Lestari", phone_wa="6281279001240"
    )
    parent_wijaya = await _get_or_create_parent(
        db, name="Ibu Wijaya", phone_wa="6281279001241"
    )

    rubby = await _get_or_create_student(
        db,
        nis="24781025",
        name="Rubby Ibnu Anantara",
        class_id=xi_ipa_1.id,
        parent_id=parent_anantara.id,
    )
    deni = await _get_or_create_student(
        db,
        nis="24781007",
        name="Deni Prawira",
        class_id=xi_ipa_1.id,
        parent_id=parent_prawira.id,
    )
    septi = await _get_or_create_student(
        db,
        nis="24781026",
        name="Septi Cahyaningtias",
        class_id=xi_ipa_1.id,
        parent_id=parent_cahyo.id,
    )
    yoga = await _get_or_create_student(
        db,
        nis="24781030",
        name="Yoga Ricky Pasaribu",
        class_id=xi_ipa_1.id,
        parent_id=parent_pasaribu.id,
    )
    ahmad = await _get_or_create_student(
        db,
        nis="24781031",
        name="Ahmad Fauzi",
        class_id=xi_ipa_1.id,
        parent_id=parent_fauzi.id,
    )
    nadia = await _get_or_create_student(
        db,
        nis="24781040",
        name="Nadia Pratama",
        class_id=xi_ipa_2.id,
        parent_id=parent_pratama.id,
    )
    rizky = await _get_or_create_student(
        db,
        nis="24781041",
        name="Rizky Lestari",
        class_id=xi_ips_1.id,
        parent_id=parent_lestari.id,
    )
    putri = await _get_or_create_student(
        db,
        nis="24781042",
        name="Putri Wijaya",
        class_id=xii_ipa_1.id,
        parent_id=parent_wijaya.id,
    )

    all_students = [rubby, deni, septi, yoga, ahmad, nadia, rizky, putri]

    # 5. Face Embeddings (sample deterministic vectors so face_count > 0)
    face_count_seeded = 0
    for student in [rubby, deni, septi, yoga, ahmad]:
        for idx in (1, 2):
            image_path = f"faces/{student.id}/seed_{idx}.jpg"
            existing_face = await db.scalar(
                select(FaceEmbedding).where(
                    FaceEmbedding.student_id == student.id,
                    FaceEmbedding.image_path == image_path,
                )
            )
            if existing_face is None:
                db.add(
                    FaceEmbedding(
                        student_id=student.id,
                        image_path=image_path,
                        embedding=_deterministic_embedding(f"{student.nis}:{idx}"),
                        quality_score=0.92,
                    )
                )
                face_count_seeded += 1

    # 6. Weekly Schedules (including today's schedule for XI IPA 1 - Pemrograman Mobile)
    mobile_schedule = await _get_or_create_schedule(
        db,
        class_id=xi_ipa_1.id,
        teacher_id=sari.id,
        subject_name="Pemrograman Mobile",
        day_of_week=today_dow,
        start_time=time(7, 30),
        end_time=time(9, 30),
        late_tolerance_minutes=15,
    )
    await _get_or_create_schedule(
        db,
        class_id=xi_ipa_1.id,
        teacher_id=dwi.id,
        subject_name="Basis Data Lanjut",
        day_of_week=today_dow,
        start_time=time(9, 45),
        end_time=time(11, 15),
        late_tolerance_minutes=15,
    )
    await _get_or_create_schedule(
        db,
        class_id=xi_ipa_2.id,
        teacher_id=budi.id,
        subject_name="Matematika Wajib",
        day_of_week=((today_dow % 5) + 1),
        start_time=time(7, 30),
        end_time=time(9, 0),
        late_tolerance_minutes=15,
    )
    await _get_or_create_schedule(
        db,
        class_id=xi_ips_1.id,
        teacher_id=dewi.id,
        subject_name="Bahasa Indonesia",
        day_of_week=((today_dow % 5) + 1),
        start_time=time(9, 15),
        end_time=time(10, 45),
        late_tolerance_minutes=15,
    )
    await _get_or_create_schedule(
        db,
        class_id=xii_ipa_1.id,
        teacher_id=dwi.id,
        subject_name="Kecerdasan Buatan",
        day_of_week=((today_dow % 5) + 1),
        start_time=time(11, 0),
        end_time=time(12, 30),
        late_tolerance_minutes=15,
    )

    # 7. Active Attendance Session today: XI IPA 1 — Pemrograman Mobile
    active_session = await db.scalar(
        select(AttendanceSession).where(
            AttendanceSession.class_id == xi_ipa_1.id,
            AttendanceSession.teacher_id == sari.id,
            AttendanceSession.schedule_id == mobile_schedule.id,
            AttendanceSession.session_date == today_wib,
        )
    )
    if active_session is None:
        active_session = AttendanceSession(
            class_id=xi_ipa_1.id,
            teacher_id=sari.id,
            schedule_id=mobile_schedule.id,
            session_type="subject",
            session_date=today_wib,
            expected_start_time=mobile_schedule.start_time,
            late_tolerance_minutes=mobile_schedule.late_tolerance_minutes,
            status="open",
        )
        db.add(active_session)
        await db.flush()

    seed_attendances = [
        (rubby, "present", "face_kiosk", 0.89, "sent"),
        (deni, "late", "face_kiosk", 0.83, "sent"),
        (yoga, "present", "face_kiosk", 0.91, "sent"),
    ]
    for student, att_status, method, sim_score, wa_status in seed_attendances:
        existing_att = await db.scalar(
            select(Attendance).where(
                Attendance.session_id == active_session.id,
                Attendance.student_id == student.id,
            )
        )
        if existing_att is None:
            db.add(
                Attendance(
                    session_id=active_session.id,
                    student_id=student.id,
                    status=att_status,
                    verification_method=method,
                    scanned_at=now_utc - timedelta(minutes=25),
                    similarity_score=sim_score,
                    wa_status=wa_status,
                    wa_notified_at=now_utc - timedelta(minutes=24),
                )
            )

    # 8. Two Pending Leave Requests (Septi Sakit + Ahmad Fauzi Izin)
    leave_specs = [
        (
            septi,
            parent_cahyo,
            "sick",
            "Demam tinggi dan batuk, sedang beristirahat sesuai anjuran dokter.",
        ),
        (
            ahmad,
            parent_fauzi,
            "permit",
            "Mengikuti lomba karya tulis ilmiah tingkat provinsi mewakili sekolah.",
        ),
    ]
    for student, parent, req_type, reason in leave_specs:
        existing_leave = await db.scalar(
            select(LeaveRequest).where(
                LeaveRequest.student_id == student.id,
                LeaveRequest.start_date == today_wib,
                LeaveRequest.request_type == req_type,
            )
        )
        if existing_leave is None:
            db.add(
                LeaveRequest(
                    student_id=student.id,
                    parent_id=parent.id,
                    request_type=req_type,
                    start_date=today_wib,
                    end_date=today_wib,
                    reason=reason,
                    status="pending",
                )
            )

    # 9. Labeled Face Recognition Evaluation Logs (TP, FP impostor, FN, TN impostor)
    face_log_specs = [
        ("face-log-tp-1", rubby.id, rubby.id, 0.89, True, True, 112, "pencahayaan_normal"),
        ("face-log-tp-2", deni.id, deni.id, 0.83, True, True, 124, "pencahayaan_normal"),
        ("face-log-tp-3", yoga.id, yoga.id, 0.91, True, True, 108, "pencahayaan_normal"),
        ("face-log-tp-4", septi.id, septi.id, 0.86, True, True, 118, "kacamata"),
        ("face-log-fn-1", None, ahmad.id, 0.51, True, False, 136, "cahaya_redup"),
        ("face-log-fp-1", rubby.id, None, 0.57, True, True, 129, "impostor:kemiripan_tinggi"),
        ("face-log-tn-1", None, None, 0.28, True, False, 98, "impostor:non_siswa"),
        ("face-log-tn-2", None, None, 0.34, True, False, 104, "impostor:foto_cetak"),
    ]
    for idx, (
        key,
        pred_id,
        act_id,
        score,
        liveness,
        matched,
        latency,
        note,
    ) in enumerate(face_log_specs):
        log_id = _seed_uuid(key)
        if await db.get(FaceRecognitionLog, log_id) is None:
            db.add(
                FaceRecognitionLog(
                    id=log_id,
                    session_id=active_session.id,
                    predicted_student_id=pred_id,
                    actual_student_id=act_id,
                    top_similarity_score=score,
                    threshold_used=0.55,
                    liveness_passed=liveness,
                    is_match=matched,
                    latency_ms=latency,
                    condition_note=note,
                    created_at=now_utc - timedelta(minutes=30 - idx),
                )
            )

    # 10. Chatbot Evaluation Logs
    chatbot_log_specs = [
        (
            "chat-log-1",
            parent_anantara,
            "Apakah Rubby sudah masuk kelas hari ini?",
            "cek_kehadiran_hari_ini",
            "get_today_attendance",
            "Ananda Rubby Ibnu Anantara tercatat Hadir pada sesi Pemrograman Mobile.",
            True,
            False,
            245,
        ),
        (
            "chat-log-2",
            parent_cahyo,
            "Mohon izin anak saya Septi hari ini sakit demam.",
            "ajukan_izin_atau_sakit",
            "submit_leave_request",
            "Pengajuan izin sakit untuk Septi Cahyaningtias telah dicatat dan menunggu verifikasi guru.",
            True,
            False,
            312,
        ),
        (
            "chat-log-3",
            parent_pasaribu,
            "Jadwal pelajaran Yoga hari ini apa saja ya?",
            "cek_jadwal_pelajaran",
            "get_class_schedule",
            "Jadwal kelas XI IPA 1 hari ini: Pemrograman Mobile (07:30-09:30), Basis Data Lanjut (09:45-11:15).",
            True,
            False,
            198,
        ),
        (
            "chat-log-4",
            parent_prawira,
            "Kapan pembagian rapor dan berapa biaya SPP semester ini?",
            "out_of_domain",
            None,
            "Mohon maaf, layanan ini hanya membahas kehadiran, rekap absensi, jadwal pelajaran, dan izin siswa.",
            False,
            True,
            142,
        ),
    ]
    for idx, (
        key,
        parent,
        user_msg,
        intent,
        tool_called,
        bot_reply,
        in_domain,
        is_fallback,
        latency,
    ) in enumerate(chatbot_log_specs):
        log_id = _seed_uuid(key)
        if await db.get(ChatbotLog, log_id) is None:
            db.add(
                ChatbotLog(
                    id=log_id,
                    parent_id=parent.id,
                    phone_wa=parent.phone_wa,
                    user_message=user_msg,
                    detected_intent=intent,
                    tool_called=tool_called,
                    bot_response=bot_reply,
                    is_in_domain=in_domain,
                    is_fallback=is_fallback,
                    latency_ms=latency,
                    created_at=now_utc - timedelta(minutes=20 - idx),
                )
            )

    await db.commit()
    return {
        "users": 5,
        "classes": 4,
        "students": len(all_students),
        "face_embeddings_added": face_count_seeded,
        "face_logs": len(face_log_specs),
        "chatbot_logs": len(chatbot_log_specs),
    }


async def _run_cli() -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings.database_url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            summary = await seed_demo_data(session)
        print(f"Demo data seeded successfully: {summary}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run_cli())

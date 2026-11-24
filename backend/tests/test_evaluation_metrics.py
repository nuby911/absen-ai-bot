import csv
import io
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    User,
)
from app.seed import seed_demo_data

WIB = timezone(timedelta(hours=7))


async def test_evaluation_metrics_empty_db_safe_zero_division(
    client,
    admin_headers,
    teacher_headers,
):
    forbidden_res = await client.get("/api/v1/evaluation/metrics", headers=teacher_headers)
    assert forbidden_res.status_code == 403

    res = await client.get("/api/v1/evaluation/metrics", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()

    face = data["face_metrics"]
    assert face["total_scans"] == 0
    assert face["total_labeled"] == 0
    assert face["tp"] == 0
    assert face["fp"] == 0
    assert face["fn"] == 0
    assert face["tn"] == 0
    assert face["accuracy"] == 0.0
    assert face["far"] == 0.0
    assert face["frr"] == 0.0
    assert face["avg_scan_latency_ms"] == 0.0
    assert face["threshold"] == pytest.approx(0.55)

    chatbot = data["chatbot_metrics"]
    assert chatbot["total_messages"] == 0
    assert chatbot["in_domain_count"] == 0
    assert chatbot["in_domain_rate"] == 0.0
    assert chatbot["fallback_count"] == 0
    assert chatbot["fallback_rate"] == 0.0
    assert chatbot["avg_latency_ms"] == 0.0
    assert chatbot["recent_logs"] == []

    assert data["class_recaps"] == []
    assert data["recent_face_logs"] == []


async def test_confusion_matrix_far_frr_accuracy_and_labeling(
    client,
    db_session: AsyncSession,
    admin_headers,
    seeded_teacher: User,
):
    school_class = SchoolClass(
        name="XI IPA 1",
        homeroom_teacher_id=seeded_teacher.id,
    )
    parent = Parent(name="Bapak Anantara", phone_wa="6281279001234")
    db_session.add_all([school_class, parent])
    await db_session.flush()

    student_1 = Student(
        nis="24781025",
        name="Rubby Ibnu Anantara",
        class_id=school_class.id,
        parent_id=parent.id,
    )
    student_2 = Student(
        nis="24781007",
        name="Deni Prawira",
        class_id=school_class.id,
        parent_id=parent.id,
    )
    db_session.add_all([student_1, student_2])
    await db_session.flush()

    today_wib = datetime.now(WIB).date()
    session_row = AttendanceSession(
        class_id=school_class.id,
        teacher_id=seeded_teacher.id,
        session_type="gate_in",
        session_date=today_wib,
        expected_start_time=time(7, 15),
        late_tolerance_minutes=15,
        status="open",
    )
    db_session.add(session_row)
    await db_session.flush()

    db_session.add_all(
        [
            Attendance(
                session_id=session_row.id,
                student_id=student_1.id,
                status="present",
                verification_method="face_recognition",
                scanned_at=datetime.now(timezone.utc),
                similarity_score=0.88,
                wa_status="sent",
            ),
            Attendance(
                session_id=session_row.id,
                student_id=student_2.id,
                status="late",
                verification_method="face_recognition",
                scanned_at=datetime.now(timezone.utc),
                similarity_score=0.81,
                wa_status="failed",
            ),
        ]
    )

    logs: list[FaceRecognitionLog] = []
    # 19 TP
    for i in range(19):
        logs.append(
            FaceRecognitionLog(
                session_id=session_row.id,
                predicted_student_id=student_1.id,
                actual_student_id=student_1.id,
                top_similarity_score=0.85,
                threshold_used=0.55,
                liveness_passed=True,
                is_match=True,
                latency_ms=100 + i,
                condition_note="normal",
            )
        )
    # 1 FP (impostor matched)
    logs.append(
        FaceRecognitionLog(
            session_id=session_row.id,
            predicted_student_id=student_1.id,
            actual_student_id=None,
            top_similarity_score=0.58,
            threshold_used=0.55,
            liveness_passed=True,
            is_match=True,
            latency_ms=120,
            condition_note="impostor",
        )
    )
    # 2 FN
    for _ in range(2):
        logs.append(
            FaceRecognitionLog(
                session_id=session_row.id,
                predicted_student_id=None,
                actual_student_id=student_1.id,
                top_similarity_score=0.49,
                threshold_used=0.55,
                liveness_passed=True,
                is_match=False,
                latency_ms=110,
                condition_note="low_light",
            )
        )
    # 8 TN (impostor rejected)
    for _ in range(8):
        logs.append(
            FaceRecognitionLog(
                session_id=session_row.id,
                predicted_student_id=None,
                actual_student_id=None,
                top_similarity_score=0.31,
                threshold_used=0.55,
                liveness_passed=True,
                is_match=False,
                latency_ms=95,
                condition_note="impostor:non_student",
            )
        )
    # 1 unlabeled log (should count in total_scans=31, not total_labeled=30)
    unlabeled_log = FaceRecognitionLog(
        session_id=session_row.id,
        predicted_student_id=student_2.id,
        actual_student_id=None,
        top_similarity_score=0.84,
        threshold_used=0.55,
        liveness_passed=True,
        is_match=True,
        latency_ms=130,
        condition_note=None,
    )
    logs.append(unlabeled_log)
    db_session.add_all(logs)

    db_session.add_all(
        [
            ChatbotLog(
                parent_id=parent.id,
                phone_wa=parent.phone_wa,
                user_message="Apakah anak saya hadir hari ini?",
                detected_intent="cek_kehadiran_hari_ini",
                tool_called="get_today_attendance",
                bot_response="Ananda hadir tepat waktu.",
                is_in_domain=True,
                is_fallback=False,
                latency_ms=200,
            ),
            ChatbotLog(
                parent_id=parent.id,
                phone_wa=parent.phone_wa,
                user_message="Berapa harga SPP bulan depan?",
                detected_intent="out_of_domain",
                tool_called=None,
                bot_response="Maaf, saya hanya melayani informasi absensi.",
                is_in_domain=False,
                is_fallback=True,
                latency_ms=100,
            ),
        ]
    )
    await db_session.commit()
    await db_session.refresh(unlabeled_log)

    res = await client.get("/api/v1/evaluation/metrics", headers=admin_headers)
    assert res.status_code == 200
    payload = res.json()

    face = payload["face_metrics"]
    assert face["total_scans"] == 31
    assert face["total_labeled"] == 30
    assert face["tp"] == 19
    assert face["fp"] == 1
    assert face["fn"] == 2
    assert face["tn"] == 8
    assert face["accuracy"] == pytest.approx(90.0)
    assert face["far"] == pytest.approx(1 / 9 * 100, rel=1e-2)
    assert face["frr"] == pytest.approx(2 / 21 * 100, rel=1e-2)
    assert face["avg_scan_latency_ms"] > 0.0

    chatbot = payload["chatbot_metrics"]
    assert chatbot["total_messages"] == 2
    assert chatbot["in_domain_count"] == 1
    assert chatbot["out_of_domain_count"] == 1
    assert chatbot["in_domain_rate"] == pytest.approx(50.0)
    assert chatbot["fallback_count"] == 1
    assert chatbot["fallback_rate"] == pytest.approx(50.0)
    assert chatbot["avg_latency_ms"] == pytest.approx(150.0)
    assert len(chatbot["recent_logs"]) == 2
    assert chatbot["recent_logs"][0]["bot_response"] != ""
    assert chatbot["recent_logs"][0]["created_at"].endswith("Z")

    assert len(payload["class_recaps"]) == 1
    recap = payload["class_recaps"][0]
    assert recap["class_name"] == "XI IPA 1"
    assert recap["homeroom_teacher_name"] == seeded_teacher.name
    assert recap["session_count"] == 1
    assert recap["present_count"] == 1
    assert recap["late_count"] == 1
    assert recap["wa_sent_count"] == 1
    assert recap["wa_total_count"] == 2
    assert len(payload["recent_face_logs"]) == 20
    assert payload["recent_face_logs"][0]["created_at"].endswith("Z")

    # Invalid student_id returns 404
    missing_student_res = await client.post(
        f"/api/v1/evaluation/face-logs/{unlabeled_log.id}/label",
        headers=admin_headers,
        json={"actual_student_id": "nonexistent-student-id", "is_impostor": False},
    )
    assert missing_student_res.status_code == 404

    # Combining is_impostor=True with non-null actual_student_id must be rejected with 422
    invalid_combo = await client.post(
        f"/api/v1/evaluation/face-logs/{unlabeled_log.id}/label",
        headers=admin_headers,
        json={"actual_student_id": student_2.id, "is_impostor": True, "condition_note": "foto_cetak"},
    )
    assert invalid_combo.status_code == 422

    # Labeling unlabeled scan as student_2 -> updates TP from 19 to 20
    label_res = await client.post(
        f"/api/v1/evaluation/face-logs/{unlabeled_log.id}/label",
        headers=admin_headers,
        json={"actual_student_id": student_2.id, "is_impostor": False, "condition_note": "lab_test"},
    )
    assert label_res.status_code == 200
    labeled_item = label_res.json()
    assert labeled_item["actual_student_id"] == student_2.id
    assert labeled_item["is_impostor"] is False

    # Re-label as impostor (with actual_student_id=None)
    impostor_res = await client.post(
        f"/api/v1/evaluation/face-logs/{unlabeled_log.id}/label",
        headers=admin_headers,
        json={"actual_student_id": None, "is_impostor": True, "condition_note": "foto_cetak"},
    )
    assert impostor_res.status_code == 200
    impostor_item = impostor_res.json()
    assert impostor_item["actual_student_id"] is None
    assert impostor_item["is_impostor"] is True
    assert impostor_item["condition_note"] == "foto_cetak"
    assert impostor_item["classification"] == "FP"

    # Unlabel cleanly (is_impostor=False, actual_student_id=None)
    unlabel_res = await client.post(
        f"/api/v1/evaluation/face-logs/{unlabeled_log.id}/label",
        headers=admin_headers,
        json={"actual_student_id": None, "is_impostor": False},
    )
    assert unlabel_res.status_code == 200
    unlabeled_again = unlabel_res.json()
    assert unlabeled_again["is_impostor"] is False
    assert unlabeled_again["actual_student_id"] is None
    assert unlabeled_again["classification"] == "unlabeled"
    assert unlabeled_again["condition_note"] == "foto_cetak"

    # Label back to student_2 (preserving clean note) and confirm metrics updated live
    back_res = await client.post(
        f"/api/v1/evaluation/face-logs/{unlabeled_log.id}/label",
        headers=admin_headers,
        json={"actual_student_id": student_2.id, "is_impostor": False},
    )
    assert back_res.status_code == 200
    assert back_res.json()["condition_note"] == "foto_cetak"
    updated_metrics = (
        await client.get("/api/v1/evaluation/metrics", headers=admin_headers)
    ).json()["face_metrics"]
    assert updated_metrics["total_labeled"] == 31
    assert updated_metrics["tp"] == 20


async def test_attendance_csv_export_headers_and_rows(
    client,
    db_session: AsyncSession,
    admin_headers,
    seeded_teacher: User,
):
    school_class = SchoolClass(name="XI IPA 1", homeroom_teacher_id=seeded_teacher.id)
    parent = Parent(name="Bapak Anantara", phone_wa="6281279001234")
    db_session.add_all([school_class, parent])
    await db_session.flush()

    student_1 = Student(
        nis="24781025",
        name="Rubby Ibnu Anantara",
        class_id=school_class.id,
        parent_id=parent.id,
    )
    student_2 = Student(
        nis="24781026",
        name="Siti Nurhaliza",
        class_id=school_class.id,
        parent_id=parent.id,
    )
    student_3 = Student(
        nis="24781027",
        name="Taufik Hidayat",
        class_id=school_class.id,
        parent_id=parent.id,
    )
    db_session.add_all([student_1, student_2, student_3])
    await db_session.flush()

    target_date = date(2026, 11, 23)
    session_row = AttendanceSession(
        class_id=school_class.id,
        teacher_id=seeded_teacher.id,
        session_type="subject",
        session_date=target_date,
        expected_start_time=time(7, 30),
        late_tolerance_minutes=15,
        status="open",
    )
    db_session.add(session_row)
    await db_session.flush()

    db_session.add_all(
        [
            Attendance(
                session_id=session_row.id,
                student_id=student_1.id,
                status="present",
                verification_method="face_kiosk",
                scanned_at=datetime(2026, 11, 23, 0, 25, tzinfo=timezone.utc),
                similarity_score=0.91,
                wa_status="sent",
            ),
            Attendance(
                session_id=session_row.id,
                student_id=student_2.id,
                status="late",
                verification_method="manual_teacher",
                scanned_at=datetime(2026, 11, 23, 0, 50, tzinfo=timezone.utc),
                similarity_score=None,
                wa_status="sent",
            ),
            Attendance(
                session_id=session_row.id,
                student_id=student_3.id,
                status="sick",
                verification_method="leave_approved",
                scanned_at=None,
                similarity_score=None,
                wa_status="sent",
            ),
        ]
    )
    await db_session.commit()

    res = await client.get(
        "/api/v1/reports/attendance.csv",
        params={
            "class_id": school_class.id,
            "start_date": "2026-11-23",
            "end_date": "2026-11-23",
        },
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    assert "rekap-absensi.csv" in res.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(res.text)))
    assert rows[0] == [
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
    assert len(rows) == 4
    rows_by_nis = {row[3]: row for row in rows[1:]}
    assert rows_by_nis["24781025"][0] == "2026-11-23"
    assert rows_by_nis["24781025"][1] == "Sesi Mata Pelajaran"
    assert rows_by_nis["24781025"][2] == "XI IPA 1"
    assert rows_by_nis["24781025"][4] == "Rubby Ibnu Anantara"
    assert rows_by_nis["24781025"][5] == "Hadir"
    assert rows_by_nis["24781025"][6] == "Scan Wajah Kiosk"
    assert "07:25" in rows_by_nis["24781025"][7]

    assert rows_by_nis["24781026"][5] == "Terlambat"
    assert rows_by_nis["24781026"][6] == "Input Manual Guru"

    assert rows_by_nis["24781027"][5] == "Sakit"
    assert rows_by_nis["24781027"][6] == "Izin Disetujui Guru"


async def test_seed_demo_data_is_idempotent(db_session: AsyncSession, tmp_path):
    seed_uploads = tmp_path / "seed_uploads"
    first_summary = await seed_demo_data(db_session, upload_dir=str(seed_uploads))
    assert first_summary["students"] >= 5

    async def _collect_counts() -> dict[str, int]:
        models = {
            "users": User,
            "classes": SchoolClass,
            "parents": Parent,
            "students": Student,
            "schedules": Schedule,
            "face_embeddings": FaceEmbedding,
            "sessions": AttendanceSession,
            "attendances": Attendance,
            "leaves": LeaveRequest,
            "face_logs": FaceRecognitionLog,
            "chatbot_logs": ChatbotLog,
        }
        return {
            name: int((await db_session.scalar(select(func.count()).select_from(model))) or 0)
            for name, model in models.items()
        }

    counts_after_first = await _collect_counts()
    await seed_demo_data(db_session, upload_dir=str(seed_uploads))
    counts_after_second = await _collect_counts()

    assert counts_after_second == counts_after_first
    assert counts_after_first["users"] >= 5
    assert counts_after_first["classes"] >= 4
    assert counts_after_first["students"] >= 5
    assert counts_after_first["leaves"] >= 2
    assert counts_after_first["face_logs"] >= 4
    assert counts_after_first["chatbot_logs"] >= 3

    # Verify every seeded face embedding has a real JPEG file on disk (3 per student)
    faces = (await db_session.scalars(select(FaceEmbedding))).all()
    assert len(faces) == counts_after_first["students"] * 3
    for face in faces:
        disk_file = seed_uploads / face.image_path
        assert disk_file.exists() and disk_file.stat().st_size > 100
        assert disk_file.read_bytes()[:2] == b"\xff\xd8"

    rubby = await db_session.scalar(select(Student).where(Student.nis == "24781025"))
    assert rubby is not None
    assert rubby.name == "Rubby Ibnu Anantara"

    sari = await db_session.scalar(
        select(User).where(User.email == "sari.wulandari@sekolah.sch.id")
    )
    assert sari is not None
    assert sari.role == "teacher"

    seeded_methods = set(
        (await db_session.scalars(select(Attendance.verification_method))).all()
    )
    assert seeded_methods == {"face_kiosk"}


async def test_evaluation_pagination_simulator_unregistered_exclusion_and_csv_sanitization(
    client,
    db_session: AsyncSession,
    admin_headers,
    seeded_teacher: User,
    mock_wa,
):
    """Test paginated evaluation logs, dry-run chatbot simulator, unregistered exclusion, and CSV formula sanitization."""
    school_class = SchoolClass(name="=XI IPA Formula", homeroom_teacher_id=seeded_teacher.id)
    parent = Parent(name="Bapak Sim", phone_wa="6281279007777")
    db_session.add_all([school_class, parent])
    await db_session.flush()

    student = Student(
        nis="24789999",
        name="=CMD|' /C calc'!A0",
        class_id=school_class.id,
        parent_id=parent.id,
    )
    schedule = Schedule(
        class_id=school_class.id,
        teacher_id=seeded_teacher.id,
        subject_name="+Matematika",
        day_of_week=1,
        start_time=time(7, 30),
        end_time=time(9, 0),
    )
    db_session.add_all([student, schedule])
    await db_session.flush()

    session_row = AttendanceSession(
        class_id=school_class.id,
        teacher_id=seeded_teacher.id,
        schedule_id=schedule.id,
        session_type="subject",
        session_date=date(2026, 11, 24),
        status="open",
    )
    db_session.add(session_row)
    await db_session.flush()

    db_session.add(
        Attendance(
            session_id=session_row.id,
            student_id=student.id,
            status="present",
            verification_method="face_kiosk",
            scanned_at=datetime(2026, 11, 24, 0, 30, tzinfo=timezone.utc),
            wa_status="sent",
        )
    )
    db_session.add_all(
        [
            FaceRecognitionLog(
                session_id=session_row.id,
                predicted_student_id=student.id,
                actual_student_id=student.id,
                top_similarity_score=0.91,
                threshold_used=0.55,
                liveness_passed=True,
                is_match=True,
                latency_ms=100,
            ),
            FaceRecognitionLog(
                session_id=session_row.id,
                predicted_student_id=None,
                actual_student_id=student.id,
                top_similarity_score=0.41,
                threshold_used=0.55,
                liveness_passed=True,
                is_match=False,
                latency_ms=110,
            ),
            FaceRecognitionLog(
                session_id=session_row.id,
                predicted_student_id=student.id,
                actual_student_id=None,
                top_similarity_score=0.77,
                threshold_used=0.55,
                liveness_passed=True,
                is_match=True,
                latency_ms=95,
            ),
        ]
    )
    db_session.add(
        ChatbotLog(
            parent_id=None,
            phone_wa="6281999999999",
            user_message="Siapa ini?",
            detected_intent="unregistered_parent",
            tool_called=None,
            bot_response="Nomor belum terdaftar.",
            is_in_domain=True,
            is_fallback=False,
            latency_ms=10,
        )
    )
    await db_session.commit()

    # 1. Paginated face-logs filters: all / labeled / unlabeled / errors
    all_faces = (
        await client.get("/api/v1/evaluation/face-logs?status=all&limit=2&offset=0", headers=admin_headers)
    ).json()
    assert all_faces["total"] == 3
    assert len(all_faces["items"]) == 2
    assert all_faces["limit"] == 2
    assert all_faces["offset"] == 0

    err_faces = (
        await client.get("/api/v1/evaluation/face-logs?status=errors", headers=admin_headers)
    ).json()
    assert err_faces["total"] == 1
    assert err_faces["items"][0]["classification"] == "FN"

    unlabeled_faces = (
        await client.get("/api/v1/evaluation/face-logs?status=unlabeled", headers=admin_headers)
    ).json()
    assert unlabeled_faces["total"] == 1

    # 2. Admin chatbot-simulate dry-run (does NOT send WA, logs reply, tests OOD too)
    sim_in = await client.post(
        "/api/v1/evaluation/chatbot-simulate",
        headers=admin_headers,
        json={"phone_wa": "0812-7900-7777", "message_text": "Jadwal pelajaran hari Senin apa?"},
    )
    assert sim_in.status_code == 200
    assert sim_in.json()["wa_sent"] is False
    assert sim_in.json()["is_in_domain"] is True
    assert sim_in.json()["tool_called"] == "get_class_schedule"
    assert len(mock_wa.sent) == 0

    sim_ood = await client.post(
        "/api/v1/evaluation/chatbot-simulate",
        headers=admin_headers,
        json={"phone_wa": "0812-7900-7777", "message_text": "Izin tanya SPP semester ini"},
    )
    assert sim_ood.status_code == 200
    assert sim_ood.json()["wa_sent"] is False
    assert sim_ood.json()["is_in_domain"] is False
    assert len(mock_wa.sent) == 0

    # unregistered_parent must be excluded from in_domain_rate denominator: 1 in-domain / (1 + 1) = 50%
    metrics = (await client.get("/api/v1/evaluation/metrics", headers=admin_headers)).json()
    assert metrics["chatbot_metrics"]["total_messages"] == 3
    assert metrics["chatbot_metrics"]["in_domain_count"] == 1
    assert metrics["chatbot_metrics"]["out_of_domain_count"] == 1
    assert metrics["chatbot_metrics"]["in_domain_rate"] == pytest.approx(50.0)

    # 3. Paginated chatbot-logs endpoint with in_domain filter & bot_response
    ood_logs = (
        await client.get(
            "/api/v1/evaluation/chatbot-logs?in_domain=false&limit=10&offset=0",
            headers=admin_headers,
        )
    ).json()
    assert ood_logs["total"] == 1
    assert "maaf" in ood_logs["items"][0]["bot_response"].lower()

    # 4. CSV formula sanitization + Sesi / Mata Pelajaran column
    csv_res = await client.get("/api/v1/reports/attendance.csv", headers=admin_headers)
    assert csv_res.status_code == 200
    csv_rows = list(csv.reader(io.StringIO(csv_res.text)))
    data_row = csv_rows[1]
    assert data_row[1] == "Mata Pelajaran +Matematika"
    assert data_row[2] == "'=XI IPA Formula"
    assert data_row[4] == "'=CMD|' /C calc'!A0"

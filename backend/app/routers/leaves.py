from datetime import date, datetime, timezone
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    Attendance,
    AttendanceSession,
    LeaveRequest,
    Parent,
    SchoolClass,
    Student,
    User,
)
from app.providers.whatsapp import WhatsAppProvider, get_whatsapp_provider
from app.schemas import (
    LeaveRequestResponse,
    LeaveVerifyRequest,
    LeaveVerifyResponse,
)
from app.security import get_current_user, require_teacher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["leaves"])

_LEAVE_TYPE_LABELS_ID: dict[str, str] = {
    "sick": "SAKIT",
    "permit": "IZIN",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_date_range_id(start_date: date, end_date: date) -> str:
    start_str = start_date.strftime("%d/%m/%Y")
    if start_date == end_date:
        return start_str
    return f"{start_str} s.d. {end_date.strftime('%d/%m/%Y')}"


def _build_leave_wa_message(
    decision: Literal["approved", "rejected"],
    request_type: str,
    student_name: str,
    class_name: str,
    start_date: date,
    end_date: date,
    teacher_name: str,
    note: str | None = None,
) -> str:
    """Build a polite Indonesian WhatsApp reply for a verified leave request."""
    type_label = _LEAVE_TYPE_LABELS_ID.get(request_type, request_type.upper())
    date_range_str = _format_date_range_id(start_date, end_date)

    if decision == "approved":
        lines = [
            "Yth. Bapak/Ibu Orang Tua/Wali Murid,",
            "",
            (
                f"Pengajuan *{type_label}* untuk ananda *{student_name}* "
                f"(Kelas {class_name}) pada tanggal {date_range_str} telah "
                f"*DISETUJUI* oleh Bapak/Ibu Guru *{teacher_name}*."
            ),
        ]
        if note:
            lines.append(f"Catatan guru: {note}")
        lines.extend(
            [
                "",
                "Data presensi siswa telah disesuaikan secara otomatis.",
                "",
                "Terima kasih atas konfirmasi Bapak/Ibu.",
            ]
        )
        return "\n".join(lines)

    lines = [
        "Yth. Bapak/Ibu Orang Tua/Wali Murid,",
        "",
        (
            f"Mohon maaf, pengajuan *{type_label}* untuk ananda *{student_name}* "
            f"(Kelas {class_name}) pada tanggal {date_range_str} *DITOLAK* "
            f"oleh Bapak/Ibu Guru *{teacher_name}*."
        ),
    ]
    if note:
        lines.append(f"Catatan guru: {note}")
    lines.extend(
        [
            "",
            "Silakan hubungi wali kelas atau pihak sekolah apabila memerlukan informasi lebih lanjut.",
            "",
            "Terima kasih atas perhatian Bapak/Ibu.",
        ]
    )
    return "\n".join(lines)


def _to_leave_response(
    leave_req: LeaveRequest,
    student: Student,
    school_class: SchoolClass,
    parent: Parent,
    verified_by_name: str | None,
) -> LeaveRequestResponse:
    return LeaveRequestResponse(
        id=leave_req.id,
        student_id=student.id,
        student_name=student.name,
        student_nis=student.nis,
        class_id=school_class.id,
        class_name=school_class.name,
        parent_id=parent.id,
        parent_name=parent.name,
        parent_phone_wa=parent.phone_wa,
        request_type=leave_req.request_type,
        start_date=leave_req.start_date,
        end_date=leave_req.end_date,
        reason=leave_req.reason,
        attachment_url=leave_req.attachment_url,
        status=leave_req.status,
        verified_by=leave_req.verified_by,
        verified_by_name=verified_by_name,
        verified_at=leave_req.verified_at,
        verification_note=leave_req.verification_note,
        created_at=leave_req.created_at,
    )


@router.get("/leave-requests", response_model=list[LeaveRequestResponse])
async def list_leave_requests(
    status_filter: Literal["pending", "approved", "rejected"] | None = Query(
        default=None, alias="status"
    ),
    class_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LeaveRequestResponse]:
    """List student leave requests enriched with student, class, parent, and verifier details."""
    if current_user.role not in {"admin", "teacher"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak.",
        )

    stmt = (
        select(
            LeaveRequest,
            Student,
            SchoolClass,
            Parent,
            User.name.label("verified_by_name"),
        )
        .join(Student, LeaveRequest.student_id == Student.id)
        .join(SchoolClass, Student.class_id == SchoolClass.id)
        .join(Parent, LeaveRequest.parent_id == Parent.id)
        .outerjoin(User, LeaveRequest.verified_by == User.id)
        .order_by(LeaveRequest.created_at.desc(), LeaveRequest.id.desc())
    )

    if status_filter is not None:
        stmt = stmt.where(LeaveRequest.status == status_filter)
    if class_id is not None:
        stmt = stmt.where(Student.class_id == class_id)

    rows = (await db.execute(stmt)).all()
    return [
        _to_leave_response(leave_req, student, school_class, parent, verifier_name)
        for leave_req, student, school_class, parent, verifier_name in rows
    ]


@router.patch("/leave-requests/{leave_id}/verify", response_model=LeaveVerifyResponse)
async def verify_leave_request(
    leave_id: str,
    payload: LeaveVerifyRequest,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
    whatsapp_provider: WhatsAppProvider = Depends(get_whatsapp_provider),
) -> LeaveVerifyResponse:
    """Approve or reject a pending leave request, sync matching sessions, and notify parent WA."""
    row = (
        await db.execute(
            select(LeaveRequest, Student, SchoolClass, Parent)
            .join(Student, LeaveRequest.student_id == Student.id)
            .join(SchoolClass, Student.class_id == SchoolClass.id)
            .join(Parent, LeaveRequest.parent_id == Parent.id)
            .where(LeaveRequest.id == leave_id)
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pengajuan izin tidak ditemukan.",
        )

    leave_req, student, school_class, parent = row
    if not student.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Siswa berstatus tidak aktif. Pengajuan izin tidak dapat diverifikasi.",
        )
    if leave_req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pengajuan izin ini sudah diverifikasi sebelumnya.",
        )

    now_utc = _utc_now()
    teacher_id = current_user.id
    teacher_name = current_user.name
    leave_id_val = leave_req.id
    leave_req_type = leave_req.request_type
    leave_start_date = leave_req.start_date
    leave_end_date = leave_req.end_date
    leave_reason = leave_req.reason
    leave_attachment_url = leave_req.attachment_url
    leave_created_at = leave_req.created_at
    student_id_val = student.id
    student_name = student.name
    student_nis = student.nis
    class_id_val = school_class.id
    class_name = school_class.name
    parent_id_val = parent.id
    parent_name = parent.name
    parent_phone_wa = parent.phone_wa

    update_result = await db.execute(
        update(LeaveRequest)
        .where(
            LeaveRequest.id == leave_id_val,
            LeaveRequest.status == "pending",
        )
        .values(
            status=payload.decision,
            verified_by=teacher_id,
            verified_at=now_utc,
            verification_note=payload.note,
        )
        .execution_options(synchronize_session=False)
    )
    if update_result.rowcount != 1:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pengajuan izin ini sudah diverifikasi sebelumnya.",
        )

    leave_response = LeaveRequestResponse(
        id=leave_id_val,
        student_id=student_id_val,
        student_name=student_name,
        student_nis=student_nis,
        class_id=class_id_val,
        class_name=class_name,
        parent_id=parent_id_val,
        parent_name=parent_name,
        parent_phone_wa=parent_phone_wa,
        request_type=leave_req_type,
        start_date=leave_start_date,
        end_date=leave_end_date,
        reason=leave_reason,
        attachment_url=leave_attachment_url,
        status=payload.decision,
        verified_by=teacher_id,
        verified_by_name=teacher_name,
        verified_at=now_utc,
        verification_note=payload.note,
        created_at=leave_created_at,
    )
    wa_text = _build_leave_wa_message(
        decision=payload.decision,
        request_type=leave_req_type,
        student_name=student_name,
        class_name=class_name,
        start_date=leave_start_date,
        end_date=leave_end_date,
        teacher_name=teacher_name,
        note=payload.note,
    )

    synced_attendances: list[Attendance] = []
    if payload.decision == "approved":
        matching_sessions = (
            await db.scalars(
                select(AttendanceSession).where(
                    AttendanceSession.session_date >= leave_start_date,
                    AttendanceSession.session_date <= leave_end_date,
                    or_(
                        AttendanceSession.class_id == class_id_val,
                        AttendanceSession.class_id.is_(None),
                    ),
                )
            )
        ).all()

        if matching_sessions:
            session_ids = [sess.id for sess in matching_sessions]
            existing_rows = (
                await db.scalars(
                    select(Attendance).where(
                        Attendance.session_id.in_(session_ids),
                        Attendance.student_id == student_id_val,
                    )
                )
            ).all()
            existing_by_session = {att.session_id: att for att in existing_rows}

            for sess in matching_sessions:
                existing_att = existing_by_session.get(sess.id)
                if existing_att is not None:
                    if (
                        existing_att.verification_method == "face_kiosk"
                        and existing_att.status in {"present", "late"}
                    ):
                        continue
                    existing_att.status = leave_req_type
                    existing_att.verification_method = "leave_approved"
                    existing_att.scanned_at = None
                    existing_att.similarity_score = None
                    existing_att.wa_status = "pending"
                    synced_attendances.append(existing_att)
                else:
                    new_att = Attendance(
                        session_id=sess.id,
                        student_id=student_id_val,
                        status=leave_req_type,
                        verification_method="leave_approved",
                        scanned_at=None,
                        similarity_score=None,
                        wa_status="pending",
                        wa_notified_at=None,
                    )
                    try:
                        async with db.begin_nested():
                            db.add(new_att)
                            await db.flush()
                        synced_attendances.append(new_att)
                    except IntegrityError:
                        concurrent_att = await db.scalar(
                            select(Attendance).where(
                                Attendance.session_id == sess.id,
                                Attendance.student_id == student_id_val,
                            )
                        )
                        if concurrent_att is not None and not (
                            concurrent_att.verification_method == "face_kiosk"
                            and concurrent_att.status in {"present", "late"}
                        ):
                            concurrent_att.status = leave_req_type
                            concurrent_att.verification_method = "leave_approved"
                            concurrent_att.scanned_at = None
                            concurrent_att.similarity_score = None
                            concurrent_att.wa_status = "pending"
                            synced_attendances.append(concurrent_att)

    await db.flush()
    synced_ids = [att.id for att in synced_attendances]

    # Commit verification and attendance synchronization first so WA gateway
    # outages never revert the teacher's verification decision.
    await db.commit()

    wa_sent = False
    try:
        wa_sent = bool(await whatsapp_provider.send_message(parent_phone_wa, wa_text))
    except Exception as exc:
        logger.warning(
            "Exception saat mengirim notifikasi WA verifikasi izin %s: %s",
            leave_id_val,
            exc,
        )
        wa_sent = False

    if synced_ids:
        update_values: dict[str, object] = {"wa_status": "sent" if wa_sent else "failed"}
        if wa_sent:
            update_values["wa_notified_at"] = _utc_now()
        try:
            await db.execute(
                update(Attendance)
                .where(Attendance.id.in_(synced_ids))
                .values(**update_values)
            )
            await db.commit()
        except Exception as exc:
            logger.warning(
                "Gagal memperbarui status WA presensi untuk izin %s: %s",
                leave_id_val,
                exc,
            )
            await db.rollback()

    action_label = "disetujui" if payload.decision == "approved" else "ditolak"
    return LeaveVerifyResponse(
        leave=leave_response,
        synced_sessions_count=len(synced_ids),
        wa_sent=wa_sent,
        message=f"Pengajuan izin {student_name} berhasil {action_label}.",
    )

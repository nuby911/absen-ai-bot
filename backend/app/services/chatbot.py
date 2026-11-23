from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone
import logging
from pathlib import PurePosixPath
import time as time_perf
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Attendance,
    AttendanceSession,
    ChatbotLog,
    LeaveRequest,
    Parent,
    Schedule,
    SchoolClass,
    Student,
    User,
)
from app.providers.llm import (
    FALLBACK_MENU_REPLY,
    LEAVE_GUIDE_REPLY,
    LLMProvider,
    LLMResult,
    format_class_schedule_reply,
    format_monthly_recap_reply,
    format_today_attendance_reply,
)
from app.providers.whatsapp import ATTENDANCE_STATUS_LABELS_ID, WhatsAppProvider
from app.schemas import WhatsAppWebhookResponse
from app.security import normalize_wa_phone

logger = logging.getLogger(__name__)

WIB = timezone(timedelta(hours=7))

UNKNOWN_PARENT_REPLY = (
    "Mohon maaf, nomor WhatsApp Anda belum terdaftar di sistem absensi sekolah. "
    "Silakan hubungi admin atau tata usaha sekolah untuk mendaftarkan nomor Anda."
)

_MONTH_NAMES_ID: dict[int, str] = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}

_DAY_NAMES_ID: dict[int, str] = {
    1: "Senin",
    2: "Selasa",
    3: "Rabu",
    4: "Kamis",
    5: "Jumat",
    6: "Sabtu",
    7: "Minggu",
}

_SESSION_TYPE_LABELS_ID: dict[str, str] = {
    "gate_in": "Gerbang Masuk",
    "gate_out": "Gerbang Pulang",
    "subject": "Sesi Mata Pelajaran",
}

_LEAVE_STATUS_LABELS_ID: dict[str, str] = {
    "pending": "Menunggu Verifikasi",
    "approved": "Disetujui",
    "rejected": "Ditolak",
}

CHATBOT_SYSTEM_PROMPT = (
    "Anda adalah Asisten Resmi Sekolah pada layanan WhatsApp Orang Tua. "
    "Gunakan Bahasa Indonesia yang sopan, singkat, dan informatif. "
    "Anda hanya boleh membahas kehadiran siswa hari ini, rekap kehadiran bulanan, "
    "jadwal pelajaran, dan pengajuan izin/sakit anak milik orang tua yang sedang menghubungi. "
    "Selalu gunakan tool yang tersedia untuk mengambil atau menyimpan data, jangan pernah mengarang data. "
    "Jika pertanyaan orang tua di luar domain layanan sekolah tersebut, tolak dengan sopan "
    "dan awali respons dengan penanda [OUT_OF_DOMAIN]."
)


def _wib_now() -> datetime:
    return datetime.now(WIB)


def _format_wib_time(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    target = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    return target.astimezone(WIB).strftime("%H:%M WIB")


def _parse_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sanitize_attachment_url(raw_url: str | None) -> str | None:
    """Allow only http(s) URLs or normalized local `/uploads/...` paths without traversal."""
    if raw_url is None:
        return None
    cleaned = str(raw_url).strip()
    if not cleaned:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        return None
    if "\\" in cleaned or any(ch.isspace() for ch in cleaned):
        return None

    parsed = urlsplit(cleaned)
    scheme = parsed.scheme.lower()
    if scheme:
        if scheme in {"http", "https"} and parsed.netloc:
            return cleaned
        return None

    if parsed.netloc:
        return None
    if not parsed.path.startswith("/uploads/"):
        return None

    posix_parts = PurePosixPath(parsed.path).parts
    if ".." in posix_parts or len(posix_parts) < 3 or posix_parts[:2] != ("/", "uploads"):
        return None
    return cleaned


def _parse_leave_date(raw: str | None, default_date: date) -> date:
    if raw is None or not str(raw).strip():
        return default_date
    cleaned = str(raw).strip()
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError("Format tanggal izin tidak valid. Gunakan format YYYY-MM-DD.")


async def _resolve_owned_students(
    db: AsyncSession,
    parent_id: str,
    student_id: str | None,
    allow_multiple: bool,
) -> tuple[list[tuple[Student, SchoolClass]] | None, dict[str, Any] | None]:
    """Strictly verify student ownership (`Student.parent_id == parent_id`) for every tool."""
    cleaned_id = student_id.strip() if isinstance(student_id, str) else None
    if cleaned_id:
        row = (
            await db.execute(
                select(Student, SchoolClass)
                .join(SchoolClass, Student.class_id == SchoolClass.id)
                .where(
                    Student.id == cleaned_id,
                    Student.parent_id == parent_id,
                )
            )
        ).first()
        if row is None:
            return None, {
                "ok": False,
                "error": "Akses ditolak: data siswa tidak ditemukan atau tidak terdaftar pada akun orang tua ini.",
            }
        return [(row[0], row[1])], None

    rows = (
        await db.execute(
            select(Student, SchoolClass)
            .join(SchoolClass, Student.class_id == SchoolClass.id)
            .where(
                Student.parent_id == parent_id,
                Student.is_active.is_(True),
            )
            .order_by(Student.name)
        )
    ).all()
    if not rows:
        return None, {
            "ok": False,
            "error": "Belum ada siswa aktif yang terdaftar pada akun orang tua ini.",
        }

    owned = [(row[0], row[1]) for row in rows]
    if not allow_multiple and len(owned) > 1:
        names = ", ".join(s.name for s, _ in owned)
        return None, {
            "ok": False,
            "error": (
                f"Terdapat lebih dari satu siswa terdaftar ({names}). "
                "Mohon sebutkan nama anak yang ingin diajukan izin."
            ),
        }
    return owned, None


async def _safe_send_wa(
    whatsapp_provider: WhatsAppProvider,
    phone_wa: str,
    text: str,
) -> bool:
    """Deliver outbound WhatsApp text without raising gateway exceptions to the webhook."""
    try:
        return bool(await whatsapp_provider.send_message(phone_wa, text))
    except Exception as exc:
        logger.warning("Gagal mengirim balasan chatbot WhatsApp ke %s: %s", phone_wa, exc)
        return False


class KeywordFallbackEngine:
    """Deterministic numbered keyword menu fallback when the primary LLM fails or times out."""

    async def handle(
        self,
        message_text: str | None,
        tool_executor: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    ) -> LLMResult:
        """Handle quick menu choices `1`..`4` or present the fallback menu."""
        cmd = (message_text or "").strip().lower()

        if cmd in {"1", "menu 1", "status hari ini"}:
            data = await tool_executor("get_today_attendance", {})
            return LLMResult(
                reply_text=format_today_attendance_reply(data),
                detected_intent="fallback_today_attendance",
                tool_called="get_today_attendance",
                is_in_domain=True,
            )

        if cmd in {"2", "menu 2", "rekap bulanan"}:
            data = await tool_executor("get_monthly_recap", {})
            return LLMResult(
                reply_text=format_monthly_recap_reply(data),
                detected_intent="fallback_monthly_recap",
                tool_called="get_monthly_recap",
                is_in_domain=True,
            )

        if cmd in {"3", "menu 3", "jadwal pelajaran"}:
            data = await tool_executor("get_class_schedule", {})
            return LLMResult(
                reply_text=format_class_schedule_reply(data),
                detected_intent="fallback_class_schedule",
                tool_called="get_class_schedule",
                is_in_domain=True,
            )

        if cmd in {"4", "menu 4", "cara ajukan izin"}:
            return LLMResult(
                reply_text=LEAVE_GUIDE_REPLY,
                detected_intent="fallback_leave_help",
                tool_called=None,
                is_in_domain=True,
            )

        return LLMResult(
            reply_text=FALLBACK_MENU_REPLY,
            detected_intent="fallback_menu",
            tool_called=None,
            is_in_domain=True,
        )


class ChatbotOrchestrator:
    """Orchestrates parent-isolated AI chatbot tool calls, fallback, and audit logging."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        whatsapp_provider: WhatsAppProvider,
        fallback_engine: KeywordFallbackEngine | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.whatsapp_provider = whatsapp_provider
        self.fallback_engine = fallback_engine or KeywordFallbackEngine()

    def _build_tool_executor(
        self,
        db: AsyncSession,
        parent_id: str,
        default_media_url: str | None,
    ) -> Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]:
        """Create a parent-scoped tool dispatcher bound strictly to `parent_id`."""

        async def get_today_attendance(student_id: str | None = None) -> dict[str, Any]:
            owned, err = await _resolve_owned_students(
                db, parent_id=parent_id, student_id=student_id, allow_multiple=True
            )
            if err is not None or owned is None:
                return err or {"ok": False, "error": "Akses ditolak."}

            today = _wib_now().date()
            student_ids = [stu.id for stu, _ in owned]

            att_rows = (
                await db.execute(
                    select(Attendance, AttendanceSession, Schedule.subject_name)
                    .join(AttendanceSession, Attendance.session_id == AttendanceSession.id)
                    .outerjoin(Schedule, AttendanceSession.schedule_id == Schedule.id)
                    .where(
                        Attendance.student_id.in_(student_ids),
                        AttendanceSession.session_date == today,
                    )
                    .order_by(
                        Attendance.scanned_at.asc().nullslast(),
                        AttendanceSession.opened_at.asc(),
                    )
                )
            ).all()

            records_by_student: dict[str, list[dict[str, Any]]] = {sid: [] for sid in student_ids}
            for att, sess, subject_name in att_rows:
                session_label = (
                    f"Mata Pelajaran {subject_name}"
                    if subject_name
                    else _SESSION_TYPE_LABELS_ID.get(sess.session_type, sess.session_type)
                )
                records_by_student[att.student_id].append(
                    {
                        "session_type": sess.session_type,
                        "session_label": session_label,
                        "status": att.status,
                        "status_label": ATTENDANCE_STATUS_LABELS_ID.get(att.status, att.status),
                        "verification_method": att.verification_method,
                        "scanned_at_wib": _format_wib_time(att.scanned_at),
                    }
                )

            leave_rows = (
                await db.scalars(
                    select(LeaveRequest)
                    .where(
                        LeaveRequest.student_id.in_(student_ids),
                        LeaveRequest.parent_id == parent_id,
                        LeaveRequest.start_date <= today,
                        LeaveRequest.end_date >= today,
                    )
                    .order_by(LeaveRequest.created_at.desc())
                )
            ).all()
            leave_by_student: dict[str, str] = {}
            for lr in leave_rows:
                if lr.student_id not in leave_by_student:
                    type_lbl = "Sakit" if lr.request_type == "sick" else "Izin"
                    status_lbl = _LEAVE_STATUS_LABELS_ID.get(lr.status, lr.status)
                    leave_by_student[lr.student_id] = f"{type_lbl} ({status_lbl})"

            return {
                "ok": True,
                "date": today.isoformat(),
                "students": [
                    {
                        "student_id": stu.id,
                        "student_name": stu.name,
                        "nis": stu.nis,
                        "class_name": sc.name,
                        "records": records_by_student[stu.id],
                        "has_records": bool(records_by_student[stu.id]),
                        "leave_status_today": leave_by_student.get(stu.id),
                    }
                    for stu, sc in owned
                ],
            }

        async def get_monthly_recap(
            student_id: str | None = None,
            month: int | None = None,
            year: int | None = None,
        ) -> dict[str, Any]:
            owned, err = await _resolve_owned_students(
                db, parent_id=parent_id, student_id=student_id, allow_multiple=True
            )
            if err is not None or owned is None:
                return err or {"ok": False, "error": "Akses ditolak."}

            now_wib = _wib_now()
            parsed_month = _parse_optional_int(month)
            parsed_year = _parse_optional_int(year)
            resolved_month = now_wib.month if parsed_month is None else parsed_month
            resolved_year = now_wib.year if parsed_year is None else parsed_year
            if not (1 <= resolved_month <= 12) or not (2000 <= resolved_year <= 2100):
                return {"ok": False, "error": "Bulan atau tahun rekap tidak valid."}

            month_start = date(resolved_year, resolved_month, 1)
            next_month_start = (
                date(resolved_year + 1, 1, 1)
                if resolved_month == 12
                else date(resolved_year, resolved_month + 1, 1)
            )

            student_ids = [stu.id for stu, _ in owned]
            rows = (
                await db.execute(
                    select(Attendance.student_id, Attendance.status)
                    .join(AttendanceSession, Attendance.session_id == AttendanceSession.id)
                    .where(
                        Attendance.student_id.in_(student_ids),
                        AttendanceSession.session_date >= month_start,
                        AttendanceSession.session_date < next_month_start,
                    )
                )
            ).all()

            counts_map: dict[str, dict[str, int]] = {
                sid: {"present": 0, "late": 0, "permit": 0, "sick": 0, "absent": 0}
                for sid in student_ids
            }
            for sid, att_status in rows:
                if att_status in counts_map[sid]:
                    counts_map[sid][att_status] += 1

            student_summaries: list[dict[str, Any]] = []
            for stu, sc in owned:
                c = counts_map[stu.id]
                total_records = sum(c.values())
                attended = c["present"] + c["late"]
                rate = (
                    round(attended / total_records * 100.0, 2)
                    if total_records > 0
                    else 0.0
                )
                student_summaries.append(
                    {
                        "student_id": stu.id,
                        "student_name": stu.name,
                        "nis": stu.nis,
                        "class_name": sc.name,
                        "total_records": total_records,
                        "present_count": c["present"],
                        "late_count": c["late"],
                        "permit_count": c["permit"],
                        "sick_count": c["sick"],
                        "absent_count": c["absent"],
                        "attendance_rate": rate,
                    }
                )

            month_name = _MONTH_NAMES_ID.get(resolved_month, str(resolved_month))
            return {
                "ok": True,
                "month": resolved_month,
                "year": resolved_year,
                "month_label": f"{month_name} {resolved_year}",
                "students": student_summaries,
            }

        async def get_class_schedule(
            student_id: str | None = None,
            day_of_week: int | None = None,
        ) -> dict[str, Any]:
            owned, err = await _resolve_owned_students(
                db, parent_id=parent_id, student_id=student_id, allow_multiple=True
            )
            if err is not None or owned is None:
                return err or {"ok": False, "error": "Akses ditolak."}

            resolved_dow = _parse_optional_int(day_of_week)
            if resolved_dow is not None and not (1 <= resolved_dow <= 7):
                return {
                    "ok": False,
                    "error": "Hari jadwal harus bernilai 1 (Senin) sampai 7 (Minggu).",
                }

            class_ids = list({stu.class_id for stu, _ in owned})
            stmt = (
                select(Schedule, User.name.label("teacher_name"))
                .join(User, Schedule.teacher_id == User.id)
                .where(Schedule.class_id.in_(class_ids))
                .order_by(Schedule.day_of_week.asc(), Schedule.start_time.asc())
            )
            if resolved_dow is not None:
                stmt = stmt.where(Schedule.day_of_week == resolved_dow)

            schedule_rows = (await db.execute(stmt)).all()
            schedules_by_class: dict[str, list[dict[str, Any]]] = {cid: [] for cid in class_ids}
            for sched, teacher_name in schedule_rows:
                schedules_by_class[sched.class_id].append(
                    {
                        "day_of_week": sched.day_of_week,
                        "day_name": _DAY_NAMES_ID.get(sched.day_of_week, str(sched.day_of_week)),
                        "subject_name": sched.subject_name,
                        "start_time": sched.start_time.strftime("%H:%M"),
                        "end_time": sched.end_time.strftime("%H:%M"),
                        "teacher_name": teacher_name,
                    }
                )

            return {
                "ok": True,
                "day_of_week": resolved_dow,
                "day_name": _DAY_NAMES_ID.get(resolved_dow) if resolved_dow else None,
                "students": [
                    {
                        "student_id": stu.id,
                        "student_name": stu.name,
                        "class_name": sc.name,
                        "schedules": schedules_by_class.get(stu.class_id, []),
                    }
                    for stu, sc in owned
                ],
            }

        async def submit_leave_request(
            student_id: str | None = None,
            request_type: str = "permit",
            start_date: str | None = None,
            end_date: str | None = None,
            reason: str = "",
            attachment_url: str | None = None,
        ) -> dict[str, Any]:
            owned, err = await _resolve_owned_students(
                db, parent_id=parent_id, student_id=student_id, allow_multiple=False
            )
            if err is not None or owned is None:
                return err or {"ok": False, "error": "Akses ditolak."}

            student, school_class = owned[0]
            raw_type = str(request_type or "").strip().lower()
            type_map = {
                "permit": "permit",
                "izin": "permit",
                "ijin": "permit",
                "sick": "sick",
                "sakit": "sick",
            }
            normalized_type = type_map.get(raw_type)
            if normalized_type is None:
                return {
                    "ok": False,
                    "error": "Jenis pengajuan harus 'permit' (izin) atau 'sick' (sakit).",
                }

            today = _wib_now().date()
            try:
                parsed_start = _parse_leave_date(start_date, today)
                parsed_end = _parse_leave_date(end_date, parsed_start)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}

            if parsed_end < parsed_start:
                return {
                    "ok": False,
                    "error": "Tanggal selesai izin tidak boleh lebih awal dari tanggal mulai.",
                }

            cleaned_reason = str(reason or "").strip()
            if not cleaned_reason:
                return {
                    "ok": False,
                    "error": "Alasan pengajuan izin atau sakit wajib diisi.",
                }

            explicit_attachment = (
                str(attachment_url).strip()
                if attachment_url is not None and str(attachment_url).strip()
                else None
            )
            if explicit_attachment is not None:
                resolved_attachment = _sanitize_attachment_url(explicit_attachment)
                if resolved_attachment is None:
                    logger.warning(
                        "URL lampiran izin tidak valid diabaikan untuk siswa %s: %s",
                        student.id,
                        explicit_attachment,
                    )
            else:
                resolved_attachment = _sanitize_attachment_url(default_media_url)

            student_name = student.name
            student_id_val = student.id
            class_name = school_class.name

            leave_req = LeaveRequest(
                student_id=student_id_val,
                parent_id=parent_id,
                request_type=normalized_type,
                start_date=parsed_start,
                end_date=parsed_end,
                reason=cleaned_reason,
                attachment_url=resolved_attachment,
                status="pending",
            )
            db.add(leave_req)
            await db.flush()
            leave_id = leave_req.id

            return {
                "ok": True,
                "leave_id": leave_id,
                "student_id": student_id_val,
                "student_name": student_name,
                "class_name": class_name,
                "request_type": normalized_type,
                "start_date": parsed_start.isoformat(),
                "end_date": parsed_end.isoformat(),
                "reason": cleaned_reason,
                "attachment_url": resolved_attachment,
                "status": "pending",
            }

        async def dispatch(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
            safe_args = args if isinstance(args, dict) else {}
            if tool_name == "get_today_attendance":
                return await get_today_attendance(student_id=safe_args.get("student_id"))
            if tool_name == "get_monthly_recap":
                return await get_monthly_recap(
                    student_id=safe_args.get("student_id"),
                    month=safe_args.get("month"),
                    year=safe_args.get("year"),
                )
            if tool_name == "get_class_schedule":
                return await get_class_schedule(
                    student_id=safe_args.get("student_id"),
                    day_of_week=safe_args.get("day_of_week"),
                )
            if tool_name == "submit_leave_request":
                return await submit_leave_request(
                    student_id=safe_args.get("student_id"),
                    request_type=safe_args.get("request_type", "permit"),
                    start_date=safe_args.get("start_date"),
                    end_date=safe_args.get("end_date"),
                    reason=safe_args.get("reason", ""),
                    attachment_url=safe_args.get("attachment_url"),
                )
            return {"ok": False, "error": f"Tool '{tool_name}' tidak dikenali."}

        return dispatch

    async def handle_incoming_message(
        self,
        db: AsyncSession,
        phone_wa_raw: str,
        message_text: str | None = None,
        media_url: str | None = None,
    ) -> WhatsAppWebhookResponse:
        """Normalize sender phone, execute parent-isolated chatbot flow, log, and reply WA."""
        started_at = time_perf.perf_counter()
        normalized_phone = normalize_wa_phone(phone_wa_raw)
        sanitized_media_url = _sanitize_attachment_url(media_url)
        if media_url is not None and str(media_url).strip() and sanitized_media_url is None:
            logger.warning(
                "URL media webhook tidak valid diabaikan dari %s: %s",
                normalized_phone,
                media_url,
            )

        cleaned_message = (message_text or "").strip()
        if not cleaned_message and sanitized_media_url:
            cleaned_message = "Lampiran surat izin"

        parent = await db.scalar(select(Parent).where(Parent.phone_wa == normalized_phone))
        if parent is None:
            latency_ms = max(0, int(round((time_perf.perf_counter() - started_at) * 1000)))
            db.add(
                ChatbotLog(
                    parent_id=None,
                    phone_wa=normalized_phone,
                    user_message=cleaned_message,
                    detected_intent="unregistered_parent",
                    tool_called=None,
                    bot_response=UNKNOWN_PARENT_REPLY,
                    is_in_domain=True,
                    is_fallback=False,
                    latency_ms=latency_ms,
                )
            )
            await db.commit()
            wa_sent = await _safe_send_wa(
                self.whatsapp_provider, normalized_phone, UNKNOWN_PARENT_REPLY
            )
            return WhatsAppWebhookResponse(
                reply_text=UNKNOWN_PARENT_REPLY,
                is_in_domain=True,
                is_fallback=False,
                tool_called=None,
                detected_intent="unregistered_parent",
                latency_ms=latency_ms,
                wa_sent=wa_sent,
                ignored=False,
            )

        # Capture parent scalars before any commit/rollback so async attributes never expire
        parent_id = parent.id
        parent_name = parent.name
        parent_phone = parent.phone_wa

        student_rows = (
            await db.execute(
                select(Student, SchoolClass)
                .join(SchoolClass, Student.class_id == SchoolClass.id)
                .where(Student.parent_id == parent_id, Student.is_active.is_(True))
                .order_by(Student.name)
            )
        ).all()

        today_wib = _wib_now().date()
        context: dict[str, Any] = {
            "parent_name": parent_name,
            "today": today_wib.isoformat(),
            "today_day_of_week": today_wib.isoweekday(),
            "media_url": sanitized_media_url,
            "students": [
                {
                    "id": stu.id,
                    "nis": stu.nis,
                    "name": stu.name,
                    "class_name": sc.name,
                }
                for stu, sc in student_rows
            ],
        }

        tool_executor = self._build_tool_executor(
            db=db,
            parent_id=parent_id,
            default_media_url=sanitized_media_url,
        )

        is_fallback = False
        try:
            llm_result = await self.llm_provider.generate_with_tools(
                system_prompt=CHATBOT_SYSTEM_PROMPT,
                user_message=cleaned_message,
                context=context,
                tool_executor=tool_executor,
            )
        except Exception as exc:
            logger.warning(
                "LLMProvider gagal/timeout untuk orang tua %s (%s), beralih ke fallback: %s",
                parent_id,
                parent_phone,
                exc,
            )
            await db.rollback()
            is_fallback = True
            llm_result = await self.fallback_engine.handle(cleaned_message, tool_executor)

        latency_ms = max(0, int(round((time_perf.perf_counter() - started_at) * 1000)))
        reply_text = llm_result.reply_text
        detected_intent = llm_result.detected_intent
        tool_called = llm_result.tool_called
        is_in_domain = llm_result.is_in_domain

        db.add(
            ChatbotLog(
                parent_id=parent_id,
                phone_wa=parent_phone,
                user_message=cleaned_message,
                detected_intent=detected_intent,
                tool_called=tool_called,
                bot_response=reply_text,
                is_in_domain=is_in_domain,
                is_fallback=is_fallback,
                latency_ms=latency_ms,
            )
        )
        await db.commit()

        wa_sent = await _safe_send_wa(self.whatsapp_provider, parent_phone, reply_text)

        return WhatsAppWebhookResponse(
            reply_text=reply_text,
            is_in_domain=is_in_domain,
            is_fallback=is_fallback,
            tool_called=tool_called,
            detected_intent=detected_intent,
            latency_ms=latency_ms,
            wa_sent=wa_sent,
            ignored=False,
        )

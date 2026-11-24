from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta
import logging
import re
from typing import Any, Protocol, runtime_checkable

from fastapi import Request
import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

OUT_OF_DOMAIN_MARKER = "[OUT_OF_DOMAIN]"

OUT_OF_DOMAIN_REPLY = (
    "Mohon maaf, saya adalah Asisten Sekolah resmi yang hanya dapat membantu informasi "
    "kehadiran siswa, rekap absensi bulanan, jadwal pelajaran, serta pengajuan izin/sakit. "
    "Silakan tanyakan seputar layanan sekolah tersebut."
)

LEAVE_GUIDE_REPLY = (
    "Untuk mengajukan izin atau sakit melalui WhatsApp, silakan kirim pesan dengan format:\n"
    "- *Sakit:* \"Anak saya [Nama Anak] sakit [alasan] hari ini/tanggal YYYY-MM-DD\"\n"
    "- *Izin:* \"Mohon izin [Nama Anak] tidak masuk tanggal YYYY-MM-DD karena [alasan]\"\n\n"
    "Bapak/Ibu juga dapat melampirkan foto surat keterangan dokter atau surat izin."
)

GREETING_HELP_REPLY = (
    "Selamat datang di Layanan Asisten WhatsApp Sekolah.\n"
    "Bapak/Ibu dapat menanyakan:\n"
    "1. Status kehadiran anak hari ini\n"
    "2. Rekap kehadiran bulanan\n"
    "3. Jadwal pelajaran kelas\n"
    "4. Pengajuan izin atau sakit anak (dapat disertai foto surat keterangan)\n\n"
    "Silakan ketik pertanyaan Bapak/Ibu atau balas angka *1* sampai *4*."
)

FALLBACK_MENU_REPLY = (
    "Mohon maaf, asisten AI sedang mengalami gangguan sementara. "
    "Silakan pilih menu layanan cepat dengan membalas angka berikut:\n\n"
    "1. Status Kehadiran Hari Ini\n"
    "2. Rekap Kehadiran Bulanan\n"
    "3. Jadwal Pelajaran\n"
    "4. Cara Ajukan Izin / Sakit"
)

_TOOL_TO_INTENT: dict[str, str] = {
    "get_today_attendance": "check_today_attendance",
    "get_monthly_recap": "check_monthly_recap",
    "get_class_schedule": "check_schedule",
    "submit_leave_request": "submit_leave",
}

_MONTH_NAMES_ID: dict[str, int] = {
    "januari": 1,
    "jan": 1,
    "februari": 2,
    "feb": 2,
    "maret": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "mei": 5,
    "juni": 6,
    "jun": 6,
    "juli": 7,
    "jul": 7,
    "agustus": 8,
    "agust": 8,
    "agu": 8,
    "agt": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "oktober": 10,
    "okt": 10,
    "november": 11,
    "nov": 11,
    "desember": 12,
    "des": 12,
}

_MONTH_REGEX_PATTERN = "|".join(
    sorted((re.escape(name) for name in _MONTH_NAMES_ID), key=len, reverse=True)
)

_DAY_NAMES_ID: dict[str, int] = {
    "senin": 1,
    "selasa": 2,
    "rabu": 3,
    "kamis": 4,
    "jumat": 5,
    "jum'at": 5,
    "sabtu": 6,
    "minggu": 7,
    "ahad": 7,
}

_STUDENT_MATCH_STOPWORDS: frozenset[str] = frozenset(
    {
        "anak",
        "saya",
        "siswa",
        "murid",
        "kelas",
        "hari",
        "ini",
        "besok",
        "lusa",
        "izin",
        "ijin",
        "sakit",
        "hadir",
        "absen",
        "absensi",
        "presensi",
        "rekap",
        "bulan",
        "jadwal",
        "pelajaran",
        "mapel",
        "cek",
        "status",
        "mohon",
        "tolong",
        "yang",
        "dan",
        "atau",
        "dari",
        "untuk",
        "pada",
        "tidak",
        "bisa",
        "masuk",
        "sekolah",
        "guru",
        "wali",
        "bapak",
        "ibu",
        "ananda",
        "putra",
        "putri",
        "sudah",
        "belum",
        "apakah",
        "karena",
        "selama",
        "sampai",
        "hingga",
        "dengan",
        "surat",
        "dokter",
        "demam",
        "acara",
        "keluarga",
        *_DAY_NAMES_ID.keys(),
        *_MONTH_NAMES_ID.keys(),
    }
)

CHATBOT_TOOL_DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "get_today_attendance",
        "description": (
            "Ambil status kehadiran siswa milik orang tua untuk hari ini "
            "(gerbang masuk/pulang dan mata pelajaran)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "student_id": {
                    "type": "STRING",
                    "description": "UUID siswa milik orang tua (opsional jika hanya 1 anak).",
                },
            },
        },
    },
    {
        "name": "get_monthly_recap",
        "description": (
            "Ambil rekapitulasi dan persentase kehadiran bulanan siswa milik orang tua."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "student_id": {
                    "type": "STRING",
                    "description": "UUID siswa milik orang tua (opsional).",
                },
                "month": {
                    "type": "INTEGER",
                    "description": "Nomor bulan 1-12 (opsional, default bulan berjalan).",
                },
                "year": {
                    "type": "INTEGER",
                    "description": "Tahun 4 digit, mis. 2026 (opsional, default tahun berjalan).",
                },
            },
        },
    },
    {
        "name": "get_class_schedule",
        "description": "Ambil jadwal pelajaran mingguan atau harian untuk kelas siswa milik orang tua.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "student_id": {
                    "type": "STRING",
                    "description": "UUID siswa milik orang tua (opsional).",
                },
                "day_of_week": {
                    "type": "INTEGER",
                    "description": "Hari ke 1 (Senin) sampai 7 (Minggu). Kosongkan untuk semua hari.",
                },
            },
        },
    },
    {
        "name": "submit_leave_request",
        "description": (
            "Ajukan permohonan izin atau sakit untuk siswa milik orang tua dengan status awal pending."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "student_id": {
                    "type": "STRING",
                    "description": "UUID siswa milik orang tua (opsional jika hanya 1 anak).",
                },
                "request_type": {
                    "type": "STRING",
                    "description": "Jenis pengajuan: 'permit' (izin) atau 'sick' (sakit).",
                    "enum": ["permit", "sick"],
                },
                "start_date": {
                    "type": "STRING",
                    "description": "Tanggal mulai format YYYY-MM-DD (default hari ini).",
                },
                "end_date": {
                    "type": "STRING",
                    "description": "Tanggal selesai format YYYY-MM-DD (default sama dengan start_date).",
                },
                "reason": {
                    "type": "STRING",
                    "description": "Alasan izin atau keterangan sakit dari orang tua.",
                },
            },
            "required": ["request_type", "reason"],
        },
    },
]


@dataclass(frozen=True, slots=True)
class LLMResult:
    """Normalized output returned by an LLMProvider or KeywordFallbackEngine."""

    reply_text: str
    detected_intent: str | None = None
    tool_called: str | None = None
    is_in_domain: bool = True


ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for conversational school-assistant LLM backends with function calling."""

    async def generate_with_tools(
        self,
        system_prompt: str,
        user_message: str,
        context: dict[str, Any],
        tool_executor: ToolExecutor,
    ) -> LLMResult:
        """Process a parent's message, optionally invoke tools, and return an Indonesian reply."""
        ...


# ---------------------------------------------------------------------------
# Shared Indonesian Tool Response Formatters
# ---------------------------------------------------------------------------


def format_today_attendance_reply(data: dict[str, Any]) -> str:
    """Format `get_today_attendance` tool result into polite Indonesian WhatsApp text."""
    if not data.get("ok"):
        return str(data.get("error") or "Data kehadiran hari ini tidak dapat diambil.")

    date_str = str(data.get("date", ""))
    students = data.get("students") or []
    if not students:
        return "Belum ada data siswa yang terdaftar pada akun Bapak/Ibu."

    blocks: list[str] = [f"*Status Kehadiran Hari Ini ({date_str}):*"]
    for stu in students:
        header = f"- *{stu['student_name']}* (Kelas {stu['class_name']})"
        records = stu.get("records") or []
        leave_today = stu.get("leave_status_today")
        if not records:
            if leave_today:
                blocks.append(f"{header}\n  Status pengajuan izin hari ini: {leave_today}")
            else:
                blocks.append(f"{header}\n  Belum ada catatan presensi hari ini.")
            continue

        lines = [header]
        for rec in records:
            time_part = f" pukul {rec['scanned_at_wib']}" if rec.get("scanned_at_wib") else ""
            lines.append(
                f"  • {rec['session_label']}: *{rec['status_label']}*{time_part}"
            )
        if leave_today:
            lines.append(f"  • Status pengajuan izin hari ini: {leave_today}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def format_monthly_recap_reply(data: dict[str, Any]) -> str:
    """Format `get_monthly_recap` tool result into polite Indonesian WhatsApp text."""
    if not data.get("ok"):
        return str(data.get("error") or "Rekap kehadiran bulanan tidak dapat diambil.")

    month_label = str(data.get("month_label") or f"{data.get('month')}/{data.get('year')}")
    students = data.get("students") or []
    if not students:
        return "Belum ada data siswa yang terdaftar pada akun Bapak/Ibu."

    blocks: list[str] = [f"*Rekap Kehadiran Bulan {month_label}:*"]
    for stu in students:
        rate = stu.get("attendance_rate", 0.0)
        blocks.append(
            "\n".join(
                [
                    f"- *{stu['student_name']}* (Kelas {stu['class_name']})",
                    f"  Total Sesi Tercatat: {stu['total_records']}",
                    f"  Hadir: {stu['present_count']} | Terlambat: {stu['late_count']} | "
                    f"Izin: {stu['permit_count']} | Sakit: {stu['sick_count']} | Alfa: {stu['absent_count']}",
                    f"  Persentase Kehadiran: *{rate:.1f}%*",
                ]
            )
        )
    return "\n\n".join(blocks)


def format_class_schedule_reply(data: dict[str, Any]) -> str:
    """Format `get_class_schedule` tool result into polite Indonesian WhatsApp text."""
    if not data.get("ok"):
        return str(data.get("error") or "Jadwal pelajaran tidak dapat diambil.")

    students = data.get("students") or []
    if not students:
        return "Belum ada data siswa yang terdaftar pada akun Bapak/Ibu."

    day_label = data.get("day_name")
    title = (
        f"*Jadwal Pelajaran Hari {day_label}:*"
        if day_label
        else "*Jadwal Pelajaran Mingguan:*"
    )
    blocks: list[str] = [title]
    for stu in students:
        header = f"- *{stu['student_name']}* (Kelas {stu['class_name']})"
        items = stu.get("schedules") or []
        if not items:
            blocks.append(f"{header}\n  Tidak ada jadwal pelajaran yang tercatat.")
            continue
        lines = [header]
        for item in items:
            lines.append(
                f"  • {item['day_name']} {item['start_time']}–{item['end_time']}: "
                f"*{item['subject_name']}* (Guru: {item['teacher_name']})"
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def format_leave_submission_reply(data: dict[str, Any]) -> str:
    """Format `submit_leave_request` tool result into polite Indonesian WhatsApp text."""
    if not data.get("ok"):
        return str(data.get("error") or "Pengajuan izin tidak dapat diproses.")

    type_label = "Sakit" if data.get("request_type") == "sick" else "Izin"
    start_str = str(data.get("start_date", ""))
    end_str = str(data.get("end_date", ""))
    date_part = start_str if start_str == end_str else f"{start_str} s.d. {end_str}"
    lines = [
        f"Pengajuan *{type_label}* untuk ananda *{data['student_name']}* "
        f"(Kelas {data['class_name']}) telah kami terima dan berstatus *Menunggu Verifikasi* guru/wali kelas.",
        f"- Tanggal: {date_part}",
        f"- Alasan: {data['reason']}",
    ]
    if data.get("attachment_url"):
        lines.append("- Lampiran surat: Tersimpan")
    lines.append(
        "\nBapak/Ibu akan menerima notifikasi WhatsApp kembali setelah pengajuan diverifikasi."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gemini REST Function-Calling Provider
# ---------------------------------------------------------------------------


class GeminiLLMProvider:
    """Google Gemini REST API provider supporting structured function calling."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        timeout_seconds: float = 15.0,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.base_url = base_url.rstrip("/")
        self._transport = transport

    async def generate_with_tools(
        self,
        system_prompt: str,
        user_message: str,
        context: dict[str, Any],
        tool_executor: ToolExecutor,
    ) -> LLMResult:
        """Call Gemini generateContent with up to 2 tool-execution iterations."""
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY belum dikonfigurasi.")

        students = context.get("students") or []
        students_desc = (
            ", ".join(
                f"{s['name']} (student_id={s['id']}, nis={s.get('nis', '-')}, kelas={s['class_name']})"
                for s in students
            )
            or "Belum ada siswa terdaftar"
        )
        initial_prompt = (
            "Konteks Orang Tua Terautentikasi:\n"
            f"- Nama Orang Tua: {context.get('parent_name', '-')}\n"
            f"- Tanggal Hari Ini (WIB): {context.get('today', '-')}\n"
            f"- Anak Terdaftar: {students_desc}\n"
            f"- URL Lampiran Media: {context.get('media_url') or 'tidak ada'}\n\n"
            f"Pesan Orang Tua:\n{user_message}"
        )

        contents: list[dict[str, Any]] = [
            {"role": "user", "parts": [{"text": initial_prompt}]}
        ]
        url = f"{self.base_url}/models/{self.model}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        last_tool_called: str | None = None
        max_tool_iterations = 2

        for iteration in range(max_tool_iterations + 1):
            body = {
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": contents,
                "tools": [{"functionDeclarations": CHATBOT_TOOL_DECLARATIONS}],
                "generationConfig": {"temperature": 0.2},
            }

            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    transport=self._transport,
                ) as client:
                    response = await client.post(url, json=body, headers=headers)
            except httpx.TimeoutException as exc:
                raise TimeoutError("Permintaan ke Gemini LLM melewati batas waktu.") from exc
            except (httpx.HTTPError, OSError) as exc:
                raise RuntimeError(f"Gagal menghubungi Gemini LLM: {exc}") from exc

            if not response.is_success:
                raise RuntimeError(
                    f"Gemini LLM mengembalikan status HTTP {response.status_code}."
                )

            try:
                data = response.json()
            except ValueError as exc:
                raise RuntimeError("Respons Gemini LLM bukan JSON yang valid.") from exc

            candidates = data.get("candidates") or []
            if not candidates:
                raise RuntimeError("Gemini LLM tidak mengembalikan kandidat respons.")

            model_content = candidates[0].get("content") or {}
            parts = model_content.get("parts") or []
            function_calls = [
                part["functionCall"]
                for part in parts
                if isinstance(part, dict) and isinstance(part.get("functionCall"), dict)
            ]
            text_parts = [
                part["text"]
                for part in parts
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            ]

            if function_calls:
                if iteration >= max_tool_iterations:
                    raise RuntimeError("Batas iterasi function calling Gemini terlampaui.")

                contents.append({"role": "model", "parts": parts})
                response_parts: list[dict[str, Any]] = []
                for fc in function_calls:
                    fn_name = str(fc.get("name", "")).strip()
                    fn_args = fc.get("args") if isinstance(fc.get("args"), dict) else {}
                    tool_output = await tool_executor(fn_name, fn_args)
                    last_tool_called = fn_name
                    response_parts.append(
                        {
                            "functionResponse": {
                                "name": fn_name,
                                "response": {"result": tool_output},
                            }
                        }
                    )
                contents.append({"role": "user", "parts": response_parts})
                continue

            reply_text = "\n".join(t.strip() for t in text_parts if t.strip()).strip()
            if not reply_text:
                raise RuntimeError("Gemini LLM mengembalikan teks respons kosong.")

            is_in_domain = True
            detected_intent = _TOOL_TO_INTENT.get(last_tool_called or "")
            if OUT_OF_DOMAIN_MARKER in reply_text:
                reply_text = reply_text.replace(OUT_OF_DOMAIN_MARKER, "").strip()
                is_in_domain = False
                detected_intent = "out_of_domain"
            elif last_tool_called is None:
                lowered = reply_text.lower()
                if (
                    "di luar layanan" in lowered
                    or "hanya dapat membantu informasi kehadiran" in lowered
                    or "tidak dapat menjawab pertanyaan di luar" in lowered
                ):
                    is_in_domain = False
                    detected_intent = "out_of_domain"
                else:
                    detected_intent = "general_school_help"

            return LLMResult(
                reply_text=reply_text or OUT_OF_DOMAIN_REPLY,
                detected_intent=detected_intent,
                tool_called=last_tool_called,
                is_in_domain=is_in_domain,
            )

        raise RuntimeError("Gemini LLM gagal menyelesaikan respons.")


# ---------------------------------------------------------------------------
# Rule-Based Natural Indonesian Provider (Local Demo / API-Key-Free Mode)
# ---------------------------------------------------------------------------


def _match_student_id(lower_msg: str, students: list[dict[str, Any]]) -> str | None:
    """Rank-match a parent's child by NIS -> full name -> distinctive tokens; ties return None."""
    if not students:
        return None

    # 1. Exact NIS match
    nis_matches: list[str] = []
    for stu in students:
        nis = str(stu.get("nis", "")).strip().lower()
        if nis and re.search(rf"(?<!\d){re.escape(nis)}(?!\d)", lower_msg):
            nis_matches.append(str(stu["id"]))
    if len(nis_matches) == 1:
        return nis_matches[0]
    if len(nis_matches) > 1:
        return None

    # 2. Full student name match
    full_matches: list[str] = []
    for stu in students:
        name = re.sub(r"\s+", " ", str(stu.get("name", "")).strip().lower())
        if name and re.search(rf"\b{re.escape(name)}\b", lower_msg):
            full_matches.append(str(stu["id"]))
    if len(full_matches) == 1:
        return full_matches[0]
    if len(full_matches) > 1:
        return None

    # 3. Distinctive token match (excluding stopwords & resolving shared-surname ties to None)
    token_scores: list[tuple[int, str]] = []
    for stu in students:
        name = str(stu.get("name", "")).strip().lower()
        distinctive_tokens = {
            tok
            for tok in re.findall(r"[a-z0-9]+", name)
            if len(tok) >= 3 and tok not in _STUDENT_MATCH_STOPWORDS
        }
        matched_count = sum(
            1
            for tok in distinctive_tokens
            if re.search(rf"\b{re.escape(tok)}\b", lower_msg)
        )
        if matched_count > 0:
            token_scores.append((matched_count, str(stu["id"])))

    if not token_scores:
        return None

    token_scores.sort(key=lambda item: item[0], reverse=True)
    top_score = token_scores[0][0]
    top_candidates = [sid for score, sid in token_scores if score == top_score]
    if len(top_candidates) == 1:
        return top_candidates[0]
    return None


def _extract_leave_duration_days(lower_msg: str) -> int | None:
    """Extract intended leave duration in days while ignoring past-tense symptom durations."""
    candidates: list[tuple[int, int, int]] = []  # (start_pos, end_pos, days)

    for match in re.finditer(r"\b(?:selama\s+|untuk\s+)?(\d{1,3})\s+hari\b", lower_msg):
        days = int(match.group(1))
        if days > 0:
            candidates.append((match.start(), match.end(), min(days, 365)))

    for match in re.finditer(r"\b(?:selama\s+|untuk\s+)?(\d{1,2})\s+minggu\b", lower_msg):
        weeks = int(match.group(1))
        if weeks > 0:
            candidates.append((match.start(), match.end(), min(weeks * 7, 365)))

    for match in re.finditer(r"\b(?:selama\s+|untuk\s+)?seminggu\b", lower_msg):
        candidates.append((match.start(), match.end(), 7))

    candidates.sort(key=lambda item: item[0])

    for start_pos, end_pos, days in candidates:
        after = lower_msg[end_pos : end_pos + 20]
        if re.match(r"^\s*(?:yang\s+)?lalu\b", after):
            continue

        before = lower_msg[max(0, start_pos - 35) : start_pos]
        past_matches = list(re.finditer(r"\b(?:sudah|sejak|dari|selama\s+ini)\b", before))
        if past_matches:
            tail_after_past = before[past_matches[-1].end() :]
            span_text = lower_msg[start_pos:end_pos]
            has_explicit_leave_cue = bool(
                re.search(
                    r"\b(?:izin|ijin|tidak\s+(?:bisa\s+)?masuk|cuti|selama|untuk)\b",
                    tail_after_past,
                )
                or re.match(r"^(?:selama|untuk)\b", span_text)
            )
            if not has_explicit_leave_cue:
                continue

        return days
    return None


def _parse_dates_from_text(lower_msg: str, today: date) -> tuple[str, str]:
    """Extract start_date and end_date ISO strings from natural Indonesian text."""
    # 1. Explicit named-month date range (e.g., "25-27 November 2026", "25 s.d. 27 Nov")
    named_range_re = re.compile(
        rf"\b(\d{{1,2}})\s*(?:-|s\.?d\.?|sampai(?:\s+dengan)?|hingga)\s*(\d{{1,2}})\s+({_MONTH_REGEX_PATTERN})(?:\s+(20\d{{2}}))?\b"
    )
    range_match = named_range_re.search(lower_msg)
    if range_match:
        d1 = int(range_match.group(1))
        d2 = int(range_match.group(2))
        month_num = _MONTH_NAMES_ID[range_match.group(3)]
        year_num = int(range_match.group(4)) if range_match.group(4) else today.year
        try:
            start_d = date(year_num, month_num, d1)
            end_d = date(year_num, month_num, d2)
            return start_d.isoformat(), end_d.isoformat()
        except ValueError:
            pass

    # 2. Explicit dates (ISO, DD/MM/YYYY, DD-MM-YYYY, DD Month [YYYY]) in text order
    found_dates: list[tuple[int, int, date]] = []  # (start, end, date_val)

    def _overlaps_existing(s: int, e: int) -> bool:
        return any(not (e <= es or s >= ee) for es, ee, _ in found_dates)

    for match in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", lower_msg):
        try:
            parsed = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            found_dates.append((match.start(), match.end(), parsed))
        except ValueError:
            pass

    for match in re.finditer(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", lower_msg):
        if _overlaps_existing(match.start(), match.end()):
            continue
        try:
            parsed = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
            found_dates.append((match.start(), match.end(), parsed))
        except ValueError:
            pass

    named_single_re = re.compile(
        rf"\b(\d{{1,2}})\s+({_MONTH_REGEX_PATTERN})(?:\s+(20\d{{2}}))?\b"
    )
    for match in named_single_re.finditer(lower_msg):
        if _overlaps_existing(match.start(), match.end()):
            continue
        day_num = int(match.group(1))
        month_num = _MONTH_NAMES_ID[match.group(2)]
        year_num = int(match.group(3)) if match.group(3) else today.year
        try:
            parsed = date(year_num, month_num, day_num)
            found_dates.append((match.start(), match.end(), parsed))
        except ValueError:
            pass

    if found_dates:
        found_dates.sort(key=lambda item: item[0])
        if len(found_dates) >= 2:
            # Preserve order (including inverted ranges) so submit_leave_request validates cleanly
            return found_dates[0][2].isoformat(), found_dates[1][2].isoformat()
        start_d = found_dates[0][2]
        duration_days = _extract_leave_duration_days(lower_msg)
        end_d = start_d + timedelta(days=duration_days - 1) if duration_days else start_d
        return start_d.isoformat(), end_d.isoformat()

    # 3. Multi-day relative Indonesian phrases
    has_today = bool(re.search(r"\bhari\s+ini\b", lower_msg))
    has_besok = bool(re.search(r"\bbesok\b", lower_msg))
    has_lusa = bool(re.search(r"\blusa\b", lower_msg))

    if has_today and has_lusa:
        return today.isoformat(), (today + timedelta(days=2)).isoformat()
    if has_today and has_besok:
        return today.isoformat(), (today + timedelta(days=1)).isoformat()
    if has_besok and has_lusa:
        return (today + timedelta(days=1)).isoformat(), (today + timedelta(days=2)).isoformat()

    # 4. Single relative anchor + optional duration
    if has_lusa:
        start_d = today + timedelta(days=2)
    elif has_besok:
        start_d = today + timedelta(days=1)
    else:
        start_d = today

    duration_days = _extract_leave_duration_days(lower_msg)
    end_d = start_d + timedelta(days=duration_days - 1) if duration_days else start_d
    return start_d.isoformat(), end_d.isoformat()


def _parse_month_year(lower_msg: str, today: date) -> tuple[int, int]:
    """Extract target month and year from Indonesian monthly recap requests."""
    year_match = re.search(r"\b(20\d{2})\b", lower_msg)
    year = int(year_match.group(1)) if year_match else today.year

    if "bulan lalu" in lower_msg or "bulan kemarin" in lower_msg:
        if today.month == 1:
            return 12, year - 1
        return today.month - 1, year

    for month_name, month_num in sorted(
        _MONTH_NAMES_ID.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if re.search(rf"\b{re.escape(month_name)}\b", lower_msg):
            return month_num, year

    return today.month, year


def _parse_day_of_week(lower_msg: str, today: date) -> int | None:
    """Extract ISO day_of_week (1=Monday..7=Sunday) from Indonesian schedule queries."""
    has_week_phrase = bool(
        re.search(
            r"\b(?:minggu\s+(?:ini|depan|lalu)|(?:\d+|satu|dua|tiga|se)\s*minggu|selama\s+\d*\s*minggu)\b",
            lower_msg,
        )
    )
    for day_name, dow in _DAY_NAMES_ID.items():
        if day_name == "minggu" and has_week_phrase and "hari minggu" not in lower_msg:
            continue
        if re.search(rf"\b{re.escape(day_name)}\b", lower_msg):
            return dow
    if re.search(r"\bhari\s+ini\b", lower_msg):
        return today.isoweekday()
    if re.search(r"\blusa\b", lower_msg):
        return (today + timedelta(days=2)).isoweekday()
    if re.search(r"\bbesok\b", lower_msg):
        return (today + timedelta(days=1)).isoweekday()
    return None


def _has_any_phrase(lower_msg: str, phrases: tuple[str, ...]) -> bool:
    """Match any whole word or phrase using word boundaries to avoid substring collisions."""
    return any(re.search(rf"\b{re.escape(phrase)}\b", lower_msg) for phrase in phrases)


class RuleBasedLLMProvider:
    """Deterministic Indonesian natural-language LLM provider connected to the 4 DB tools."""

    async def generate_with_tools(
        self,
        system_prompt: str,
        user_message: str,
        context: dict[str, Any],
        tool_executor: ToolExecutor,
    ) -> LLMResult:
        """Detect Indonesian parent intent, invoke matching tool, and format reply."""
        _ = system_prompt
        text = user_message.strip()
        lower_msg = text.lower()
        students: list[dict[str, Any]] = list(context.get("students") or [])
        today_str = str(context.get("today") or "")
        today = date.fromisoformat(today_str) if today_str else date.today()
        student_id = _match_student_id(lower_msg, students)
        media_url = context.get("media_url")

        # 1. Quick menu shortcuts ("1"-"4", "1."-"4.", "menu 1"-"menu 4")
        menu_cmd = re.sub(r"\s+", " ", lower_msg).rstrip(". ")
        if menu_cmd in {"1", "menu 1"}:
            result = await tool_executor("get_today_attendance", {"student_id": student_id})
            return LLMResult(
                reply_text=format_today_attendance_reply(result),
                detected_intent="check_today_attendance",
                tool_called="get_today_attendance",
                is_in_domain=True,
            )
        if menu_cmd in {"2", "menu 2"}:
            result = await tool_executor("get_monthly_recap", {"student_id": student_id})
            return LLMResult(
                reply_text=format_monthly_recap_reply(result),
                detected_intent="check_monthly_recap",
                tool_called="get_monthly_recap",
                is_in_domain=True,
            )
        if menu_cmd in {"3", "menu 3"}:
            result = await tool_executor("get_class_schedule", {"student_id": student_id})
            return LLMResult(
                reply_text=format_class_schedule_reply(result),
                detected_intent="check_schedule",
                tool_called="get_class_schedule",
                is_in_domain=True,
            )
        if menu_cmd in {"4", "menu 4"}:
            return LLMResult(
                reply_text=LEAVE_GUIDE_REPLY,
                detected_intent="leave_instructions",
                tool_called=None,
                is_in_domain=True,
            )

        # Strip polite conversational openers like "izin tanya ..." so they don't file leaves
        leave_scan_msg = re.sub(
            r"\b(?:izin|ijin)\s+(?:bertanya|tanya|nanya)\b",
            "tanya",
            lower_msg,
        )

        # 2. Explicit "how to apply for leave" inquiry
        if _has_any_phrase(
            leave_scan_msg,
            ("cara", "bagaimana cara", "format izin", "syarat izin", "panduan izin"),
        ) and _has_any_phrase(leave_scan_msg, ("izin", "ijin", "sakit", "cuti")):
            return LLMResult(
                reply_text=LEAVE_GUIDE_REPLY,
                detected_intent="leave_instructions",
                tool_called=None,
                is_in_domain=True,
            )

        sick_keywords = (
            "sakit",
            "demam",
            "flu",
            "batuk",
            "pilek",
            "dirawat",
            "dokter",
            "klinik",
            "puskesmas",
            "rumah sakit",
        )
        leave_keywords = (
            "izin",
            "ijin",
            "tidak masuk",
            "tidak bisa masuk",
            "berhalangan",
            "acara keluarga",
            "cuti",
        )
        inquiry_keywords = (
            "cek",
            "periksa",
            "lihat",
            "status",
            "tanya",
            "bertanya",
            "nanya",
            "sudah disetujui",
            "sudah diverifikasi",
            "apakah sudah",
            "apakah",
            "apa",
            "bagaimana",
            "gimana",
            "kapan",
            "berapa",
            "siapa",
        )
        ood_keywords = (
            "spp",
            "biaya",
            "uang",
            "pembayaran",
            "seragam",
            "rapor",
            "raport",
            "libur",
            "kantin",
            "beasiswa",
            "ppdb",
            "ekstrakurikuler",
            "eskul",
            "ekskul",
            "presiden",
            "cuaca",
        )

        has_sick = _has_any_phrase(leave_scan_msg, sick_keywords)
        has_leave = _has_any_phrase(leave_scan_msg, leave_keywords)
        has_absence_reason = has_sick or _has_any_phrase(
            leave_scan_msg, ("tidak masuk", "tidak bisa masuk", "berhalangan", "acara keluarga", "cuti")
        )
        has_attendance_word = _has_any_phrase(
            lower_msg, ("absen", "absensi", "presensi", "hadir", "kehadiran")
        )
        has_schedule_word = _has_any_phrase(
            lower_msg, ("jadwal", "pelajaran", "mapel", "mata pelajaran", "schedule")
        )

        # 2.5 Out-of-domain early guard (e.g., "izin tanya SPP", "biaya seragam", "pembagian rapor")
        if (
            _has_any_phrase(lower_msg, ood_keywords)
            and not has_absence_reason
            and not has_attendance_word
            and not has_schedule_word
        ):
            return LLMResult(
                reply_text=OUT_OF_DOMAIN_REPLY,
                detected_intent="out_of_domain",
                tool_called=None,
                is_in_domain=False,
            )

        # 3. Leave / sick submission (inquiry verbs ALWAYS beat mohon/tolong)
        has_inquiry_signal = (
            lower_msg.endswith("?")
            or _has_any_phrase(leave_scan_msg, inquiry_keywords)
            or bool(re.match(r"^sudah\b", leave_scan_msg))
        )
        if not has_inquiry_signal and (has_sick or has_leave):
            if leave_scan_msg in {"izin", "ijin", "sakit"} and not media_url:
                return LLMResult(
                    reply_text=LEAVE_GUIDE_REPLY,
                    detected_intent="leave_instructions",
                    tool_called=None,
                    is_in_domain=True,
                )

            request_type = "sick" if has_sick else "permit"
            start_date, end_date = _parse_dates_from_text(lower_msg, today)
            reason = text if text else "Pengajuan izin orang tua"
            result = await tool_executor(
                "submit_leave_request",
                {
                    "student_id": student_id,
                    "request_type": request_type,
                    "start_date": start_date,
                    "end_date": end_date,
                    "reason": reason,
                },
            )
            return LLMResult(
                reply_text=format_leave_submission_reply(result),
                detected_intent="submit_leave",
                tool_called="submit_leave_request",
                is_in_domain=True,
            )

        # 4. Monthly recap (require attendance word alongside "bulan ini"/"bulan lalu"/month name)
        has_month_name = _has_any_phrase(lower_msg, tuple(_MONTH_NAMES_ID.keys()))
        has_relative_month = _has_any_phrase(
            lower_msg, ("bulan ini", "bulan lalu", "bulan kemarin")
        )
        if (
            _has_any_phrase(lower_msg, ("rekap", "bulanan", "persentase", "statistik"))
            or ((has_month_name or has_relative_month) and has_attendance_word)
        ):
            month, year = _parse_month_year(lower_msg, today)
            result = await tool_executor(
                "get_monthly_recap",
                {"student_id": student_id, "month": month, "year": year},
            )
            return LLMResult(
                reply_text=format_monthly_recap_reply(result),
                detected_intent="check_monthly_recap",
                tool_called="get_monthly_recap",
                is_in_domain=True,
            )

        # 5. Class schedule
        if has_schedule_word:
            dow = _parse_day_of_week(lower_msg, today)
            result = await tool_executor(
                "get_class_schedule",
                {"student_id": student_id, "day_of_week": dow},
            )
            return LLMResult(
                reply_text=format_class_schedule_reply(result),
                detected_intent="check_schedule",
                tool_called="get_class_schedule",
                is_in_domain=True,
            )

        # 6. Today's attendance (including status inquiries about sakit/izin)
        today_attendance_keywords = (
            "absen",
            "absensi",
            "presensi",
            "hadir",
            "kehadiran",
            "datang",
            "pulang",
            "terlambat",
            "telat",
            "masuk sekolah",
            "sudah masuk",
            "belum masuk",
            "status anak",
            "gerbang",
        )
        if (
            _has_any_phrase(lower_msg, today_attendance_keywords)
            or (has_inquiry_signal and (has_sick or has_leave))
            or (student_id is not None and _has_any_phrase(lower_msg, ("hari ini", "status", "sudah")))
        ):
            result = await tool_executor(
                "get_today_attendance",
                {"student_id": student_id},
            )
            return LLMResult(
                reply_text=format_today_attendance_reply(result),
                detected_intent="check_today_attendance",
                tool_called="get_today_attendance",
                is_in_domain=True,
            )

        # 7. Polite greeting / help
        greeting_tokens = (
            "halo",
            "hai",
            "hello",
            "hi",
            "assalamualaikum",
            "selamat pagi",
            "selamat siang",
            "selamat sore",
            "selamat malam",
            "menu",
            "bantuan",
            "help",
            "mulai",
            "terima kasih",
            "makasih",
        )
        if _has_any_phrase(lower_msg, greeting_tokens):
            return LLMResult(
                reply_text=GREETING_HELP_REPLY,
                detected_intent="greeting_help",
                tool_called=None,
                is_in_domain=True,
            )

        # 8. Out-of-domain guard
        return LLMResult(
            reply_text=OUT_OF_DOMAIN_REPLY,
            detected_intent="out_of_domain",
            tool_called=None,
            is_in_domain=False,
        )


def create_llm_provider(settings: Settings) -> LLMProvider:
    """Instantiate the configured LLMProvider from application settings."""
    mode = settings.llm_provider_mode.strip().lower()
    if mode in {"fallback", "rule_based", "mock"}:
        return RuleBasedLLMProvider()
    if mode == "gemini":
        if not settings.gemini_api_key.strip():
            return RuleBasedLLMProvider()
        return GeminiLLMProvider(
            api_key=settings.gemini_api_key.strip(),
            model=settings.gemini_model,
        )
    raise ValueError(f"Mode llm_provider_mode tidak dikenali: {settings.llm_provider_mode}")


def get_llm_provider(request: Request) -> LLMProvider:
    """FastAPI dependency returning the app-level LLMProvider instance."""
    provider = getattr(request.app.state, "llm_provider", None)
    if provider is None:
        provider = create_llm_provider(get_settings())
        request.app.state.llm_provider = provider
    return provider

from dataclasses import dataclass
import logging
from typing import Protocol, runtime_checkable

from fastapi import Request
import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

ATTENDANCE_STATUS_LABELS_ID: dict[str, str] = {
    "present": "Hadir",
    "late": "Terlambat",
    "permit": "Izin",
    "sick": "Sakit",
    "absent": "Alfa / Tidak Hadir",
}


@dataclass(frozen=True, slots=True)
class WhatsAppMessage:
    """Recorded outbound WhatsApp message payload."""

    phone_wa: str
    text: str


@runtime_checkable
class WhatsAppProvider(Protocol):
    """Protocol for sending outbound WhatsApp text notifications."""

    async def send_message(self, phone_wa: str, text: str) -> bool:
        """Send a text message to a normalized Indonesian WhatsApp number (`628...`)."""
        ...


class WahaWhatsAppProvider:
    """WhatsApp HTTP API (WAHA) provider using `POST /api/sendText`."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        session: str = "default",
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = session
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    async def send_message(self, phone_wa: str, text: str) -> bool:
        """Send a WhatsApp text message via WAHA, returning False on gateway failure."""
        clean_phone = phone_wa.strip()
        chat_id = clean_phone if "@" in clean_phone else f"{clean_phone}@c.us"
        headers = {"X-Api-Key": self.api_key} if self.api_key else {}
        payload = {
            "chatId": chat_id,
            "text": text,
            "session": self.session,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{self.base_url}/api/sendText",
                    json=payload,
                    headers=headers,
                )
            return response.is_success
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("Gagal mengirim pesan WhatsApp via WAHA ke %s: %s", phone_wa, exc)
            return False


class MockWhatsAppProvider:
    """In-memory deterministic WhatsApp provider for automated tests and offline dev."""

    def __init__(
        self,
        should_fail: bool = False,
        fail_exception: Exception | None = None,
    ) -> None:
        self.sent: list[WhatsAppMessage] = []
        self.should_fail = should_fail
        self.fail_exception = fail_exception

    async def send_message(self, phone_wa: str, text: str) -> bool:
        """Record outbound message unless configured to simulate gateway failure."""
        if self.fail_exception is not None:
            raise self.fail_exception
        if self.should_fail:
            return False
        self.sent.append(WhatsAppMessage(phone_wa=phone_wa, text=text))
        return True


def create_whatsapp_provider(settings: Settings) -> WhatsAppProvider:
    """Instantiate the configured WhatsAppProvider implementation from settings."""
    mode = settings.whatsapp_provider_mode.strip().lower()
    if mode == "mock":
        return MockWhatsAppProvider()
    if mode == "waha":
        return WahaWhatsAppProvider(
            base_url=settings.waha_base_url,
            api_key=settings.waha_api_key,
            session=settings.waha_session,
        )
    raise ValueError(f"Mode whatsapp_provider_mode tidak dikenali: {settings.whatsapp_provider_mode}")


def get_whatsapp_provider(request: Request) -> WhatsAppProvider:
    """FastAPI dependency returning the app-level WhatsAppProvider instance."""
    provider = getattr(request.app.state, "whatsapp_provider", None)
    if provider is None:
        provider = create_whatsapp_provider(get_settings())
        request.app.state.whatsapp_provider = provider
    return provider


def build_attendance_wa_message(
    student_name: str,
    class_name: str,
    status: str,
    scanned_at_str: str,
    session_label: str,
) -> str:
    """Build a polite Indonesian WhatsApp notification message for a student's parent."""
    status_label = ATTENDANCE_STATUS_LABELS_ID.get(status, status)
    return (
        "Yth. Bapak/Ibu Orang Tua/Wali Murid,\n\n"
        f"Kami informasikan status presensi ananda *{student_name}* (Kelas {class_name}):\n"
        f"- Sesi: {session_label}\n"
        f"- Status: *{status_label}*\n"
        f"- Waktu: {scanned_at_str}\n\n"
        "Terima kasih atas perhatian Bapak/Ibu."
    )

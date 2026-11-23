import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.providers.llm import LLMProvider, get_llm_provider
from app.providers.whatsapp import WhatsAppProvider, get_whatsapp_provider
from app.schemas import WhatsAppWebhookRequest, WhatsAppWebhookResponse
from app.services.chatbot import ChatbotOrchestrator

router = APIRouter(prefix="/api/v1", tags=["webhook"])


@router.post("/webhook/whatsapp", response_model=WhatsAppWebhookResponse)
async def handle_whatsapp_webhook(
    request_payload: WhatsAppWebhookRequest,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    llm_provider: LLMProvider = Depends(get_llm_provider),
    whatsapp_provider: WhatsAppProvider = Depends(get_whatsapp_provider),
) -> WhatsAppWebhookResponse:
    """Receive incoming WhatsApp messages (standard or WAHA format) and reply via AI chatbot."""
    expected_secret = settings.waha_webhook_secret.strip()
    if expected_secret and (
        x_webhook_secret is None
        or not secrets.compare_digest(x_webhook_secret, expected_secret)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Secret webhook WhatsApp tidak valid.",
        )

    phone_wa_raw, message_text, media_url, ignored = request_payload.extract_normalized_fields()
    if ignored:
        return WhatsAppWebhookResponse(
            reply_text="",
            is_in_domain=True,
            is_fallback=False,
            tool_called=None,
            detected_intent="ignored",
            latency_ms=0,
            wa_sent=False,
            ignored=True,
        )

    if not phone_wa_raw or not phone_wa_raw.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Nomor WhatsApp pengirim wajib diisi.",
        )

    normalized_message = message_text or ""

    orchestrator = ChatbotOrchestrator(
        llm_provider=llm_provider,
        whatsapp_provider=whatsapp_provider,
    )
    try:
        return await orchestrator.handle_incoming_message(
            db=db,
            phone_wa_raw=phone_wa_raw,
            message_text=normalized_message,
            media_url=media_url,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

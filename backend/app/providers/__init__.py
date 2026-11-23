"""External service provider interfaces and implementations."""

from app.providers.face_engine import (
    DeterministicFaceEngine,
    FaceEngine,
    FaceExtractionResult,
    FaceValidationError,
    InsightFaceEngine,
    cosine_similarity,
    create_face_engine,
    get_face_engine,
)
from app.providers.llm import (
    CHATBOT_TOOL_DECLARATIONS,
    GeminiLLMProvider,
    LLMProvider,
    LLMResult,
    RuleBasedLLMProvider,
    create_llm_provider,
    get_llm_provider,
)
from app.providers.whatsapp import (
    MockWhatsAppProvider,
    WahaWhatsAppProvider,
    WhatsAppMessage,
    WhatsAppProvider,
    build_attendance_wa_message,
    create_whatsapp_provider,
    get_whatsapp_provider,
)

__all__ = [
    "CHATBOT_TOOL_DECLARATIONS",
    "DeterministicFaceEngine",
    "FaceEngine",
    "FaceExtractionResult",
    "FaceValidationError",
    "GeminiLLMProvider",
    "InsightFaceEngine",
    "LLMProvider",
    "LLMResult",
    "MockWhatsAppProvider",
    "RuleBasedLLMProvider",
    "WahaWhatsAppProvider",
    "WhatsAppMessage",
    "WhatsAppProvider",
    "build_attendance_wa_message",
    "cosine_similarity",
    "create_face_engine",
    "create_llm_provider",
    "create_whatsapp_provider",
    "get_face_engine",
    "get_llm_provider",
    "get_whatsapp_provider",
]

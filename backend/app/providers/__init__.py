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
    "DeterministicFaceEngine",
    "FaceEngine",
    "FaceExtractionResult",
    "FaceValidationError",
    "InsightFaceEngine",
    "MockWhatsAppProvider",
    "WahaWhatsAppProvider",
    "WhatsAppMessage",
    "WhatsAppProvider",
    "build_attendance_wa_message",
    "cosine_similarity",
    "create_face_engine",
    "create_whatsapp_provider",
    "get_face_engine",
    "get_whatsapp_provider",
]

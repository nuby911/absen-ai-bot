from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_JWT_SECRET = "smart-school-attendance-dev-secret-key-2026"
KNOWN_DEFAULT_JWT_SECRETS = frozenset(
    {
        DEFAULT_JWT_SECRET,
        "smart-school-attendance-dev-secret-key-change-in-production",
    }
)


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite+aiosqlite:///./smart_school.db"
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    face_similarity_threshold: float = 0.55
    face_engine_mode: str = "auto"

    whatsapp_provider_mode: str = "mock"
    waha_base_url: str = "http://localhost:3000"
    waha_api_key: str = ""
    waha_session: str = "default"
    waha_webhook_secret: str = ""

    llm_provider_mode: str = "fallback"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    upload_dir: str = "uploads"
    cors_allow_origins: str = "*"

    def get_cors_origins(self) -> list[str]:
        """Parse comma-separated CORS_ALLOW_ORIGINS into a normalized allowlist."""
        raw = self.cors_allow_origins.strip()
        if not raw or raw == "*":
            return ["*"]
        origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
        return origins or ["*"]


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()

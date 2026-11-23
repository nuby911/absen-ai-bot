from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite+aiosqlite:///./smart_school.db"
    jwt_secret: str = "smart-school-attendance-dev-secret-key-2026"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    face_similarity_threshold: float = 0.55
    face_engine_mode: str = "auto"

    whatsapp_provider_mode: str = "mock"
    waha_base_url: str = "http://localhost:3000"
    waha_api_key: str = ""
    waha_session: str = "default"

    llm_provider_mode: str = "fallback"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    upload_dir: str = "uploads"


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()

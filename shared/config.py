"""
Configuration module - Central access point for environment variables.

CRITICAL: Access ALL environment variables through this module.
NEVER use os.getenv() directly in application code.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://atrevete:changeme@postgres:5432/atrevete_db",
        description="PostgreSQL connection string with asyncpg driver"
    )
    POSTGRES_DB: str = Field(default="atrevete_db")
    POSTGRES_USER: str = Field(default="atrevete")
    POSTGRES_PASSWORD: str = Field(default="changeme")

    # Redis
    REDIS_URL: str = Field(
        default="redis://redis:6379/0",
        description="Redis connection string"
    )

    # Google Calendar API
    GOOGLE_SERVICE_ACCOUNT_JSON: str = Field(
        default="/path/to/service-account-key.json",
        description="Path to Google service account JSON key file"
    )
    GOOGLE_CALENDAR_IDS: str = Field(
        default="",
        description="Comma-separated Google Calendar IDs for stylists"
    )

    # Chatwoot
    CHATWOOT_API_URL: str = Field(default="https://app.chatwoot.com")
    CHATWOOT_API_TOKEN: str = Field(default="placeholder")
    CHATWOOT_ACCOUNT_ID: str = Field(default="12345")
    CHATWOOT_INBOX_ID: str = Field(default="67890")
    CHATWOOT_TEAM_GROUP_ID: str = Field(default="group_id")
    CHATWOOT_WEBHOOK_TOKEN: str = Field(
        default="chatwoot_webhook_token_placeholder",
        description="Secret token for Chatwoot webhook URL authentication (min 24 chars recommended)"
    )

    # OpenRouter (Unified LLM API)
    OPENROUTER_API_KEY: str = Field(default="sk-or-placeholder")
    LLM_MODEL: str = Field(
        default="openai/gpt-4o-mini",
        description="AI model for conversations (OpenRouter format). Options: openai/gpt-4o-mini, anthropic/claude-sonnet-3.5, anthropic/claude-haiku-4.5"
    )
    SITE_URL: str = Field(
        default="https://atrevetepeluqueria.com",
        description="Site URL for OpenRouter rankings (optional)"
    )
    SITE_NAME: str = Field(
        default="Atrévete Bot",
        description="Site name for OpenRouter rankings (optional)"
    )

    # Langfuse (Observability & Monitoring)
    LANGFUSE_PUBLIC_KEY: str = Field(
        default="pk-lf-placeholder",
        description="Langfuse public key for tracing and monitoring"
    )
    LANGFUSE_SECRET_KEY: str = Field(
        default="sk-lf-placeholder",
        description="Langfuse secret key for authentication"
    )
    LANGFUSE_BASE_URL: str = Field(
        default="https://cloud.langfuse.com",
        description="Langfuse API base URL (EU: cloud.langfuse.com, US: us.cloud.langfuse.com)"
    )

    # Groq API (Audio Transcription)
    GROQ_API_KEY: str = Field(
        default="gsk-placeholder",
        description="Groq API key for Whisper audio transcription (console.groq.com)"
    )

    # Application Settings
    TIMEZONE: str = Field(default="Europe/Madrid")
    LOG_LEVEL: str = Field(default="INFO")
    SALON_ADDRESS: str = Field(
        default="Calle de la Constitución, 5, 28100 Alcobendas, Madrid",
        description="Physical address of the beauty salon"
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"  # Ignore extra env vars (e.g., LANGCHAIN_* variables)


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are loaded only once.
    """
    return Settings()

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

    # Stripe
    STRIPE_SECRET_KEY: str = Field(default="sk_test_placeholder")
    STRIPE_PUBLISHABLE_KEY: str = Field(default="pk_test_placeholder")
    STRIPE_WEBHOOK_SECRET: str = Field(default="whsec_placeholder")
    STRIPE_API_VERSION: str = Field(default="2024-11-20.acacia")

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

    # Anthropic
    ANTHROPIC_API_KEY: str = Field(default="sk-ant-placeholder")

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

    # Application Settings
    TIMEZONE: str = Field(default="Europe/Madrid")
    LOG_LEVEL: str = Field(default="INFO")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are loaded only once.
    """
    return Settings()

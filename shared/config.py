"""
Configuration module - Central access point for environment variables.

CRITICAL: Access ALL environment variables through this module.
NEVER use os.getenv() directly in application code.
"""

from decimal import Decimal
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://atrevete:changeme@postgres:5432/atrevete_db",
        description="PostgreSQL connection string with asyncpg driver",
    )
    POSTGRES_DB: str = Field(default="atrevete_db")
    POSTGRES_USER: str = Field(default="atrevete")
    POSTGRES_PASSWORD: str = Field(default="changeme")

    # Redis
    REDIS_URL: str = Field(default="redis://redis:6379/0", description="Redis connection string")
    REDIS_PASSWORD: str = Field(
        default="", description="Redis password for authentication (required in production)"
    )
    USE_REDIS_STREAMS: bool = Field(
        default=True,
        description="Use Redis Streams instead of Pub/Sub for message delivery. "
        "Streams provide persistence and acknowledgment. Set to False to use legacy Pub/Sub.",
    )

    # Google Calendar API
    GOOGLE_SERVICE_ACCOUNT_JSON: str = Field(
        default="/path/to/service-account-key.json",
        description="Path to Google service account JSON key file",
    )
    GOOGLE_CALENDAR_IDS: str = Field(
        default="", description="Comma-separated Google Calendar IDs for stylists"
    )

    # Chatwoot
    CHATWOOT_API_URL: str = Field(default="https://app.chatwoot.com")
    CHATWOOT_API_TOKEN: str = Field(default="placeholder")
    CHATWOOT_ACCOUNT_ID: str = Field(default="12345")
    CHATWOOT_INBOX_ID: str = Field(default="67890")
    CHATWOOT_TEAM_GROUP_ID: str = Field(default="group_id")
    CHATWOOT_TEAM_ID: int | None = Field(
        default=None,
        description="Chatwoot team ID for automatic conversation assignment during escalation",
    )
    CHATWOOT_WEBHOOK_TOKEN: str = Field(
        default="chatwoot_webhook_token_placeholder",
        description="Secret token for Chatwoot webhook URL authentication (min 24 chars recommended)",
    )
    CHATWOOT_RATE_LIMIT_PER_MINUTE: int = Field(
        default=60,
        ge=0,
        description="Maximum Chatwoot API requests per minute. 0 = disabled.",
    )

    # OpenRouter (Unified LLM API)
    OPENROUTER_API_KEY: str = Field(default="sk-or-placeholder")
    LLM_MODEL: str = Field(
        default="openai/gpt-4.1-mini",
        description=(
            "AI model for conversations (OpenRouter format). "
            "Default: openai/gpt-4.1-mini (strict tool calling, constrained decoding)"
        ),
    )
    SITE_URL: str = Field(
        default="https://atrevetepeluqueria.com",
        description="Site URL for OpenRouter rankings (optional)",
    )
    SITE_NAME: str = Field(
        default="Atrévete Peluquería", description="Site name for OpenRouter rankings (optional)"
    )

    # Token Cost Tracking (EUR per 1M tokens)
    TOKEN_PRICE_INPUT: Decimal = Field(
        default=Decimal("0.15"),
        description="Price per 1M input tokens in EUR (gpt-4.1-mini default)",
    )
    TOKEN_PRICE_OUTPUT: Decimal = Field(
        default=Decimal("0.60"),
        description="Price per 1M output tokens in EUR (gpt-4.1-mini default)",
    )

    # Token Budget Alerting (fire-and-forget, no hard limits)
    TOKEN_BUDGET_MONTHLY_USD: float | None = Field(
        default=None,
        description="Monthly cost alert threshold in USD. None = disabled.",
    )
    TOKEN_BUDGET_PER_TURN_TOKENS: int | None = Field(
        default=None,
        description="Per-turn input token alert threshold. None = disabled.",
    )

    # Billing & Invoicing
    MONTHLY_MAINTENANCE_EUR: Decimal = Field(
        default=Decimal("50.00"),
        description="Fixed monthly maintenance charge in EUR (hosting, support, etc.)",
    )

    # Stripe (Payment Gateway)
    STRIPE_SECRET_KEY: str = Field(
        default="",
        description="Stripe secret API key (sk_live_... or sk_test_...)",
    )
    STRIPE_PUBLISHABLE_KEY: str = Field(
        default="",
        description="Stripe publishable API key (pk_live_... or pk_test_...)",
    )
    STRIPE_WEBHOOK_SECRET: str = Field(
        default="",
        description="Stripe webhook signing secret (whsec_...)",
    )

    # Fiscal compliance — Spain B2B invoicing
    COMPANY_NIF: str = Field(default="", description="NIF del proveedor (emisor de facturas)")
    COMPANY_LEGAL_NAME: str = Field(
        default="", description="Nombre/Razón social del proveedor"
    )
    COMPANY_FISCAL_ADDRESS: str = Field(
        default="", description="Domicilio fiscal del proveedor"
    )
    CLIENT_NIF: str = Field(default="", description="NIF del cliente (receptor de facturas)")
    CLIENT_COMPANY_NAME: str = Field(
        default="", description="Nombre/Razón social del cliente"
    )
    CLIENT_FISCAL_ADDRESS: str = Field(
        default="", description="Domicilio fiscal del cliente"
    )
    STRIPE_TAX_RATE_ID: str = Field(
        default="", description="Stripe TaxRate ID para IVA 21% (txr_...)"
    )

    # Email (SMTP for invoice delivery)
    OPERATOR_EMAIL: str = Field(
        default="",
        description="Operator email — receives invoice copies",
    )
    SMTP_HOST: str = Field(default="", description="SMTP server hostname")
    SMTP_PORT: int = Field(default=587, description="SMTP server port (587 for STARTTLS)")
    SMTP_USER: str = Field(default="", description="SMTP username")
    SMTP_PASSWORD: str = Field(default="", description="SMTP password")
    SMTP_FROM: str = Field(default="", description="From email address for invoices")

    # Invoice Storage
    INVOICES_DIR: str = Field(
        default="data/invoices",
        description="Directory for generated invoice PDFs",
    )

    # Resilience Layer (Multi-Provider Fallback + Retry)
    RESILIENCE_ENABLED: bool = Field(
        default=True,
        description=(
            "Feature flag for the LLM resilience layer. When True, enables multi-provider "
            "fallback, progressive retry with exponential backoff, and enhanced circuit "
            "breaker integration. Set to False to use the original single-provider path."
        ),
    )
    LLM_FALLBACK_MODEL: str = Field(
        default="deepseek/deepseek-chat",
        description=(
            "OpenRouter model slug used as the first fallback when the primary model "
            "(LLM_MODEL) fails. Only used when RESILIENCE_ENABLED=True."
        ),
    )
    LLM_EMERGENCY_MODEL: str = Field(
        default="meta-llama/llama-3.1-8b-instruct",
        description=(
            "OpenRouter model slug used as the emergency last-resort fallback when both "
            "primary and fallback providers fail. Only used when RESILIENCE_ENABLED=True."
        ),
    )
    MAX_PROVIDER_FAILURES: int = Field(
        default=3,
        ge=1,
        description=(
            "Number of consecutive failures allowed for a provider before it is "
            "considered unhealthy and skipped in the fallback chain."
        ),
    )
    RETRY_BUDGET_PER_CONVERSATION: int = Field(
        default=5,
        ge=1,
        description=(
            "Maximum total retry attempts allowed per conversation across all error types. "
            "Prevents runaway retry loops. Budget resets when a successful response is produced."
        ),
    )

    # Langfuse (Observability & Monitoring)
    LANGFUSE_PUBLIC_KEY: str = Field(
        default="pk-lf-placeholder", description="Langfuse public key for tracing and monitoring"
    )
    LANGFUSE_SECRET_KEY: str = Field(
        default="sk-lf-placeholder", description="Langfuse secret key for authentication"
    )
    LANGFUSE_BASE_URL: str = Field(
        default="https://cloud.langfuse.com",
        description="Langfuse API base URL (EU: cloud.langfuse.com, US: us.cloud.langfuse.com)",
    )

    # Groq API (Audio Transcription)
    GROQ_API_KEY: str = Field(
        default="gsk-placeholder",
        description="Groq API key for Whisper audio transcription (console.groq.com)",
    )

    # State Delivery — synthetic message primitive (E1 seed)
    STATE_DELIVERY_SYNTHETIC_ENABLED: bool = Field(
        default=True,
        description=(
            "Feature flag for the synthetic state-delivery message primitive. "
            "When True, deliver_state_update() emits synthetic (AIMessage + ToolMessage) "
            "pairs to correct LLM anchoring mid-flow. "
            "Set to False for emergency rollback without code revert."
        ),
    )

    @property
    def state_delivery_synthetic_enabled(self) -> bool:
        """Lowercase alias for STATE_DELIVERY_SYNTHETIC_ENABLED (ergonomic access)."""
        return self.STATE_DELIVERY_SYNTHETIC_ENABLED

    # Prompt System Optimization
    USE_OPTIMIZED_PROMPTS: bool = Field(
        default=True,
        description=(
            "Feature flag for the optimized prompt system. When True, uses layered prompts "
            "(cached system content + dynamic context) for 25% token reduction. "
            "When False, falls back to legacy inline prompts for backward compatibility."
        ),
    )
    # Application Settings
    TIMEZONE: str = Field(default="Europe/Madrid")
    LOG_LEVEL: str = Field(default="INFO")
    SALON_ADDRESS: str = Field(
        default="Calle de la Constitución, 5, 28100 Alcobendas, Madrid",
        description="Physical address of the beauty salon",
    )
    MESSAGE_BATCH_WINDOW_SECONDS: int = Field(
        default=30,
        ge=0,
        le=120,
        description="Message batching window in seconds. Collects messages within this window and processes them as one. Set to 0 to disable batching.",
    )

    # Appointment Confirmation System
    CONFIRMATION_TEMPLATE_NAME: str = Field(
        default="appointment_confirmation_48h",
        description="WhatsApp template name for 48h confirmation request",
    )
    AUTO_CANCEL_TEMPLATE_NAME: str = Field(
        default="appointment_auto_cancelled",
        description="WhatsApp template name for auto-cancellation notification",
    )
    CUSTOMER_CANCEL_TEMPLATE_NAME: str = Field(
        default="appointment_cancelled_by_customer",
        description="WhatsApp template name when customer declines appointment",
    )
    REMINDER_TEMPLATE_NAME: str = Field(
        default="appointment_reminder_2h", description="WhatsApp template name for 2h reminder"
    )
    ADMIN_APPOINTMENT_TEMPLATE_NAME: str = Field(
        default="appointment_booked_by_admin",
        description="WhatsApp template name for admin-created appointment notification",
    )
    CONFIRMATION_HOURS_BEFORE: int = Field(
        default=48,
        ge=24,
        le=72,
        description="Hours before appointment to send confirmation request",
    )
    AUTO_CANCEL_HOURS_BEFORE: int = Field(
        default=24,
        ge=12,
        le=48,
        description="Hours before appointment to auto-cancel if no confirmation received",
    )
    REMINDER_HOURS_BEFORE: int = Field(
        default=2,
        ge=1,
        le=24,
        description="Hours before appointment to send reminder for confirmed appointments",
    )

    # Admin Panel Authentication
    ADMIN_USERNAME: str = Field(default="admin", description="Admin panel username")
    ADMIN_PASSWORD: str = Field(
        default="",
        description="Admin panel password in plain text (DEPRECATED: use ADMIN_PASSWORD_HASH instead)",
    )
    ADMIN_PASSWORD_HASH: str = Field(
        default="",
        description="Bcrypt hash of admin password. Generate with: "
        "python -c \"from passlib.hash import bcrypt; print(bcrypt.hash('your_password'))\"",
    )
    ADMIN_JWT_SECRET: str = Field(
        default="", description="JWT secret key for admin panel authentication (min 32 chars)"
    )

    # Google OAuth2 (optional — system uses service account if not set)
    # Configure these when using OAuth2 flow from admin panel instead of service account JSON.
    # Leave empty to keep using service-account-key.json (legacy mode).
    GOOGLE_OAUTH_CLIENT_ID: str = Field(
        default="",
        description=(
            "Google OAuth2 client ID (from Google Cloud Console → Credentials). "
            "Required for OAuth2 flow. Leave empty to use service account."
        ),
    )
    GOOGLE_OAUTH_CLIENT_SECRET: str = Field(
        default="",
        description=(
            "Google OAuth2 client secret (from Google Cloud Console → Credentials). "
            "Required for OAuth2 flow. Leave empty to use service account."
        ),
    )
    GOOGLE_OAUTH_REDIRECT_URI: str = Field(
        default="",
        description=(
            "OAuth2 redirect URI — must match exactly what is registered in Google Cloud Console. "
            "Example: http://localhost:8000/api/admin/google/callback"
        ),
    )

    # Admin Panel URL (used for OAuth2 callback redirects)
    ADMIN_PANEL_URL: str = Field(
        default="http://localhost:8001",
        description=(
            "Base URL of the Django/Next.js admin panel. "
            "Used by the Google OAuth2 callback to redirect back after connecting a Google account. "
            "Example: http://localhost:8001 (dev) or https://admin.yourdomain.com (prod)"
        ),
    )

    # CORS Origins for API
    CORS_ORIGINS: str = Field(
        default="http://localhost:3000,http://localhost:8000,http://localhost:8001,http://api:8000",
        description="Comma-separated list of allowed origins for CORS (e.g., 'http://localhost:3000,https://admin.domain.com')",
    )

    @property
    def google_oauth_configured(self) -> bool:
        """True if Google OAuth2 credentials are configured (OAuth2 mode active).

        Returns False when the system should fall back to service account JSON auth.
        Both client_id AND client_secret must be set for OAuth2 to be active.
        """
        return bool(self.GOOGLE_OAUTH_CLIENT_ID and self.GOOGLE_OAUTH_CLIENT_SECRET)

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

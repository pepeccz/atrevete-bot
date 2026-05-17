"""
Tests for CORS_ORIGINS startup validation (admin-auth-cookie-only, PR-2 cleanup).

Covers the 3 cases flagged in the PR-1 verify WARNING:
- Wildcard '*' in CORS_ORIGINS is rejected unconditionally
- HTTPS enforcement when ADMIN_JWT_COOKIE_SECURE=True
- secure=False skips the HTTPS enforcement
"""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(cors_origins: str, cookie_secure: bool = True) -> MagicMock:
    """Build a minimal Settings mock."""
    s = MagicMock()
    s.CORS_ORIGINS = cors_origins
    s.ADMIN_JWT_COOKIE_SECURE = cookie_secure
    # Other required fields that validate_startup_config reads
    s.GOOGLE_SERVICE_ACCOUNT_JSON = "/path/to/service-account-key.json"
    s.OPENROUTER_API_KEY = "sk-or-real-key"
    s.CHATWOOT_API_TOKEN = "real-token"
    s.CHATWOOT_WEBHOOK_TOKEN = "a" * 24  # >= 24 chars
    s.DATABASE_URL = "postgresql+asyncpg://x"
    s.LANGFUSE_PUBLIC_KEY = "pk-lf-placeholder"
    s.GROQ_API_KEY = "gsk-placeholder"
    return s


# ---------------------------------------------------------------------------
# Case 1: Wildcard in CORS_ORIGINS is always rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cors_wildcard_is_rejected():
    """CORS_ORIGINS='*' must cause StartupValidationError regardless of cookie_secure."""
    from shared.startup_validator import StartupValidationError, validate_startup_config

    settings = _make_settings("*", cookie_secure=False)

    with (
        patch("shared.startup_validator.get_settings", return_value=settings),
        pytest.raises(StartupValidationError) as exc_info,
    ):
        await validate_startup_config(require_google_calendar=False)

    assert "wildcard" in str(exc_info.value).lower() or "*" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Case 2: Non-HTTPS origin with ADMIN_JWT_COOKIE_SECURE=True is rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_http_origin_rejected_when_cookie_secure_true():
    """Non-HTTPS origin must fail when ADMIN_JWT_COOKIE_SECURE=True."""
    from shared.startup_validator import StartupValidationError, validate_startup_config

    settings = _make_settings("http://admin.example.com", cookie_secure=True)

    with (
        patch("shared.startup_validator.get_settings", return_value=settings),
        pytest.raises(StartupValidationError) as exc_info,
    ):
        await validate_startup_config(require_google_calendar=False)

    error_text = str(exc_info.value)
    assert "https" in error_text.lower() or "HTTPS" in error_text


# ---------------------------------------------------------------------------
# Case 3: Non-HTTPS origin is allowed when ADMIN_JWT_COOKIE_SECURE=False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_http_origin_allowed_when_cookie_secure_false():
    """Non-HTTPS origin must NOT raise when ADMIN_JWT_COOKIE_SECURE=False (dev mode)."""
    from shared.startup_validator import StartupValidationError, validate_startup_config

    settings = _make_settings("http://localhost:3000", cookie_secure=False)

    # Should NOT raise StartupValidationError for CORS reasons.
    # Redis/other checks may fail; we only care about the CORS check here.
    # We catch StartupValidationError and assert the error is NOT about HTTPS.
    with patch("shared.startup_validator.get_settings", return_value=settings):
        try:
            await validate_startup_config(require_google_calendar=False)
        except StartupValidationError as exc:
            error_text = str(exc)
            # CORS HTTPS check must NOT be in the error when secure=False
            assert "ADMIN_JWT_COOKIE_SECURE=True requires all CORS_ORIGINS" not in error_text
        except Exception:
            # Other infrastructure errors (Redis, etc.) are acceptable
            pass

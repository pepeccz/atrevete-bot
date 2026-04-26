"""
Tests for WhatsApp template name resolution via SettingsService.

Covers:
- DB row present → DB value returned (parametrized over all 3 keys)
- DB row absent → ENV fallback returned
- CUSTOMER_CANCEL_TEMPLATE_NAME removed from config
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.config import get_settings
from shared.settings_service import SettingsService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEMPLATE_CASES = [
    (
        "whatsapp_template_confirm_48h",
        "WHATSAPP_TEMPLATE_CONFIRM_48H",
        "",  # default in ENV
    ),
    (
        "whatsapp_template_reminder_24h",
        "WHATSAPP_TEMPLATE_REMINDER_24H",
        "",
    ),
    (
        "whatsapp_template_admin_booking",
        "ADMIN_APPOINTMENT_TEMPLATE_NAME",
        "appointment_booked_by_admin",
    ),
]


def _make_service_with_mock_session(db_value: str | None) -> SettingsService:
    """Return a SettingsService whose _get_session returns a mock that yields
    a SystemSetting row (or None) with the given value."""
    svc = SettingsService.__new__(SettingsService)
    svc._cache = {}
    svc._cache_lock = __import__("asyncio").Lock()
    svc._initialized = True

    from database.models import SettingValueType, SystemSetting

    if db_value is not None:
        mock_setting = MagicMock(spec=SystemSetting)
        mock_setting.value = db_value
        mock_setting.value_type = SettingValueType.STRING.value
    else:
        mock_setting = None

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_setting

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    svc._get_session = AsyncMock(return_value=mock_session)

    return svc


# ---------------------------------------------------------------------------
# Task 2.1 — DB row present → DB value used (parametrized over 3 keys)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key,env_attr,env_default", _TEMPLATE_CASES)
async def test_template_key_uses_db_value_when_row_exists(
    key: str, env_attr: str, env_default: str
) -> None:
    """When a DB row exists for the template key, svc.get() returns its value."""
    SettingsService.reset_instance()
    expected = "custom_template_v2"

    svc = _make_service_with_mock_session(db_value=expected)
    result = await svc.get(key, env_default)

    assert result == expected


# ---------------------------------------------------------------------------
# Task 2.2 — DB row absent → ENV fallback returned
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key,env_attr,env_default", _TEMPLATE_CASES)
async def test_template_key_falls_back_to_env_when_row_absent(
    key: str, env_attr: str, env_default: str
) -> None:
    """When no DB row exists, svc.get(key, env_default) returns env_default."""
    SettingsService.reset_instance()

    svc = _make_service_with_mock_session(db_value=None)
    settings = get_settings()
    fallback = getattr(settings, env_attr, env_default)

    result = await svc.get(key, fallback)

    assert result == fallback


# ---------------------------------------------------------------------------
# Task 2.3 — CUSTOMER_CANCEL_TEMPLATE_NAME must NOT exist on Settings
# ---------------------------------------------------------------------------


def test_customer_cancel_template_name_removed_from_config() -> None:
    """shared/config.py must NOT define CUSTOMER_CANCEL_TEMPLATE_NAME."""
    assert not hasattr(
        get_settings(), "CUSTOMER_CANCEL_TEMPLATE_NAME"
    ), "CUSTOMER_CANCEL_TEMPLATE_NAME should have been removed from shared/config.py"

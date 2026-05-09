"""
conftest.py for tests/agent/tools/

Auto-patches SettingsService for check_availability tests so that
the lead-time guard does not hit a live DB during unit tests.

Default: minimum_booking_days_advance=0 (no restriction) — existing tests
keep passing. Tests that need a specific min_days override this patch
explicitly within their own `with patch(...)` context.
"""

from unittest.mock import AsyncMock, patch

import pytest


def _make_settings_service(min_days: int = 0, buffer_hours: int = 0):
    service = AsyncMock()

    async def fake_get(key: str, default=None):
        if key == "minimum_booking_days_advance":
            return min_days
        if key == "same_day_buffer_hours":
            return buffer_hours
        return default

    service.get = fake_get
    return service


@pytest.fixture(autouse=True)
def auto_patch_settings_service():
    """Patch SettingsService singleton for all tool tests (min_days=0 default)."""
    with patch(
        "shared.settings_service.get_settings_service",
        new_callable=AsyncMock,
        return_value=_make_settings_service(min_days=0),
    ):
        yield


@pytest.fixture(autouse=True)
def auto_patch_stylist_names_map():
    """Patch _get_stylist_names_map to return empty dict by default.

    Individual tests that need real names must override this patch explicitly.
    """
    with patch(
        "agent.tools.check_availability.get_stylist_names_map",
        new_callable=AsyncMock,
        return_value={},
    ):
        yield

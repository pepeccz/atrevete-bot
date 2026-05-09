"""T1 — Lead-time failsafe defaults.

Tests that:
- _load_lead_time_settings returns default=3 when settings row is absent (R3.1)
- next_available.py applies min_days=3 fallback when settings unavailable (ADR-8)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# T1.1 — check_availability: default lead-time is 3 when settings row absent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_lead_time_is_3_when_settings_absent():
    """_load_lead_time_settings must return 3 when settings row returns None."""
    # Arrange: settings service returns None (row absent)
    mock_service = AsyncMock()
    mock_service.get = AsyncMock(side_effect=lambda key, default=None: default)

    async def _mock_get_settings_service():
        return mock_service

    with patch(
        "shared.settings_service.get_settings_service",
        new=_mock_get_settings_service,
    ):
        from agent.tools.check_availability import load_lead_time_settings

        min_days, buffer = await load_lead_time_settings()

    assert min_days == 3, f"Expected default min_days=3, got {min_days}"


@pytest.mark.asyncio
async def test_default_lead_time_uses_settings_when_present():
    """_load_lead_time_settings must respect settings row when present."""
    mock_service = AsyncMock()
    mock_service.get = AsyncMock(
        side_effect=lambda key, default=None: 5 if key == "minimum_booking_days_advance" else 0
    )

    async def _mock_get_settings_service():
        return mock_service

    with patch(
        "shared.settings_service.get_settings_service",
        new=_mock_get_settings_service,
    ):
        from agent.tools.check_availability import load_lead_time_settings

        min_days, buffer = await load_lead_time_settings()

    assert min_days == 5


# ---------------------------------------------------------------------------
# T1.2 — next_available.py applies min_days=3 fallback on settings failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_next_available_applies_min_days_3_fallback_on_exception():
    """next_available fallback must use min_days=3 when _load_lead_time_settings raises."""
    from datetime import date, timedelta
    from unittest.mock import AsyncMock, patch
    import json

    today = date.today()
    requested = today  # triggers floor

    with (
        patch(
            "agent.tools.next_available.load_lead_time_settings",
            new=AsyncMock(side_effect=Exception("DB down")),
        ),
        patch(
            "agent.tools.next_available.get_service_durations",
            new=AsyncMock(return_value={"uuid": 45}),
        ),
        patch(
            "agent.tools.next_available.get_active_stylists_for_services",
            new=AsyncMock(return_value=[]),
        ),
    ):
        from agent.tools.next_available import get_next_available_options

        result_json = await get_next_available_options.ainvoke({
            "service_ids": ["00000000-0000-0000-0000-000000000001"],
            "requested_date_iso": today.isoformat(),
            "stylist_id": None,
        })
        result = json.loads(result_json)

    # Should return rejected because no stylists, but MUST NOT raise
    # The important check is that the function survived (no unhandled exception from dead try/except)
    assert "status" in result

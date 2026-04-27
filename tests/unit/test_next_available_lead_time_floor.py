"""T3 — RED tests for next_available lead-time floor enforcement.

Tests that get_next_available_options applies a minimum lead-time floor
from _load_lead_time_settings before querying the availability service.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest


class TestLeadTimeFloor:
    """Lead-time floor applied to get_next_available_options."""

    @pytest.mark.asyncio
    async def test_floor_applied_when_requested_date_is_too_soon(self):
        """When requested_date < today + min_days, service receives today + min_days
        and payload contains effective_from_iso."""
        today = date.today()
        too_soon = today  # requesting today itself
        min_days = 3
        expected_floor = today + timedelta(days=min_days)

        service_result = {"options": [], "searched_until": expected_floor.isoformat()}

        with (
            patch(
                "agent.tools.next_available._load_lead_time_settings",
                new=AsyncMock(return_value=(min_days, 0)),
            ),
            patch(
                "agent.tools.next_available.get_next_available_options_service",
                new=AsyncMock(return_value=service_result),
            ) as mock_service,
            patch(
                "agent.tools.next_available._get_service_durations",
                new=AsyncMock(return_value={None: 30}),
            ),
            patch(
                "agent.tools.next_available._get_active_stylists_for_services",
                new=AsyncMock(return_value=["stylist-uuid"]),
            ),
            patch(
                "agent.tools.next_available.get_service_display_label_by_ids",
                new=AsyncMock(return_value="Test Service"),
            ),
        ):
            from agent.tools.next_available import get_next_available_options

            result_json = await get_next_available_options.ainvoke(
                {
                    "service_ids": ["00000000-0000-0000-0000-000000000001"],
                    "requested_date_iso": too_soon.isoformat(),
                    "stylist_id": None,
                }
            )

        result = json.loads(result_json)
        # Service was called with the floor date, not the original requested date
        call_kwargs = mock_service.call_args.kwargs
        assert call_kwargs["requested_date"] == expected_floor

        # Payload reflects the floor was applied
        assert result["status"] == "ok"
        assert result["payload"]["effective_from_iso"] == expected_floor.isoformat()

    @pytest.mark.asyncio
    async def test_fallback_to_3_days_when_settings_raises(self):
        """When _load_lead_time_settings raises, tool falls back to 3-day floor
        and does NOT raise an uncaught exception."""
        today = date.today()
        requested = today  # today — should be floored to today+3
        expected_floor = today + timedelta(days=3)

        service_result = {"options": [], "searched_until": expected_floor.isoformat()}

        with (
            patch(
                "agent.tools.next_available._load_lead_time_settings",
                new=AsyncMock(side_effect=Exception("DB unavailable")),
            ),
            patch(
                "agent.tools.next_available.get_next_available_options_service",
                new=AsyncMock(return_value=service_result),
            ) as mock_service,
            patch(
                "agent.tools.next_available._get_service_durations",
                new=AsyncMock(return_value={None: 30}),
            ),
            patch(
                "agent.tools.next_available._get_active_stylists_for_services",
                new=AsyncMock(return_value=["stylist-uuid"]),
            ),
            patch(
                "agent.tools.next_available.get_service_display_label_by_ids",
                new=AsyncMock(return_value="Test Service"),
            ),
        ):
            from agent.tools.next_available import get_next_available_options

            # Must NOT raise
            result_json = await get_next_available_options.ainvoke(
                {
                    "service_ids": ["00000000-0000-0000-0000-000000000001"],
                    "requested_date_iso": requested.isoformat(),
                    "stylist_id": None,
                }
            )

        result = json.loads(result_json)
        # Service called with 3-day floor (fallback)
        call_kwargs = mock_service.call_args.kwargs
        assert call_kwargs["requested_date"] == expected_floor
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_no_floor_applied_when_date_already_past_minimum(self):
        """When requested_date >= today + min_days, floor is NOT applied
        and effective_from_iso is NOT in payload."""
        today = date.today()
        min_days = 3
        far_future = today + timedelta(days=10)  # well past floor

        service_result = {"options": [], "searched_until": far_future.isoformat()}

        with (
            patch(
                "agent.tools.next_available._load_lead_time_settings",
                new=AsyncMock(return_value=(min_days, 0)),
            ),
            patch(
                "agent.tools.next_available.get_next_available_options_service",
                new=AsyncMock(return_value=service_result),
            ) as mock_service,
            patch(
                "agent.tools.next_available._get_service_durations",
                new=AsyncMock(return_value={None: 30}),
            ),
            patch(
                "agent.tools.next_available._get_active_stylists_for_services",
                new=AsyncMock(return_value=["stylist-uuid"]),
            ),
            patch(
                "agent.tools.next_available.get_service_display_label_by_ids",
                new=AsyncMock(return_value="Test Service"),
            ),
        ):
            from agent.tools.next_available import get_next_available_options

            result_json = await get_next_available_options.ainvoke(
                {
                    "service_ids": ["00000000-0000-0000-0000-000000000001"],
                    "requested_date_iso": far_future.isoformat(),
                    "stylist_id": None,
                }
            )

        result = json.loads(result_json)
        # Service called with the original requested date (no floor needed)
        call_kwargs = mock_service.call_args.kwargs
        assert call_kwargs["requested_date"] == far_future
        # No effective_from_iso since floor was not applied
        assert "effective_from_iso" not in result.get("payload", {})

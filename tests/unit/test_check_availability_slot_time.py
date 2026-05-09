"""T4 — check_availability slot_time exact-match param.

Tests spec R2.4 / ADR-7.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

FAKE_SERVICE_ID = uuid4()
FAKE_STYLIST_ID = uuid4()


def _future_date_iso(days_ahead: int = 5) -> str:
    return (date.today() + timedelta(days=days_ahead)).isoformat()


def _make_slot(time_str: str = "10:00", stylist_id=None) -> dict:
    """Slot in the format returned by get_available_slots (before check_availability wraps it)."""
    sid = str(stylist_id or FAKE_STYLIST_ID)
    target_date = date.today() + timedelta(days=5)
    return {
        "time": time_str,
        "end_time": f"{int(time_str[:2]) + 1}:00",
        "full_datetime": f"{target_date}T{time_str}:00+02:00",
        "stylist_id": sid,
        "adjacent_priority": 1,
    }


def _base_patches(slots=None, min_days=3):
    slots = slots if slots is not None else [_make_slot("10:00"), _make_slot("11:00")]
    return {
        "agent.tools.check_availability.load_lead_time_settings": AsyncMock(
            return_value=(min_days, 0)
        ),
        "agent.tools.check_availability.get_service_durations": AsyncMock(
            return_value={FAKE_SERVICE_ID: 45}
        ),
        "agent.tools.check_availability.get_active_stylists_for_services": AsyncMock(
            return_value=[FAKE_STYLIST_ID]
        ),
        "agent.tools.check_availability.get_stylist_names_map": AsyncMock(
            return_value={FAKE_STYLIST_ID: "Marta"}
        ),
        "agent.tools.check_availability.get_available_slots": AsyncMock(
            return_value=slots
        ),
        "shared.business_hours_validator.is_date_closed": AsyncMock(return_value=False),
        "agent.tools._booking_helpers._compute_first_valid_date": MagicMock(
            return_value=date.today() + timedelta(days=3)
        ),
    }


@pytest.mark.asyncio
async def test_slot_time_exact_match_found():
    """When slot_time matches a slot, returns status=ok with exact_match=True."""
    from agent.tools.check_availability import check_availability

    date_iso = _future_date_iso(5)
    patches = _base_patches(slots=[_make_slot("10:00"), _make_slot("11:00")])

    with (
        patch(
            "agent.tools.check_availability.load_lead_time_settings",
            patches["agent.tools.check_availability.load_lead_time_settings"],
        ),
        patch(
            "agent.tools.check_availability.get_service_durations",
            patches["agent.tools.check_availability.get_service_durations"],
        ),
        patch(
            "agent.tools.check_availability.get_active_stylists_for_services",
            patches["agent.tools.check_availability.get_active_stylists_for_services"],
        ),
        patch(
            "agent.tools.check_availability.get_stylist_names_map",
            patches["agent.tools.check_availability.get_stylist_names_map"],
        ),
        patch(
            "agent.tools.check_availability.get_available_slots",
            patches["agent.tools.check_availability.get_available_slots"],
        ),
        patch(
            "shared.business_hours_validator.is_date_closed",
            patches["shared.business_hours_validator.is_date_closed"],
        ),
        patch(
            "agent.tools._booking_helpers._compute_first_valid_date",
            patches["agent.tools._booking_helpers._compute_first_valid_date"],
        ),
    ):
        result_json = await check_availability.ainvoke({
            "service_ids": [str(FAKE_SERVICE_ID)],
            "stylist_id": str(FAKE_STYLIST_ID),
            "date_iso": date_iso,
            "slot_time": "10:00",
        })

    result = json.loads(result_json)
    assert result["status"] == "ok", f"Expected ok, got: {result}"
    assert result["payload"]["exact_match"] is True


@pytest.mark.asyncio
async def test_slot_time_exact_match_missing_returns_alternatives():
    """When slot_time does not match, returns status=rejected with alternatives."""
    from agent.tools.check_availability import check_availability

    date_iso = _future_date_iso(5)
    patches = _base_patches(slots=[_make_slot("10:00"), _make_slot("11:00")])

    with (
        patch(
            "agent.tools.check_availability.load_lead_time_settings",
            patches["agent.tools.check_availability.load_lead_time_settings"],
        ),
        patch(
            "agent.tools.check_availability.get_service_durations",
            patches["agent.tools.check_availability.get_service_durations"],
        ),
        patch(
            "agent.tools.check_availability.get_active_stylists_for_services",
            patches["agent.tools.check_availability.get_active_stylists_for_services"],
        ),
        patch(
            "agent.tools.check_availability.get_stylist_names_map",
            patches["agent.tools.check_availability.get_stylist_names_map"],
        ),
        patch(
            "agent.tools.check_availability.get_available_slots",
            patches["agent.tools.check_availability.get_available_slots"],
        ),
        patch(
            "shared.business_hours_validator.is_date_closed",
            patches["shared.business_hours_validator.is_date_closed"],
        ),
        patch(
            "agent.tools._booking_helpers._compute_first_valid_date",
            patches["agent.tools._booking_helpers._compute_first_valid_date"],
        ),
    ):
        result_json = await check_availability.ainvoke({
            "service_ids": [str(FAKE_SERVICE_ID)],
            "stylist_id": str(FAKE_STYLIST_ID),
            "date_iso": date_iso,
            "slot_time": "15:00",  # not available
        })

    result = json.loads(result_json)
    assert result["status"] == "rejected", f"Expected rejected, got: {result}"
    assert result.get("next_step") == "slot_no_longer_available"
    assert "alternatives" in result["payload"]
    assert len(result["payload"]["alternatives"]) <= 3

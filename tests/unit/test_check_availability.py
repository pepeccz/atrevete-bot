"""TDD tests for booking-ideal-flow-completion — check_availability closed_day detection.

Tasks 3.1 (RED) → 3.2 (GREEN): REQ-P2A-2 / REQ-P2A-3.

When ALL queried days in the result are closed-day rejections (i.e. no slots returned
because every day in the candidate range is closed), check_availability must return
next_step="closed_day" instead of a generic no-slots response.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

FAKE_SERVICE_ID = uuid4()
FAKE_STYLIST_ID = uuid4()


def parse_response(raw: str) -> dict:
    return json.loads(raw)


def _sunday_iso() -> str:
    """Return the ISO date of the next Sunday."""
    today = date.today()
    days_until_sunday = (6 - today.weekday()) % 7
    if days_until_sunday == 0:
        days_until_sunday = 7
    return (today + timedelta(days=days_until_sunday + 7)).isoformat()  # +7 for min_advance


def _tuesday_iso() -> str:
    """Return the ISO date of a Tuesday >= 7 days from now."""
    today = date.today()
    days_until_tuesday = (1 - today.weekday()) % 7  # 1=Tuesday
    if days_until_tuesday < 7:
        days_until_tuesday += 7
    return (today + timedelta(days=days_until_tuesday)).isoformat()


# ---------------------------------------------------------------------------
# Shared patch helpers
# ---------------------------------------------------------------------------


def _check_availability_base_patches(
    *,
    service_durations: dict | None = None,
    stylist_ids: list | None = None,
    stylist_names: dict | None = None,
    slots: list | None = None,
    min_days: int = 0,
    is_date_closed_return: bool = False,
):
    """Return dict of patches for check_availability internals."""
    service_durations = service_durations or {FAKE_SERVICE_ID: 45}
    stylist_ids = stylist_ids or [FAKE_STYLIST_ID]
    stylist_names = stylist_names or {FAKE_STYLIST_ID: "Marta Test"}
    slots = slots if slots is not None else []

    return {
        "agent.tools.check_availability.load_lead_time_settings": AsyncMock(
            return_value=(min_days, 0)
        ),
        "agent.tools.check_availability.get_service_durations": AsyncMock(
            return_value=service_durations
        ),
        "agent.tools.check_availability.get_active_stylists_for_services": AsyncMock(
            return_value=stylist_ids
        ),
        "agent.tools.check_availability.get_stylist_names_map": AsyncMock(
            return_value=stylist_names
        ),
        "agent.services.availability_service.get_available_slots": AsyncMock(
            return_value=slots
        ),
        "shared.business_hours_validator.is_date_closed": AsyncMock(
            return_value=is_date_closed_return
        ),
        "agent.tools._booking_helpers._compute_first_valid_date": MagicMock(
            return_value=date.today() + timedelta(days=3)
        ),
    }


# ---------------------------------------------------------------------------
# Task 3.1 RED — new cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_availability_returns_closed_day_when_all_days_closed():
    """REQ-P2A-2: querying a closed date → next_step=closed_day (not generic no-slots)."""
    from agent.tools.check_availability import check_availability

    sunday = _sunday_iso()
    patches = _check_availability_base_patches(
        is_date_closed_return=True,
        slots=[],  # no slots because it's closed
    )

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
            "agent.services.availability_service.get_available_slots",
            patches["agent.services.availability_service.get_available_slots"],
        ),
        patch(
            "shared.business_hours_validator.is_date_closed",
            patches["shared.business_hours_validator.is_date_closed"],
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": str(FAKE_STYLIST_ID),
                "date_iso": sunday,
                "no_preference": False,
            }
        )

    data = parse_response(raw)
    assert data.get("next_step") == "closed_day", (
        f"Expected next_step=closed_day, got: {data}"
    )
    assert data.get("status") == "rejected"
    payload = data.get("payload", {})
    assert "closed_date" in payload or "requested_date_iso" in payload or payload


@pytest.mark.asyncio
async def test_check_availability_unchanged_when_some_days_open():
    """REQ-P2A-2 regression: open date + empty slots → generic ok response (no closed_day)."""
    from agent.tools.check_availability import check_availability

    tuesday = _tuesday_iso()
    patches = _check_availability_base_patches(
        is_date_closed_return=False,  # open day
        slots=[],  # genuinely no slots, but not because of closure
    )

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
            "agent.services.availability_service.get_available_slots",
            patches["agent.services.availability_service.get_available_slots"],
        ),
        patch(
            "shared.business_hours_validator.is_date_closed",
            patches["shared.business_hours_validator.is_date_closed"],
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": str(FAKE_STYLIST_ID),
                "date_iso": tuesday,
                "no_preference": False,
            }
        )

    data = parse_response(raw)
    # Must NOT return closed_day — this is a genuine no-availability day
    assert data.get("next_step") != "closed_day", (
        f"Should not return closed_day for an open day: {data}"
    )
    assert data.get("status") == "ok"


# ---------------------------------------------------------------------------
# slot_time Filter Boundary Tightening (T12–T15)
# Spec: §slot_time Filter Boundary Tightening / Design ADR-5
# ---------------------------------------------------------------------------


def _future_date_iso(days_ahead: int = 8) -> str:
    return (date.today() + timedelta(days=days_ahead)).isoformat()


def _make_slot_raw(time_str: str, seconds: str = "00") -> dict:
    """Build a raw slot as returned by get_available_slots."""
    target = date.today() + timedelta(days=8)
    return {
        "time": time_str,
        "end_time": "11:30",
        "full_datetime": f"{target}T{time_str}:{seconds}+02:00",
        "stylist_id": str(FAKE_STYLIST_ID),
        "adjacent_priority": 1,
    }


def _slot_time_patches(slots: list[dict]) -> dict:
    return {
        "agent.tools.check_availability.load_lead_time_settings": AsyncMock(
            return_value=(3, 0)
        ),
        "agent.tools.check_availability.get_service_durations": AsyncMock(
            return_value={FAKE_SERVICE_ID: 45}
        ),
        "agent.tools.check_availability.get_active_stylists_for_services": AsyncMock(
            return_value=[FAKE_STYLIST_ID]
        ),
        "agent.tools.check_availability.get_stylist_names_map": AsyncMock(
            return_value={FAKE_STYLIST_ID: "Marta Test"}
        ),
        "agent.tools.check_availability.get_available_slots": AsyncMock(
            return_value=slots
        ),
        "shared.business_hours_validator.is_date_closed": AsyncMock(return_value=False),
        "agent.tools._booking_helpers._compute_first_valid_date": MagicMock(
            return_value=date.today() + timedelta(days=3)
        ),
    }


# T12 — RED: partial collision accepted (wrong behavior with old T{slot_time}: filter)
@pytest.mark.asyncio
async def test_slot_time_partial_seconds_collision_rejected():
    """T12: slot with non-standard seconds (e.g. :45) must NOT match slot_time='10:30'.

    Old filter: f'T{slot_time}:' → 'T10:30:' matches '10:30:45' (wrong).
    New filter: f'T{slot_time}:00' → does NOT match '10:30:45' (correct).
    """
    from agent.tools.check_availability import check_availability

    date_iso = _future_date_iso(8)
    # Slot with non-standard :45 seconds
    slots = [_make_slot_raw("10:30", "45")]
    patches = _slot_time_patches(slots)

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
        raw = await check_availability.ainvoke({
            "service_ids": [str(FAKE_SERVICE_ID)],
            "stylist_id": str(FAKE_STYLIST_ID),
            "date_iso": date_iso,
            "slot_time": "10:30",
        })

    data = parse_response(raw)
    # The :45 slot must NOT match slot_time=10:30 — should return rejected (slot_no_longer_available)
    assert data.get("status") != "ok" or data.get("payload", {}).get("exact_match") is not True, (
        f"Slot with :45 seconds must NOT match slot_time='10:30', got: {data}"
    )


# T13 — Exact :00 seconds boundary match still passes (regression guard)
@pytest.mark.asyncio
async def test_slot_time_exact_seconds_00_passes():
    """T13: slot with :00 seconds must still match slot_time='10:30' (regression guard)."""
    from agent.tools.check_availability import check_availability

    date_iso = _future_date_iso(8)
    # Standard :00 seconds slot
    slots = [_make_slot_raw("10:30", "00")]
    patches = _slot_time_patches(slots)

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
        raw = await check_availability.ainvoke({
            "service_ids": [str(FAKE_SERVICE_ID)],
            "stylist_id": str(FAKE_STYLIST_ID),
            "date_iso": date_iso,
            "slot_time": "10:30",
        })

    data = parse_response(raw)
    assert data.get("status") == "ok", f"Expected ok for exact :00 match, got: {data}"
    assert data.get("payload", {}).get("exact_match") is True

"""T3 — get_availability_window aggregator.

Tests spec R1.2, R1.4 / ADR-2.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


FAKE_STYLIST_ID = uuid4()
FAKE_SERVICE_ID = uuid4()


def _make_slot(time_str: str = "10:00") -> dict:
    return {
        "time": time_str,
        "end_time": "11:00",
        "full_datetime": f"2026-05-01T{time_str}:00+02:00",
        "stylist_id": str(FAKE_STYLIST_ID),
        "adjacent_priority": 1,
    }


@pytest.mark.asyncio
async def test_get_availability_window_returns_structured_dict():
    """Returns {stylist_name: [{date_iso, weekday_es, slots:[...]}]} structure."""
    from agent.services.availability_service import get_availability_window

    today = date.today()

    with (
        patch(
            "agent.services.availability_service._get_active_stylists_for_window",
            new=AsyncMock(return_value=[(FAKE_STYLIST_ID, "Pilar", "HAIRDRESSING")]),
        ),
        patch(
            "agent.services.availability_service._get_total_duration_for_window",
            new=AsyncMock(return_value=45),
        ),
        patch(
            "agent.services.availability_service.get_available_slots",
            new=AsyncMock(return_value=[_make_slot("10:00"), _make_slot("11:00")]),
        ),
        patch(
            "agent.services.availability_service._load_lead_time_min_days",
            new=AsyncMock(return_value=3),
        ),
    ):
        result = await get_availability_window(
            service_ids=[FAKE_SERVICE_ID],
            audience=None,
            days=3,
            max_slots_per_day=4,
        )

    assert isinstance(result, dict)
    assert "Pilar" in result
    days_data = result["Pilar"]
    assert len(days_data) > 0
    first_day = days_data[0]
    assert "date_iso" in first_day
    assert "weekday_es" in first_day
    assert "slots" in first_day
    assert isinstance(first_day["slots"], list)


@pytest.mark.asyncio
async def test_get_availability_window_applies_lead_time_floor():
    """start_date must be today + min_days (lead-time floor applied)."""
    from agent.services.availability_service import get_availability_window

    today = date.today()
    calls_dates = []

    async def fake_get_slots(stylist_id, target_date, service_duration_minutes, **kw):
        calls_dates.append(target_date)
        return [_make_slot("10:00")]

    with (
        patch(
            "agent.services.availability_service._get_active_stylists_for_window",
            new=AsyncMock(return_value=[(FAKE_STYLIST_ID, "Pilar", "HAIRDRESSING")]),
        ),
        patch(
            "agent.services.availability_service._get_total_duration_for_window",
            new=AsyncMock(return_value=45),
        ),
        patch(
            "agent.services.availability_service.get_available_slots",
            new=fake_get_slots,
        ),
        patch(
            "agent.services.availability_service._load_lead_time_min_days",
            new=AsyncMock(return_value=3),
        ),
    ):
        await get_availability_window(
            service_ids=[FAKE_SERVICE_ID],
            audience=None,
            days=3,
            max_slots_per_day=4,
        )

    assert len(calls_dates) > 0
    # All queried dates must be >= today + 3
    floor = today + timedelta(days=3)
    for d in calls_dates:
        assert d >= floor, f"Date {d} is before lead-time floor {floor}"


@pytest.mark.asyncio
async def test_get_availability_window_caps_slots_per_day():
    """max_slots_per_day limits slots returned per day."""
    from agent.services.availability_service import get_availability_window

    many_slots = [_make_slot(f"{10 + i}:00") for i in range(10)]

    with (
        patch(
            "agent.services.availability_service._get_active_stylists_for_window",
            new=AsyncMock(return_value=[(FAKE_STYLIST_ID, "Pilar", "HAIRDRESSING")]),
        ),
        patch(
            "agent.services.availability_service._get_total_duration_for_window",
            new=AsyncMock(return_value=45),
        ),
        patch(
            "agent.services.availability_service.get_available_slots",
            new=AsyncMock(return_value=many_slots),
        ),
        patch(
            "agent.services.availability_service._load_lead_time_min_days",
            new=AsyncMock(return_value=3),
        ),
    ):
        result = await get_availability_window(
            service_ids=[FAKE_SERVICE_ID],
            audience=None,
            days=3,
            max_slots_per_day=2,
        )

    for stylist_name, days_data in result.items():
        for day_entry in days_data:
            assert len(day_entry["slots"]) <= 2, (
                f"max_slots_per_day=2 violated: got {len(day_entry['slots'])} slots"
            )


@pytest.mark.asyncio
async def test_get_availability_window_skips_empty_days():
    """Days with no slots are excluded from output."""
    from agent.services.availability_service import get_availability_window

    call_count = [0]

    async def alternating_slots(stylist_id, target_date, service_duration_minutes, **kw):
        call_count[0] += 1
        # Only return slots on odd calls
        if call_count[0] % 2 == 1:
            return [_make_slot("10:00")]
        return []

    with (
        patch(
            "agent.services.availability_service._get_active_stylists_for_window",
            new=AsyncMock(return_value=[(FAKE_STYLIST_ID, "Pilar", "HAIRDRESSING")]),
        ),
        patch(
            "agent.services.availability_service._get_total_duration_for_window",
            new=AsyncMock(return_value=45),
        ),
        patch(
            "agent.services.availability_service.get_available_slots",
            new=alternating_slots,
        ),
        patch(
            "agent.services.availability_service._load_lead_time_min_days",
            new=AsyncMock(return_value=3),
        ),
    ):
        result = await get_availability_window(
            service_ids=[FAKE_SERVICE_ID],
            audience=None,
            days=4,
            max_slots_per_day=4,
        )

    for stylist_name, days_data in result.items():
        for day_entry in days_data:
            assert len(day_entry["slots"]) > 0, "Empty days must be excluded"


@pytest.mark.asyncio
async def test_get_availability_window_empty_when_no_stylists():
    """Returns empty dict when no eligible stylists."""
    from agent.services.availability_service import get_availability_window

    with (
        patch(
            "agent.services.availability_service._get_active_stylists_for_window",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "agent.services.availability_service._get_total_duration_for_window",
            new=AsyncMock(return_value=45),
        ),
        patch(
            "agent.services.availability_service._load_lead_time_min_days",
            new=AsyncMock(return_value=3),
        ),
    ):
        result = await get_availability_window(
            service_ids=[FAKE_SERVICE_ID],
            audience=None,
        )

    assert result == {}

"""
Tests for agent/tools/check_availability.py — Task 3.3 (RED).

check_availability wraps agent/services/availability_service.py.
It does NOT re-implement availability logic — it calls get_available_slots.
"""

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_response(raw: str):
    return json.loads(raw)


def future_date_iso(days_ahead: int = 5) -> str:
    """Return a date ISO string at least days_ahead from today."""
    d = date.today() + timedelta(days=days_ahead)
    return d.isoformat()


FAKE_STYLIST_ID = uuid4()
FAKE_SERVICE_ID = uuid4()


# ---------------------------------------------------------------------------
# Import smoke
# ---------------------------------------------------------------------------


def test_check_availability_importable():
    from agent.tools.check_availability import check_availability  # noqa: F401

    assert hasattr(check_availability, "invoke")


def test_check_availability_has_tool_name():
    from agent.tools.check_availability import check_availability

    assert hasattr(check_availability, "name")
    assert "check_availability" in check_availability.name


# ---------------------------------------------------------------------------
# Happy path — slots found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_availability_returns_ok_when_slots_available():
    """When get_available_slots returns slots, tool returns status=ok."""
    from agent.tools.check_availability import check_availability

    fake_slots = [
        {
            "time": "10:00",
            "end_time": "11:00",
            "full_datetime": f"{future_date_iso()}T10:00:00+01:00",
            "stylist_id": str(FAKE_STYLIST_ID),
            "adjacent_priority": 1,
        }
    ]

    with (
        patch(
            "agent.tools.check_availability.get_available_slots",
            new_callable=AsyncMock,
            return_value=fake_slots,
        ),
        patch(
            "agent.tools.check_availability._get_service_durations",
            new_callable=AsyncMock,
            return_value={FAKE_SERVICE_ID: 60},
        ),
        patch(
            "agent.tools.check_availability._get_active_stylists_for_services",
            new_callable=AsyncMock,
            return_value=[FAKE_STYLIST_ID],
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": str(FAKE_STYLIST_ID),
                "date_iso": future_date_iso(),
                "audience": None,
            }
        )

    data = parse_response(raw)
    assert data["status"] == "ok"
    assert "slots" in data["payload"]
    assert len(data["payload"]["slots"]) == 1
    assert "total_duration_minutes" in data["payload"]
    assert data["payload"]["total_duration_minutes"] == 60


@pytest.mark.asyncio
async def test_check_availability_slot_shape():
    """Each slot has start_iso, end_iso, stylist_id, stylist_name."""
    from agent.tools.check_availability import check_availability

    fake_slots = [
        {
            "time": "10:00",
            "end_time": "11:00",
            "full_datetime": f"{future_date_iso()}T10:00:00+01:00",
            "stylist_id": str(FAKE_STYLIST_ID),
            "adjacent_priority": 0,
        }
    ]

    with (
        patch(
            "agent.tools.check_availability.get_available_slots",
            new_callable=AsyncMock,
            return_value=fake_slots,
        ),
        patch(
            "agent.tools.check_availability._get_service_durations",
            new_callable=AsyncMock,
            return_value={FAKE_SERVICE_ID: 60},
        ),
        patch(
            "agent.tools.check_availability._get_active_stylists_for_services",
            new_callable=AsyncMock,
            return_value=[FAKE_STYLIST_ID],
        ),
        patch(
            "agent.tools.check_availability._get_stylist_name",
            new_callable=AsyncMock,
            return_value="Marta",
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": str(FAKE_STYLIST_ID),
                "date_iso": future_date_iso(),
                "audience": None,
            }
        )

    data = parse_response(raw)
    slot = data["payload"]["slots"][0]
    assert "start_iso" in slot
    assert "end_iso" in slot
    assert "stylist_id" in slot


# ---------------------------------------------------------------------------
# No slots — alt_dates hint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_availability_no_slots_returns_ok_with_empty_slots():
    """When no slots exist on requested date, returns ok with empty slots list."""
    from agent.tools.check_availability import check_availability

    with (
        patch(
            "agent.tools.check_availability.get_available_slots",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "agent.tools.check_availability._get_service_durations",
            new_callable=AsyncMock,
            return_value={FAKE_SERVICE_ID: 60},
        ),
        patch(
            "agent.tools.check_availability._get_active_stylists_for_services",
            new_callable=AsyncMock,
            return_value=[FAKE_STYLIST_ID],
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": str(FAKE_STYLIST_ID),
                "date_iso": future_date_iso(),
                "audience": None,
            }
        )

    data = parse_response(raw)
    assert data["status"] == "ok"
    assert data["payload"]["slots"] == []


# ---------------------------------------------------------------------------
# Rejection: past date
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_availability_rejects_past_date():
    """Dates in the past return status=rejected."""
    from agent.tools.check_availability import check_availability

    past_date = (date.today() - timedelta(days=1)).isoformat()

    raw = await check_availability.ainvoke(
        {
            "service_ids": [str(FAKE_SERVICE_ID)],
            "stylist_id": str(FAKE_STYLIST_ID),
            "date_iso": past_date,
            "audience": None,
        }
    )

    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert len(data["errors"]) > 0
    # Errors must be non-imperative (no direct commands to user)
    for err in data["errors"]:
        assert not err.lower().startswith(
            ("use ", "choose ", "select ", "enter ", "provide ")
        ), f"Error is imperative: {err!r}"


# ---------------------------------------------------------------------------
# stylist_id=None — aggregates across all stylists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_availability_no_stylist_aggregates():
    """When stylist_id=None, aggregates slots from all qualifying stylists."""
    from agent.tools.check_availability import check_availability

    stylist_a = uuid4()
    stylist_b = uuid4()

    fake_slots_a = [
        {
            "time": "10:00",
            "end_time": "11:00",
            "full_datetime": f"{future_date_iso()}T10:00:00+01:00",
            "stylist_id": str(stylist_a),
            "adjacent_priority": 1,
        }
    ]
    fake_slots_b = [
        {
            "time": "11:00",
            "end_time": "12:00",
            "full_datetime": f"{future_date_iso()}T11:00:00+01:00",
            "stylist_id": str(stylist_b),
            "adjacent_priority": 1,
        }
    ]

    async def mock_get_slots(stylist_id, target_date, service_duration_minutes, **kwargs):
        if stylist_id == stylist_a:
            return fake_slots_a
        return fake_slots_b

    with (
        patch(
            "agent.tools.check_availability.get_available_slots",
            side_effect=mock_get_slots,
        ),
        patch(
            "agent.tools.check_availability._get_service_durations",
            new_callable=AsyncMock,
            return_value={FAKE_SERVICE_ID: 60},
        ),
        patch(
            "agent.tools.check_availability._get_active_stylists_for_services",
            new_callable=AsyncMock,
            return_value=[stylist_a, stylist_b],
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": None,
                "date_iso": future_date_iso(),
                "audience": None,
            }
        )

    data = parse_response(raw)
    assert data["status"] == "ok"
    assert len(data["payload"]["slots"]) == 2


# ---------------------------------------------------------------------------
# Returns JSON string
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_availability_returns_json_string():
    from agent.tools.check_availability import check_availability

    with (
        patch(
            "agent.tools.check_availability.get_available_slots",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "agent.tools.check_availability._get_service_durations",
            new_callable=AsyncMock,
            return_value={FAKE_SERVICE_ID: 30},
        ),
        patch(
            "agent.tools.check_availability._get_active_stylists_for_services",
            new_callable=AsyncMock,
            return_value=[FAKE_STYLIST_ID],
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": str(FAKE_STYLIST_ID),
                "date_iso": future_date_iso(),
                "audience": None,
            }
        )

    assert isinstance(raw, str)
    data = json.loads(raw)
    assert isinstance(data, dict)

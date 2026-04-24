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
    assert data["payload"]["requested_date_iso"] == future_date_iso()
    assert data["payload"]["is_exact_day"] is True
    assert data["payload"]["has_availability"] is True


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
    assert data["payload"]["requested_date_iso"] == future_date_iso()
    assert data["payload"]["is_exact_day"] is True
    assert data["payload"]["has_availability"] is False
    assert "options" not in data["payload"]


@pytest.mark.asyncio
async def test_check_availability_keeps_requested_day_in_all_returned_slots():
    """Exact-day tool must never return cross-day fallback slots."""
    from agent.tools.check_availability import check_availability

    requested_date = future_date_iso()
    fake_slots = [
        {
            "time": "10:00",
            "end_time": "11:00",
            "full_datetime": f"{requested_date}T10:00:00+01:00",
            "stylist_id": str(FAKE_STYLIST_ID),
            "adjacent_priority": 1,
        },
        {
            "time": "12:00",
            "end_time": "13:00",
            "full_datetime": f"{requested_date}T12:00:00+01:00",
            "stylist_id": str(FAKE_STYLIST_ID),
            "adjacent_priority": 0,
        },
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
                "date_iso": requested_date,
                "audience": None,
            }
        )

    data = parse_response(raw)
    assert {slot["start_iso"][:10] for slot in data["payload"]["slots"]} == {requested_date}
    assert data["payload"]["requested_date_iso"] == requested_date
    assert data["payload"]["is_exact_day"] is True


@pytest.mark.asyncio
async def test_check_availability_queries_all_stylists_for_requested_day_only():
    """No-preference mode should aggregate exact-day slots, not broaden the date."""
    from agent.tools.check_availability import check_availability

    requested_date = future_date_iso()
    stylist_a = uuid4()
    stylist_b = uuid4()

    async def mock_get_slots(stylist_id, target_date, service_duration_minutes, **kwargs):
        assert target_date.isoformat() == requested_date
        if stylist_id == stylist_a:
            return []
        return [
            {
                "time": "11:00",
                "end_time": "12:00",
                "full_datetime": f"{requested_date}T11:00:00+01:00",
                "stylist_id": str(stylist_b),
                "adjacent_priority": 1,
            }
        ]

    with (
        patch(
            "agent.tools.check_availability.get_available_slots", side_effect=mock_get_slots
        ) as mock_slots,
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
                "date_iso": requested_date,
                "audience": None,
            }
        )

    data = parse_response(raw)
    assert mock_slots.call_count == 2
    assert data["payload"]["has_availability"] is True
    assert "options" not in data["payload"]


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
        assert not err.lower().startswith(("use ", "choose ", "select ", "enter ", "provide ")), (
            f"Error is imperative: {err!r}"
        )


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


# ---------------------------------------------------------------------------
# Phase 2 — Lead-time guard (V1 spec)
# ---------------------------------------------------------------------------


def _mock_settings_service(min_days: int, buffer_hours: int = 0):
    """Build an AsyncMock SettingsService that returns the given lead-time values."""
    service = AsyncMock()

    async def fake_get(key: str, default=None):
        if key == "minimum_booking_days_advance":
            return min_days
        if key == "same_day_buffer_hours":
            return buffer_hours
        return default

    service.get = fake_get
    return service


def _patch_settings(min_days: int, buffer_hours: int = 0):
    """Context-manager patch for get_settings_service."""
    return patch(
        "shared.settings_service.get_settings_service",
        new_callable=AsyncMock,
        return_value=_mock_settings_service(min_days, buffer_hours),
    )


def _patch_db_calls(
    service_duration: int = 60,
    stylist_ids: list | None = None,
    slots: list | None = None,
):
    """Patch all DB-touching helpers so lead-time tests don't need a live DB."""
    if stylist_ids is None:
        stylist_ids = [FAKE_STYLIST_ID]
    if slots is None:
        slots = []

    from unittest.mock import patch as _patch

    return (
        _patch(
            "agent.tools.check_availability._get_service_durations",
            new_callable=AsyncMock,
            return_value={FAKE_SERVICE_ID: service_duration},
        ),
        _patch(
            "agent.tools.check_availability._get_active_stylists_for_services",
            new_callable=AsyncMock,
            return_value=stylist_ids,
        ),
        _patch(
            "agent.tools.check_availability.get_available_slots",
            new_callable=AsyncMock,
            return_value=slots,
        ),
    )


@pytest.mark.asyncio
async def test_rejects_same_day_when_min_days_positive():
    """V1-FR-01: same-day booking rejected when min_days=3."""
    from agent.tools.check_availability import check_availability

    today_iso = date.today().isoformat()
    dur_patch, stylist_patch, slots_patch = _patch_db_calls()

    with _patch_settings(min_days=3), dur_patch, stylist_patch, slots_patch:
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": None,
                "date_iso": today_iso,
                "audience": None,
            }
        )

    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert len(data["errors"]) > 0
    assert any("antelación" in e or "días" in e for e in data["errors"]), (
        f"Expected lead-time message, got: {data['errors']}"
    )


@pytest.mark.asyncio
async def test_rejects_day_plus_1_when_min_3():
    """V1-FR-02: today+1 rejected when min_days=3."""
    from agent.tools.check_availability import check_availability

    tomorrow_iso = (date.today() + timedelta(days=1)).isoformat()
    dur_patch, stylist_patch, slots_patch = _patch_db_calls()

    with _patch_settings(min_days=3), dur_patch, stylist_patch, slots_patch:
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": None,
                "date_iso": tomorrow_iso,
                "audience": None,
            }
        )

    data = parse_response(raw)
    assert data["status"] == "rejected"


@pytest.mark.asyncio
async def test_accepts_boundary_day_plus_3_when_min_3():
    """V1-FR-03: today+3 accepted when min_days=3."""
    from agent.tools.check_availability import check_availability

    boundary_iso = (date.today() + timedelta(days=3)).isoformat()
    dur_patch, stylist_patch, slots_patch = _patch_db_calls()

    with _patch_settings(min_days=3), dur_patch, stylist_patch, slots_patch:
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": None,
                "date_iso": boundary_iso,
                "audience": None,
            }
        )

    data = parse_response(raw)
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_allows_same_day_when_min_0():
    """V1-FR-05: same-day allowed when min_days=0."""
    from agent.tools.check_availability import check_availability

    today_iso = date.today().isoformat()
    dur_patch, stylist_patch, slots_patch = _patch_db_calls()

    with _patch_settings(min_days=0), dur_patch, stylist_patch, slots_patch:
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": None,
                "date_iso": today_iso,
                "audience": None,
            }
        )

    data = parse_response(raw)
    # Should pass the lead-time gate (may still be ok with empty slots or rejected
    # for other reasons, but NOT because of lead-time)
    assert data["status"] != "rejected" or not any(
        "antelación" in e for e in data.get("errors", [])
    ), f"Should not reject same-day when min_days=0, got: {data}"


@pytest.mark.asyncio
async def test_fails_closed_when_settings_service_raises():
    """D3: when SettingsService raises, tool returns rejected (fail-closed)."""
    from agent.tools.check_availability import check_availability

    failing_service = AsyncMock()
    failing_service.get = AsyncMock(side_effect=Exception("DB connection lost"))

    with patch(
        "shared.settings_service.get_settings_service",
        new_callable=AsyncMock,
        return_value=failing_service,
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": None,
                "date_iso": future_date_iso(5),
                "audience": None,
            }
        )

    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert len(data["errors"]) > 0

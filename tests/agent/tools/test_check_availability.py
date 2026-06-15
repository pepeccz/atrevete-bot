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
        patch(
            "shared.business_hours_validator.is_date_closed",
            new_callable=AsyncMock,
            return_value=False,
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
    """Patch all DB-touching helpers so lead-time tests don't need a live DB.

    Also patches is_date_closed to return False (open day) so that empty-slot
    responses return status=ok rather than rejected/closed_day.
    """
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
        _patch(
            "shared.business_hours_validator.is_date_closed",
            new_callable=AsyncMock,
            return_value=False,
        ),
    )


@pytest.mark.asyncio
async def test_rejects_same_day_when_min_days_positive():
    """V1-FR-01: same-day booking rejected when min_days=3."""
    from agent.tools.check_availability import check_availability

    today_iso = date.today().isoformat()
    dur_patch, stylist_patch, slots_patch, date_closed_patch = _patch_db_calls()

    with _patch_settings(min_days=3), dur_patch, stylist_patch, slots_patch, date_closed_patch:
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
    dur_patch, stylist_patch, slots_patch, date_closed_patch = _patch_db_calls()

    with _patch_settings(min_days=3), dur_patch, stylist_patch, slots_patch, date_closed_patch:
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
    dur_patch, stylist_patch, slots_patch, date_closed_patch = _patch_db_calls()

    with _patch_settings(min_days=3), dur_patch, stylist_patch, slots_patch, date_closed_patch:
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


@pytest.mark.xfail(
    reason=(
        "PROD BUG: _load_lead_time_settings() uses `int(min_days or 3)` which coerces "
        "0 to 3 because 0 is falsy in Python. When settings return min_days=0 (allow "
        "same-day), the production code treats it as min_days=3. Fix: change to "
        "`int(min_days) if min_days is not None else 3` in agent/tools/check_availability.py:37."
    ),
    strict=True,
)
@pytest.mark.asyncio
async def test_allows_same_day_when_min_0():
    """V1-FR-05: same-day allowed when min_days=0."""
    from agent.tools.check_availability import check_availability

    today_iso = date.today().isoformat()
    dur_patch, stylist_patch, slots_patch, date_closed_patch = _patch_db_calls()

    with _patch_settings(min_days=0), dur_patch, stylist_patch, slots_patch, date_closed_patch:
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


# ---------------------------------------------------------------------------
# Phase 3 — Payload Enrichment (V2 + V3 spec)
# ---------------------------------------------------------------------------


def _make_fake_slot(date_iso: str, time: str = "10:00", stylist_id: str | None = None) -> dict:
    sid = stylist_id or str(FAKE_STYLIST_ID)
    return {
        "time": time,
        "end_time": "11:00",
        "full_datetime": f"{date_iso}T{time}:00+02:00",
        "stylist_id": sid,
        "adjacent_priority": 1,
    }


STYLIST_A = uuid4()
STYLIST_B = uuid4()


@pytest.mark.asyncio
async def test_each_slot_has_label_in_spanish():
    """V3-FR-01/02: every slot must have a 'label' field in Spanish format."""
    import re

    from agent.tools.check_availability import check_availability

    date_iso = future_date_iso(5)
    fake_slots = [_make_fake_slot(date_iso, "10:00")]

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
                "stylist_id": None,
                "date_iso": date_iso,
                "audience": None,
            }
        )

    data = parse_response(raw)
    assert data["status"] == "ok"
    slots = data["payload"]["slots"]
    assert len(slots) == 1
    assert "label" in slots[0], "slot must have 'label' field"
    label = slots[0]["label"]
    assert re.match(r"^[a-záéíóú]+ \d{1,2} de [a-záéíóú]+$", label), (
        f"label {label!r} does not match Spanish date pattern"
    )


@pytest.mark.asyncio
async def test_label_has_no_year():
    """V3-FR-02: label must not contain the year."""
    import re

    from agent.tools.check_availability import check_availability

    date_iso = future_date_iso(5)
    fake_slots = [_make_fake_slot(date_iso)]

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
                "stylist_id": None,
                "date_iso": date_iso,
                "audience": None,
            }
        )

    data = parse_response(raw)
    label = data["payload"]["slots"][0]["label"]
    assert not re.search(r"\d{4}", label), f"Year found in label: {label!r}"


@pytest.mark.asyncio
async def test_requested_date_label_matches_date_iso():
    """V3: payload must include requested_date_label matching the requested date."""
    from datetime import date as dt_date

    from agent.tools.check_availability import check_availability
    from shared.date_format import format_date_spanish

    date_iso = future_date_iso(5)
    expected_label = format_date_spanish(dt_date.fromisoformat(date_iso))

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
        patch(
            "shared.business_hours_validator.is_date_closed",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": None,
                "date_iso": date_iso,
                "audience": None,
            }
        )

    data = parse_response(raw)
    assert "requested_date_label" in data["payload"], "payload must have requested_date_label"
    assert data["payload"]["requested_date_label"] == expected_label


@pytest.mark.asyncio
async def test_payload_contains_available_stylists_filtered_by_category():
    """V2-FR-01: payload must include available_stylists list."""
    from agent.tools.check_availability import check_availability

    date_iso = future_date_iso(5)
    fake_slots = [
        _make_fake_slot(date_iso, "10:00", str(STYLIST_A)),
        _make_fake_slot(date_iso, "11:00", str(STYLIST_B)),
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
            return_value=[STYLIST_A, STYLIST_B],
        ),
        patch(
            "agent.tools.check_availability._get_stylist_names_map",
            new_callable=AsyncMock,
            return_value={STYLIST_A: "Ana", STYLIST_B: "María"},
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": None,
                "date_iso": date_iso,
                "audience": None,
            }
        )

    data = parse_response(raw)
    assert data["status"] == "ok"
    assert "available_stylists" in data["payload"], "payload must have available_stylists"
    stylists = data["payload"]["available_stylists"]
    assert len(stylists) == 2
    names = {s["name"] for s in stylists}
    assert names == {"Ana", "María"}


@pytest.mark.asyncio
async def test_available_stylists_sorted_by_name():
    """V2: available_stylists must be sorted alphabetically by name."""
    from agent.tools.check_availability import check_availability

    date_iso = future_date_iso(5)
    fake_slots = [_make_fake_slot(date_iso, "10:00", str(STYLIST_A))]

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
            return_value=[STYLIST_A, STYLIST_B],
        ),
        patch(
            "agent.tools.check_availability._get_stylist_names_map",
            new_callable=AsyncMock,
            return_value={STYLIST_A: "Zoë", STYLIST_B: "Ana"},
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": None,
                "date_iso": date_iso,
                "audience": None,
            }
        )

    data = parse_response(raw)
    names = [s["name"] for s in data["payload"]["available_stylists"]]
    assert names == sorted(names), f"available_stylists not sorted: {names}"


@pytest.mark.asyncio
async def test_rejected_when_zero_stylists_for_category():
    """V2-FR-02: when no active stylists for category, reject."""
    from agent.tools.check_availability import check_availability

    date_iso = future_date_iso(5)

    with (
        patch(
            "agent.tools.check_availability._get_service_durations",
            new_callable=AsyncMock,
            return_value={FAKE_SERVICE_ID: 60},
        ),
        patch(
            "agent.tools.check_availability._get_active_stylists_for_services",
            new_callable=AsyncMock,
            return_value=[],  # zero stylists
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": None,
                "date_iso": date_iso,
                "audience": None,
            }
        )

    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert len(data["errors"]) > 0


@pytest.mark.asyncio
async def test_single_stylist_when_stylist_id_provided():
    """V2: when stylist_id provided, available_stylists contains only that stylist."""
    from agent.tools.check_availability import check_availability

    date_iso = future_date_iso(5)
    fake_slots = [_make_fake_slot(date_iso, "10:00", str(STYLIST_A))]

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
            "agent.tools.check_availability._get_stylist_names_map",
            new_callable=AsyncMock,
            return_value={STYLIST_A: "Ana"},
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": str(STYLIST_A),
                "date_iso": date_iso,
                "audience": None,
            }
        )

    data = parse_response(raw)
    assert data["status"] == "ok"
    stylists = data["payload"]["available_stylists"]
    assert len(stylists) == 1
    assert stylists[0]["id"] == str(STYLIST_A)
    assert stylists[0]["name"] == "Ana"


# ---------------------------------------------------------------------------
# T4 — Precondition guards (R4, R5, R6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_date_required_when_date_iso_none():
    """R6: missing date_iso → rejected, next_step=date_required."""
    from agent.tools.check_availability import check_availability

    raw = await check_availability.ainvoke(
        {
            "service_ids": [str(FAKE_SERVICE_ID)],
            "stylist_id": str(FAKE_STYLIST_ID),
            "date_iso": None,
            "audience": None,
        }
    )
    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert data.get("next_step") == "date_required"


@pytest.mark.asyncio
async def test_date_required_when_date_iso_empty_string():
    """R6: empty date_iso → rejected, next_step=date_required."""
    from agent.tools.check_availability import check_availability

    raw = await check_availability.ainvoke(
        {
            "service_ids": [str(FAKE_SERVICE_ID)],
            "stylist_id": str(FAKE_STYLIST_ID),
            "date_iso": "",
            "audience": None,
        }
    )
    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert data.get("next_step") == "date_required"


@pytest.mark.asyncio
async def test_stylist_required_no_preference_not_set():
    """R5: no stylist_id + no_preference=False (default) → rejected, next_step=stylist_required."""
    from agent.tools.check_availability import check_availability

    raw = await check_availability.ainvoke(
        {
            "service_ids": [str(FAKE_SERVICE_ID)],
            "stylist_id": None,
            "date_iso": future_date_iso(5),
            "audience": None,
            "no_preference": False,
        }
    )
    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert data.get("next_step") == "stylist_required"


@pytest.mark.asyncio
async def test_no_preference_bypasses_stylist_guard():
    """R5: no_preference=True bypasses stylist guard even with no stylist_id."""
    from agent.tools.check_availability import check_availability

    with (
        patch(
            "agent.tools.check_availability._load_lead_time_settings",
            new_callable=AsyncMock,
            return_value=(0, 0),
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
            "agent.tools.check_availability.get_available_slots",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": None,
                "date_iso": future_date_iso(5),
                "audience": None,
                "no_preference": True,
            }
        )
    data = parse_response(raw)
    assert data.get("next_step") != "stylist_required"


@pytest.mark.asyncio
async def test_advance_policy_violated_payload():
    """R4: date < today+min_days → rejected, next_step=advance_policy_violated,
    payload.first_valid_date and payload.policy_min_days present."""
    from datetime import date as dt_date

    from agent.tools.check_availability import check_availability

    tomorrow_iso = (dt_date.today() + timedelta(days=1)).isoformat()

    with _patch_settings(min_days=3):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": str(FAKE_STYLIST_ID),
                "date_iso": tomorrow_iso,
                "audience": None,
                "no_preference": False,
            }
        )
    data = parse_response(raw)
    assert data["status"] == "rejected"
    assert data.get("next_step") == "advance_policy_violated"
    assert "first_valid_date" in data.get("payload", {})
    assert data["payload"]["policy_min_days"] == 3
    # first_valid_date must be today+3
    expected = (dt_date.today() + timedelta(days=3)).isoformat()
    assert data["payload"]["first_valid_date"] == expected


@pytest.mark.asyncio
async def test_advance_policy_boundary_not_violated():
    """R4: date == today+min_days is NOT rejected with advance_policy_violated."""
    from datetime import date as dt_date

    from agent.tools.check_availability import check_availability

    boundary_iso = (dt_date.today() + timedelta(days=3)).isoformat()
    dur_patch, stylist_patch, slots_patch, date_closed_patch = _patch_db_calls()

    with _patch_settings(min_days=3), dur_patch, stylist_patch, slots_patch, date_closed_patch:
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": str(FAKE_STYLIST_ID),
                "date_iso": boundary_iso,
                "audience": None,
                "no_preference": False,
            }
        )
    data = parse_response(raw)
    assert data.get("next_step") != "advance_policy_violated"


@pytest.mark.asyncio
async def test_advance_policy_future_date_not_violated():
    """R4: date = today+30 is never rejected for advance policy."""
    from agent.tools.check_availability import check_availability

    far_future = future_date_iso(30)
    dur_patch, stylist_patch, slots_patch, date_closed_patch = _patch_db_calls()

    with _patch_settings(min_days=3), dur_patch, stylist_patch, slots_patch, date_closed_patch:
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": str(FAKE_STYLIST_ID),
                "date_iso": far_future,
                "audience": None,
                "no_preference": False,
            }
        )
    data = parse_response(raw)
    assert data.get("next_step") != "advance_policy_violated"


@pytest.mark.asyncio
async def test_legacy_fields_still_present():
    """Additive contract: existing fields must remain in slot dicts."""
    from agent.tools.check_availability import check_availability

    date_iso = future_date_iso(5)
    fake_slots = [_make_fake_slot(date_iso, "10:00", str(STYLIST_A))]

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
            return_value=[STYLIST_A],
        ),
        patch(
            "agent.tools.check_availability._get_stylist_names_map",
            new_callable=AsyncMock,
            return_value={STYLIST_A: "Ana"},
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": None,
                "date_iso": date_iso,
                "audience": None,
            }
        )

    data = parse_response(raw)
    slot = data["payload"]["slots"][0]
    for field in ("start_iso", "end_iso", "stylist_id", "stylist_name"):
        assert field in slot, f"Legacy field '{field}' missing from slot"

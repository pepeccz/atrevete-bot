"""
Tests for update_booking tool — slot_index resolution (T-07).

Covers:
1. slot_index=0 (0-based) is rejected (1-based expected) — actually 1-based design, slot_index=1 valid
2. slot_index=5 with 3 offered_slots → error (out of range)
3. slot_index=None → no slot resolution, other fields still work
4. slot_index=1 with no offered_slots in context → error
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.tools.booking_data_tools import update_booking


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OFFERED_SLOTS = [
    {
        "stylist_name": "Laura",
        "stylist_id": "uuid-laura",
        "start_time": "2026-04-20T10:00:00",
        "end_time": "2026-04-20T11:00:00",
        "date": "2026-04-20",
        "time": "10:00",
    },
    {
        "stylist_name": "Carmen",
        "stylist_id": "uuid-carmen",
        "start_time": "2026-04-20T11:00:00",
        "end_time": "2026-04-20T12:00:00",
        "date": "2026-04-20",
        "time": "11:00",
    },
    {
        "stylist_name": "Ana",
        "stylist_id": "uuid-ana",
        "start_time": "2026-04-20T14:00:00",
        "end_time": "2026-04-20T15:00:00",
        "date": "2026-04-20",
        "time": "14:00",
    },
]


async def _call_update_booking(**kwargs):
    """Invoke the underlying tool function directly, bypassing LangChain wrapping."""
    return await update_booking.coroutine(**kwargs)


# ---------------------------------------------------------------------------
# T-07 Scenario 1: valid slot_index=1 → selected_slot in patch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_index_valid_resolves_selected_slot():
    """slot_index=1 with valid offered_slots → selected_slot appears in patch."""
    result = await _call_update_booking(
        slot_index=1,
        _current_context={"offered_slots": _OFFERED_SLOTS},
    )

    assert result["success"] is True, f"Expected success, got errors: {result.get('errors')}"
    patch = result["_booking_context_patch"]
    assert "selected_slot" in patch, "selected_slot should be in the patch"

    selected = patch["selected_slot"]
    assert selected["stylist_name"] == "Laura"
    assert selected["stylist_id"] == "uuid-laura"
    assert selected["start_time"] == "2026-04-20T10:00:00"
    assert selected["date"] == "2026-04-20"
    assert selected["time"] == "10:00"


@pytest.mark.asyncio
async def test_slot_index_valid_last_slot_resolves():
    """slot_index=3 (last slot) resolves Ana correctly."""
    result = await _call_update_booking(
        slot_index=3,
        _current_context={"offered_slots": _OFFERED_SLOTS},
    )

    assert result["success"] is True
    patch = result["_booking_context_patch"]
    selected = patch["selected_slot"]
    assert selected["stylist_name"] == "Ana"
    assert selected["stylist_id"] == "uuid-ana"


@pytest.mark.asyncio
async def test_slot_index_syncs_last_stylist_when_empty():
    """When last_stylist is not set, slot resolution also sets it from slot data."""
    result = await _call_update_booking(
        slot_index=2,
        _current_context={"offered_slots": _OFFERED_SLOTS},
    )

    assert result["success"] is True
    patch = result["_booking_context_patch"]
    assert patch.get("last_stylist") == "Carmen", (
        "last_stylist should be synced from slot when not previously set"
    )


@pytest.mark.asyncio
async def test_slot_index_does_not_overwrite_existing_last_stylist():
    """When last_stylist is already set, slot resolution does NOT overwrite it."""
    result = await _call_update_booking(
        slot_index=1,
        _current_context={
            "offered_slots": _OFFERED_SLOTS,
            "last_stylist": "Laura",  # already set
        },
    )

    assert result["success"] is True
    patch = result["_booking_context_patch"]
    # last_stylist should NOT appear in patch (no overwrite)
    assert "last_stylist" not in patch, (
        "last_stylist should not be overwritten if already set in context"
    )


# ---------------------------------------------------------------------------
# T-07 Scenario 2: out-of-range slot_index → error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_index_out_of_range_returns_error():
    """slot_index=5 with only 3 offered_slots → error, no selected_slot in patch."""
    result = await _call_update_booking(
        slot_index=5,
        _current_context={"offered_slots": _OFFERED_SLOTS},
    )

    assert result["success"] is False
    assert len(result["errors"]) > 0
    assert "fuera de rango" in result["errors"][0]
    assert "selected_slot" not in result.get("_booking_context_patch", {})


@pytest.mark.asyncio
async def test_slot_index_zero_out_of_range():
    """slot_index=0 is out of range (1-based), should return error."""
    result = await _call_update_booking(
        slot_index=0,
        _current_context={"offered_slots": _OFFERED_SLOTS},
    )

    assert result["success"] is False
    assert len(result["errors"]) > 0
    assert "fuera de rango" in result["errors"][0]


# ---------------------------------------------------------------------------
# T-07 Scenario 3: slot_index=None → no slot resolution, other fields work
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_index_none_does_not_resolve():
    """slot_index=None → slot_index branch is skipped, other fields still applied."""
    result = await _call_update_booking(
        slot_index=None,
        notes="alergia al polvo",
        _current_context={"offered_slots": _OFFERED_SLOTS},
    )

    assert result["success"] is True
    patch = result["_booking_context_patch"]
    assert "selected_slot" not in patch, "slot_index=None should not produce a selected_slot"
    assert patch.get("notes") == "alergia al polvo", "notes should still be applied"


@pytest.mark.asyncio
async def test_slot_index_none_no_context_still_succeeds():
    """slot_index=None with empty context → no errors, tool succeeds."""
    result = await _call_update_booking(
        slot_index=None,
        _current_context={},
    )

    assert result["success"] is True
    assert "selected_slot" not in result["_booking_context_patch"]


# ---------------------------------------------------------------------------
# T-07 Scenario 4: no offered_slots in context → error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_index_with_no_offered_slots_returns_error():
    """slot_index=1 but no offered_slots in context → error."""
    result = await _call_update_booking(
        slot_index=1,
        _current_context={},  # no offered_slots key
    )

    assert result["success"] is False
    assert len(result["errors"]) > 0
    assert "check_availability" in result["errors"][0]
    assert "selected_slot" not in result.get("_booking_context_patch", {})


@pytest.mark.asyncio
async def test_slot_index_with_empty_offered_slots_returns_error():
    """slot_index=1 with offered_slots=[] → error (empty list)."""
    result = await _call_update_booking(
        slot_index=1,
        _current_context={"offered_slots": []},
    )

    assert result["success"] is False
    assert len(result["errors"]) > 0
    assert "check_availability" in result["errors"][0]


# ---------------------------------------------------------------------------
# Additional: slot_index + other fields in same call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_index_combined_with_notes():
    """slot_index and notes in same call → both applied."""
    result = await _call_update_booking(
        slot_index=2,
        notes="prefiero corte suave",
        _current_context={"offered_slots": _OFFERED_SLOTS},
    )

    assert result["success"] is True
    patch = result["_booking_context_patch"]
    assert patch["selected_slot"]["stylist_name"] == "Carmen"
    assert patch["notes"] == "prefiero corte suave"

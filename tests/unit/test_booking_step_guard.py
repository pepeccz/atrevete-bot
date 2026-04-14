"""Unit tests for BookingModeNode safety gates and _booking_complete.

LLM-driven architecture: _compute_step and regex patterns removed.
Tests focus on:
- _booking_complete() field-presence check
- _pre_tool_call() guard for check_availability (disambiguation + stylist)
- _pre_tool_call() guard for book() (field-presence gate)
"""

from __future__ import annotations

import pytest

from agent.modes.base import ToolCallRejection
from agent.modes.booking_mode import BookingModeNode


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def booking_node() -> BookingModeNode:
    """Create a bare BookingModeNode (no LLM needed for unit tests)."""
    return BookingModeNode(tools=[])


# ===========================================================================
# _booking_complete — field-presence check (replaces _compute_step)
# ===========================================================================


class TestBookingCompleteGate:
    """_booking_complete is a GATE, not a sequencer."""

    def test_empty_context(self):
        is_complete, missing = BookingModeNode._booking_complete({})
        assert is_complete is False
        assert set(missing) == {"servicio", "estilista", "fecha/hora", "nombre"}

    def test_service_only(self):
        _, missing = BookingModeNode._booking_complete({"last_services": ["Cortar"]})
        assert "servicio" not in missing
        assert "estilista" in missing

    def test_no_preference_counts_as_stylist(self):
        _, missing = BookingModeNode._booking_complete({"no_preference_stylist": True})
        assert "estilista" not in missing

    def test_all_fields_complete(self):
        ctx = {
            "last_services": ["Cortar"],
            "last_stylist": "Ana",
            "selected_slot": {"time": "10:00"},
            "customer_name": "María",
        }
        is_complete, missing = BookingModeNode._booking_complete(ctx)
        assert is_complete is True
        assert missing == []

    def test_notes_not_required_for_complete(self):
        """notes_asked is NOT a gate — notes are optional, handled by prompt."""
        ctx = {
            "last_services": ["Cortar"],
            "last_stylist": "Ana",
            "selected_slot": {"time": "10:00"},
            "customer_name": "María",
        }
        is_complete, _ = BookingModeNode._booking_complete(ctx)
        assert is_complete is True


# ===========================================================================
# _pre_tool_call — check_availability guards
# ===========================================================================


@pytest.mark.asyncio
async def test_pre_tool_call_allows_with_stylist(booking_node: BookingModeNode):
    """check_availability with last_stylist set → allowed."""
    booking_node._mode_context = {"last_services": ["Cortar"], "last_stylist": "Ana"}
    result = await booking_node._pre_tool_call(
        "check_availability", {"service_names": ["Cortar"], "stylist_name": "Ana"}
    )
    assert not isinstance(result, ToolCallRejection)


@pytest.mark.asyncio
async def test_pre_tool_call_allows_with_no_preference(booking_node: BookingModeNode):
    """check_availability with no_preference_stylist → allowed."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "no_preference_stylist": True,
        "last_stylist": "Sin preferencia",
    }
    result = await booking_node._pre_tool_call(
        "check_availability", {"service_names": ["Cortar"]}
    )
    assert not isinstance(result, ToolCallRejection)


@pytest.mark.asyncio
async def test_pre_tool_call_allows_stylist_name_in_args(booking_node: BookingModeNode):
    """LLM provides stylist_name in tool_args → guard passes."""
    booking_node._mode_context = {"last_services": ["Cortar"]}
    result = await booking_node._pre_tool_call(
        "check_availability", {"service_names": ["Cortar"], "stylist_name": "Victor"}
    )
    assert not isinstance(result, ToolCallRejection)


@pytest.mark.asyncio
async def test_pre_tool_call_sets_last_stylist_from_args(booking_node: BookingModeNode):
    """stylist_name from tool_args promotes to mode_context."""
    booking_node._mode_context = {"last_services": ["Cortar"]}
    await booking_node._pre_tool_call(
        "check_availability", {"service_names": ["Cortar"], "stylist_name": "Marta"}
    )
    assert booking_node._mode_context.get("last_stylist") == "Marta"


@pytest.mark.asyncio
async def test_pre_tool_call_does_not_overwrite_existing_stylist(booking_node: BookingModeNode):
    """Existing last_stylist is NOT overwritten by tool_args."""
    booking_node._mode_context = {"last_services": ["Cortar"], "last_stylist": "Harolyn"}
    await booking_node._pre_tool_call(
        "check_availability", {"service_names": ["Cortar"], "stylist_name": "Pilar"}
    )
    assert booking_node._mode_context.get("last_stylist") == "Harolyn"


@pytest.mark.asyncio
async def test_check_availability_allowed_despite_disambiguation(booking_node: BookingModeNode):
    """check_availability NOT blocked by _has_pending_disambiguation — gate removed."""
    booking_node._mode_context = {"_has_pending_disambiguation": True}
    result = await booking_node._pre_tool_call(
        "check_availability", {"service_names": ["Cortar"]}
    )
    assert not isinstance(result, ToolCallRejection)


@pytest.mark.asyncio
async def test_pre_tool_call_allows_no_stylist_no_context(booking_node: BookingModeNode):
    """check_availability without stylist info → allowed (LLM decides)."""
    booking_node._mode_context = {"last_services": ["Cortar"]}
    result = await booking_node._pre_tool_call(
        "check_availability", {"service_names": ["Cortar"]}
    )
    assert not isinstance(result, ToolCallRejection)


@pytest.mark.asyncio
async def test_pre_tool_call_empty_stylist_passes(booking_node: BookingModeNode):
    """stylist_name='' → passes through."""
    booking_node._mode_context = {"last_services": ["Cortar"]}
    result = await booking_node._pre_tool_call(
        "check_availability", {"service_names": ["Cortar"], "stylist_name": ""}
    )
    assert not isinstance(result, ToolCallRejection)


# ===========================================================================
# _pre_tool_call — book() field-presence gate
# ===========================================================================


@pytest.mark.asyncio
async def test_book_rejected_missing_name(booking_node: BookingModeNode):
    """book() rejected when customer_name is missing."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
        "selected_slot": {"time": "10:00", "stylist_id": "x", "start_time": "2026-04-20T10:00"},
        "offered_slots": [{"time": "10:00", "stylist_id": "x", "start_time": "2026-04-20T10:00"}],
    }
    result = await booking_node._pre_tool_call("book", {"slot_index": 1, "services": ["Cortar"]})
    assert isinstance(result, ToolCallRejection)
    assert "nombre" in result.error_message


@pytest.mark.asyncio
async def test_book_allowed_without_notes(booking_node: BookingModeNode):
    """book() allowed when notes_asked is missing — notes are optional."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
        "selected_slot": {"time": "10:00", "stylist_id": "x", "start_time": "2026-04-20T10:00"},
        "offered_slots": [{"time": "10:00", "stylist_id": "x", "start_time": "2026-04-20T10:00"}],
        "customer_name": "Ana",
    }
    result = await booking_node._pre_tool_call("book", {"slot_index": 1, "services": ["Cortar"]})
    assert not isinstance(result, ToolCallRejection)


@pytest.mark.asyncio
async def test_book_captures_notes_from_args(booking_node: BookingModeNode):
    """book() captures notes from tool args into mode_context."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
        "selected_slot": {"time": "10:00", "stylist_id": "x", "start_time": "2026-04-20T10:00"},
        "offered_slots": [{"time": "10:00", "stylist_id": "x", "start_time": "2026-04-20T10:00"}],
        "customer_name": "Ana",
    }
    await booking_node._pre_tool_call(
        "book", {"slot_index": 1, "services": ["Cortar"], "notes": "Alergia al amoniaco"}
    )
    assert booking_node._mode_context["notes"] == "Alergia al amoniaco"
    assert booking_node._mode_context["notes_asked"] is True


@pytest.mark.asyncio
async def test_book_notes_no_clears_to_none(booking_node: BookingModeNode):
    """book() with notes='no' stores None (no notes)."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
        "selected_slot": {"time": "10:00", "stylist_id": "x", "start_time": "2026-04-20T10:00"},
        "offered_slots": [{"time": "10:00", "stylist_id": "x", "start_time": "2026-04-20T10:00"}],
        "customer_name": "Ana",
    }
    await booking_node._pre_tool_call(
        "book", {"slot_index": 1, "services": ["Cortar"], "notes": "no"}
    )
    assert booking_node._mode_context["notes"] is None
    assert booking_node._mode_context["notes_asked"] is True

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
    node = BookingModeNode(tools=[])
    # Pre-load known stylists so the stylist gate can validate names from args
    node._cached_stylists_by_category = {
        "HAIRDRESSING": ["Pilar", "Marta", "Victor", "Harolyn", "Ana"],
    }
    return node


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
    """check_availability with last_stylist set + date → allowed."""
    booking_node._mode_context = {"last_services": ["Cortar"], "last_stylist": "Ana", "_date_question_asked": True}
    result = await booking_node._pre_tool_call(
        "check_availability",
        {"service_names": ["Cortar"], "stylist_name": "Ana", "date": "el martes"},
    )
    assert not isinstance(result, ToolCallRejection)


@pytest.mark.asyncio
async def test_pre_tool_call_allows_with_no_preference(booking_node: BookingModeNode):
    """check_availability with no_preference_stylist + date → allowed."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "no_preference_stylist": True,
        "last_stylist": "Sin preferencia",
        "_date_question_asked": True,
    }
    result = await booking_node._pre_tool_call(
        "check_availability", {"service_names": ["Cortar"], "date": "mañana"}
    )
    assert not isinstance(result, ToolCallRejection)


@pytest.mark.asyncio
async def test_pre_tool_call_allows_stylist_name_in_args(booking_node: BookingModeNode):
    """LLM provides stylist_name + date in tool_args → guard passes when stylist already in context."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Victor",
        "_date_question_asked": True,
    }
    result = await booking_node._pre_tool_call(
        "check_availability",
        {"service_names": ["Cortar"], "stylist_name": "Victor", "date": "el viernes"},
    )
    assert not isinstance(result, ToolCallRejection)


@pytest.mark.asyncio
async def test_pre_tool_call_sets_last_stylist_from_args(booking_node: BookingModeNode):
    """Stylist must be in mode_context (via update_booking) before check_availability passes."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
        "_date_question_asked": True,
    }
    result = await booking_node._pre_tool_call(
        "check_availability",
        {"service_names": ["Cortar"], "stylist_name": "Marta", "date": "el lunes"},
    )
    assert not isinstance(result, ToolCallRejection)
    assert booking_node._mode_context.get("last_stylist") == "Marta"


@pytest.mark.asyncio
async def test_pre_tool_call_does_not_overwrite_existing_stylist(booking_node: BookingModeNode):
    """Existing last_stylist is NOT overwritten by tool_args."""
    booking_node._mode_context = {"last_services": ["Cortar"], "last_stylist": "Harolyn", "_date_question_asked": True}
    await booking_node._pre_tool_call(
        "check_availability",
        {"service_names": ["Cortar"], "stylist_name": "Pilar", "date": "el martes"},
    )
    assert booking_node._mode_context.get("last_stylist") == "Harolyn"


@pytest.mark.asyncio
async def test_check_availability_allowed_despite_disambiguation(booking_node: BookingModeNode):
    """check_availability NOT blocked by _has_pending_disambiguation — gate removed."""
    booking_node._mode_context = {
        "_has_pending_disambiguation": True,
        "last_services": ["Cortar"],
        "last_stylist": "Ana",
        "_date_question_asked": True,
    }
    result = await booking_node._pre_tool_call(
        "check_availability",
        {"service_names": ["Cortar"], "stylist_name": "Ana", "date": "el martes"},
    )
    assert not isinstance(result, ToolCallRejection)


@pytest.mark.asyncio
async def test_pre_tool_call_rejects_no_stylist(booking_node: BookingModeNode):
    """check_availability without stylist → rejected by stylist gate."""
    booking_node._mode_context = {"last_services": ["Cortar"]}
    result = await booking_node._pre_tool_call(
        "check_availability", {"service_names": ["Cortar"]}
    )
    assert isinstance(result, ToolCallRejection)
    assert result.error_code == "STYLIST_NOT_RESOLVED"


@pytest.mark.asyncio
async def test_pre_tool_call_rejects_no_date(booking_node: BookingModeNode):
    """check_availability with stylist but no date → rejected by date gate."""
    booking_node._mode_context = {"last_services": ["Cortar"], "last_stylist": "Ana"}
    result = await booking_node._pre_tool_call(
        "check_availability", {"service_names": ["Cortar"], "stylist_name": "Ana"}
    )
    assert isinstance(result, ToolCallRejection)
    assert result.error_code == "DATE_NOT_PROVIDED"


@pytest.mark.asyncio
async def test_pre_tool_call_rejects_unknown_stylist(booking_node: BookingModeNode):
    """check_availability with unknown stylist_name in args → rejected by stylist gate."""
    booking_node._mode_context = {"last_services": ["Cortar"]}
    result = await booking_node._pre_tool_call(
        "check_availability",
        {"service_names": ["Cortar"], "stylist_name": "Inventada", "date": "el martes"},
    )
    assert isinstance(result, ToolCallRejection)
    assert result.error_code == "STYLIST_NOT_RESOLVED"


@pytest.mark.asyncio
async def test_pre_tool_call_accepts_no_preference_phrase(booking_node: BookingModeNode):
    """check_availability with no-preference set in context → accepted."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "no_preference_stylist": True,
        "last_stylist": "Sin preferencia",
        "_date_question_asked": True,
    }
    result = await booking_node._pre_tool_call(
        "check_availability",
        {"service_names": ["Cortar"], "date": "el martes"},
    )
    assert not isinstance(result, ToolCallRejection)
    assert booking_node._mode_context.get("no_preference_stylist") is True


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
        "customer_name": "Ana García",
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
        "customer_name": "Ana García",
    }
    await booking_node._pre_tool_call(
        "book", {"slot_index": 1, "services": ["Cortar"], "notes": "Alergia al amoniaco"}
    )
    assert booking_node._mode_context["notes"] == "Alergia al amoniaco"
    assert booking_node._mode_context["notes_state"] in ("provided", "skipped")


@pytest.mark.asyncio
async def test_book_notes_no_clears_to_none(booking_node: BookingModeNode):
    """book() with notes='no' stores None (no notes)."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
        "selected_slot": {"time": "10:00", "stylist_id": "x", "start_time": "2026-04-20T10:00"},
        "offered_slots": [{"time": "10:00", "stylist_id": "x", "start_time": "2026-04-20T10:00"}],
        "customer_name": "Ana García",
    }
    await booking_node._pre_tool_call(
        "book", {"slot_index": 1, "services": ["Cortar"], "notes": "no"}
    )
    assert booking_node._mode_context["notes"] is None
    assert booking_node._mode_context["notes_state"] in ("provided", "skipped")


# ===========================================================================
# Gate 3 — date flag paths (REQ-G1)
# ===========================================================================


@pytest.mark.asyncio
async def test_gate3_rejects_date_without_flag(booking_node: BookingModeNode):
    """Date present but _date_question_asked=False → DATE_NOT_FROM_CLIENT guidance."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
    }
    result = await booking_node._pre_tool_call(
        "check_availability",
        {"service_names": ["Cortar"], "date": "sábado 19 de abril"},
    )
    assert isinstance(result, ToolCallRejection)
    assert result.error_code == "DATE_NOT_FROM_CLIENT"


@pytest.mark.asyncio
async def test_gate3_allows_date_with_flag(booking_node: BookingModeNode):
    """Date present + _date_question_asked=True → allowed."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
        "_date_question_asked": True,
    }
    result = await booking_node._pre_tool_call(
        "check_availability",
        {"service_names": ["Cortar"], "date": "el martes"},
    )
    assert not isinstance(result, ToolCallRejection)


@pytest.mark.asyncio
async def test_gate3_allows_shortcut_without_flag(booking_node: BookingModeNode):
    """Shortcut path (preferred_date_hint) bypasses flag check."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
        "preferred_date_hint": "viernes",
    }
    result = await booking_node._pre_tool_call(
        "check_availability",
        {"service_names": ["Cortar"], "date": "viernes"},
    )
    assert not isinstance(result, ToolCallRejection)


# ===========================================================================
# Surname guidance (REQ-G3)
# ===========================================================================


@pytest.mark.asyncio
async def test_single_name_accepted_in_book(booking_node: BookingModeNode):
    """book() accepts single-word name (surname validation moved to update_booking)."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
        "selected_slot": {"time": "10:00", "stylist_id": "x", "start_time": "2026-04-20T10:00"},
        "offered_slots": [{"time": "10:00", "stylist_id": "x", "start_time": "2026-04-20T10:00"}],
    }
    result = await booking_node._pre_tool_call(
        "book", {"slot_index": 1, "customer_first_name": "María", "customer_last_name": ""}
    )
    # Single-word name passes book() gate — update_booking handles surname enforcement
    assert booking_node._mode_context.get("customer_name") == "María"


@pytest.mark.asyncio
async def test_surname_present_multi_word(booking_node: BookingModeNode):
    """book() with first+last name → no rejection, name stored."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
        "selected_slot": {"time": "10:00", "stylist_id": "x", "start_time": "2026-04-20T10:00"},
        "offered_slots": [{"time": "10:00", "stylist_id": "x", "start_time": "2026-04-20T10:00"}],
    }
    result = await booking_node._pre_tool_call(
        "book", {"slot_index": 1, "customer_first_name": "María", "customer_last_name": "García"}
    )
    # Should pass surname check (may still fail at confirmation gate for missing notes, that's ok)
    if isinstance(result, ToolCallRejection):
        assert result.error_code != "SURNAME_MISSING"
    assert booking_node._mode_context.get("customer_name") == "María García"


@pytest.mark.asyncio
async def test_surname_compound_name_passes(booking_node: BookingModeNode):
    """book() with compound first name (has space) → passes surname check."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Marta",
        "selected_slot": {"time": "10:00", "stylist_id": "x", "start_time": "2026-04-20T10:00"},
        "offered_slots": [{"time": "10:00", "stylist_id": "x", "start_time": "2026-04-20T10:00"}],
    }
    result = await booking_node._pre_tool_call(
        "book", {"slot_index": 1, "customer_first_name": "María José", "customer_last_name": ""}
    )
    if isinstance(result, ToolCallRejection):
        assert result.error_code != "SURNAME_MISSING"
    assert booking_node._mode_context.get("customer_name") == "María José"

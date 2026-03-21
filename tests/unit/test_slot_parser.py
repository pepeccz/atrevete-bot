from unittest.mock import AsyncMock, patch
from typing import cast

import pytest

from agent.modes.booking_context import BookingSubstep
from agent.modes.booking_mode import BookingMode
from agent.state.schemas import ConversationState
from agent.state.schemas import create_initial_state


def make_slots() -> list[dict]:
    return [
        {"id": "slot-1", "date": "2026-03-26", "time": "10:00", "start_time": "2026-03-26T10:00:00+01:00"},
        {"id": "slot-2", "date": "2026-03-26", "time": "12:30", "start_time": "2026-03-26T12:30:00+01:00"},
        {"id": "slot-3", "date": "2026-03-26", "time": "16:00", "start_time": "2026-03-26T16:00:00+01:00"},
    ]


def make_slot_state(user_message: str) -> dict:
    state = create_initial_state("conv-slot-parser", "+34600000000")
    state["customer_name"] = "Ana"
    state["current_mode"] = "BOOKING"
    state["messages"] = [
        {"role": "user", "content": user_message, "timestamp": "2026-03-20T10:00:00"},
    ]
    state["mode_context"] = {
        "booking_step": BookingSubstep.SLOT_SELECTION.value,
        "service_id": "svc-1",
        "service_name": "Corte",
        "stylist_id": "550e8400-e29b-41d4-a716-446655440000",
        "stylist_name": "Pilar",
        "offered_slots": make_slots(),
    }
    return state


def test_numeric_slot_selection_resolves_first_slot():
    resolved = BookingMode._resolve_slot_from_message("1", make_slots())
    assert resolved is not None
    assert resolved["id"] == "slot-1"


def test_el_primero_resolves_first_slot():
    resolved = BookingMode._resolve_slot_from_message("el primero", make_slots())
    assert resolved is not None
    assert resolved["id"] == "slot-1"


def test_el_primero_disponible_resolves_first_slot():
    resolved = BookingMode._resolve_slot_from_message("el primero disponible", make_slots())
    assert resolved is not None
    assert resolved["id"] == "slot-1"


def test_el_segundo_resolves_second_slot():
    resolved = BookingMode._resolve_slot_from_message("el segundo", make_slots())
    assert resolved is not None
    assert resolved["id"] == "slot-2"


def test_la_segunda_opcion_resolves_second_slot():
    resolved = BookingMode._resolve_slot_from_message("la segunda opcion", make_slots())
    assert resolved is not None
    assert resolved["id"] == "slot-2"


def test_cualquiera_resolves_first_slot():
    resolved = BookingMode._resolve_slot_from_message("cualquiera", make_slots())
    assert resolved is not None
    assert resolved["id"] == "slot-1"


def test_confirmation_defaults_to_first_slot():
    resolved = BookingMode._resolve_slot_from_message("dale, ese esta bien", make_slots())
    assert resolved is not None
    assert resolved["id"] == "slot-1"


def test_time_reference_matches_slot_time():
    resolved = BookingMode._resolve_slot_from_message("el de las 10", make_slots())
    assert resolved is not None
    assert resolved["id"] == "slot-1"


def test_new_search_hint_does_not_resolve_existing_slot():
    assert BookingMode._resolve_slot_from_message("manana por la tarde", make_slots()) is None


def test_unknown_message_falls_through():
    assert BookingMode._resolve_slot_from_message("", make_slots()) is None
    assert BookingMode._resolve_slot_from_message("ni idea", make_slots()) is None


@pytest.mark.asyncio
async def test_handle_slot_selection_resolves_without_llm_tool_call():
    mode = BookingMode(tools=[])
    state = cast(ConversationState, make_slot_state("el primero disponible"))
    mode_context = dict(state.get("mode_context") or {})

    with patch.object(mode, "_run_agentic_loop", new=AsyncMock()) as mock_loop:
        result = await mode._handle_slot_selection(state, mode_context)

    mock_loop.assert_not_awaited()
    assert result["mode_context"]["booking_step"] == BookingSubstep.NOTES.value
    assert result["mode_context"]["selected_slot"]["id"] == "slot-1"

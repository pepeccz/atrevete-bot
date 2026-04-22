"""Tests for escape_gate node — Phase 5.6."""

from __future__ import annotations

import pytest
from langgraph.constants import END
from langgraph.types import Command


def _state(escape_intent, booking_extra=None):
    booking = {
        "step": "date",
        "service_ids": [],
        "audience": "adult_female",
        "date": "2026-05-10",
        "offered_slots": None,
        "selected_slot": None,
        "_escape_intent": escape_intent,
    }
    if booking_extra:
        booking.update(booking_extra)
    return {
        "booking": booking,
        "messages": [],
        "current_mode": "BOOKING",
        "user_message": "cancelar",
        "conversation_id": "conv-1",
        "customer_phone": "+34600000000",
        "pending_whatsapp_name": None,
        "customer_id": None,
        "customer_name": None,
    }


@pytest.mark.asyncio
async def test_cancel_goes_to_end():
    from agent.booking.escape_gate import escape_gate

    result = await escape_gate(_state("cancel"))

    assert isinstance(result, Command)
    assert result.goto == END
    assert result.update["current_mode"] == "GENERAL"
    assert result.update["booking"] is None
    # Must include a cancellation message
    msgs = result.update.get("messages", [])
    assert any("cancel" in m.content.lower() or "cita" in m.content.lower() for m in msgs)


@pytest.mark.asyncio
async def test_start_over_resets_to_service_step():
    from agent.booking.escape_gate import escape_gate

    result = await escape_gate(_state("start_over"))

    assert isinstance(result, Command)
    assert result.goto == "route_next"
    assert result.update["booking"]["step"] == "service"


@pytest.mark.asyncio
async def test_change_date_resets_date_and_slots():
    from agent.booking.escape_gate import escape_gate

    result = await escape_gate(_state("change_date"))

    assert isinstance(result, Command)
    assert result.goto == "route_next"
    b = result.update["booking"]
    assert b["date"] is None
    assert b["offered_slots"] is None
    assert b["selected_slot"] is None
    assert b["step"] == "date"
    # Service and audience preserved
    assert b["service_ids"] == []
    assert b["audience"] == "adult_female"


@pytest.mark.asyncio
async def test_change_service_resets_to_service_step():
    from agent.booking.escape_gate import escape_gate

    result = await escape_gate(_state("change_service"))

    assert isinstance(result, Command)
    assert result.goto == "route_next"
    assert result.update["booking"]["step"] == "service"


@pytest.mark.asyncio
async def test_change_stylist_clears_stylist_keeps_rest():
    from agent.booking.escape_gate import escape_gate

    state = _state("change_stylist", {"stylist_id": "some-uuid", "step": "name"})
    result = await escape_gate(state)

    assert isinstance(result, Command)
    assert result.goto == "route_next"
    b = result.update["booking"]
    assert b["stylist_id"] is None
    assert b["step"] == "stylist"
    # Other fields preserved
    assert b["audience"] == "adult_female"


@pytest.mark.asyncio
async def test_no_escape_intent_passes_through():
    from agent.booking.escape_gate import escape_gate

    result = await escape_gate(_state(None))

    assert isinstance(result, Command)
    assert result.goto == "route_next"
    # update must be empty or not change booking
    assert result.update == {}

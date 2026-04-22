"""Tests for await_confirmation node — Phase 5.9."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langgraph.types import Command


def _state(booking_extra=None):
    booking = {
        "step": "confirm",
        "service_ids": [],
        "audience": "adult_female",
        "stylist_id": None,
        "no_preference": True,
        "date": "2026-05-10",
        "offered_slots": [{"start": "10:00"}],
        "selected_slot": {"start": "10:00", "end": "10:30", "stylist": "Marta"},
        "customer_full_name": "Ana García",
        "notes": None,
        "_escape_intent": None,
    }
    if booking_extra:
        booking.update(booking_extra)
    return {
        "booking": booking,
        "messages": [],
        "conversation_id": "conv-1",
        "customer_phone": "+34600000000",
        "current_mode": "BOOKING",
        "pending_whatsapp_name": None,
        "customer_id": None,
        "customer_name": None,
        "user_message": "",
    }


@pytest.mark.asyncio
async def test_first_invocation_emits_summary_then_raises_interrupt():
    """On first call (no resume value), node should emit summary and call interrupt()."""
    from agent.booking.await_confirmation import await_confirmation

    interrupt_values = []

    def fake_interrupt(val):
        interrupt_values.append(val)
        raise Exception("GraphInterrupt")  # simulate LangGraph behavior

    with patch("agent.booking.await_confirmation.interrupt", side_effect=fake_interrupt):
        with pytest.raises(Exception, match="GraphInterrupt"):
            await await_confirmation(_state())

    assert len(interrupt_values) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("user_text", ["sí", "si", "yes", "dale", "confirmo"])
async def test_resume_with_affirmative_goes_to_execute_book(user_text):
    from agent.booking.await_confirmation import await_confirmation

    interrupt_resume_values = []

    def fake_interrupt(val):
        # On first call during resume, return the user text
        interrupt_resume_values.append(val)
        return user_text

    with patch("agent.booking.await_confirmation.interrupt", side_effect=fake_interrupt):
        result = await await_confirmation(_state())

    assert isinstance(result, Command)
    assert result.goto == "execute_book"


@pytest.mark.asyncio
@pytest.mark.parametrize("user_text", ["no", "cancel", "no quiero"])
async def test_resume_with_negative_reopens_slot(user_text):
    from agent.booking.await_confirmation import await_confirmation

    def fake_interrupt(val):
        return user_text

    with patch("agent.booking.await_confirmation.interrupt", side_effect=fake_interrupt):
        result = await await_confirmation(_state())

    assert isinstance(result, Command)
    assert result.goto == "route_next"
    assert result.update["booking"]["step"] == "slot"
    assert result.update["booking"].get("offered_slots") is None


@pytest.mark.asyncio
async def test_summary_message_contains_booking_details():
    """The AIMessage emitted before interrupt should mention key booking details."""
    from agent.booking.await_confirmation import await_confirmation

    emitted_messages = []

    def fake_interrupt(val):
        return "sí"

    # Capture messages returned in update
    with patch("agent.booking.await_confirmation.interrupt", side_effect=fake_interrupt):
        result = await await_confirmation(_state())

    # Summary message should be in the update
    if "messages" in result.update:
        for m in result.update["messages"]:
            if isinstance(m, AIMessage):
                emitted_messages.append(m.content)

    # At least one message should mention date or customer name
    combined = " ".join(emitted_messages).lower()
    assert "2026" in combined or "ana" in combined or "turno" in combined or "reserva" in combined

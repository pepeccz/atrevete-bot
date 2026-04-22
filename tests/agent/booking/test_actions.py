"""Tests for fetch_availability_node and execute_book_node — Phase 5.7."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from langgraph.constants import END
from langgraph.types import Command


def _make_state(step="date", offered_slots=None, extra_booking=None):
    booking = {
        "step": step,
        "service_ids": [str(uuid4())],
        "audience": "adult_female",
        "stylist_id": str(uuid4()),
        "date": "2026-05-10",
        "offered_slots": offered_slots,
        "selected_slot": None,
        "customer_full_name": "Ana García",
        "_escape_intent": None,
    }
    if extra_booking:
        booking.update(extra_booking)
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


# --- fetch_availability_node ---


@pytest.mark.asyncio
async def test_fetch_availability_ok_updates_slots():
    from agent.booking.actions import fetch_availability_node
    from agent.tools.schemas import ToolResponse

    slots = [{"start": "10:00", "end": "10:30", "stylist": "Marta"}]
    response = ToolResponse(status="ok", payload={"slots": slots}, next_step="slot")

    mock_tool = AsyncMock(return_value=json.dumps(response.model_dump()))

    with patch("agent.booking.actions.check_availability_tool", mock_tool):
        result = await fetch_availability_node(_make_state())

    assert isinstance(result, Command)
    assert result.goto == "ask_slot"
    assert result.update["booking"]["offered_slots"] == slots
    assert result.update["booking"]["step"] == "slot"


@pytest.mark.asyncio
async def test_fetch_availability_rejected_reopens_date():
    from agent.booking.actions import fetch_availability_node
    from agent.tools.schemas import ToolResponse

    response = ToolResponse(
        status="rejected",
        errors=["Sin disponibilidad para esa fecha"],
        next_step="date",
    )

    mock_tool = AsyncMock(return_value=json.dumps(response.model_dump()))

    with patch("agent.booking.actions.check_availability_tool", mock_tool):
        result = await fetch_availability_node(_make_state())

    assert isinstance(result, Command)
    assert result.goto == END
    assert result.update["booking"]["step"] == "date"
    # Should emit a message explaining the rejection
    msgs = result.update.get("messages", [])
    assert len(msgs) > 0


@pytest.mark.asyncio
async def test_fetch_availability_partial_treated_as_ok():
    """Status 'partial' with slots should still advance to slot step."""
    from agent.booking.actions import fetch_availability_node
    from agent.tools.schemas import ToolResponse

    slots = [{"start": "14:00", "end": "15:00", "stylist": "Pilar"}]
    response = ToolResponse(status="partial", payload={"slots": slots}, next_step="slot")

    mock_tool = AsyncMock(return_value=json.dumps(response.model_dump()))

    with patch("agent.booking.actions.check_availability_tool", mock_tool):
        result = await fetch_availability_node(_make_state())

    assert result.update["booking"]["step"] == "slot"


# --- execute_book_node ---


@pytest.mark.asyncio
async def test_execute_book_ok_marks_done():
    from agent.booking.actions import execute_book_node
    from agent.tools.schemas import ToolResponse

    appt_id = str(uuid4())
    response = ToolResponse(
        status="ok",
        payload={"appointment_id": appt_id},
        next_step="done",
    )

    mock_tool = AsyncMock(return_value=json.dumps(response.model_dump()))
    state = _make_state(
        step="confirm",
        extra_booking={
            "selected_slot": {"start": "10:00", "end": "10:30", "stylist_id": str(uuid4())}
        },
    )

    with patch("agent.booking.actions.book_tool", mock_tool):
        result = await execute_book_node(state)

    assert isinstance(result, Command)
    assert result.goto == END
    assert result.update["booking"]["step"] == "done"
    assert result.update["booking"].get("appointment_id") == appt_id


@pytest.mark.asyncio
async def test_execute_book_rejected_reopens_slot():
    from agent.booking.actions import execute_book_node
    from agent.tools.schemas import ToolResponse

    response = ToolResponse(
        status="rejected",
        errors=["Ese turno ya fue tomado"],
        next_step="slot",
    )

    mock_tool = AsyncMock(return_value=json.dumps(response.model_dump()))
    state = _make_state(
        step="confirm",
        extra_booking={
            "selected_slot": {"start": "10:00", "end": "10:30", "stylist_id": str(uuid4())},
            "offered_slots": None,
        },
    )

    with patch("agent.booking.actions.book_tool", mock_tool):
        result = await execute_book_node(state)

    assert isinstance(result, Command)
    assert result.goto == END
    assert result.update["booking"]["step"] == "slot"
    msgs = result.update.get("messages", [])
    assert len(msgs) > 0

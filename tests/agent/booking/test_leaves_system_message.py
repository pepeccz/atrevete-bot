"""Tests for SystemMessage injection in booking leaves — Task 3.1 (booking-prompts-audit-fix).

Spec:
- Every leaf must call build_leaf_system_message(step, booking, state).
- The first message passed to ainvoke must be a SystemMessage.
- ask_service must NOT write booking["audience"] under any circumstance.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.constants import END

from agent.booking.schemas import (
    AudienceResponse,
    DateResponse,
    NameResponse,
    NotesResponse,
    ServiceSelectionResponse,
    SlotResponse,
    StylistResponse,
)

_MOCK_SYSTEM_MSG = SystemMessage(content="mock system message from builder")


def _base_state(step: str, booking_extra: dict | None = None):
    booking = {
        "step": step,
        "service_ids": [],
        "audience": None,
        "stylist_id": None,
        "no_preference": False,
        "date": None,
        "offered_slots": None,
        "selected_slot": None,
        "customer_full_name": None,
        "notes": None,
        "_escape_intent": None,
        "_notes_asked": False,
    }
    if booking_extra:
        booking.update(booking_extra)
    return {
        "booking": booking,
        "messages": [HumanMessage(content="hola")],
        "conversation_id": "conv-1",
        "customer_phone": "+34600000000",
        "current_mode": "BOOKING",
        "pending_whatsapp_name": None,
        "customer_id": None,
        "customer_name": None,
        "user_message": "hola",
    }


def _mock_llm(response_obj):
    captured_messages = []

    async def ainvoke(messages):
        captured_messages.extend(messages)
        return response_obj

    structured = MagicMock()
    structured.ainvoke = ainvoke
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)
    llm._captured = captured_messages
    return llm


# --- ask_service: SystemMessage injected as first message ---


@pytest.mark.asyncio
async def test_ask_service_prepends_system_message():
    from agent.booking.leaves import ask_service

    uid = uuid4()
    resp = ServiceSelectionResponse(
        message="¿Qué servicio?", needs_clarification=False, selected_service_ids=[uid]
    )
    llm = _mock_llm(resp)
    state = _base_state("service")

    with (
        patch("agent.booking.leaves.get_llm", return_value=llm),
        patch(
            "agent.booking.prompt_builder.build_leaf_system_message",
            new=AsyncMock(return_value=_MOCK_SYSTEM_MSG),
        ),
    ):
        await ask_service(state)

    assert len(llm._captured) >= 1
    assert isinstance(llm._captured[0], SystemMessage)


@pytest.mark.asyncio
async def test_ask_service_never_sets_audience():
    """ask_service must never write booking['audience'] — no collapse allowed."""
    from agent.booking.leaves import ask_service

    uid = uuid4()
    # Even if the LLM somehow returns something that had audience, it must not be written
    resp = ServiceSelectionResponse(
        message="Servicio seleccionado", needs_clarification=False, selected_service_ids=[uid]
    )
    llm = _mock_llm(resp)
    state = _base_state("service")

    with (
        patch("agent.booking.leaves.get_llm", return_value=llm),
        patch(
            "agent.booking.prompt_builder.build_leaf_system_message",
            new=AsyncMock(return_value=_MOCK_SYSTEM_MSG),
        ),
    ):
        result = await ask_service(state)

    assert result.update["booking"].get("audience") is None


# --- ask_audience: SystemMessage injected ---


@pytest.mark.asyncio
async def test_ask_audience_prepends_system_message():
    from agent.booking.leaves import ask_audience

    resp = AudienceResponse(message="¿Para quién?", inferred_audience="adult_female")
    llm = _mock_llm(resp)
    state = _base_state("audience")

    with (
        patch("agent.booking.leaves.get_llm", return_value=llm),
        patch(
            "agent.booking.prompt_builder.build_leaf_system_message",
            new=AsyncMock(return_value=_MOCK_SYSTEM_MSG),
        ),
    ):
        await ask_audience(state)

    assert isinstance(llm._captured[0], SystemMessage)


# --- ask_stylist ---


@pytest.mark.asyncio
async def test_ask_stylist_prepends_system_message():
    from agent.booking.leaves import ask_stylist

    resp = StylistResponse(message="¿Con quién?", no_preference=True)
    llm = _mock_llm(resp)
    state = _base_state("stylist")

    with (
        patch("agent.booking.leaves.get_llm", return_value=llm),
        patch(
            "agent.booking.prompt_builder.build_leaf_system_message",
            new=AsyncMock(return_value=_MOCK_SYSTEM_MSG),
        ),
    ):
        await ask_stylist(state)

    assert isinstance(llm._captured[0], SystemMessage)


# --- ask_date ---


@pytest.mark.asyncio
async def test_ask_date_prepends_system_message():
    from agent.booking.leaves import ask_date
    from datetime import date

    resp = DateResponse(message="¿Qué fecha?", inferred_date=date(2026, 6, 1))
    llm = _mock_llm(resp)
    state = _base_state("date")

    with (
        patch("agent.booking.leaves.get_llm", return_value=llm),
        patch(
            "agent.booking.prompt_builder.build_leaf_system_message",
            new=AsyncMock(return_value=_MOCK_SYSTEM_MSG),
        ),
    ):
        await ask_date(state)

    assert isinstance(llm._captured[0], SystemMessage)


# --- ask_slot ---


@pytest.mark.asyncio
async def test_ask_slot_prepends_system_message():
    from agent.booking.leaves import ask_slot

    slots = [{"start": "10:00"}]
    resp = SlotResponse(message="¿Cuál turno?", selected_slot_index=0)
    llm = _mock_llm(resp)
    state = _base_state("slot", {"offered_slots": slots})

    with (
        patch("agent.booking.leaves.get_llm", return_value=llm),
        patch(
            "agent.booking.prompt_builder.build_leaf_system_message",
            new=AsyncMock(return_value=_MOCK_SYSTEM_MSG),
        ),
    ):
        await ask_slot(state)

    assert isinstance(llm._captured[0], SystemMessage)


# --- ask_name ---


@pytest.mark.asyncio
async def test_ask_name_prepends_system_message():
    from agent.booking.leaves import ask_name

    resp = NameResponse(message="¿Tu nombre?", first_name="Ana", first_surname="García")
    llm = _mock_llm(resp)
    state = _base_state("name")

    with (
        patch("agent.booking.leaves.get_llm", return_value=llm),
        patch(
            "agent.booking.prompt_builder.build_leaf_system_message",
            new=AsyncMock(return_value=_MOCK_SYSTEM_MSG),
        ),
    ):
        await ask_name(state)

    assert isinstance(llm._captured[0], SystemMessage)


# --- ask_notes ---


@pytest.mark.asyncio
async def test_ask_notes_prepends_system_message():
    from agent.booking.leaves import ask_notes

    resp = NotesResponse(message="¿Alguna nota?", user_declined=True)
    llm = _mock_llm(resp)
    state = _base_state("notes")

    with (
        patch("agent.booking.leaves.get_llm", return_value=llm),
        patch(
            "agent.booking.prompt_builder.build_leaf_system_message",
            new=AsyncMock(return_value=_MOCK_SYSTEM_MSG),
        ),
    ):
        await ask_notes(state)

    assert isinstance(llm._captured[0], SystemMessage)

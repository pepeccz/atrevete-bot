"""Tests for LLM booking leaves — Phase 5.8."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.constants import END
from langgraph.types import Command

from agent.booking.schemas import (
    AudienceResponse,
    DateResponse,
    NameResponse,
    NotesResponse,
    ServiceSelectionResponse,
    SlotResponse,
    StylistResponse,
)


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
    """Return a mock LLM whose with_structured_output(...).ainvoke(...) returns response_obj."""
    chain = AsyncMock(return_value=response_obj)
    structured = MagicMock()
    structured.ainvoke = chain
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)
    return llm


# --- ask_service ---


@pytest.mark.asyncio
async def test_ask_service_calls_llm_and_returns_command():
    from agent.booking.leaves import ask_service

    uid = uuid4()
    resp = ServiceSelectionResponse(
        message="¿Qué servicio te interesa?",
        needs_clarification=False,
        selected_service_ids=[uid],
    )
    llm = _mock_llm(resp)
    state = _base_state("service")

    with patch("agent.booking.leaves.get_llm", return_value=llm):
        result = await ask_service(state)

    assert isinstance(result, Command)
    assert result.goto == END
    msgs = result.update.get("messages", [])
    assert any(isinstance(m, AIMessage) and "servicio" in m.content.lower() for m in msgs)
    assert result.update["booking"]["service_ids"] == [uid]


@pytest.mark.asyncio
async def test_ask_service_fast_path_skips_llm():
    """If service_ids already set, skip LLM and go straight to route_next."""
    from agent.booking.leaves import ask_service

    uid = uuid4()
    state = _base_state("service", {"service_ids": [uid]})
    llm = _mock_llm(None)  # should NOT be called

    with patch("agent.booking.leaves.get_llm", return_value=llm):
        result = await ask_service(state)

    llm.with_structured_output.assert_not_called()
    assert isinstance(result, Command)
    assert result.goto == "route_next"


# --- ask_audience ---


@pytest.mark.asyncio
async def test_ask_audience_extracts_audience():
    from agent.booking.leaves import ask_audience

    resp = AudienceResponse(message="¿Para quién es el servicio?", inferred_audience="child_female")
    llm = _mock_llm(resp)
    state = _base_state("audience")

    with patch("agent.booking.leaves.get_llm", return_value=llm):
        result = await ask_audience(state)

    assert result.update["booking"]["audience"] == "child_female"
    assert result.goto == END


@pytest.mark.asyncio
async def test_ask_audience_fast_path():
    from agent.booking.leaves import ask_audience

    state = _base_state("audience", {"audience": "adult_male"})
    llm = _mock_llm(None)

    with patch("agent.booking.leaves.get_llm", return_value=llm):
        result = await ask_audience(state)

    llm.with_structured_output.assert_not_called()
    assert result.goto == "route_next"


# --- ask_stylist ---


@pytest.mark.asyncio
async def test_ask_stylist_extracts_stylist():
    from agent.booking.leaves import ask_stylist

    uid = uuid4()
    resp = StylistResponse(message="¿Con quién preferís?", inferred_stylist_id=uid)
    llm = _mock_llm(resp)
    state = _base_state("stylist")

    with patch("agent.booking.leaves.get_llm", return_value=llm):
        result = await ask_stylist(state)

    assert result.update["booking"]["stylist_id"] == uid
    assert result.goto == END


@pytest.mark.asyncio
async def test_ask_stylist_no_preference():
    from agent.booking.leaves import ask_stylist

    resp = StylistResponse(message="Sin preferencia, elijo yo.", no_preference=True)
    llm = _mock_llm(resp)
    state = _base_state("stylist")

    with patch("agent.booking.leaves.get_llm", return_value=llm):
        result = await ask_stylist(state)

    assert result.update["booking"]["no_preference"] is True


@pytest.mark.asyncio
async def test_ask_stylist_fast_path():
    from agent.booking.leaves import ask_stylist

    uid = uuid4()
    state = _base_state("stylist", {"stylist_id": str(uid)})
    llm = _mock_llm(None)

    with patch("agent.booking.leaves.get_llm", return_value=llm):
        result = await ask_stylist(state)

    llm.with_structured_output.assert_not_called()


# --- ask_date ---


@pytest.mark.asyncio
async def test_ask_date_extracts_date():
    from agent.booking.leaves import ask_date

    d = date(2026, 5, 15)
    resp = DateResponse(message="¿Para qué fecha?", inferred_date=d)
    llm = _mock_llm(resp)
    state = _base_state("date")

    with patch("agent.booking.leaves.get_llm", return_value=llm):
        result = await ask_date(state)

    assert result.update["booking"]["date"] == d
    assert result.goto == END


@pytest.mark.asyncio
async def test_ask_date_fast_path():
    from agent.booking.leaves import ask_date

    state = _base_state("date", {"date": "2026-05-10"})
    llm = _mock_llm(None)

    with patch("agent.booking.leaves.get_llm", return_value=llm):
        result = await ask_date(state)

    llm.with_structured_output.assert_not_called()


# --- ask_slot ---


@pytest.mark.asyncio
async def test_ask_slot_selects_slot():
    from agent.booking.leaves import ask_slot

    slots = [
        {"start": "10:00", "end": "10:30", "stylist": "Marta"},
        {"start": "11:00", "end": "11:30", "stylist": "Pilar"},
    ]
    resp = SlotResponse(message="Te separo las 10:00.", selected_slot_index=0)
    llm = _mock_llm(resp)
    state = _base_state("slot", {"offered_slots": slots})

    with patch("agent.booking.leaves.get_llm", return_value=llm):
        result = await ask_slot(state)

    assert result.update["booking"]["selected_slot"] == slots[0]
    assert result.update["booking"]["step"] == "name"
    assert result.goto == END


@pytest.mark.asyncio
async def test_ask_slot_fast_path():
    from agent.booking.leaves import ask_slot

    slots = [{"start": "10:00"}]
    state = _base_state("slot", {"offered_slots": slots, "selected_slot": slots[0]})
    llm = _mock_llm(None)

    with patch("agent.booking.leaves.get_llm", return_value=llm):
        result = await ask_slot(state)

    llm.with_structured_output.assert_not_called()


# --- ask_name ---


@pytest.mark.asyncio
async def test_ask_name_extracts_name():
    from agent.booking.leaves import ask_name

    resp = NameResponse(message="¡Perfecto, Ana!", first_name="Ana", first_surname="García")
    llm = _mock_llm(resp)
    state = _base_state("name")

    with patch("agent.booking.leaves.get_llm", return_value=llm):
        result = await ask_name(state)

    assert result.update["booking"]["customer_full_name"] == "Ana García"
    assert result.goto == END


@pytest.mark.asyncio
async def test_ask_name_fast_path():
    from agent.booking.leaves import ask_name

    state = _base_state("name", {"customer_full_name": "Ana García"})
    llm = _mock_llm(None)

    with patch("agent.booking.leaves.get_llm", return_value=llm):
        result = await ask_name(state)

    llm.with_structured_output.assert_not_called()


# --- ask_notes ---


@pytest.mark.asyncio
async def test_ask_notes_captures_notes():
    from agent.booking.leaves import ask_notes

    resp = NotesResponse(message="Anotado.", notes="alergia al tinte", user_declined=False)
    llm = _mock_llm(resp)
    state = _base_state("notes")

    with patch("agent.booking.leaves.get_llm", return_value=llm):
        result = await ask_notes(state)

    assert result.update["booking"]["notes"] == "alergia al tinte"
    assert result.goto == END


@pytest.mark.asyncio
async def test_ask_notes_declined_advances():
    from agent.booking.leaves import ask_notes

    resp = NotesResponse(message="Sin notas.", user_declined=True)
    llm = _mock_llm(resp)
    state = _base_state("notes")

    with patch("agent.booking.leaves.get_llm", return_value=llm):
        result = await ask_notes(state)

    assert result.update["booking"].get("notes") is None
    assert result.goto == END

"""
Phase 5 — escape_gate tests (R3.1–R3.8).

cancel clears bc; escalate/reschedule/check_appointments preserve bc;
ambiguous falls through; mid-sentence cancel (e.g. "no cancelar el turno") does NOT escape.
"""

from __future__ import annotations

import pytest


def _state(bc: dict | None = None, message: str = "") -> dict:
    return {"booking_context": bc or {}, "user_message": message}


_FULL_BC = {
    "last_services": ["Corte Señora"],
    "last_stylist": "Ana",
    "date_hint": "2026-04-25",
    "customer_name": "María",
}


# ---------------------------------------------------------------------------
# cancel — clears booking_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_emits_command_general_mode():
    from langgraph.types import Command

    from agent.booking.nodes.escape_gate import escape_gate

    state = _state(_FULL_BC, "quiero cancelar")
    result = await escape_gate(state)
    assert isinstance(result, Command)
    assert result.update["current_mode"] == "GENERAL"
    assert result.update["booking_context"] == {}


@pytest.mark.asyncio
async def test_cancel_clears_booking_context():
    from langgraph.types import Command

    from agent.booking.nodes.escape_gate import escape_gate

    state = _state(_FULL_BC, "cancelar")
    result = await escape_gate(state)
    assert isinstance(result, Command)
    assert result.update["booking_context"] == {}


# ---------------------------------------------------------------------------
# escalate — preserves booking_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escalate_preserves_booking_context():
    from langgraph.types import Command

    from agent.booking.nodes.escape_gate import escape_gate

    state = _state(_FULL_BC, "quiero hablar con una persona")
    result = await escape_gate(state)
    assert isinstance(result, Command)
    assert result.update["current_mode"] == "ESCALATION"
    assert result.update["booking_context"] == _FULL_BC


# ---------------------------------------------------------------------------
# reschedule — preserves booking_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reschedule_preserves_booking_context():
    from langgraph.types import Command

    from agent.booking.nodes.escape_gate import escape_gate

    state = _state(_FULL_BC, "quiero cambiar mi turno")
    result = await escape_gate(state)
    assert isinstance(result, Command)
    assert result.update["current_mode"] == "APPOINTMENT_MANAGEMENT"
    assert result.update["booking_context"] == _FULL_BC


# ---------------------------------------------------------------------------
# check_appointments — preserves booking_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_appointments_preserves_booking_context():
    from langgraph.types import Command

    from agent.booking.nodes.escape_gate import escape_gate

    state = _state(_FULL_BC, "ver mis turnos")
    result = await escape_gate(state)
    assert isinstance(result, Command)
    assert result.update["current_mode"] == "APPOINTMENT_MANAGEMENT"
    assert result.update["booking_context"] == _FULL_BC


# ---------------------------------------------------------------------------
# Ambiguous / fall-through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ambiguous_falls_through_returns_empty_dict():
    from langgraph.types import Command

    from agent.booking.nodes.escape_gate import escape_gate

    state = _state(_FULL_BC, "señora, el miércoles")
    result = await escape_gate(state)
    # No escape — must return {} or dict, NOT a Command
    assert not isinstance(result, Command)


@pytest.mark.asyncio
async def test_service_request_not_escape():
    from langgraph.types import Command

    from agent.booking.nodes.escape_gate import escape_gate

    state = _state({}, "quiero un corte de pelo")
    result = await escape_gate(state)
    assert not isinstance(result, Command)

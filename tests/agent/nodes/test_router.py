"""Tests for agent/nodes/router.py — Task 6.1."""

from __future__ import annotations

import pytest
from langgraph.types import Command


@pytest.fixture
def base_state():
    return {
        "conversation_id": "conv-1",
        "customer_phone": "+5491100000000",
        "user_message": "",
        "pending_whatsapp_name": None,
        "current_mode": "GENERAL",
        "messages": [],
        "booking": None,
        "customer_id": None,
        "customer_name": None,
    }


# ---------------------------------------------------------------------------
# Import guard (RED before module exists)
# ---------------------------------------------------------------------------


def _import_router():
    from agent.nodes.router import router_node

    return router_node


# ---------------------------------------------------------------------------
# Booking keyword detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "quiero reservar una cita",
        "quiero sacar turno",
        "quiero agendar",
        "necesito cortarme el pelo",
        "me gustaría tintarme",
        "quiero mechas",
        "quiero hacerme la manicura",
        "pedicura por favor",
        "quiero un masaje",
        "quiero maquillaje para el sábado",
        "me quiero hacer un peinado",
        "quiero cortar mi cabello",
        "Quiero RESERVAR",  # case insensitive
        "quiero sacar una CITA",
        "agendar turno",
    ],
)
def test_booking_keywords_route_to_booking(base_state, text):
    router_node = _import_router()
    state = {**base_state, "user_message": text}
    result = router_node(state)
    assert isinstance(result, Command)
    assert result.goto == "booking"
    assert result.update.get("current_mode") == "BOOKING"


@pytest.mark.parametrize(
    "text",
    [
        "qué horarios tienen?",
        "cuánto cuesta un corte?",
        "hola buenas",
        "tienen estacionamiento?",
        "cómo llego?",
        "gracias",
    ],
)
def test_general_keywords_route_to_general(base_state, text):
    router_node = _import_router()
    state = {**base_state, "user_message": text}
    result = router_node(state)
    assert isinstance(result, Command)
    assert result.goto == "general"
    assert result.update.get("current_mode") == "GENERAL"


# ---------------------------------------------------------------------------
# Sticky mode: if booking flow is active, keep in booking regardless of text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "step",
    ["service", "audience", "stylist", "date", "slot", "name", "notes", "confirm"],
)
def test_sticky_booking_mode(base_state, step):
    """If booking dict has active step, keep routing to booking."""
    router_node = _import_router()
    state = {
        **base_state,
        "user_message": "mañana a las 5",  # no booking keyword
        "current_mode": "BOOKING",
        "booking": {"step": step},
    }
    result = router_node(state)
    assert isinstance(result, Command)
    assert result.goto == "booking"
    assert result.update.get("current_mode") == "BOOKING"


def test_sticky_mode_done_step_routes_normally(base_state):
    """booking.step == 'done' → no longer sticky; pure keyword classification."""
    router_node = _import_router()
    state = {
        **base_state,
        "user_message": "gracias, chau",
        "current_mode": "BOOKING",
        "booking": {"step": "done"},
    }
    result = router_node(state)
    assert isinstance(result, Command)
    # no booking keyword → general
    assert result.goto == "general"


def test_booking_none_and_no_keyword_routes_to_general(base_state):
    """No active booking, no keyword → GENERAL."""
    router_node = _import_router()
    state = {**base_state, "user_message": "qué servicios ofrecen?"}
    result = router_node(state)
    assert result.goto == "general"


# ---------------------------------------------------------------------------
# Accent / unicode insensitivity
# ---------------------------------------------------------------------------


def test_accent_insensitive_reservar(base_state):
    router_node = _import_router()
    state = {**base_state, "user_message": "quisiera réservar"}
    result = router_node(state)
    assert result.goto == "booking"


def test_accent_insensitive_manicura(base_state):
    router_node = _import_router()
    state = {**base_state, "user_message": "quiero mánicura"}
    result = router_node(state)
    assert result.goto == "booking"

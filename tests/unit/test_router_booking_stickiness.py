"""
Unit tests for Phase 2 — Router Stickiness (booking-flow-resilience).

Tests the expanded _is_booking_related_query, _wants_to_exit_booking,
booking inertia guard in Rule 6, and GREETING re-entry prevention.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.graphs.conversation_flow import (
    _is_booking_related_query,
    _wants_to_exit_booking,
)
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


# ============================================================================
# Helpers
# ============================================================================


def _make_state(
    current_mode: str = "GENERAL",
    customer_name: str | None = "Ana",
    is_first_interaction: bool = False,
    error_count: int = 0,
    user_message: str = "Hola",
    mode_context: dict | None = None,
) -> dict:
    """Build a minimal ConversationState for router_node tests."""
    state = create_initial_state("conv-sticky-001", "+34600000001")
    state["current_mode"] = current_mode
    state["customer_name"] = customer_name
    state["is_first_interaction"] = is_first_interaction
    state["error_count"] = error_count
    state["escalation_triggered"] = False
    state["messages"] = [
        {"role": "user", "content": user_message, "timestamp": "2026-01-01T00:00:00"}
    ]
    state["user_message"] = user_message
    if mode_context:
        state["mode_context"] = mode_context
    return state


def _make_mock_router(intent: str, confidence: float = 0.9) -> MagicMock:
    """Create a mock IntentRouter that returns the given intent."""
    mock = MagicMock()
    mock.classify = AsyncMock(
        return_value=IntentResult(
            intent=intent,
            confidence=confidence,
            raw_input="",
            mode_hint=None,
        )
    )
    return mock


# ============================================================================
# T-2.1: _is_booking_related_query — expanded terms
# ============================================================================


class TestBookingRelatedQuery:
    """Tests for expanded _is_booking_related_query terms."""

    @pytest.mark.parametrize(
        "message",
        [
            "el jueves puedo",
            "¿hay algo el miércoles?",
            "quiero cancelar",
            "otra vez por favor",
            "prefiero por la tarde",
            "da igual la hora",
            "¿cuántas opciones hay?",
            "tiene hueco mañana",
            "lunes me viene bien",
            "quiero reservar a las 10",
            "confirmar la cita",
            "¿cuáles son los horarios?",
            "la próxima semana",
        ],
    )
    def test_recognizes_new_booking_terms(self, message: str):
        """Expanded terms from T-2.1 are recognized as booking-related."""
        assert _is_booking_related_query(message) is True

    @pytest.mark.parametrize(
        "message",
        [
            "¿dónde están ubicados?",
            "¿aceptan tarjeta?",
            "quiero hablar con alguien",
            "¿cómo llego al salón?",
        ],
    )
    def test_non_booking_queries_not_matched(self, message: str):
        """Non-booking queries still return False."""
        assert _is_booking_related_query(message) is False

    def test_empty_message_returns_false(self):
        assert _is_booking_related_query("") is False

    def test_none_message_returns_false(self):
        assert _is_booking_related_query(None) is False


# ============================================================================
# T-2.2: _wants_to_exit_booking
# ============================================================================


class TestWantsToExitBooking:
    """Tests for the booking exit phrase detection."""

    @pytest.mark.parametrize(
        "message",
        [
            "salir",
            "otra cosa quiero",
            "dejalo",
            "dejémoslo así",
            "no quiero reservar",
            "olvidalo",
        ],
    )
    def test_exit_phrases_detected(self, message: str):
        """Exit phrases trigger booking exit."""
        assert _wants_to_exit_booking(message) is True

    @pytest.mark.parametrize(
        "message",
        [
            "quiero reservar",
            "el jueves",
            "sí, confirmo",
            "otra vez por favor",
        ],
    )
    def test_non_exit_messages_not_detected(self, message: str):
        """Normal booking messages do not trigger exit."""
        assert _wants_to_exit_booking(message) is False

    def test_empty_message_returns_false(self):
        assert _wants_to_exit_booking("") is False


# ============================================================================
# T-2.3: Booking inertia guard — active booking prevents GREETING re-entry
# ============================================================================


class TestBookingInertiaGuard:
    """Tests for booking inertia preventing unwanted mode transitions."""

    @pytest.mark.asyncio
    async def test_active_booking_step_prevents_greeting_reentry(self):
        """Rule 4: if booking_step is set, do NOT re-enter GREETING even with
        is_first_interaction=True and customer_name=None."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name=None,
            is_first_interaction=True,
            user_message="hola",
            mode_context={"booking_step": "stylist_selection"},
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("greet")
            result = await router_node(state)

        # Should stay in BOOKING (Rule 7 catches it), not go to GREETING
        assert result.get("current_mode", "BOOKING") != "GREETING"

    @pytest.mark.asyncio
    async def test_ask_info_with_active_booking_stays_in_booking(self):
        """Rule 6 inertia: ask_info + active booking_step + no exit phrase → stay BOOKING."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name="Ana",
            user_message="¿tienen parking?",
            mode_context={"booking_step": "stylist_selection"},
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ask_info")
            result = await router_node(state)

        # Should stay in BOOKING due to inertia
        assert result.get("current_mode", "BOOKING") != "GENERAL"

    @pytest.mark.asyncio
    async def test_ask_info_with_exit_phrase_leaves_booking(self):
        """Rule 6: ask_info + active booking + exit phrase → allow GENERAL transition."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name="Ana",
            user_message="dejalo, otra cosa",
            mode_context={"booking_step": "stylist_selection"},
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ask_info")
            result = await router_node(state)

        # Should transition to GENERAL because of exit phrase
        assert result.get("current_mode") == "GENERAL"

    @pytest.mark.asyncio
    async def test_ambiguous_intent_active_booking_stays_in_booking(self):
        """Ambiguous intent + active booking (booking_step set) → stays in BOOKING (Rule 7)."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name="Ana",
            user_message="mmm no sé",
            mode_context={"booking_step": "slot_selection"},
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ambiguous")
            result = await router_node(state)

        # Rule 7: current_mode=BOOKING and intent not cancel/reject/ask_info → stay
        assert result.get("current_mode", "BOOKING") != "GENERAL"
        assert result.get("current_mode", "BOOKING") != "GREETING"

    @pytest.mark.asyncio
    async def test_no_booking_step_ask_info_goes_to_general(self):
        """Without active booking_step, ask_info with non-booking query → GENERAL."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name="Ana",
            user_message="¿aceptan tarjeta?",
            mode_context={},  # no booking_step
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ask_info")
            result = await router_node(state)

        # Without booking_step, non-booking query should go to GENERAL
        assert result.get("current_mode") == "GENERAL"

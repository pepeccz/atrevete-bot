"""
Unit tests for agent/modes/greeting_mode.py — create_agent migration (M3).

Coverage:
- Pure welcome + menu: greeting sends a welcome and transitions without any DB writes.
- Name-free guarantee: NO customer name appears in any response.
- Intent-aware transitions: BOOKING when booking content detected, GENERAL otherwise.
- New customer NEVER gets customer_name set in state by GREETING.

All LLM calls are short-circuited via `_use_optimized_prompts=False` — the node
uses the canned welcome string in that path and the LLM is never invoked.
"""

from unittest.mock import MagicMock

import pytest

from agent.modes import greeting_mode as gm_module
from agent.modes.greeting_mode import (
    _WELCOME_NEW,
    _WELCOME_RETURNING,
    _has_booking_content,
    _resolve_target_mode,
    build_greeting_node,
)
from agent.state.schemas import create_initial_state


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def greeting_node(monkeypatch):
    """Build a greeting node with the LLM path disabled (canned welcome)."""
    monkeypatch.setattr(gm_module, "_use_optimized_prompts", lambda: False)
    return build_greeting_node(llm_factory=lambda: MagicMock())


# =============================================================================
# Anti-loop guarantee (returning customer)
# =============================================================================


class TestGreetingNodeReturningCustomer:
    """Anti-loop: customer_name set → immediate transition with a name-free greeting."""

    @pytest.mark.asyncio
    async def test_customer_name_set_transitions_to_general(self, greeting_node):
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "Juan"

        result = await greeting_node(state)

        assert result["current_mode"] == "GENERAL"

    @pytest.mark.asyncio
    async def test_returning_customer_greeting_does_not_contain_name(self, greeting_node):
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "María"

        result = await greeting_node(state)

        combined = " ".join(m.get("content", "") for m in result.get("messages", []))
        assert "María" not in combined

    @pytest.mark.asyncio
    async def test_returning_customer_does_not_ask_for_name(self, greeting_node):
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "Carlos"

        result = await greeting_node(state)

        combined = " ".join(m.get("content", "") for m in result.get("messages", []))
        assert "¿Con quién" not in combined
        assert "nombre" not in combined.lower()
        assert "llamas" not in combined.lower()

    @pytest.mark.asyncio
    async def test_returning_customer_sets_previous_mode(self, greeting_node):
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "Ana"
        state["current_mode"] = "GREETING"

        result = await greeting_node(state)

        assert result.get("previous_mode") == "GREETING"

    @pytest.mark.asyncio
    async def test_returning_customer_clears_user_message(self, greeting_node):
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "Pedro"

        result = await greeting_node(state)

        assert result.get("user_message") is None


# =============================================================================
# New customer — NO DB writes, NO customer_name set
# =============================================================================


class TestGreetingNodeNewCustomer:
    """New-customer flow must NOT set customer_name in state."""

    @pytest.mark.asyncio
    async def test_handle_new_customer_never_sets_customer_name(self, greeting_node):
        state = create_initial_state("conv-002", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = "María García"
        state["messages"] = [
            {"role": "user", "content": "hola", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        result = await greeting_node(state)

        assert "customer_name" not in result or result.get("customer_name") is None

    @pytest.mark.asyncio
    async def test_new_customer_transitions_to_general(self, greeting_node):
        state = create_initial_state("conv-002", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = "Pedro"
        state["messages"] = [
            {"role": "user", "content": "hola", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        result = await greeting_node(state)

        assert result["current_mode"] == "GENERAL"

    @pytest.mark.asyncio
    async def test_new_customer_response_does_not_contain_name(self, greeting_node):
        state = create_initial_state("conv-002", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = "María"
        state["messages"] = [
            {
                "role": "user",
                "content": "buenas tardes",
                "timestamp": "2026-03-18T10:00:00+01:00",
            }
        ]

        result = await greeting_node(state)

        combined = " ".join(m.get("content", "") for m in result.get("messages", []))
        assert "María" not in combined

    @pytest.mark.asyncio
    async def test_new_customer_without_whatsapp_name_still_transitions(self, greeting_node):
        state = create_initial_state("conv-003", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = None
        state["messages"] = [
            {"role": "user", "content": "hola", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        result = await greeting_node(state)

        assert result["current_mode"] == "GENERAL"
        assert "customer_name" not in result or result.get("customer_name") is None

    @pytest.mark.asyncio
    async def test_new_customer_without_name_does_not_ask_for_name(self, greeting_node):
        state = create_initial_state("conv-003", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = None
        state["messages"] = [
            {"role": "user", "content": "hola", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        result = await greeting_node(state)

        combined = " ".join(m.get("content", "") for m in result.get("messages", []))
        assert "nombre" not in combined.lower()
        assert "llamas" not in combined.lower()
        assert "¿Con quién" not in combined


# =============================================================================
# Intent-aware mode transitions (greeting → BOOKING when intent is book)
# =============================================================================


class TestGreetingNodeIntentAwareTransition:
    """Greeting respects last_intent in mode_context and routes accordingly."""

    @pytest.mark.asyncio
    async def test_new_customer_with_book_intent_transitions_to_booking(self, greeting_node):
        state = create_initial_state("conv-100", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = "Pepe"
        state["mode_context"] = {"last_intent": "book", "last_intent_confidence": 0.85}
        state["messages"] = [
            {
                "role": "user",
                "content": "Hola, quiero cortarme el pelo",
                "timestamp": "2026-03-18T10:00:00+01:00",
            }
        ]

        result = await greeting_node(state)

        assert result["current_mode"] == "BOOKING"

    @pytest.mark.asyncio
    async def test_returning_customer_with_book_intent_transitions_to_booking(self, greeting_node):
        state = create_initial_state("conv-101", "+34612345678")
        state["customer_name"] = "Ana"
        state["mode_context"] = {"last_intent": "book", "last_intent_confidence": 0.90}

        result = await greeting_node(state)

        assert result["current_mode"] == "BOOKING"

    @pytest.mark.asyncio
    async def test_greet_only_intent_transitions_to_general(self, greeting_node):
        state = create_initial_state("conv-102", "+34612345678")
        state["customer_name"] = "Carlos"
        state["mode_context"] = {"last_intent": "greet", "last_intent_confidence": 0.90}

        result = await greeting_node(state)

        assert result["current_mode"] == "GENERAL"

    @pytest.mark.asyncio
    async def test_no_intent_in_context_defaults_to_general(self, greeting_node):
        state = create_initial_state("conv-103", "+34612345678")
        state["customer_name"] = "Laura"
        state["mode_context"] = {}

        result = await greeting_node(state)

        assert result["current_mode"] == "GENERAL"

    @pytest.mark.asyncio
    async def test_ambiguous_intent_transitions_to_general(self, greeting_node):
        state = create_initial_state("conv-104", "+34612345678")
        state["customer_name"] = "Diego"
        state["mode_context"] = {"last_intent": "ambiguous", "last_intent_confidence": 0.30}

        result = await greeting_node(state)

        assert result["current_mode"] == "GENERAL"


# =============================================================================
# F-9 — Booking content detection forces BOOKING transition
# =============================================================================


class TestResolveTargetModeBookingContent:
    """_has_booking_content token detection + _resolve_target_mode override."""

    def test_booking_service_word_detected(self):
        assert _has_booking_content("hola quiero un corte") is True

    def test_booking_verb_turno_detected(self):
        assert _has_booking_content("buenas, quería pedir un turno") is True

    def test_booking_verb_reservar_detected(self):
        assert _has_booking_content("quiero reservar una cita") is True

    def test_booking_service_tinte_detected(self):
        assert _has_booking_content("necesito un tinte") is True

    def test_booking_service_mechas_detected(self):
        assert _has_booking_content("me gustaría hacerme unas mechas") is True

    def test_booking_service_barba_detected(self):
        assert _has_booking_content("quiero arreglarme la barba") is True

    def test_booking_service_manicura_detected(self):
        assert _has_booking_content("quiero una manicura") is True

    def test_pure_greeting_hola_not_detected(self):
        assert _has_booking_content("Hola") is False

    def test_pure_greeting_buenas_not_detected(self):
        assert _has_booking_content("Buenas tardes") is False

    def test_pure_greeting_question_not_detected(self):
        assert _has_booking_content("¿Cómo estáis?") is False

    def test_empty_message_not_detected(self):
        assert _has_booking_content("") is False

    def test_none_message_not_detected(self):
        assert _has_booking_content(None) is False

    def test_booking_content_forces_booking_even_with_greet_intent(self):
        assert _resolve_target_mode({"last_intent": "greet"}, has_booking_content=True) == "BOOKING"

    def test_booking_content_forces_booking_with_no_intent(self):
        assert _resolve_target_mode({}, has_booking_content=True) == "BOOKING"

    def test_booking_content_forces_booking_with_ambiguous_intent(self):
        assert (
            _resolve_target_mode({"last_intent": "ambiguous"}, has_booking_content=True)
            == "BOOKING"
        )

    def test_no_booking_content_greet_intent_returns_general(self):
        assert _resolve_target_mode({"last_intent": "greet"}, has_booking_content=False) == "GENERAL"

    def test_no_booking_content_no_intent_returns_general(self):
        assert _resolve_target_mode({}, has_booking_content=False) == "GENERAL"

    def test_book_intent_returns_booking_regardless_of_content(self):
        ctx = {"last_intent": "book"}
        assert _resolve_target_mode(ctx, has_booking_content=False) == "BOOKING"
        assert _resolve_target_mode(ctx, has_booking_content=True) == "BOOKING"

    def test_default_no_content_param_returns_general(self):
        assert _resolve_target_mode({"last_intent": "greet"}) == "GENERAL"


class TestGreetingNodeBookingContentTransition:
    """F-9: booking content in greeting message forces BOOKING through full node flow."""

    @pytest.mark.asyncio
    async def test_booking_content_new_customer_forces_booking_transition(self, greeting_node):
        state = create_initial_state("conv-f9-001", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = "Rosa"
        state["mode_context"] = {"last_intent": "greet"}
        state["messages"] = [
            {
                "role": "user",
                "content": "Hola, quiero un corte",
                "timestamp": "2026-03-18T10:00:00+01:00",
            }
        ]

        result = await greeting_node(state)

        assert result["current_mode"] == "BOOKING"
        assert "customer_name" not in result or result.get("customer_name") is None

    @pytest.mark.asyncio
    async def test_booking_content_returning_customer_forces_booking_transition(self, greeting_node):
        state = create_initial_state("conv-f9-002", "+34612345678")
        state["customer_name"] = "Elena"
        state["mode_context"] = {"last_intent": "greet"}
        state["messages"] = [
            {
                "role": "user",
                "content": "Hola, necesito un tinte",
                "timestamp": "2026-03-18T10:00:00+01:00",
            }
        ]

        result = await greeting_node(state)

        assert result["current_mode"] == "BOOKING"

    @pytest.mark.asyncio
    async def test_pure_greeting_no_content_goes_to_general(self, greeting_node):
        state = create_initial_state("conv-f9-003", "+34612345678")
        state["customer_name"] = "Marcos"
        state["mode_context"] = {"last_intent": "greet"}
        state["messages"] = [
            {
                "role": "user",
                "content": "Hola",
                "timestamp": "2026-03-18T10:00:00+01:00",
            }
        ]

        result = await greeting_node(state)

        assert result["current_mode"] == "GENERAL"

    @pytest.mark.asyncio
    async def test_booking_handoff_context_set_when_booking_content_detected(self, greeting_node):
        state = create_initial_state("conv-f9-004", "+34612345678")
        state["customer_name"] = "Luis"
        state["mode_context"] = {"last_intent": "greet"}
        state["messages"] = [
            {
                "role": "user",
                "content": "Hola, quiero reservar una cita para corte",
                "timestamp": "2026-03-18T10:00:00+01:00",
            }
        ]

        result = await greeting_node(state)

        assert result["current_mode"] == "BOOKING"
        booking_ctx = result.get("booking_context", {})
        assert "opening_booking_request" in booking_ctx


# =============================================================================
# Canned welcome content (fallback path sanity)
# =============================================================================


class TestGreetingNodeFallbackContent:
    """When optimized prompts are disabled, the welcome messages come from constants."""

    @pytest.mark.asyncio
    async def test_new_customer_uses_new_welcome_string(self, greeting_node):
        state = create_initial_state("conv-cw-001", "+34612345678")
        state["messages"] = [
            {"role": "user", "content": "Hola", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        result = await greeting_node(state)

        last = result["messages"][-1]["content"]
        assert _WELCOME_NEW in last

    @pytest.mark.asyncio
    async def test_returning_customer_uses_returning_welcome_after_disclosure(self, greeting_node):
        """When the EU-AI-Act intro was already sent, the returning welcome passes through."""
        state = create_initial_state("conv-cw-002", "+34612345678")
        state["customer_name"] = "Sofía"
        state["ai_disclosure_sent"] = True

        result = await greeting_node(state)

        last = result["messages"][-1]["content"]
        assert _WELCOME_RETURNING in last

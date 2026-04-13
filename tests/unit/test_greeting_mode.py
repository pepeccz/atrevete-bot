"""
Unit tests for agent/modes/greeting_mode.py — GreetingMode (scope-realignment refactor).

Coverage:
- Pure welcome + menu: GreetingMode sends a welcome and transitions without any DB writes
- Name-free guarantee: NO customer name appears in any response
- Intent-aware transitions: BOOKING when booking content detected, GENERAL otherwise
- New customer NEVER gets customer_name set in state by GREETING

All LLM calls are mocked — tests do NOT require a real LLM.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.modes.greeting_mode import (
    GreetingMode,
    _WELCOME_NEW,
    _WELCOME_RETURNING,
    _has_booking_content,
    _resolve_target_mode,
)
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def make_intent(intent: str = "greet", confidence: float = 0.9) -> IntentResult:
    return IntentResult(
        intent=intent, confidence=confidence, raw_input="test", mode_hint="GREETING"
    )


def make_mock_llm(response_content: str = "¡Hola! ¿En qué puedo ayudarte?") -> AsyncMock:
    """Build a mock LLM that returns a simple content string."""
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_content
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def make_greeting_mode(llm_response: str = "¡Hola! ¿En qué puedo ayudarte?") -> GreetingMode:
    mock_llm = make_mock_llm(llm_response)
    mode = GreetingMode(tools=[], llm_client=mock_llm)
    # Disable optimized prompts so _render_layered_response uses fallback
    # without triggering DB/catalog calls in unit tests.
    mode._use_optimized_prompts = lambda: False  # type: ignore[method-assign]
    return mode


# =============================================================================
# Anti-loop guarantee (returning customer)
# =============================================================================


class TestGreetingModeReturningCustomer:
    """
    Verify the anti-loop guarantee:
    If customer_name is already set in state, GreetingMode MUST
    transition to GENERAL immediately with a NAME-FREE greeting.
    """

    @pytest.mark.asyncio
    async def test_customer_name_set_transitions_to_general(self):
        """Core anti-loop: customer_name present → current_mode becomes GENERAL."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "Juan"

        result = await mode.handle(state, make_intent())

        assert result["current_mode"] == "GENERAL"

    @pytest.mark.asyncio
    async def test_returning_customer_greeting_does_not_contain_name(self):
        """Returning customer greeting must NOT contain the customer's name."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "María"

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        combined_content = " ".join(m.get("content", "") for m in messages)
        assert "María" not in combined_content

    @pytest.mark.asyncio
    async def test_returning_customer_does_not_ask_for_name(self):
        """No message should ask for name when customer is known."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "Carlos"

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        combined_content = " ".join(m.get("content", "") for m in messages)
        assert "¿Con quién" not in combined_content
        assert "nombre" not in combined_content.lower()
        assert "llamas" not in combined_content.lower()

    @pytest.mark.asyncio
    async def test_returning_customer_sets_previous_mode(self):
        """Mode transition should record GREETING as previous_mode."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "Ana"
        state["current_mode"] = "GREETING"

        result = await mode.handle(state, make_intent())

        assert result.get("previous_mode") == "GREETING"

    @pytest.mark.asyncio
    async def test_returning_customer_clears_user_message(self):
        """user_message must be set to None after processing."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "Pedro"

        result = await mode.handle(state, make_intent())

        assert result.get("user_message") is None


# =============================================================================
# New customer — NO DB writes, NO customer_name set
# =============================================================================


class TestGreetingModeNewCustomer:
    """
    Tests for new customer flow: GREETING must NOT set customer_name in state.
    Customer creation happens later, atomically inside book().
    """

    @pytest.mark.asyncio
    async def test_handle_new_customer_never_sets_customer_name(self):
        """Core invariant: handle() return dict must NOT contain customer_name key."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-002", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = "María García"
        state["messages"] = [
            {"role": "user", "content": "hola", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        result = await mode.handle(state, make_intent())

        # GREETING must NOT set customer_name — that's book()'s responsibility
        assert "customer_name" not in result or result.get("customer_name") is None

    @pytest.mark.asyncio
    async def test_new_customer_transitions_to_general(self):
        """New customer flow must transition to GENERAL."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-002", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = "Pedro"
        state["messages"] = [
            {"role": "user", "content": "hola", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        result = await mode.handle(state, make_intent())

        assert result["current_mode"] == "GENERAL"

    @pytest.mark.asyncio
    async def test_new_customer_response_does_not_contain_name(self):
        """New customer greeting must NOT contain the sender's name."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-002", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = "María"
        state["messages"] = [
            {"role": "user", "content": "buenas tardes", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        combined_content = " ".join(m.get("content", "") for m in messages)
        assert "María" not in combined_content

    @pytest.mark.asyncio
    async def test_new_customer_without_whatsapp_name_still_transitions(self):
        """No pending_whatsapp_name → still transitions to GENERAL cleanly."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-003", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = None
        state["messages"] = [
            {"role": "user", "content": "hola", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        result = await mode.handle(state, make_intent())

        assert result["current_mode"] == "GENERAL"
        assert "customer_name" not in result or result.get("customer_name") is None

    @pytest.mark.asyncio
    async def test_new_customer_without_name_does_not_ask_for_name(self):
        """Must NOT ask for the customer's name."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-003", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = None
        state["messages"] = [
            {"role": "user", "content": "hola", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        combined_content = " ".join(m.get("content", "") for m in messages)
        assert "nombre" not in combined_content.lower()
        assert "llamas" not in combined_content.lower()
        assert "¿Con quién" not in combined_content


# =============================================================================
# Intent-aware mode transitions (greeting → BOOKING when intent is book)
# =============================================================================


class TestGreetingModeIntentAwareTransition:
    """
    When the router classifies a message as greeting but also detects an
    actionable intent (e.g., booking), GreetingMode should transition to
    the appropriate mode instead of always defaulting to GENERAL.
    """

    @pytest.mark.asyncio
    async def test_new_customer_with_book_intent_transitions_to_booking(self):
        """'Hola, quiero cortarme el pelo' → greet + book → greeting then BOOKING."""
        mode = make_greeting_mode()
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

        result = await mode.handle(state, make_intent())

        assert result["current_mode"] == "BOOKING"

    @pytest.mark.asyncio
    async def test_returning_customer_with_book_intent_transitions_to_booking(self):
        """Returning customer with booking intent → greeting then BOOKING."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-101", "+34612345678")
        state["customer_name"] = "Ana"
        state["mode_context"] = {"last_intent": "book", "last_intent_confidence": 0.90}

        result = await mode.handle(state, make_intent())

        assert result["current_mode"] == "BOOKING"

    @pytest.mark.asyncio
    async def test_greet_only_intent_transitions_to_general(self):
        """Pure greeting intent (no booking) → GENERAL (backward-compatible)."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-102", "+34612345678")
        state["customer_name"] = "Carlos"
        state["mode_context"] = {"last_intent": "greet", "last_intent_confidence": 0.90}

        result = await mode.handle(state, make_intent())

        assert result["current_mode"] == "GENERAL"

    @pytest.mark.asyncio
    async def test_no_intent_in_context_defaults_to_general(self):
        """No last_intent in mode_context → GENERAL (backward-compatible)."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-103", "+34612345678")
        state["customer_name"] = "Laura"
        state["mode_context"] = {}

        result = await mode.handle(state, make_intent())

        assert result["current_mode"] == "GENERAL"

    @pytest.mark.asyncio
    async def test_ambiguous_intent_transitions_to_general(self):
        """Ambiguous intent → GENERAL (default safe behavior)."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-104", "+34612345678")
        state["customer_name"] = "Diego"
        state["mode_context"] = {"last_intent": "ambiguous", "last_intent_confidence": 0.30}

        result = await mode.handle(state, make_intent())

        assert result["current_mode"] == "GENERAL"


# =============================================================================
# T-13: F-9 — Booking content detection forces BOOKING transition
# =============================================================================


class TestResolveTargetModeBookingContent:
    """
    T-13: Unit tests for _resolve_target_mode() with has_booking_content parameter.

    F-9 guardrail: when the user's first message contains clear booking content,
    _resolve_target_mode() must return "BOOKING" regardless of last_intent.
    Pure greetings without booking tokens must still return "GENERAL".
    """

    # ── _has_booking_content() token detection ─────────────────────────────

    def test_booking_service_word_detected(self):
        """Message with a service name → has_booking_content returns True."""
        assert _has_booking_content("hola quiero un corte") is True

    def test_booking_verb_turno_detected(self):
        """Message with 'turno' → True."""
        assert _has_booking_content("buenas, quería pedir un turno") is True

    def test_booking_verb_reservar_detected(self):
        """Message with 'reservar' → True."""
        assert _has_booking_content("quiero reservar una cita") is True

    def test_booking_service_tinte_detected(self):
        """Message with 'tinte' → True."""
        assert _has_booking_content("necesito un tinte") is True

    def test_booking_service_mechas_detected(self):
        """Message with 'mechas' → True."""
        assert _has_booking_content("me gustaría hacerme unas mechas") is True

    def test_booking_service_barba_detected(self):
        """Message with 'barba' → True (expanded set)."""
        assert _has_booking_content("quiero arreglarme la barba") is True

    def test_booking_service_manicura_detected(self):
        """Message with 'manicura' → True (expanded set)."""
        assert _has_booking_content("quiero una manicura") is True

    def test_pure_greeting_hola_not_detected(self):
        """'Hola' alone → has_booking_content returns False."""
        assert _has_booking_content("Hola") is False

    def test_pure_greeting_buenas_not_detected(self):
        """'Buenas tardes' → False."""
        assert _has_booking_content("Buenas tardes") is False

    def test_pure_greeting_question_not_detected(self):
        """'¿Cómo estáis?' → False."""
        assert _has_booking_content("¿Cómo estáis?") is False

    def test_empty_message_not_detected(self):
        """Empty message → False."""
        assert _has_booking_content("") is False

    def test_none_message_not_detected(self):
        """None message → False."""
        assert _has_booking_content(None) is False

    # ── _resolve_target_mode() with has_booking_content ────────────────────

    def test_booking_content_forces_booking_even_with_greet_intent(self):
        """has_booking_content=True + intent='greet' → 'BOOKING'."""
        mode_context = {"last_intent": "greet"}
        assert _resolve_target_mode(mode_context, has_booking_content=True) == "BOOKING"

    def test_booking_content_forces_booking_with_no_intent(self):
        """has_booking_content=True + no last_intent → 'BOOKING'."""
        assert _resolve_target_mode({}, has_booking_content=True) == "BOOKING"

    def test_booking_content_forces_booking_with_ambiguous_intent(self):
        """has_booking_content=True + intent='ambiguous' → 'BOOKING'."""
        mode_context = {"last_intent": "ambiguous"}
        assert _resolve_target_mode(mode_context, has_booking_content=True) == "BOOKING"

    def test_no_booking_content_greet_intent_returns_general(self):
        """has_booking_content=False + intent='greet' → 'GENERAL'."""
        mode_context = {"last_intent": "greet"}
        assert _resolve_target_mode(mode_context, has_booking_content=False) == "GENERAL"

    def test_no_booking_content_no_intent_returns_general(self):
        """has_booking_content=False + no last_intent → 'GENERAL' (default)."""
        assert _resolve_target_mode({}, has_booking_content=False) == "GENERAL"

    def test_book_intent_returns_booking_regardless_of_content(self):
        """last_intent='book' always returns 'BOOKING', content flag irrelevant."""
        mode_context = {"last_intent": "book"}
        assert _resolve_target_mode(mode_context, has_booking_content=False) == "BOOKING"
        assert _resolve_target_mode(mode_context, has_booking_content=True) == "BOOKING"

    def test_default_no_content_param_returns_general(self):
        """Default param (no has_booking_content) + 'greet' → 'GENERAL'."""
        mode_context = {"last_intent": "greet"}
        assert _resolve_target_mode(mode_context) == "GENERAL"


class TestGreetingModeBookingContentTransition:
    """
    T-13: Integration tests — booking content in greeting message forces BOOKING
    transition through the full GreetingMode.handle() flow.
    """

    @pytest.mark.asyncio
    async def test_booking_content_new_customer_forces_booking_transition(self):
        """
        New customer says 'Hola, quiero un corte' with intent='greet' →
        greeting handles it, but transitions to BOOKING (F-9 override).
        """
        mode = make_greeting_mode()
        state = create_initial_state("conv-f9-001", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = "Rosa"
        # intent='greet' — router did NOT classify as booking
        state["mode_context"] = {"last_intent": "greet"}
        state["messages"] = [
            {
                "role": "user",
                "content": "Hola, quiero un corte",
                "timestamp": "2026-03-18T10:00:00+01:00",
            }
        ]

        result = await mode.handle(state, make_intent("greet"))

        # F-9: must go to BOOKING even though intent was 'greet'
        assert result["current_mode"] == "BOOKING"
        # And NEVER sets customer_name
        assert "customer_name" not in result or result.get("customer_name") is None

    @pytest.mark.asyncio
    async def test_booking_content_returning_customer_forces_booking_transition(self):
        """
        Returning customer says 'Hola, necesito un tinte' with intent='greet' →
        transitions to BOOKING (F-9 override).
        """
        mode = make_greeting_mode()
        state = create_initial_state("conv-f9-002", "+34612345678")
        state["customer_name"] = "Elena"
        # intent='greet' — router did NOT classify as booking
        state["mode_context"] = {"last_intent": "greet"}

        # Simulate message in history
        state["messages"] = [
            {
                "role": "user",
                "content": "Hola, necesito un tinte",
                "timestamp": "2026-03-18T10:00:00+01:00",
            }
        ]

        result = await mode.handle(state, make_intent("greet"))

        # F-9: must go to BOOKING even though intent was 'greet'
        assert result["current_mode"] == "BOOKING"

    @pytest.mark.asyncio
    async def test_pure_greeting_no_content_goes_to_general(self):
        """
        'Hola' with intent='greet' and no booking content → GENERAL (unchanged).
        Verifies F-9 does NOT trigger on pure greetings.
        """
        mode = make_greeting_mode()
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

        result = await mode.handle(state, make_intent("greet"))

        assert result["current_mode"] == "GENERAL"

    @pytest.mark.asyncio
    async def test_booking_handoff_context_set_when_booking_content_detected(self):
        """
        When booking content is detected and F-9 forces BOOKING transition,
        booking_context must include opening_booking_request for the handoff.
        """
        mode = make_greeting_mode()
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

        result = await mode.handle(state, make_intent("greet"))

        # Must transition to BOOKING
        assert result["current_mode"] == "BOOKING"
        # opening_booking_request must be set in booking_context (single source of truth)
        booking_ctx = result.get("booking_context", {})
        assert "opening_booking_request" in booking_ctx

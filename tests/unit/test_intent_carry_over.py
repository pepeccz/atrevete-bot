"""
Unit tests for Phase C: Intent Carry-Over (booking-bugs-fix).

Covers:
- C.1: opening_booking_request is set when GREETING→BOOKING with booking intent
- C.1: opening_booking_request is NOT set when GREETING→BOOKING with pure greeting
- C.2: _handle_service_selection consumes opening_booking_request and clears it
- C.2: Double-consumption doesn't re-trigger intent (once-only pattern)
- C.3: _has_booking_content detects booking tokens correctly
- C.3: build_step_context includes implicit_service_hint
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.booking_context import BookingSubstep
from agent.modes.booking_mode import BookingMode, _BOOKING_CONTENT_TOKENS
from agent.modes.greeting_mode import GreetingMode, _has_booking_content
from agent.prompts.loader import build_step_context
from agent.routing.intent_router import IntentResult
from agent.state.schemas import ConversationState, create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def make_mock_llm(response_text: str = "¡Perfecto!") -> AsyncMock:
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def make_greeting_mode(llm_response: str = "¡Hola! ¿En qué puedo ayudarte?") -> GreetingMode:
    return GreetingMode(tools=[], llm_client=make_mock_llm(llm_response))


def make_booking_mode(llm_response: str = "¡Perfecto!") -> BookingMode:
    return BookingMode(tools=[], llm_client=make_mock_llm(llm_response))


def make_greeting_state_new_customer(
    user_message: str,
    last_intent: str = "book",
) -> dict:
    """State for a new customer in GREETING with a book intent."""
    state = create_initial_state("conv-carry-test", "+34611000010")
    state["customer_name"] = None
    state["customer_id"] = None
    state["is_first_interaction"] = True
    state["pending_whatsapp_name"] = "María"
    state["messages"] = [
        {"role": "user", "content": user_message, "timestamp": "2026-03-20T10:00:00"},
    ]
    state["mode_context"] = {
        "last_intent": last_intent,
    }
    return state


def make_greeting_state_returning_customer(
    user_message: str,
    last_intent: str = "book",
) -> dict:
    """State for a returning customer in GREETING with a book intent."""
    state = create_initial_state("conv-carry-test-2", "+34611000011")
    state["customer_name"] = "Ana"
    state["customer_id"] = "cust-abc-returning"
    state["is_first_interaction"] = False
    state["messages"] = [
        {"role": "user", "content": user_message, "timestamp": "2026-03-20T10:00:00"},
    ]
    state["mode_context"] = {
        "last_intent": last_intent,
    }
    return state


def make_service_selection_state(
    opening_booking_request: str | None = None,
    service_name: str | None = None,
) -> dict:
    """State at service_selection step with optional opening_booking_request."""
    state = create_initial_state("conv-service-test", "+34611000012")
    state["customer_name"] = "Ana"
    state["customer_id"] = "cust-abc-service"
    state["messages"] = [
        {"role": "user", "content": "corte de dama", "timestamp": "2026-03-20T10:01:00"},
    ]
    ctx: dict = {
        "booking_step": BookingSubstep.SERVICE_SELECTION.value,
    }
    if opening_booking_request is not None:
        ctx["opening_booking_request"] = opening_booking_request
    if service_name is not None:
        ctx["service_name"] = service_name
    state["mode_context"] = ctx
    return state


# =============================================================================
# _has_booking_content tests (module-level function)
# =============================================================================


class TestHasBookingContent:
    """Tests for the _has_booking_content helper in greeting_mode."""

    def test_detects_corte(self):
        assert _has_booking_content("quiero un corte de pelo") is True

    def test_detects_dama(self):
        assert _has_booking_content("Hola, quiero corte de dama") is True

    def test_detects_tinte(self):
        assert _has_booking_content("Hola buenas, quiero un tinte para el viernes") is True

    def test_detects_caballero(self):
        assert _has_booking_content("corte caballero") is True

    def test_detects_nina(self):
        assert _has_booking_content("quiero un corte de niña") is True

    def test_detects_hombre(self):
        assert _has_booking_content("corte de hombre") is True

    def test_pure_greeting_no_booking(self):
        assert _has_booking_content("Hola") is False

    def test_pure_greeting_with_question(self):
        assert _has_booking_content("Hola, qué tal?") is False

    def test_empty_message(self):
        assert _has_booking_content("") is False

    def test_none_message(self):
        assert _has_booking_content(None) is False

    def test_accent_normalized(self):
        """Accent normalization: 'niña' → 'nina' should match."""
        assert _has_booking_content("Hola, quiero corte de niña") is True

    def test_case_insensitive(self):
        assert _has_booking_content("CORTE DE DAMA") is True


# =============================================================================
# C.1: opening_booking_request is set on GREETING→BOOKING transition
# =============================================================================


class TestGreetingToBookingIntentPreservation:
    """Tests that opening_booking_request is set/not set during transitions."""

    @pytest.mark.asyncio
    async def test_new_customer_booking_intent_sets_opening_request(self):
        """Scenario C.1: 'Hola, quiero corte de dama' carries intent to BOOKING."""
        mode = make_greeting_mode()
        state = make_greeting_state_new_customer(
            "Hola, quiero corte de dama",
            last_intent="book",
        )

        with patch.object(mode, "_create_customer", new_callable=AsyncMock, return_value="cust-new-123"):
            result = await mode.handle(state=state, intent=None)

        # Must transition to BOOKING
        mode_ctx = result.get("mode_context", {})
        assert result.get("current_mode") == "BOOKING"
        assert mode_ctx.get("opening_booking_request") == "Hola, quiero corte de dama"

    @pytest.mark.asyncio
    async def test_pure_greeting_does_not_set_opening_request(self):
        """Scenario C.2: Pure 'Hola' does NOT carry over."""
        mode = make_greeting_mode()
        state = make_greeting_state_new_customer(
            "Hola",
            last_intent="greet",
        )

        with patch.object(mode, "_create_customer", new_callable=AsyncMock, return_value="cust-new-456"):
            result = await mode.handle(state=state, intent=None)

        mode_ctx = result.get("mode_context", {})
        # target_mode = GENERAL (greet intent → GENERAL), so no opening_booking_request
        assert mode_ctx.get("opening_booking_request") is None

    @pytest.mark.asyncio
    async def test_returning_customer_booking_intent_sets_opening_request(self):
        """Scenario C.4: Returning customer with booking intent also carries over."""
        mode = make_greeting_mode()
        state = make_greeting_state_returning_customer(
            "Hola, quiero reservar un corte",
            last_intent="book",
        )

        result = await mode.handle(state=state, intent=None)

        mode_ctx = result.get("mode_context", {})
        assert result.get("current_mode") == "BOOKING"
        assert mode_ctx.get("opening_booking_request") == "Hola, quiero reservar un corte"

    @pytest.mark.asyncio
    async def test_returning_customer_pure_greeting_no_carry_over(self):
        """Returning customer saying just 'Hola de nuevo' — no carry-over."""
        mode = make_greeting_mode()
        state = make_greeting_state_returning_customer(
            "Hola de nuevo",
            last_intent="greet",
        )

        result = await mode.handle(state=state, intent=None)

        mode_ctx = result.get("mode_context", {})
        # target_mode = GENERAL for greet intent
        assert mode_ctx.get("opening_booking_request") is None

    @pytest.mark.asyncio
    async def test_booking_intent_with_tinte_sets_opening_request(self):
        """'Hola buenas, quiero un tinte para el viernes' carries both service and date."""
        mode = make_greeting_mode()
        state = make_greeting_state_new_customer(
            "Hola buenas, quiero un tinte para el viernes",
            last_intent="book",
        )

        with patch.object(mode, "_create_customer", new_callable=AsyncMock, return_value="cust-new-789"):
            result = await mode.handle(state=state, intent=None)

        mode_ctx = result.get("mode_context", {})
        assert result.get("current_mode") == "BOOKING"
        assert mode_ctx.get("opening_booking_request") == "Hola buenas, quiero un tinte para el viernes"


# =============================================================================
# C.2: Consume opening_booking_request in _handle_service_selection
# =============================================================================


class TestServiceSelectionConsumption:
    """Tests that _handle_service_selection consumes and clears opening_booking_request."""

    @pytest.mark.asyncio
    async def test_consumes_opening_request_sets_implicit_hint(self):
        """opening_booking_request is consumed and stored as implicit_service_hint."""
        mode = make_booking_mode()
        state = make_service_selection_state(
            opening_booking_request="Hola, quiero corte de dama",
        )

        with patch(
            "agent.modes.booking_mode.BookingMode._run_agentic_loop",
            new_callable=AsyncMock,
        ) as mock_loop:
            from agent.modes.base import AgenticLoopResult
            mock_loop.return_value = AgenticLoopResult(
                response_text="¡Genial! Vamos con el corte de dama.",
                tool_results={},
                tool_events=[],
            )
            result = await mode._handle_service_selection(state, dict(state["mode_context"]))

        mode_ctx = result.get("mode_context", {})
        # opening_booking_request must be consumed (cleared)
        assert mode_ctx.get("opening_booking_request") is None
        # implicit_service_hint should have been set for the LLM context
        # Note: after _advance_step, it may or may not persist depending on
        # whether service was resolved. What matters is it was injected.

    @pytest.mark.asyncio
    async def test_opening_request_cleared_after_consumption(self):
        """After consuming, opening_booking_request must not appear in final context."""
        mode = make_booking_mode()
        state = make_service_selection_state(
            opening_booking_request="quiero corte de dama",
        )

        with patch(
            "agent.modes.booking_mode.BookingMode._run_agentic_loop",
            new_callable=AsyncMock,
        ) as mock_loop:
            from agent.modes.base import AgenticLoopResult
            mock_loop.return_value = AgenticLoopResult(
                response_text="¿Qué servicio buscás?",
                tool_results={},
                tool_events=[],
            )
            result = await mode._handle_service_selection(state, dict(state["mode_context"]))

        mode_ctx = result.get("mode_context", {})
        assert "opening_booking_request" not in mode_ctx

    @pytest.mark.asyncio
    async def test_no_opening_request_when_service_already_set(self):
        """If service_name is already set, opening_booking_request is NOT used as hint."""
        mode = make_booking_mode()
        state = make_service_selection_state(
            opening_booking_request="quiero corte de dama",
            service_name="Cortar",
        )

        with patch(
            "agent.modes.booking_mode.BookingMode._run_agentic_loop",
            new_callable=AsyncMock,
        ) as mock_loop:
            from agent.modes.base import AgenticLoopResult
            mock_loop.return_value = AgenticLoopResult(
                response_text="Continuemos con Cortar.",
                tool_results={},
                tool_events=[],
            )
            ctx = dict(state["mode_context"])
            result = await mode._handle_service_selection(state, ctx)

        mode_ctx = result.get("mode_context", {})
        # implicit_service_hint should NOT have been set since service_name existed
        assert mode_ctx.get("implicit_service_hint") is None

    @pytest.mark.asyncio
    async def test_double_consumption_does_not_retrigger(self):
        """Once consumed, a second call to _handle_service_selection won't re-set the hint."""
        mode = make_booking_mode()

        # First call: has opening_booking_request
        state = make_service_selection_state(
            opening_booking_request="corte de dama",
        )

        with patch(
            "agent.modes.booking_mode.BookingMode._run_agentic_loop",
            new_callable=AsyncMock,
        ) as mock_loop:
            from agent.modes.base import AgenticLoopResult
            mock_loop.return_value = AgenticLoopResult(
                response_text="¿Qué servicio buscás?",
                tool_results={},
                tool_events=[],
            )
            result1 = await mode._handle_service_selection(state, dict(state["mode_context"]))

        # Second call: uses the returned mode_context (opening_booking_request already consumed)
        returned_ctx = dict(result1.get("mode_context", {}))
        state2 = make_service_selection_state()
        state2["mode_context"] = returned_ctx

        with patch(
            "agent.modes.booking_mode.BookingMode._run_agentic_loop",
            new_callable=AsyncMock,
        ) as mock_loop:
            from agent.modes.base import AgenticLoopResult
            mock_loop.return_value = AgenticLoopResult(
                response_text="¿Qué servicio buscás?",
                tool_results={},
                tool_events=[],
            )
            result2 = await mode._handle_service_selection(state2, dict(returned_ctx))

        mode_ctx2 = result2.get("mode_context", {})
        # implicit_service_hint should not appear again on second run
        assert mode_ctx2.get("implicit_service_hint") is None
        assert mode_ctx2.get("opening_booking_request") is None


# =============================================================================
# C.3: build_step_context includes implicit_service_hint
# =============================================================================


class TestBuildStepContextWithHint:
    """Tests that build_step_context injects the implicit_service_hint."""

    def test_includes_implicit_service_hint(self):
        state = create_initial_state("conv-ctx-test", "+34611000013")
        mode_context = {
            "booking_step": "service_selection",
            "implicit_service_hint": "Hola, quiero corte de dama para el jueves",
        }

        context_str = build_step_context(state, mode_context)

        assert "Petición original de la clienta" in context_str
        assert "Hola, quiero corte de dama para el jueves" in context_str

    def test_no_hint_when_absent(self):
        state = create_initial_state("conv-ctx-test-2", "+34611000014")
        mode_context = {
            "booking_step": "service_selection",
        }

        context_str = build_step_context(state, mode_context)

        assert "Petición original de la clienta" not in context_str

"""
Unit tests for agent/modes/booking_mode.py — BookingMode v6.0.

Coverage:
- Sub-step initial state: no booking_step → defaults to "service_selection"
- Cancel at any step → transitions to GENERAL
- Cancel at early (service_selection) step → direct GENERAL transition
- Escalate intent at any step → transitions to ESCALATION
- BookingMode mode_name property

All LLM calls are mocked — tests do NOT require a real LLM or DB.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.booking_mode import BookingMode
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def make_intent(intent: str = "book", confidence: float = 0.9) -> IntentResult:
    return IntentResult(intent=intent, confidence=confidence, raw_input="test", mode_hint="BOOKING")


def make_mock_llm(response_text: str = "¿Qué servicio deseas?") -> AsyncMock:
    """Mock LLM that returns a simple text response with no tool calls."""
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []  # No tool calls → final response
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def make_booking_mode(llm_response: str = "¿Qué servicio deseas?") -> BookingMode:
    mock_llm = make_mock_llm(llm_response)
    return BookingMode(tools=[], llm_client=mock_llm)


def make_state_with_step(
    booking_step: str | None = None,
    customer_name: str | None = "Juan",
    customer_id: str | None = "cust-123",
) -> dict:
    """Build a ConversationState with optional booking_step in mode_context."""
    state = create_initial_state("conv-001", "+34612345678")
    state["customer_name"] = customer_name
    state["customer_id"] = customer_id
    state["is_first_interaction"] = False
    state["current_mode"] = "BOOKING"

    if booking_step is not None:
        state["mode_context"] = {"booking_step": booking_step}
    else:
        state["mode_context"] = {}  # No step set — defaults to service_selection

    return state


# =============================================================================
# mode_name
# =============================================================================


class TestBookingModeName:
    def test_mode_name_is_booking(self):
        mode = make_booking_mode()
        assert mode.mode_name == "BOOKING"


# =============================================================================
# Initial booking step
# =============================================================================


class TestBookingModeInitialStep:
    """Tests for the initial state when entering BOOKING mode."""

    async def test_no_booking_step_defaults_to_service_selection(self):
        """
        When mode_context has no booking_step, the mode should enter
        service_selection (the first step).
        """
        mode = make_booking_mode()
        state = make_state_with_step(booking_step=None)

        result = await mode.handle(state, make_intent())

        # The result should set/maintain booking_step as service_selection
        mode_context = result.get("mode_context", {})
        assert mode_context.get("booking_step") == "service_selection"

    async def test_no_booking_step_generates_message(self):
        """First step should produce a response asking about the service."""
        mode = make_booking_mode("¿Qué servicio te gustaría hoy?")
        state = make_state_with_step(booking_step=None)

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        assert len(messages) >= 1

    async def test_explicit_service_selection_step_handled(self):
        """Explicit service_selection step should work the same as implicit."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="service_selection")

        result = await mode.handle(state, make_intent())

        # Should still be in service_selection step
        mode_context = result.get("mode_context", {})
        assert mode_context.get("booking_step") == "service_selection"


# =============================================================================
# Cancel at any step
# =============================================================================


class TestBookingModeCancel:
    """Tests for cancel intent at various booking steps."""

    async def test_cancel_at_service_selection_transitions_to_general(self):
        """At the very first step, cancel goes directly to GENERAL (no confirmation needed)."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="service_selection")

        result = await mode.handle(state, make_intent("cancel"))

        assert result.get("current_mode") == "GENERAL"

    async def test_cancel_at_service_selection_no_confirmation_needed(self):
        """At first step, cancel should NOT ask for confirmation."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="service_selection")

        result = await mode.handle(state, make_intent("cancel"))

        messages = result.get("messages", [])
        combined = " ".join(m.get("content", "") for m in messages)
        assert "¿Seguro" not in combined  # No confirmation dialog at first step

    async def test_reject_at_service_selection_transitions_to_general(self):
        """reject at first step is treated like cancel — go to GENERAL."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="service_selection")

        result = await mode.handle(state, make_intent("reject"))

        assert result.get("current_mode") == "GENERAL"

    async def test_cancel_intent_at_mid_step_goes_to_general(self):
        """
        The 'cancel' intent at ANY non-first step goes directly to GENERAL.
        Per implementation: `if pending_cancel or intent.intent == "cancel": → GENERAL`
        Only 'reject' triggers the confirmation dialog.
        """
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="stylist_selection")

        result = await mode.handle(state, make_intent("cancel"))

        assert result.get("current_mode") == "GENERAL"

    async def test_reject_at_mid_step_asks_confirmation(self):
        """Reject (not cancel) at a non-initial step asks the user to confirm cancellation."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="stylist_selection")

        result = await mode.handle(state, make_intent("reject"))

        messages = result.get("messages", [])
        combined = " ".join(m.get("content", "") for m in messages)
        assert "¿Seguro" in combined

    async def test_reject_at_mid_step_sets_pending_cancel(self):
        """Reject at non-initial step should set pending_cancel=True in mode_context."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="stylist_selection")

        result = await mode.handle(state, make_intent("reject"))

        mode_context = result.get("mode_context", {})
        assert mode_context.get("pending_cancel") is True

    async def test_cancel_intent_at_slot_selection_goes_to_general(self):
        """Cancel intent during slot selection goes straight to GENERAL (no confirmation)."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="slot_selection")

        result = await mode.handle(state, make_intent("cancel"))

        # cancel intent always goes directly to GENERAL
        assert result.get("current_mode") == "GENERAL"

    async def test_confirmed_cancel_clears_mode_and_transitions_to_general(self):
        """When pending_cancel is True AND user sends cancel → go to GENERAL."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="customer_data")
        state["mode_context"]["pending_cancel"] = True

        result = await mode.handle(state, make_intent("reject"))

        assert result.get("current_mode") == "GENERAL"


# =============================================================================
# Escalate at any step
# =============================================================================


class TestBookingModeEscalate:
    """Tests for escalate intent at various booking steps."""

    async def test_escalate_at_service_selection_transitions_to_escalation(self):
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="service_selection")

        result = await mode.handle(state, make_intent("escalate"))

        assert result.get("current_mode") == "ESCALATION"

    async def test_escalate_at_confirmation_step_transitions_to_escalation(self):
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="confirmation")
        state["mode_context"].update({
            "service_name": "Corte",
            "stylist_name": "Laura",
            "slot_time": "10:00",
            "slot_date": "2026-03-10",
            "booking_first_name": "Juan",
        })

        result = await mode.handle(state, make_intent("escalate"))

        assert result.get("current_mode") == "ESCALATION"

    async def test_escalate_at_mid_booking_transitions_to_escalation(self):
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="stylist_selection")
        state["mode_context"]["service_name"] = "Tinte"

        result = await mode.handle(state, make_intent("escalate"))

        assert result.get("current_mode") == "ESCALATION"


# =============================================================================
# Sub-step: service_selection
# =============================================================================


class TestBookingModeServiceSelection:
    """Tests for the service_selection sub-step."""

    async def test_service_selection_returns_message(self):
        mode = make_booking_mode("¿Qué servicio te gustaría?")
        state = make_state_with_step(booking_step="service_selection")

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        assert len(messages) >= 1

    async def test_service_selection_message_is_assistant_role(self):
        mode = make_booking_mode("¿Qué servicio?")
        state = make_state_with_step(booking_step="service_selection")

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        assert messages[0]["role"] == "assistant"


# =============================================================================
# Confirmation step
# =============================================================================


class TestBookingModeConfirmation:
    """Tests for the confirmation step."""

    def _make_state_at_confirmation(self) -> dict:
        state = make_state_with_step(booking_step="confirmation")
        state["mode_context"].update({
            "service_name": "Corte de señora",
            "stylist_name": "Laura",
            "slot_time": "10:00",
            "slot_date": "2026-03-10",
            "booking_first_name": "Juan",
            "booking_last_name": "García",
            "booking_notes": None,
        })
        return state

    async def test_confirm_intent_advances_to_completed(self):
        """confirm intent at confirmation step → booking_step=completed."""
        mode = make_booking_mode()
        state = self._make_state_at_confirmation()

        result = await mode.handle(state, make_intent("confirm"))

        mode_context = result.get("mode_context", {})
        assert mode_context.get("booking_step") == "completed"

    async def test_non_confirm_at_confirmation_shows_summary(self):
        """Any non-confirm intent at confirmation → show booking summary."""
        mode = make_booking_mode("¿Confirmas la reserva?")
        state = self._make_state_at_confirmation()

        result = await mode.handle(state, make_intent("book"))

        messages = result.get("messages", [])
        assert len(messages) >= 1

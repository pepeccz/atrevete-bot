"""
Unit tests for error hardening in booking flow.

Covers:
- booking_mode._handle_completed(): success=False from book() increments error_count
- greeting_mode.handle(): customer creation failure escalates to ESCALATION
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.booking_context import BookingSubstep
from agent.modes.booking_mode import BookingMode
from agent.modes.greeting_mode import GreetingMode
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def make_mock_llm(response_text: str = "Error al procesar tu reserva.") -> AsyncMock:
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def make_booking_mode(llm_response: str = "Error al procesar tu reserva.") -> BookingMode:
    return BookingMode(tools=[], llm_client=make_mock_llm(llm_response))


def make_greeting_mode() -> GreetingMode:
    return GreetingMode(tools=[], llm_client=make_mock_llm("¡Hola!"))


def make_completed_state() -> dict:
    """State with all booking data filled in, ready for _handle_completed."""
    state = create_initial_state("conv-999", "+34611000000")
    state["customer_id"] = "cust-abc-123"
    state["customer_name"] = "Ana"
    state["error_count"] = 0
    state["mode_context"] = {
        "booking_step": BookingSubstep.COMPLETED.value,
        "service_name": "Corte de pelo",
        "stylist_id": "stylist-001",
        "selected_slot": {"start_time": "2026-04-01T10:00:00"},
        "first_name": "Ana",
        "notes": "",
    }
    return state


def make_intent(intent: str = "book") -> IntentResult:
    return IntentResult(intent=intent, confidence=0.9, raw_input="reservar", mode_hint="BOOKING")


# =============================================================================
# Change 1: booking_mode._handle_completed — success=False escalates
# =============================================================================


class TestBookingHandleCompletedErrorHardening:
    """
    Verify that book() returning success=False is treated as a failure:
    - error_count is incremented
    - mode stays BOOKING (no transition)
    - No appointment_created=True in result
    """

    @pytest.mark.asyncio
    async def test_success_false_without_error_key_increments_error_count(self):
        """book() returns {success: False, error_code: INVALID_UUID} → error path."""
        mode = make_booking_mode()
        state = make_completed_state()
        mode_context = state["mode_context"]

        book_result = {"success": False, "error_code": "INVALID_UUID"}

        # book is imported lazily inside _handle_completed — patch at source module
        with (
            patch("agent.tools.booking_tools.book") as mock_book,
            patch.object(mode, "_run_agentic_loop", new_callable=AsyncMock) as mock_loop,
            patch.object(mode, "_use_optimized_prompts", return_value=False),
        ):
            mock_book.ainvoke = AsyncMock(return_value=book_result)
            loop_result = MagicMock()
            loop_result.response_text = "Hubo un error al crear tu turno."
            mock_loop.return_value = loop_result

            result = await mode._handle_completed(state, mode_context)

        assert result.get("error_count") == 1, "error_count must be incremented"
        assert result.get("appointment_created") is not True, "appointment must NOT be marked created"

    @pytest.mark.asyncio
    async def test_success_false_with_error_key_uses_error_message(self):
        """book() returns {success: False, error: 'DB down'} → error message is preserved."""
        mode = make_booking_mode()
        state = make_completed_state()
        mode_context = state["mode_context"]

        book_result = {"success": False, "error": "DB connection failed", "error_code": "DB_ERROR"}

        with (
            patch("agent.tools.booking_tools.book") as mock_book,
            patch.object(mode, "_run_agentic_loop", new_callable=AsyncMock) as mock_loop,
            patch.object(mode, "_use_optimized_prompts", return_value=False),
        ):
            mock_book.ainvoke = AsyncMock(return_value=book_result)
            loop_result = MagicMock()
            loop_result.response_text = "No se pudo crear tu turno."
            mock_loop.return_value = loop_result

            result = await mode._handle_completed(state, mode_context)

        assert result.get("error_count") == 1
        assert result.get("appointment_created") is not True
        # mode_context should contain last_error
        ctx = result.get("mode_context", {})
        assert "last_error" in ctx, "last_error must be recorded in mode_context"
        assert "DB connection failed" in ctx["last_error"]

    @pytest.mark.asyncio
    async def test_success_true_creates_appointment(self):
        """book() returns {success: True} → happy path, appointment_created=True."""
        mode = make_booking_mode("¡Turno confirmado!")
        state = make_completed_state()
        mode_context = state["mode_context"]

        book_result = {
            "success": True,
            "appointment_id": "appt-xyz",
        }

        with (
            patch("agent.tools.booking_tools.book") as mock_book,
            patch.object(mode, "_run_agentic_loop", new_callable=AsyncMock) as mock_loop,
            patch.object(mode, "_use_optimized_prompts", return_value=False),
        ):
            mock_book.ainvoke = AsyncMock(return_value=book_result)
            loop_result = MagicMock()
            loop_result.response_text = "¡Turno confirmado!"
            mock_loop.return_value = loop_result

            result = await mode._handle_completed(state, mode_context)

        assert result.get("appointment_created") is True
        assert result.get("error_count") is None or result.get("error_count") == 0

    @pytest.mark.asyncio
    async def test_error_count_accumulates_from_existing_count(self):
        """If error_count is already 2, it becomes 3 after another failure."""
        mode = make_booking_mode()
        state = make_completed_state()
        state["error_count"] = 2
        mode_context = state["mode_context"]

        book_result = {"success": False, "error_code": "TIMEOUT"}

        with (
            patch("agent.tools.booking_tools.book") as mock_book,
            patch.object(mode, "_run_agentic_loop", new_callable=AsyncMock) as mock_loop,
            patch.object(mode, "_use_optimized_prompts", return_value=False),
        ):
            mock_book.ainvoke = AsyncMock(return_value=book_result)
            loop_result = MagicMock()
            loop_result.response_text = "Error."
            mock_loop.return_value = loop_result

            result = await mode._handle_completed(state, mode_context)

        assert result.get("error_count") == 3


# =============================================================================
# Change 2: greeting_mode.handle — customer creation failure escalates
# =============================================================================


class TestGreetingModeCustomerCreationFailure:
    """
    When _create_customer() returns None (DB down, no phone, etc.),
    the greeting flow MUST escalate to ESCALATION instead of silently
    proceeding with no customer_id.
    """

    @pytest.mark.asyncio
    async def test_customer_creation_failure_escalates(self):
        """_create_customer returns None → mode transitions to ESCALATION."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-999", "+34611000000")
        state["customer_name"] = None  # new customer
        state["customer_id"] = None
        state["pending_whatsapp_name"] = "Laura"
        state["error_count"] = 0
        intent = IntentResult(intent="greet", confidence=0.9, raw_input="hola", mode_hint="GREETING")

        with patch.object(mode, "_create_customer", new_callable=AsyncMock, return_value=None):
            result = await mode.handle(state, intent)

        # Must escalate
        assert result.get("current_mode") == "ESCALATION", (
            f"Expected ESCALATION, got {result.get('current_mode')}"
        )
        # Must increment error_count
        assert result.get("error_count", 0) >= 1, "error_count must be incremented on escalation"
        # Must NOT set customer_id
        assert result.get("customer_id") is None

    @pytest.mark.asyncio
    async def test_customer_creation_success_continues_normally(self):
        """_create_customer returns a valid ID → normal GENERAL transition."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-999", "+34611000000")
        state["customer_name"] = None
        state["customer_id"] = None
        state["pending_whatsapp_name"] = "Laura"
        state["error_count"] = 0
        intent = IntentResult(intent="greet", confidence=0.9, raw_input="hola", mode_hint="GREETING")

        with (
            patch.object(mode, "_create_customer", new_callable=AsyncMock, return_value="cust-new-1"),
            patch.object(mode, "_render_layered_response", new_callable=AsyncMock, return_value="¡Hola!"),
            patch.object(mode, "_maybe_prepend_intro", return_value=("¡Hola!", False)),
        ):
            result = await mode.handle(state, intent)

        # Must go to GENERAL, not ESCALATION
        assert result.get("current_mode") != "ESCALATION"
        assert result.get("customer_id") == "cust-new-1"

    @pytest.mark.asyncio
    async def test_existing_customer_id_skips_creation_and_escalation(self):
        """If customer_id already exists in state, skip creation — no escalation even if _create_customer would fail."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-999", "+34611000000")
        state["customer_name"] = None
        state["customer_id"] = "pre-existing-cust"
        state["pending_whatsapp_name"] = "Laura"
        state["error_count"] = 0
        intent = IntentResult(intent="greet", confidence=0.9, raw_input="hola", mode_hint="GREETING")

        with (
            patch.object(mode, "_create_customer", new_callable=AsyncMock, return_value=None),
            patch.object(mode, "_render_layered_response", new_callable=AsyncMock, return_value="¡Hola!"),
            patch.object(mode, "_maybe_prepend_intro", return_value=("¡Hola!", False)),
        ):
            result = await mode.handle(state, intent)

        # Must NOT escalate — pre-existing ID is fine
        assert result.get("current_mode") != "ESCALATION"

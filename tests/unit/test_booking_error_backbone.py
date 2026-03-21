"""
Unit tests for Phase A: Error Backbone (booking-bugs-fix).

Covers:
- A.1: Error fields in BookingDraftContext
- A.2: _persist_booking_error / _clear_booking_error helpers
- A.3: error_count increment on technical errors, NOT on no-availability
- A.4: Error context in build_step_context
- A.5: Escalation-ready state after 3 consecutive errors
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.booking_context import (
    BOOKING_PRESERVE_ON_GENERAL,
    BookingDraftContext,
    BookingSubstep,
)
from agent.modes.booking_mode import BookingMode
from agent.prompts.loader import build_step_context
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def make_mock_llm(response_text: str = "Hubo un problema.") -> AsyncMock:
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def make_booking_mode(llm_response: str = "Hubo un problema.") -> BookingMode:
    return BookingMode(tools=[], llm_client=make_mock_llm(llm_response))


def make_slot_selection_state(error_count: int = 0) -> dict:
    """State ready for slot_selection with valid booking context."""
    state = create_initial_state("conv-err-test", "+34611000000")
    state["customer_id"] = "cust-abc-123"
    state["customer_name"] = "Ana"
    state["error_count"] = error_count
    state["messages"] = [
        {"role": "user", "content": "Quiero el martes", "timestamp": "2026-03-20T10:00:00"},
    ]
    state["mode_context"] = {
        "booking_step": BookingSubstep.SLOT_SELECTION.value,
        "service_name": "Cortar",
        "service_id": "svc-001",
        "service_category": "Mujer",
        "service_duration_minutes": 45,
        "stylist_id": "550e8400-e29b-41d4-a716-446655440000",
        "stylist_name": "Pilar",
    }
    return state


def make_stylist_selection_state(error_count: int = 0) -> dict:
    """State ready for stylist_selection with valid booking context."""
    state = create_initial_state("conv-err-test-2", "+34611000001")
    state["customer_id"] = "cust-abc-456"
    state["customer_name"] = "María"
    state["error_count"] = error_count
    state["messages"] = [
        {"role": "user", "content": "Cualquiera", "timestamp": "2026-03-20T10:00:00"},
    ]
    state["mode_context"] = {
        "booking_step": BookingSubstep.STYLIST_SELECTION.value,
        "service_name": "Cortar",
        "service_id": "svc-001",
        "service_category": "Mujer",
        "service_duration_minutes": 45,
    }
    return state


def make_intent(intent: str = "book") -> IntentResult:
    return IntentResult(intent=intent, confidence=0.9, raw_input="reservar", mode_hint="BOOKING")


# =============================================================================
# A.1 + A.2: Error fields and helpers
# =============================================================================


class TestPersistBookingError:
    """Test _persist_booking_error helper."""

    def test_sets_all_error_fields(self):
        mode = make_booking_mode()
        ctx = {"booking_step": "slot_selection", "service_name": "Cortar"}

        updated, delta = mode._persist_booking_error(
            ctx, "ConnectionError: DB timeout", BookingSubstep.SLOT_SELECTION
        )

        assert updated["last_booking_error"] == "ConnectionError: DB timeout"
        assert updated["booking_error_count"] == 1
        assert updated["retryable_step"] == "slot_selection"
        assert delta == 1

    def test_increments_existing_error_count(self):
        mode = make_booking_mode()
        ctx = {
            "booking_step": "slot_selection",
            "booking_error_count": 1,
            "last_booking_error": "previous error",
            "retryable_step": "slot_selection",
        }

        updated, delta = mode._persist_booking_error(
            ctx, "New error", BookingSubstep.SLOT_SELECTION
        )

        assert updated["booking_error_count"] == 2
        assert updated["last_booking_error"] == "New error"
        assert delta == 1

    def test_does_not_mutate_original_context(self):
        mode = make_booking_mode()
        ctx = {"booking_step": "slot_selection"}

        updated, _ = mode._persist_booking_error(
            ctx, "error", BookingSubstep.SLOT_SELECTION
        )

        assert "last_booking_error" not in ctx
        assert "last_booking_error" in updated


class TestClearBookingError:
    """Test _clear_booking_error helper."""

    def test_removes_all_error_fields(self):
        ctx = {
            "booking_step": "customer_name",
            "service_name": "Cortar",
            "last_booking_error": "some error",
            "booking_error_count": 2,
            "retryable_step": "slot_selection",
        }

        result = BookingMode._clear_booking_error(ctx)

        assert "last_booking_error" not in result
        assert "booking_error_count" not in result
        assert "retryable_step" not in result
        # Non-error fields preserved
        assert result["booking_step"] == "customer_name"
        assert result["service_name"] == "Cortar"

    def test_noop_when_no_error_fields(self):
        ctx = {"booking_step": "slot_selection", "service_name": "Cortar"}

        result = BookingMode._clear_booking_error(ctx)

        assert result == ctx


class TestDetectToolTechnicalError:
    """Test _detect_tool_technical_error helper."""

    def test_returns_none_for_successful_results(self):
        results = {
            "check_availability": {
                "available_slots": [{"start_time": "2026-03-20T10:00:00"}],
            }
        }
        assert BookingMode._detect_tool_technical_error(results) is None

    def test_returns_none_for_empty_slots_no_error(self):
        """No-availability is NOT a technical error."""
        results = {
            "check_availability": {
                "available_slots": [],
            }
        }
        assert BookingMode._detect_tool_technical_error(results) is None

    def test_returns_error_for_error_with_no_slots(self):
        """Error field with no valid results = technical error."""
        results = {
            "check_availability": {
                "error": "Database connection failed",
                "available_slots": [],
            }
        }
        error = BookingMode._detect_tool_technical_error(results)
        assert error is not None
        assert "Database connection failed" in error

    def test_returns_none_for_error_with_valid_slots(self):
        """Error field WITH valid results = not a pure technical error."""
        results = {
            "check_availability": {
                "error": "partial failure",
                "available_slots": [{"start_time": "2026-03-20T10:00:00"}],
            }
        }
        assert BookingMode._detect_tool_technical_error(results) is None

    def test_returns_error_for_find_next_available(self):
        results = {
            "find_next_available": {
                "error": "timeout",
            }
        }
        error = BookingMode._detect_tool_technical_error(results)
        assert error is not None
        assert "timeout" in error


# =============================================================================
# A.1: Error fields in BOOKING_PRESERVE_ON_GENERAL
# =============================================================================


class TestErrorFieldsPreserved:
    """Verify error fields survive GENERAL digressions."""

    def test_error_fields_in_preserve_set(self):
        assert "last_booking_error" in BOOKING_PRESERVE_ON_GENERAL
        assert "booking_error_count" in BOOKING_PRESERVE_ON_GENERAL
        assert "retryable_step" in BOOKING_PRESERVE_ON_GENERAL


# =============================================================================
# A.3: Technical error increments error_count in _handle_slot_selection
# =============================================================================


class TestSlotSelectionErrorCount:
    """Verify error_count behavior in _handle_slot_selection."""

    @pytest.mark.asyncio
    async def test_agentic_loop_exception_increments_error_count(self):
        """Tool exception during slot_selection → error_count incremented."""
        mode = make_booking_mode()
        state = make_slot_selection_state(error_count=1)

        with patch.object(
            mode, "_run_agentic_loop", side_effect=ConnectionError("DB down")
        ):
            result = await mode._handle_slot_selection(state, state["mode_context"])

        assert result["error_count"] == 2
        assert result["mode_context"]["last_booking_error"] == "DB down"
        assert result["mode_context"]["booking_error_count"] == 1
        assert result["mode_context"]["retryable_step"] == "slot_selection"

    @pytest.mark.asyncio
    async def test_tool_error_in_results_increments_error_count(self):
        """Tool returns {"error": "..."} with no slots → error_count incremented."""
        mode = make_booking_mode()
        state = make_slot_selection_state(error_count=0)

        mock_result = MagicMock()
        mock_result.response_text = "Hubo un problema buscando horarios."
        mock_result.tool_results = {
            "check_availability": {
                "error": "Service unavailable",
                "available_slots": [],
            }
        }
        mock_result.tool_events = []

        with patch.object(mode, "_run_agentic_loop", return_value=mock_result):
            result = await mode._handle_slot_selection(state, state["mode_context"])

        assert result["error_count"] == 1
        assert "Service unavailable" in result["mode_context"]["last_booking_error"]
        assert result["mode_context"]["retryable_step"] == "slot_selection"

    @pytest.mark.asyncio
    async def test_empty_slots_does_not_increment_error_count(self):
        """Empty slots without error key → no error_count increment."""
        mode = make_booking_mode()
        state = make_slot_selection_state(error_count=2)

        mock_result = MagicMock()
        mock_result.response_text = "No hay huecos disponibles."
        mock_result.tool_results = {
            "check_availability": {
                "available_slots": [],
            }
        }
        mock_result.tool_events = []

        with patch.object(mode, "_run_agentic_loop", return_value=mock_result):
            result = await mode._handle_slot_selection(state, state["mode_context"])

        # error_count should NOT appear in result (no increment)
        assert "error_count" not in result


class TestStylistSelectionErrorCount:
    """Verify error_count behavior in _handle_stylist_selection (prefetch path)."""

    @pytest.mark.asyncio
    async def test_prefetch_tool_error_increments_error_count(self):
        """PrefetchToolError → error_count incremented."""
        mode = make_booking_mode()
        state = make_stylist_selection_state(error_count=0)

        with patch.object(
            mode,
            "_prefetch_stylist_options",
            return_value={"status": "tool_error", "error_detail": "GCal API timeout"},
        ), patch.object(
            mode,
            "_populate_recurrent_stylist",
            return_value=state["mode_context"],
        ):
            result = await mode._handle_stylist_selection(state, state["mode_context"])

        assert result["error_count"] == 1
        assert result["mode_context"]["last_booking_error"] == "GCal API timeout"
        assert result["mode_context"]["retryable_step"] == "stylist_selection"

    @pytest.mark.asyncio
    async def test_prefetch_no_availability_does_not_increment_error_count(self):
        """PrefetchNoAvailability → error_count NOT incremented."""
        mode = make_booking_mode()
        state = make_stylist_selection_state(error_count=2)

        with patch.object(
            mode,
            "_prefetch_stylist_options",
            return_value={"status": "no_availability", "error_detail": "No stylists available"},
        ), patch.object(
            mode,
            "_populate_recurrent_stylist",
            return_value=state["mode_context"],
        ):
            result = await mode._handle_stylist_selection(state, state["mode_context"])

        # No error_count in result means no increment
        assert "error_count" not in result


# =============================================================================
# A.3: _handle_completed preserves existing error_count increment
# =============================================================================


class TestHandleCompletedErrorBackbone:
    """Verify _handle_completed still increments error_count and also sets backbone fields."""

    @pytest.mark.asyncio
    async def test_book_failure_sets_error_backbone_fields(self):
        """book() exception → error_count incremented AND backbone fields set."""
        mode = make_booking_mode()
        state = create_initial_state("conv-err-completed", "+34611000002")
        state["customer_id"] = "cust-abc-789"
        state["customer_name"] = "Laura"
        state["error_count"] = 0
        state["mode_context"] = {
            "booking_step": BookingSubstep.COMPLETED.value,
            "service_name": "Cortar",
            "stylist_id": "stylist-001",
            "selected_slot": {"start_time": "2026-04-01T10:00:00"},
            "first_name": "Laura",
            "notes": "",
        }

        with patch(
            "agent.tools.booking_tools.book",
        ) as mock_book:
            mock_book.ainvoke = AsyncMock(side_effect=Exception("Booking service down"))
            result = await mode._handle_completed(state, state["mode_context"])

        assert result["error_count"] == 1
        assert result["mode_context"]["last_booking_error"] == "Booking service down"
        assert result["mode_context"]["booking_error_count"] == 1
        assert result["mode_context"]["retryable_step"] == "completed"
        # Step should go back to confirmation for retry
        assert result["mode_context"]["booking_step"] == BookingSubstep.CONFIRMATION.value


# =============================================================================
# A.4: Error context in build_step_context
# =============================================================================


class TestBuildStepContextErrorInjection:
    """Verify build_step_context injects error context when present."""

    def test_includes_error_context_when_present(self):
        state = create_initial_state("conv-prompt-test", "+34611000003")
        mode_context = {
            "booking_step": "slot_selection",
            "service_name": "Cortar",
            "last_booking_error": "Database connection timeout",
            "booking_error_count": 2,
            "retryable_step": "slot_selection",
        }

        context_str = build_step_context(state, mode_context)

        assert "ERROR TECNICO" in context_str
        assert "Database connection timeout" in context_str
        assert "intento 2" in context_str
        assert "slot_selection" in context_str

    def test_no_error_context_when_absent(self):
        state = create_initial_state("conv-prompt-test-2", "+34611000004")
        mode_context = {
            "booking_step": "slot_selection",
            "service_name": "Cortar",
        }

        context_str = build_step_context(state, mode_context)

        assert "ERROR TECNICO" not in context_str
        assert "last_booking_error" not in context_str


# =============================================================================
# A.5: Escalation-ready state after 3 consecutive technical errors
# =============================================================================


class TestEscalationReadyState:
    """Verify that 3 consecutive technical errors produce error_count >= 3."""

    @pytest.mark.asyncio
    async def test_third_error_reaches_escalation_threshold(self):
        """After 2 prior errors, a third technical error → error_count=3."""
        mode = make_booking_mode()
        state = make_slot_selection_state(error_count=2)

        with patch.object(
            mode, "_run_agentic_loop", side_effect=RuntimeError("Crash #3")
        ):
            result = await mode._handle_slot_selection(state, state["mode_context"])

        # error_count should now be 3 (auto-escalation threshold)
        assert result["error_count"] == 3

    @pytest.mark.asyncio
    async def test_error_cleared_on_successful_advance(self):
        """When slot_selection advances to customer_name, error fields are cleared."""
        mode = make_booking_mode()
        state = make_slot_selection_state(error_count=1)
        state["mode_context"]["last_booking_error"] = "previous error"
        state["mode_context"]["booking_error_count"] = 1
        state["mode_context"]["retryable_step"] = "slot_selection"

        mock_result = MagicMock()
        mock_result.response_text = "Perfecto, el martes a las 10:00."
        mock_result.tool_results = {
            "check_availability": {
                "available_slots": [
                    {"start_time": "2026-03-24T10:00:00", "stylist_name": "Pilar"}
                ],
            }
        }
        mock_result.tool_events = []

        with patch.object(mode, "_run_agentic_loop", return_value=mock_result):
            result = await mode._handle_slot_selection(state, state["mode_context"])

        # If step advanced, error fields should be cleared
        ctx = result["mode_context"]
        if ctx.get("booking_step") != "slot_selection":
            assert "last_booking_error" not in ctx
            assert "booking_error_count" not in ctx
            assert "retryable_step" not in ctx

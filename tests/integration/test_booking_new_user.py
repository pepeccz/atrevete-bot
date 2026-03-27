"""
Integration tests for new WhatsApp user booking flow (GAP 1 & GAP 5).

Verifies that BookingMode.handle() handles the case where customer_id is None
but customer_phone and pending_whatsapp_name are available in state.

Test Coverage:
- Scenario 5.1: New WhatsApp user → _create_customer_if_needed silently creates
  customer → book() proceeds without NO_CUSTOMER_ID rejection.
- Scenario 5.2: New WhatsApp user with no phone → book() rejected with
  NO_CUSTOMER_ID, error_count NOT incremented (rejection ≠ failure).

All LLM calls, DB calls, and tool calls are mocked — tests do NOT require a
real LLM, DB, or Redis.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.base import AgenticLoopResult, ToolCallRejection
from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import BookingMode
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def _make_mode() -> BookingMode:
    """Create a BookingMode with a mocked LLM."""
    mock_llm = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = "ok"
    mock_response.tool_calls = []
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    return BookingMode(tools=[], llm_client=mock_llm)


def _make_booking_state(
    *,
    customer_id: str | None = None,
    customer_phone: str | None = None,
    pending_whatsapp_name: str | None = None,
    mode_context: dict | None = None,
) -> dict:
    """Build a ConversationState for new-user booking tests."""
    state = create_initial_state("integration-new-user-001", customer_phone or "+34600000001")
    state["customer_id"] = customer_id
    state["customer_name"] = None
    state["customer_phone"] = customer_phone
    state["pending_whatsapp_name"] = pending_whatsapp_name
    state["is_first_interaction"] = False
    state["current_mode"] = "BOOKING"
    state["mode_context"] = mode_context or {}
    state["user_message"] = "quiero reservar"
    state["messages"] = [{"role": "user", "content": "quiero reservar"}]
    return state


def _make_intent() -> IntentResult:
    return IntentResult(intent="book", confidence=0.9, raw_input="test", mode_hint="BOOKING")


# =============================================================================
# Scenario 5.1 — New WhatsApp user: _create_customer_if_needed creates customer
# =============================================================================


class TestNewUserBookingCreation:
    """Scenario 5.1 — State has phone + name but no customer_id.

    _create_customer_if_needed must silently create the customer so book()
    can proceed without the LLM having to call manage_customer first.
    """

    @pytest.mark.asyncio
    async def test_pre_tool_call_creates_customer_and_allows_book(self):
        """With phone set and customer_id=None, _create_customer_if_needed
        is called and creates the customer — NO_CUSTOMER_ID is not returned."""
        mode = _make_mode()

        # ctx mimics what handle() builds from mode_context in the real flow:
        # - customer_name IS set (collected via name extraction / pending_whatsapp_name)
        # - customer_id is NOT set (manage_customer was never called)
        # The NO_CUSTOMER_NAME guard passes because name is present.
        # The NO_CUSTOMER_ID guard triggers _create_customer_if_needed.
        ctx = BookingContext(
            customer_id=None,
            customer_name="Lucía",  # Name already collected from pending_whatsapp_name
            offered_slots=[
                {
                    "stylist_id": "sty-001",
                    "time": "10:00",
                    "date": "2026-04-10",
                    "full_datetime": "2026-04-10T10:00:00+02:00",
                    "stylist_name": "Ana",
                }
            ],
            selected_services=["Corte de Dama"],
            notes_asked=True,
            confirmation_shown=True,
        )
        mode._ctx = ctx

        state = _make_booking_state(
            customer_id=None,
            customer_phone="+34600000001",
            pending_whatsapp_name="Lucía",
        )
        mode._current_state = state

        # Mock _create_customer_if_needed at the method level to return a UUID
        with patch.object(
            mode,
            "_create_customer_if_needed",
            new_callable=AsyncMock,
            return_value="new-auto-uuid-001",
        ) as mock_create:
            # book() tool_args with slot_index
            tool_args = {"slot_index": 1}
            result = await mode._pre_tool_call("book", tool_args)

        # The call must NOT be a rejection
        assert not isinstance(result, ToolCallRejection), (
            f"Expected book() to proceed but got ToolCallRejection: {result}"
        )
        # _create_customer_if_needed was called
        mock_create.assert_called_once()
        # customer_id must be set on ctx
        assert ctx.customer_id == "new-auto-uuid-001"

    @pytest.mark.asyncio
    async def test_customer_id_populated_in_mode_context_after_creation(self):
        """mode_context returned by _build_response must include customer_id
        after silent creation."""
        mode = _make_mode()

        ctx = BookingContext(
            customer_id="auto-created-uuid",
            customer_name="Lucía",
            selected_services=["Corte de Dama"],
            book_failure_count=0,
        )

        state = _make_booking_state(
            customer_id=None,
            customer_phone="+34600000001",
            pending_whatsapp_name="Lucía",
        )

        result_obj = AgenticLoopResult(
            response_text="¿Qué servicio deseas?",
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            updates = mode._build_response(state, ctx, result_obj, prev_book_failures=0)

        mode_ctx = updates.get("mode_context", {})
        assert mode_ctx.get("customer_id") == "auto-created-uuid"
        assert "error_count" not in updates  # No failure → error_count unchanged


# =============================================================================
# Scenario 5.2 — New WhatsApp user with no phone → graceful rejection
# =============================================================================


class TestNewUserBookingNoPhone:
    """Scenario 5.2 — No phone in state: _create_customer_if_needed returns None,
    book() is rejected with NO_CUSTOMER_ID. error_count is NOT incremented."""

    @pytest.mark.asyncio
    async def test_pre_tool_call_rejects_when_no_phone(self):
        """With customer_id=None and no phone, book() must be rejected."""
        mode = _make_mode()

        # customer_name IS set (collected via name extraction), customer_id is NOT.
        # Without phone, _create_customer_if_needed returns None → NO_CUSTOMER_ID.
        ctx = BookingContext(
            customer_id=None,
            customer_name="Lucía",  # Name already collected from conversation
            offered_slots=[
                {
                    "stylist_id": "sty-001",
                    "time": "10:00",
                    "date": "2026-04-10",
                    "full_datetime": "2026-04-10T10:00:00+02:00",
                    "stylist_name": "Ana",
                }
            ],
            selected_services=["Corte de Dama"],
            notes_asked=True,
            confirmation_shown=True,
        )
        mode._ctx = ctx

        state = _make_booking_state(
            customer_id=None,
            customer_phone=None,  # No phone → can't auto-create
            pending_whatsapp_name="Lucía",
        )
        mode._current_state = state

        tool_args = {"slot_index": 1}
        result = await mode._pre_tool_call("book", tool_args)

        # Must be rejected with NO_CUSTOMER_ID
        assert isinstance(result, ToolCallRejection), (
            f"Expected ToolCallRejection but got: {result}"
        )
        assert result.error_code == "NO_CUSTOMER_ID"

    @pytest.mark.asyncio
    async def test_rejection_does_not_increment_error_count(self):
        """ToolCallRejection (not a booking failure) must NOT increment error_count.

        _build_response only increments error_count when book_failure_count
        increased (i.e., book() was actually called and failed). A rejection
        before book() runs must not be counted as a failure.
        """
        mode = _make_mode()

        ctx = BookingContext(
            customer_id=None,
            customer_name=None,
            selected_services=["Corte de Dama"],
            book_failure_count=0,  # No failures occurred — book() was rejected
        )

        state = _make_booking_state(
            customer_id=None,
            customer_phone=None,
        )
        state["error_count"] = 0

        result_obj = AgenticLoopResult(
            response_text="Necesito tu teléfono para continuar.",
            tool_results={},  # book() was never called
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            updates = mode._build_response(state, ctx, result_obj, prev_book_failures=0)

        # error_count must NOT be incremented — rejection ≠ failure
        assert "error_count" not in updates, (
            f"error_count should not be in updates but got: {updates.get('error_count')}"
        )

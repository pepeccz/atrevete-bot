"""Unit tests for booking _pre_tool_call gates.

Coverage (simplified after booking-mode-simplification Phase 2-4):
- _pre_tool_call Gate 1: reject book() when confirmation_shown is False
- _pre_tool_call Gate 2: reject book() when customer_id missing
- _pre_tool_call Gate 3: slot_index → UUID resolution
- _pre_tool_call passthrough: non-book tools (search_services, manage_customer, etc.)
- _pre_tool_call availability tools: clear stale slot state
- get_tools() circuit breaker via getattr fallback (book_failure_count via getattr)
- ToolCallRejection in agentic loop

Removed in Phase 4 (fields/functions deleted from BookingMode/BookingContext):
- Guards for offered_slots empty, needs_availability_refresh, selected_services empty,
  customer_name missing — these guards no longer exist in _pre_tool_call
- _detect_confirmation_exchange tests — function deleted
- book_failure_count, notes_asked, confirmation_gate_turn_count fields — deleted
- TestToolChoicePendingGuard — _detect_tool_skips deleted
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.modes.base import ToolCallRejection
from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import BookingMode


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


# =============================================================================
# Gate 1: reject book() when confirmation_shown is False
# =============================================================================


class TestConfirmationGate:
    """Confirmation gate: _pre_tool_call rejects book() when confirmation_shown is False."""

    @pytest.mark.asyncio
    async def test_confirmation_gate_blocks_book_without_summary(self):
        """All booking data collected but confirmation_shown=False -> CONFIRMATION_NOT_SHOWN."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            offered_slots=[
                {
                    "stylist_id": "s1",
                    "time": "10:00",
                    "start_time": "2026-03-27T10:00:00+01:00",
                    "stylist_name": "Maria",
                }
            ],
            selected_services=["Corte Dama"],
            customer_name="Laura García",
            customer_id="cust-123",
            confirmation_shown=False,
        )
        args = {"customer_id": "cust-123", "slot_index": 1}

        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "CONFIRMATION_NOT_SHOWN"

    @pytest.mark.asyncio
    async def test_confirmation_gate_allows_book_after_confirmation(self):
        """confirmation_shown=True -> book() proceeds (no rejection from confirmation gate)."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            offered_slots=[
                {
                    "stylist_id": "s1",
                    "time": "10:00",
                    "start_time": "2026-03-27T10:00:00+01:00",
                    "stylist_name": "Maria",
                }
            ],
            selected_services=["Corte Dama"],
            customer_name="Laura García",
            customer_id="cust-123",
            confirmation_shown=True,
        )
        args = {"customer_id": "cust-123", "slot_index": 1}

        result = await mode._pre_tool_call("book", args)

        # No confirmation rejection — returned modified args dict (or other rejection)
        if isinstance(result, ToolCallRejection):
            assert result.error_code != "CONFIRMATION_NOT_SHOWN"


# =============================================================================
# Gate 2: reject book() when customer_id missing
# =============================================================================


class TestGuardNoCustomerId:
    """_pre_tool_call rejects book() when customer_id is None in ctx and args."""

    @pytest.mark.asyncio
    async def test_rejects_book_when_customer_id_none_and_no_args(self):
        """ctx.customer_id=None and args has no customer_id → NO_CUSTOMER_ID."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            confirmation_shown=True,
            customer_id=None,
        )
        args = {}  # No customer_id in args either

        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_CUSTOMER_ID"

    @pytest.mark.asyncio
    async def test_injects_customer_id_from_context(self):
        """ctx.customer_id set → injects into tool_args."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            confirmation_shown=True,
            customer_id="cust-from-ctx",
            offered_slots=[{"stylist_id": "s1", "start_time": "2026-03-27T10:00:00"}],
            selected_services=["Corte"],
        )
        args = {"slot_index": 1}

        result = await mode._pre_tool_call("book", args)

        assert not isinstance(result, ToolCallRejection)
        assert result["customer_id"] == "cust-from-ctx"


# =============================================================================
# Gate 3: slot_index → UUID resolution
# =============================================================================


class TestSlotIndexResolution:
    """slot_index → UUID resolution in _pre_tool_call."""

    @pytest.mark.asyncio
    async def test_slot_index_resolved_to_uuid(self):
        """slot_index=1 → resolves to offered_slots[0] stylist_id and start_time."""
        mode = _make_mode()
        ctx = BookingContext()
        ctx.confirmation_shown = True
        ctx.customer_id = "cust-uuid"
        ctx.offered_slots = [
            {"stylist_id": "s1", "start_time": "2026-04-10T09:00", "time": "09:00"},
            {"stylist_id": "s2", "start_time": "2026-04-10T10:00", "time": "10:00"},
        ]
        ctx.selected_services = ["Corte"]
        mode._ctx = ctx
        result = await mode._pre_tool_call("book", {"slot_index": 1, "customer_id": "cust-uuid"})
        assert not isinstance(result, ToolCallRejection)
        assert result["stylist_id"] == "s1"
        assert result["start_time"] == "2026-04-10T09:00"

    @pytest.mark.asyncio
    async def test_slot_index_2_resolves_correctly(self):
        """slot_index=2 → resolves to offered_slots[1]."""
        mode = _make_mode()
        ctx = BookingContext()
        ctx.confirmation_shown = True
        ctx.customer_id = "cust-uuid"
        ctx.offered_slots = [
            {"stylist_id": "s1", "start_time": "2026-04-10T09:00"},
            {"stylist_id": "s2", "start_time": "2026-04-10T10:00"},
        ]
        ctx.selected_services = ["Corte"]
        mode._ctx = ctx
        result = await mode._pre_tool_call("book", {"slot_index": 2, "customer_id": "cust-uuid"})
        assert not isinstance(result, ToolCallRejection)
        assert result["stylist_id"] == "s2"
        assert result["start_time"] == "2026-04-10T10:00"

    @pytest.mark.asyncio
    async def test_invalid_slot_index_rejected(self):
        """slot_index out of range → INVALID_SLOT_INDEX."""
        mode = _make_mode()
        ctx = BookingContext()
        ctx.confirmation_shown = True
        ctx.customer_id = "cust-uuid"
        ctx.offered_slots = [{"stylist_id": "s1", "start_time": "2026-04-10T09:00"}]
        ctx.selected_services = ["Corte"]
        mode._ctx = ctx
        result = await mode._pre_tool_call("book", {"slot_index": 99, "customer_id": "cust-uuid"})
        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "INVALID_SLOT_INDEX"

    @pytest.mark.asyncio
    async def test_availability_tool_clears_slot_state(self):
        """check_availability/find_next_available clears offered_slots and selected_slot."""
        mode = _make_mode()
        ctx = BookingContext()
        ctx.offered_slots = [{"stylist_id": "s1"}]
        ctx.selected_slot = {"stylist_id": "s1"}
        mode._ctx = ctx
        await mode._pre_tool_call("find_next_available", {})
        assert ctx.offered_slots == []
        assert ctx.selected_slot is None

    @pytest.mark.asyncio
    async def test_check_availability_clears_slot_state(self):
        """check_availability also clears slot state."""
        mode = _make_mode()
        ctx = BookingContext()
        ctx.offered_slots = [{"stylist_id": "s1"}]
        ctx.selected_slot = {"stylist_id": "s1"}
        mode._ctx = ctx
        await mode._pre_tool_call("check_availability", {"date": "2026-03-27", "stylist_id": "s1"})
        assert ctx.offered_slots == []
        assert ctx.selected_slot is None


# =============================================================================
# Non-book tools pass through unmodified
# =============================================================================


class TestNonBookToolsPassthrough:
    """Non-book tools (except availability tools) should pass through unchanged."""

    @pytest.mark.asyncio
    async def test_search_services_passthrough(self):
        mode = _make_mode()
        mode._ctx = BookingContext()
        args = {"query": "corte"}

        result = await mode._pre_tool_call("search_services", args)

        assert result == {"query": "corte"}

    @pytest.mark.asyncio
    async def test_manage_customer_passthrough(self):
        mode = _make_mode()
        mode._ctx = BookingContext()
        args = {"action": "get", "phone": "+34612345678"}

        result = await mode._pre_tool_call("manage_customer", args)

        assert result == {"action": "get", "phone": "+34612345678"}


# =============================================================================
# Circuit breaker: get_tools() uses getattr for book_failure_count
# =============================================================================


class TestCircuitBreakerGetTools:
    """get_tools() uses getattr(ctx, 'book_failure_count', 0) — safe with any ctx."""

    def test_includes_book_when_no_ctx(self):
        """No _ctx attribute at all -> all tools returned (safe fallback)."""
        mode = _make_mode()
        # Don't set _ctx at all

        tools = mode.get_tools()
        tool_names = [t.name for t in tools]

        assert "book" in tool_names

    def test_other_tools_always_present(self):
        """booking tools are always present when book_failure_count=0."""
        mode = _make_mode()
        mode._ctx = BookingContext()

        tools = mode.get_tools()
        tool_names = [t.name for t in tools]

        assert "check_availability" in tool_names
        assert "search_services" in tool_names
        assert "manage_customer" in tool_names
        assert "book" in tool_names


# =============================================================================
# ToolCallRejection in agentic loop
# =============================================================================


class TestToolCallRejectionInAgenticLoop:
    """ToolCallRejection skips ainvoke, produces structured ToolMessage."""

    @pytest.mark.asyncio
    async def test_rejection_skips_ainvoke_and_produces_tool_message(self):
        """When _pre_tool_call returns ToolCallRejection, tool.ainvoke is NOT called."""
        mode = _make_mode()

        # Set up context that will cause CONFIRMATION_NOT_SHOWN rejection
        mode._ctx = BookingContext(
            confirmation_shown=False,
        )

        # Create a mock tool for "book"
        mock_book_tool = MagicMock()
        mock_book_tool.name = "book"
        mock_book_tool.ainvoke = AsyncMock(return_value={"success": True})

        # Set up LLM to return a tool call on first invocation, then plain text
        tool_call_response = MagicMock()
        tool_call_response.content = ""
        tool_call_response.tool_calls = [
            {"name": "book", "args": {"customer_id": "cust-1"}, "id": "call-1"}
        ]
        tool_call_response.usage_metadata = None
        tool_call_response.response_metadata = {}

        final_response = MagicMock()
        final_response.content = "No tienes disponibilidad consultada."
        final_response.tool_calls = []
        final_response.usage_metadata = None
        final_response.response_metadata = {}

        mock_llm = AsyncMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(side_effect=[tool_call_response, final_response])
        mode.llm = mock_llm

        result = await mode._run_agentic_loop(
            messages=[],
            tools=[mock_book_tool],
        )

        # tool.ainvoke should NOT have been called (rejection skips it)
        mock_book_tool.ainvoke.assert_not_called()

        # The tool_results should contain the rejection dict
        assert "book" in result.tool_results
        rejection_result = result.tool_results["book"][0]
        assert rejection_result["rejected"] is True
        assert rejection_result["error_code"] == "CONFIRMATION_NOT_SHOWN"
        assert rejection_result["tool_name"] == "book"

    @pytest.mark.asyncio
    async def test_non_rejected_tool_still_invoked(self):
        """When _pre_tool_call returns modified args (not rejection), ainvoke IS called."""
        mode = _make_mode()
        mode._ctx = BookingContext()

        # Create a mock tool for "search_services" (not book, so no guards)
        mock_tool = MagicMock()
        mock_tool.name = "search_services"
        mock_tool.ainvoke = AsyncMock(
            return_value={"services": [{"id": "s1", "name": "Corte"}], "count": 1}
        )

        tool_call_response = MagicMock()
        tool_call_response.content = ""
        tool_call_response.tool_calls = [
            {"name": "search_services", "args": {"query": "corte"}, "id": "call-1"}
        ]
        tool_call_response.usage_metadata = None
        tool_call_response.response_metadata = {}

        final_response = MagicMock()
        final_response.content = "Encontre un servicio."
        final_response.tool_calls = []
        final_response.usage_metadata = None
        final_response.response_metadata = {}

        mock_llm = AsyncMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(side_effect=[tool_call_response, final_response])
        mode.llm = mock_llm

        result = await mode._run_agentic_loop(
            messages=[],
            tools=[mock_tool],
        )

        # tool.ainvoke WAS called
        mock_tool.ainvoke.assert_called_once()

"""Unit tests for booking _pre_tool_call gates.

Coverage (simplified after booking-mode-simplification Phase 2-4):
- _pre_tool_call Gate 1: reject book() when confirmation_shown is False
- _pre_tool_call Gate 2: reject book() when customer_id missing
- _pre_tool_call Gate 3: slot_index → UUID resolution
- _pre_tool_call passthrough: non-book tools (search_services, manage_customer, etc.)
- _pre_tool_call availability tools: clear stale slot state
- get_tools() circuit breaker via getattr fallback (book_failure_count via getattr)
- ToolCallRejection in agentic loop
- TestConfirmationGateHandleFix: handle() flips confirmation_shown on "confirm" intent

Removed in Phase 4 (fields/functions deleted from BookingMode/BookingContext):
- Guards for offered_slots empty, needs_availability_refresh, selected_services empty,
  customer_name missing — these guards no longer exist in _pre_tool_call
- _detect_confirmation_exchange tests — function deleted
- book_failure_count, notes_asked, confirmation_gate_turn_count fields — deleted
- TestToolChoicePendingGuard — _detect_tool_skips deleted
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.base import AgenticLoopResult, ToolCallRejection
from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import BookingMode
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
        # Branch 3 must NOT set confirmation_summary_sent (prevents poison state)
        assert mode._ctx.confirmation_summary_sent is False

    @pytest.mark.asyncio
    async def test_confirmation_gate_blocks_book_without_notes(self):
        """All data except notes → CONFIRMATION_NOT_SHOWN with missing info."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            service_id="svc-1",
            service_name="Corte Dama",
            stylist_id="s1",
            stylist_name="Maria",
            selected_slot={
                "stylist_id": "s1",
                "time": "10:00",
                "start_time": "2026-03-27T10:00:00+01:00",
                "day_label": "Jueves 27",
            },
            selected_services=["Corte Dama"],
            customer_name="Laura García",
            customer_id="cust-123",
            notes=None,
            confirmation_shown=False,
        )
        args = {"customer_id": "cust-123", "slot_index": 1}

        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "CONFIRMATION_NOT_SHOWN"
        assert "Notas" in result.error_message
        # Branch 3 must NOT set confirmation_summary_sent (prevents poison state)
        assert mode._ctx.confirmation_summary_sent is False

    @pytest.mark.asyncio
    async def test_confirmation_gate_generates_summary_with_all_data(self):
        """All data including notes → branch 1: generates summary, sets flag."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            service_id="svc-1",
            service_name="Corte Dama",
            stylist_id="s1",
            stylist_name="Maria",
            selected_slot={
                "stylist_id": "s1",
                "time": "10:00",
                "start_time": "2026-03-27T10:00:00+01:00",
                "day_label": "Jueves 27",
            },
            selected_services=["Corte Dama"],
            customer_name="Laura García",
            customer_id="cust-123",
            notes="Sin preferencias",
            confirmation_shown=False,
        )
        args = {"customer_id": "cust-123", "slot_index": 1}

        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "CONFIRMATION_NOT_SHOWN"
        assert "resumen" in result.error_message.lower() or "confirmo" in result.error_message.lower()
        assert mode._ctx.confirmation_summary_sent is True

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
        """find_next_available clears offered_slots and selected_slot when stylists are shown."""
        mode = _make_mode()
        ctx = BookingContext(prefetched_stylists=[{"name": "Ana", "id": "test-uuid"}])
        ctx.offered_slots = [{"stylist_id": "s1"}]
        ctx.selected_slot = {"stylist_id": "s1"}
        mode._ctx = ctx
        await mode._pre_tool_call("find_next_available", {})
        assert ctx.offered_slots == []
        assert ctx.selected_slot is None

    @pytest.mark.asyncio
    async def test_check_availability_clears_slot_state(self):
        """check_availability clears slot state when stylists are shown."""
        mode = _make_mode()
        ctx = BookingContext(prefetched_stylists=[{"name": "Ana", "id": "test-uuid"}])
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
# Gate: search_services with stylist name → STYLIST_NOT_SERVICE
# =============================================================================


MOCK_STYLISTS = [
    {"name": "Pilar", "id": "uuid-pilar"},
    {"name": "Ana Maria", "id": "uuid-ana-maria"},
    {"name": "Victor", "id": "uuid-victor"},
]


class TestStylistNotServiceGate:
    """_pre_tool_call rejects search_services when query matches a stylist name."""

    @pytest.mark.asyncio
    async def test_s1_rejects_exact_stylist_name(self):
        """S1: search_services('Pilar') with stylists loaded → STYLIST_NOT_SERVICE."""
        mode = _make_mode()
        mode._ctx = BookingContext(prefetched_stylists=MOCK_STYLISTS, stylist_id=None)

        result = await mode._pre_tool_call("search_services", {"query": "Pilar"})

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "STYLIST_NOT_SERVICE"
        assert "uuid-pilar" in result.error_message

    @pytest.mark.asyncio
    async def test_s2_rejects_compound_stylist_name(self):
        """S2: search_services('Ana Maria') → STYLIST_NOT_SERVICE with correct UUID."""
        mode = _make_mode()
        mode._ctx = BookingContext(prefetched_stylists=MOCK_STYLISTS, stylist_id=None)

        result = await mode._pre_tool_call("search_services", {"query": "Ana Maria"})

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "STYLIST_NOT_SERVICE"
        assert "uuid-ana-maria" in result.error_message

    @pytest.mark.asyncio
    async def test_s3_allows_actual_service_query(self):
        """S3: search_services('corte pelo') with stylists loaded → pass through."""
        mode = _make_mode()
        mode._ctx = BookingContext(prefetched_stylists=MOCK_STYLISTS, stylist_id=None)

        result = await mode._pre_tool_call("search_services", {"query": "corte pelo"})

        assert not isinstance(result, ToolCallRejection)
        assert result == {"query": "corte pelo"}

    @pytest.mark.asyncio
    async def test_s4_allows_when_stylist_already_selected(self):
        """S4: stylist_id already set → search_services passes through."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            prefetched_stylists=MOCK_STYLISTS, stylist_id="uuid-pilar"
        )

        result = await mode._pre_tool_call("search_services", {"query": "Pilar"})

        assert not isinstance(result, ToolCallRejection)

    @pytest.mark.asyncio
    async def test_s5_allows_when_no_prefetched_stylists(self):
        """S5: no prefetched stylists → search_services passes through."""
        mode = _make_mode()
        mode._ctx = BookingContext(prefetched_stylists=[], stylist_id=None)

        result = await mode._pre_tool_call("search_services", {"query": "Pilar"})

        assert not isinstance(result, ToolCallRejection)

    @pytest.mark.asyncio
    async def test_s6_case_insensitive_match(self):
        """S6: search_services('pilar') lowercase → STYLIST_NOT_SERVICE."""
        mode = _make_mode()
        mode._ctx = BookingContext(prefetched_stylists=MOCK_STYLISTS, stylist_id=None)

        result = await mode._pre_tool_call("search_services", {"query": "pilar"})

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "STYLIST_NOT_SERVICE"


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


# =============================================================================
# Confirmation gate in handle() — BUG-1 fix (booking-confirmation-and-clarification-fix)
# =============================================================================


def _make_handle_state(mode_context: dict | None = None) -> dict:
    """Build a minimal ConversationState for BookingMode.handle() tests."""
    state = create_initial_state("conv-test", "+34600000000")
    state["current_mode"] = "BOOKING"
    state["is_first_interaction"] = False
    state["messages"] = [{"role": "user", "content": "sí, confirmalo"}]
    state["mode_context"] = mode_context or {}
    return state


def _make_stub_loop_result() -> AgenticLoopResult:
    """Build a minimal AgenticLoopResult to return from mocked _run_agentic_loop."""
    return AgenticLoopResult(
        response_text="Reserva procesada.",
        tool_results={},
    )


class TestConfirmationGateHandleFix:
    """handle() must flip confirmation_shown=True when all gate conditions are met.

    Covers spec scenarios S1/S2/S3 (R1) and lock-in tests for S4/S5/S6 (R3).
    The underlying BUG-1 fix is already in booking_mode.py; these tests lock it in.
    """

    @pytest.mark.asyncio
    async def test_confirmation_shown_flipped_on_confirm_intent(self):
        """S1: confirmation_summary_sent=True + core data present + intent='confirm' → flips True."""
        mode = _make_mode()
        state = _make_handle_state(
            mode_context={
                "confirmation_summary_sent": True,
                "confirmation_shown": False,
                "service_id": "svc-1",
                "stylist_id": "s1",
                "selected_slot": {"stylist_id": "s1", "time": "10:00"},
            }
        )

        with (
            patch.object(
                BookingMode,
                "_run_agentic_loop",
                new_callable=AsyncMock,
                return_value=_make_stub_loop_result(),
            ),
            patch.object(BookingMode, "_apply_tool_results"),
        ):
            result = await mode.handle(state, intent="confirm")

        assert result["mode_context"]["confirmation_shown"] is True

    @pytest.mark.asyncio
    async def test_no_flip_when_slot_missing(self):
        """confirmation_summary_sent=True but selected_slot=None → confirmation_shown stays False."""
        mode = _make_mode()
        state = _make_handle_state(
            mode_context={
                "confirmation_summary_sent": True,
                "confirmation_shown": False,
                "service_id": "svc-1",
                "stylist_id": "s1",
                # selected_slot intentionally absent
            }
        )

        with (
            patch.object(
                BookingMode,
                "_run_agentic_loop",
                new_callable=AsyncMock,
                return_value=_make_stub_loop_result(),
            ),
            patch.object(BookingMode, "_apply_tool_results"),
        ):
            result = await mode.handle(state, intent="confirm")

        assert result["mode_context"]["confirmation_shown"] is False

    @pytest.mark.asyncio
    async def test_no_flip_without_summary_sent(self):
        """S2: confirmation_summary_sent=False → confirmation_shown stays False even on 'confirm'."""
        mode = _make_mode()
        state = _make_handle_state(
            mode_context={
                "confirmation_summary_sent": False,
                "confirmation_shown": False,
            }
        )

        with (
            patch.object(
                BookingMode,
                "_run_agentic_loop",
                new_callable=AsyncMock,
                return_value=_make_stub_loop_result(),
            ),
            patch.object(BookingMode, "_apply_tool_results"),
        ):
            result = await mode.handle(state, intent="confirm")

        assert result["mode_context"]["confirmation_shown"] is False

    @pytest.mark.asyncio
    async def test_no_flip_on_wrong_intent(self):
        """S3: intent='book' → confirmation_shown stays False even with summary_sent=True."""
        mode = _make_mode()
        state = _make_handle_state(
            mode_context={
                "confirmation_summary_sent": True,
                "confirmation_shown": False,
            }
        )

        with (
            patch.object(
                BookingMode,
                "_run_agentic_loop",
                new_callable=AsyncMock,
                return_value=_make_stub_loop_result(),
            ),
            patch.object(BookingMode, "_apply_tool_results"),
        ):
            result = await mode.handle(state, intent="book")

        assert result["mode_context"]["confirmation_shown"] is False

    @pytest.mark.asyncio
    async def test_pre_tool_call_allows_book_when_confirmed(self):
        """S4: confirmation_shown=True → _pre_tool_call does NOT return CONFIRMATION_NOT_SHOWN."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            confirmation_shown=True,
            customer_id="test-uuid",
            offered_slots=[{"stylist_id": "s1", "start_time": "2026-04-10T10:20:00"}],
            selected_services=["Corte Dama"],
        )

        result = await mode._pre_tool_call("book", {"slot_index": 1})

        # Must NOT be a CONFIRMATION_NOT_SHOWN rejection
        if isinstance(result, ToolCallRejection):
            assert result.error_code != "CONFIRMATION_NOT_SHOWN", (
                "book() was rejected with CONFIRMATION_NOT_SHOWN despite confirmation_shown=True"
            )

    @pytest.mark.asyncio
    async def test_pre_tool_call_rejects_book_when_not_confirmed(self):
        """S5: confirmation_shown=False + confirmation_summary_sent=True → CONFIRMATION_NOT_SHOWN."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            confirmation_shown=False,
            confirmation_summary_sent=True,
        )

        result = await mode._pre_tool_call("book", {})

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "CONFIRMATION_NOT_SHOWN"

    @pytest.mark.asyncio
    async def test_pre_tool_call_rejects_confirm_from_hold_when_not_confirmed(self):
        """S6: confirm_from_hold with confirmation_shown=False → CONFIRMATION_NOT_SHOWN."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            confirmation_shown=False,
            confirmation_summary_sent=True,
        )

        result = await mode._pre_tool_call("confirm_from_hold", {})

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "CONFIRMATION_NOT_SHOWN"


# =============================================================================
# AI Disclosure in BookingMode.handle()
# =============================================================================


class TestAIDisclosureInBookingMode:
    """BookingMode.handle() must prepend AI disclosure on the first turn.

    Covers S1 (first turn → discloses), S2 (already sent → no double),
    S3 (prior message contains disclosure → no double).
    """

    @pytest.mark.asyncio
    async def test_disclosure_prepended_on_first_turn(self):
        """S1: ai_disclosure_sent=False, no prior assistant messages → prepends FIRST_TURN_INTRO."""
        from agent.modes.base import FIRST_TURN_INTRO

        mode = _make_mode()
        state = _make_handle_state(mode_context={})
        state["ai_disclosure_sent"] = False
        state["messages"] = [{"role": "user", "content": "Quiero reservar un corte"}]

        with (
            patch.object(
                BookingMode,
                "_run_agentic_loop",
                new_callable=AsyncMock,
                return_value=_make_stub_loop_result(),
            ),
            patch.object(BookingMode, "_apply_tool_results"),
        ):
            result = await mode.handle(state, intent="book")

        # The messages list in result has exactly one new message (the assistant reply)
        new_messages = result.get("messages", [])
        assert new_messages, "No messages in result"
        assistant_content = new_messages[0]["content"]
        assert assistant_content.startswith(FIRST_TURN_INTRO), (
            f"Expected disclosure prefix. Got: {assistant_content[:80]!r}"
        )
        assert result.get("ai_disclosure_sent") is True

    @pytest.mark.asyncio
    async def test_no_disclosure_on_second_turn(self):
        """S2: ai_disclosure_sent=True → response does NOT start with disclosure."""
        from agent.modes.base import FIRST_TURN_INTRO

        mode = _make_mode()
        state = _make_handle_state(mode_context={})
        state["ai_disclosure_sent"] = True
        state["messages"] = [
            {"role": "assistant", "content": f"{FIRST_TURN_INTRO} ¿En qué te ayudo?"},
            {"role": "user", "content": "Quiero reservar"},
        ]

        with (
            patch.object(
                BookingMode,
                "_run_agentic_loop",
                new_callable=AsyncMock,
                return_value=_make_stub_loop_result(),
            ),
            patch.object(BookingMode, "_apply_tool_results"),
        ):
            result = await mode.handle(state, intent="book")

        new_messages = result.get("messages", [])
        assert new_messages
        assistant_content = new_messages[0]["content"]
        assert not assistant_content.startswith(FIRST_TURN_INTRO), (
            f"Disclosure was repeated on second turn: {assistant_content[:80]!r}"
        )

    @pytest.mark.asyncio
    async def test_no_double_disclosure_if_already_in_messages(self):
        """S3: ai_disclosure_sent=False but prior message contains 'soy maite' → no double."""
        from agent.modes.base import FIRST_TURN_INTRO

        mode = _make_mode()
        state = _make_handle_state(mode_context={})
        state["ai_disclosure_sent"] = False
        state["messages"] = [
            {
                "role": "assistant",
                "content": f"{FIRST_TURN_INTRO} ¡Bienvenida!",
            },
            {"role": "user", "content": "Quiero reservar"},
        ]

        with (
            patch.object(
                BookingMode,
                "_run_agentic_loop",
                new_callable=AsyncMock,
                return_value=_make_stub_loop_result(),
            ),
            patch.object(BookingMode, "_apply_tool_results"),
        ):
            result = await mode.handle(state, intent="book")

        new_messages = result.get("messages", [])
        assert new_messages
        assistant_content = new_messages[0]["content"]
        assert not assistant_content.startswith(FIRST_TURN_INTRO), (
            f"Double disclosure detected: {assistant_content[:80]!r}"
        )


# =============================================================================
# SERVICE_NOT_RESOLVED gate in _pre_tool_call
# =============================================================================


class TestServiceNotResolvedGate:
    """SERVICE_NOT_RESOLVED gate on list_stylists."""

    @pytest.mark.asyncio
    async def test_list_stylists_rejected_without_service(self):
        """S7: no service_category → ToolCallRejection(SERVICE_NOT_RESOLVED)."""
        mode = _make_mode()
        mode._ctx = BookingContext(service_category=None)
        result = await mode._pre_tool_call("list_stylists", {})
        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "SERVICE_NOT_RESOLVED"

    @pytest.mark.asyncio
    async def test_list_stylists_passes_with_service(self):
        """S8: service_category set → gate passes through."""
        mode = _make_mode()
        mode._ctx = BookingContext(service_category="Peluquería")
        result = await mode._pre_tool_call("list_stylists", {})
        assert not isinstance(result, ToolCallRejection)

    @pytest.mark.asyncio
    async def test_no_stylists_shown_regression(self):
        """S9: NO_STYLISTS_SHOWN gate still works for availability tools."""
        mode = _make_mode()
        mode._ctx = BookingContext(prefetched_stylists=[])
        result = await mode._pre_tool_call("find_next_available", {})
        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_STYLISTS_SHOWN"


# =============================================================================
# Stylist gate in _pre_tool_call
# =============================================================================


class TestStylistGate:
    """_pre_tool_call rejects availability tools when stylist list was never shown.

    Covers S4 (find_next_available blocked), S5 (check_availability blocked),
    S6 (passes with non-empty prefetched_stylists even if stylist_id is None),
    and S7 (booking.md contains OBLIGATORIO rule).
    """

    @pytest.mark.asyncio
    async def test_find_next_available_rejected_without_stylists(self):
        """S4: ctx.prefetched_stylists=[] → ToolCallRejection(NO_STYLISTS_SHOWN)."""
        mode = _make_mode()
        mode._ctx = BookingContext(prefetched_stylists=[])

        result = await mode._pre_tool_call("find_next_available", {})

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_STYLISTS_SHOWN"

    @pytest.mark.asyncio
    async def test_check_availability_rejected_without_stylists(self):
        """S5: ctx.prefetched_stylists=[] → ToolCallRejection(NO_STYLISTS_SHOWN)."""
        mode = _make_mode()
        mode._ctx = BookingContext(prefetched_stylists=[])

        result = await mode._pre_tool_call("check_availability", {})

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_STYLISTS_SHOWN"

    @pytest.mark.asyncio
    async def test_find_next_available_passes_with_stylists_no_stylist_id(self):
        """S6: prefetched_stylists non-empty, stylist_id=None → NOT a ToolCallRejection."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            prefetched_stylists=[{"name": "Ana", "id": "test-uuid"}],
            stylist_id=None,
        )

        result = await mode._pre_tool_call("find_next_available", {})

        assert not isinstance(result, ToolCallRejection), (
            f"Expected pass-through but got ToolCallRejection: {result}"
        )

    def test_booking_md_contains_obligatorio_rule(self):
        """S7: booking.md contains 'OBLIGATORIO' near list_stylists and find_next_available."""
        content = open("agent/prompts/modes/booking.md").read()
        assert "OBLIGATORIO" in content
        assert "find_next_available" in content
        assert "list_stylists()" in content


# =============================================================================
# _extract_booking_hints — pure function tests
# =============================================================================


from agent.graphs.conversation_flow import (  # noqa: E402
    _extract_booking_hints,
    _should_transition_general_to_booking,
)


class TestExtractBookingHints:
    """Pure function tests — no mocking needed."""

    def test_extracts_stylist_and_date(self):
        """S10: both hints detected."""
        result = _extract_booking_hints("quiero una cita el viernes con Pilar")
        assert result["preferred_date_hint"] is not None
        assert "viernes" in result["preferred_date_hint"]
        assert result["preferred_stylist_name"] == "Pilar"

    def test_extracts_date_only(self):
        """S11: date but no stylist."""
        result = _extract_booking_hints("holaa teneis hueco la semana que viene")
        assert result["preferred_date_hint"] is not None
        assert "semana" in result["preferred_date_hint"].lower()
        assert result["preferred_stylist_name"] is None

    def test_no_hints(self):
        """S12: no date, no stylist."""
        result = _extract_booking_hints("quiero cortarme el pelo")
        assert result["preferred_stylist_name"] is None
        assert result["preferred_date_hint"] is None

    def test_robustness_empty_input(self):
        """S13: empty/None input → no exception."""
        assert _extract_booking_hints("") == {
            "preferred_stylist_name": None,
            "preferred_date_hint": None,
        }
        assert _extract_booking_hints(None) == {
            "preferred_stylist_name": None,
            "preferred_date_hint": None,
        }


# =============================================================================
# Rule 7.9 helper — _should_transition_general_to_booking
# =============================================================================


class TestShouldTransitionGeneralToBooking:
    """Tests for Rule 7.9 helper — GENERAL→BOOKING tiered certainty logic."""

    def test_resolved_service_confirm(self):
        """S1: resolved_service + confirm → True."""
        ctx = {"general_booking_handoff": {"resolved_service": {"id": "uuid", "name": "Cortar"}}}
        assert _should_transition_general_to_booking(ctx, "confirm") is True

    def test_resolved_service_ambiguous(self):
        """S2: resolved_service + ambiguous → True (high certainty accepts ambiguous)."""
        ctx = {"general_booking_handoff": {"resolved_service": {"id": "uuid"}}}
        assert _should_transition_general_to_booking(ctx, "ambiguous") is True

    def test_candidates_confirm(self):
        """S3: candidate_services + confirm → True (medium certainty)."""
        ctx = {"general_booking_handoff": {"candidate_services": [{"id": "uuid"}]}}
        assert _should_transition_general_to_booking(ctx, "confirm") is True

    def test_candidates_ambiguous_rejected(self):
        """S4: candidate_services + ambiguous → False (medium certainty rejects ambiguous)."""
        ctx = {"general_booking_handoff": {"candidate_services": [{"id": "uuid"}]}}
        assert _should_transition_general_to_booking(ctx, "ambiguous") is False

    def test_empty_handoff(self):
        """S5: empty handoff dict → False."""
        assert _should_transition_general_to_booking({}, "confirm") is False

    def test_none_handoff(self):
        """S6: None general_booking_handoff → False."""
        assert (
            _should_transition_general_to_booking({"general_booking_handoff": None}, "confirm")
            is False
        )

    def test_no_mode_context(self):
        """S6b: None mode_context → False."""
        assert _should_transition_general_to_booking(None, "confirm") is False

    def test_general_md_no_self_transition(self):
        """S9: general.md does not contain self-transition instruction."""
        with open("agent/prompts/modes/general.md") as f:
            content = f.read()
        assert "transición al modo BOOKING" not in content
        assert "Voy a ayudarte a agendar" not in content


# =============================================================================
# booking-data-integrity: Gate reorder — slot resolution before confirmation
# =============================================================================


class TestGateReorderSlotPersistence:
    """Verify slot_index→UUID resolution (Step A) runs BEFORE confirmation gate (Step B).

    This is the critical fix for the circular dependency where selected_slot could
    never be set because the confirmation gate rejected first.
    """

    @pytest.mark.asyncio
    async def test_s1_slot_persists_through_confirmation_rejection(self):
        """S1: book() rejected for missing confirmation, BUT selected_slot IS set.

        GIVEN offered_slots has 4 slots and selected_slot is None
        WHEN LLM calls book(slot_index=3)
        THEN selected_slot is set to offered_slots[2]
        AND the call is rejected with CONFIRMATION_NOT_SHOWN
        """
        mode = _make_mode()
        slots = [
            {"stylist_id": "s1", "start_time": "2026-04-15T14:00:00+02:00", "time": "14:00",
             "stylist_name": "Pilar", "day_label": "Miércoles 15 de abril"},
            {"stylist_id": "s1", "start_time": "2026-04-15T15:20:00+02:00", "time": "15:20",
             "stylist_name": "Pilar", "day_label": "Miércoles 15 de abril"},
            {"stylist_id": "s1", "start_time": "2026-04-15T16:40:00+02:00", "time": "16:40",
             "stylist_name": "Pilar", "day_label": "Miércoles 15 de abril"},
            {"stylist_id": "s1", "start_time": "2026-04-15T18:00:00+02:00", "time": "18:00",
             "stylist_name": "Pilar", "day_label": "Miércoles 15 de abril"},
        ]
        mode._ctx = BookingContext(
            service_id="svc-cortar",
            service_name="Cortar",
            stylist_id="s1",
            stylist_name="Pilar",
            offered_slots=slots,
            selected_slot=None,  # NOT yet selected
            selected_services=["Cortar", "Peinado Largo"],
            customer_name="Maria Garcia",
            notes=None,  # missing → confirmation won't auto-generate
            confirmation_shown=False,
        )

        result = await mode._pre_tool_call("book", {"slot_index": 3})

        # Rejected because confirmation_shown is False
        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "CONFIRMATION_NOT_SHOWN"

        # BUT selected_slot WAS persisted by Step A (before the rejection)
        assert mode._ctx.selected_slot is not None
        assert mode._ctx.selected_slot["time"] == "16:40"
        assert mode._ctx.selected_slot["start_time"] == "2026-04-15T16:40:00+02:00"

    @pytest.mark.asyncio
    async def test_s1_slot_persists_and_summary_generated_when_all_data_present(self):
        """S1 variant: all data present → slot persists AND summary is generated.

        GIVEN offered_slots, customer_name, notes all set, selected_slot is None
        WHEN book(slot_index=3) called
        THEN selected_slot set AND confirmation_summary_sent=True AND rejection includes summary
        """
        mode = _make_mode()
        slots = [
            {"stylist_id": "s1", "start_time": "2026-04-15T14:00:00+02:00", "time": "14:00",
             "stylist_name": "Pilar", "day_label": "Miércoles 15 de abril"},
            {"stylist_id": "s1", "start_time": "2026-04-15T15:20:00+02:00", "time": "15:20",
             "stylist_name": "Pilar", "day_label": "Miércoles 15 de abril"},
            {"stylist_id": "s1", "start_time": "2026-04-15T16:40:00+02:00", "time": "16:40",
             "stylist_name": "Pilar", "day_label": "Miércoles 15 de abril"},
        ]
        mode._ctx = BookingContext(
            service_id="svc-cortar",
            service_name="Cortar",
            stylist_id="s1",
            stylist_name="Pilar",
            offered_slots=slots,
            selected_slot=None,
            selected_services=["Cortar"],
            customer_name="Maria Garcia",
            notes="Sin preferencias",
            confirmation_shown=False,
        )

        result = await mode._pre_tool_call("book", {"slot_index": 3})

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "CONFIRMATION_NOT_SHOWN"
        # Step A persisted the slot
        assert mode._ctx.selected_slot is not None
        assert mode._ctx.selected_slot["time"] == "16:40"
        # Step B saw all data complete → generated summary
        assert mode._ctx.confirmation_summary_sent is True
        assert "confirmo" in result.error_message.lower() or "resumen" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_s2_invalid_slot_index_rejected_before_confirmation(self):
        """S2: Invalid slot_index → INVALID_SLOT_INDEX, selected_slot remains None.

        GIVEN offered_slots has 4 slots
        WHEN book(slot_index=7) called
        THEN rejected with INVALID_SLOT_INDEX and selected_slot stays None
        """
        mode = _make_mode()
        mode._ctx = BookingContext(
            service_id="svc-1",
            stylist_id="s1",
            offered_slots=[
                {"stylist_id": "s1", "start_time": "2026-04-15T14:00", "time": "14:00"},
                {"stylist_id": "s1", "start_time": "2026-04-15T15:20", "time": "15:20"},
                {"stylist_id": "s1", "start_time": "2026-04-15T16:40", "time": "16:40"},
                {"stylist_id": "s1", "start_time": "2026-04-15T18:00", "time": "18:00"},
            ],
            selected_slot=None,
            confirmation_shown=False,
        )

        result = await mode._pre_tool_call("book", {"slot_index": 7})

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "INVALID_SLOT_INDEX"
        assert mode._ctx.selected_slot is None

    @pytest.mark.asyncio
    async def test_s3_happy_path_all_gates_pass(self):
        """S3: All gates pass → book() proceeds with resolved args.

        GIVEN selected_slot set, confirmation_shown=True, customer_id exists
        WHEN book(slot_index=2) called
        THEN slot resolved, args include stylist_id, start_time, customer_id, services
        """
        mode = _make_mode()
        mode._ctx = BookingContext(
            service_id="svc-1",
            service_name="Cortar",
            stylist_id="s1",
            stylist_name="Pilar",
            offered_slots=[
                {"stylist_id": "s1", "start_time": "2026-04-15T14:00:00+02:00", "time": "14:00"},
                {"stylist_id": "s1", "start_time": "2026-04-15T15:20:00+02:00", "time": "15:20"},
            ],
            selected_services=["Cortar"],
            customer_name="Maria Garcia",
            customer_id="cust-123",
            notes="Sin preferencias",
            confirmation_shown=True,
        )

        result = await mode._pre_tool_call("book", {"slot_index": 2})

        # Not rejected — returns enriched args dict
        assert not isinstance(result, ToolCallRejection)
        assert result["stylist_id"] == "s1"
        assert result["start_time"] == "2026-04-15T15:20:00+02:00"
        assert result["customer_id"] == "cust-123"
        assert result["services"] == ["Cortar"]
        assert result["notes"] == "Sin preferencias"

    @pytest.mark.asyncio
    async def test_search_services_not_blocked_when_service_resolved(self):
        """Verify services_locked removal: search_services is NOT blocked.

        GIVEN service_id is set (services were resolved)
        WHEN LLM calls search_services
        THEN the call passes through (no SERVICES_ALREADY_RESOLVED rejection)
        """
        mode = _make_mode()
        mode._ctx = BookingContext(
            service_id="svc-cortar",
            service_name="Cortar",
            selected_services=["Cortar", "Peinado"],
        )

        result = await mode._pre_tool_call("search_services", {"query": "Peinado Largo"})

        assert not isinstance(result, ToolCallRejection)

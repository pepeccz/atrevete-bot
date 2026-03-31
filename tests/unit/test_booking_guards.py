"""Unit tests for booking-state-integrity guards (Phase 6).

Coverage:
- _pre_tool_call Guard 1: reject book() when offered_slots is empty (REQ-BSI-1)
- _pre_tool_call Guard 2: reject book() when needs_availability_refresh=True (REQ-BSI-2)
- _pre_tool_call Guard 3: reject book() when selected_services is empty (REQ-BSI-4)
- _pre_tool_call Guard 4: reject book() when customer_name missing (REQ-BRF-1)
- _pre_tool_call Guard 5: reject book() when customer_id missing (REQ-BRF-1)
- _pre_tool_call Guard 6: reject book() when confirmation_shown is False
- _pre_tool_call passthrough: non-book tools unaffected
- get_tools() circuit breaker: excludes book when book_failure_count >= 3 (REQ-BSI-3)
- ToolCallRejection in agentic loop: ainvoke skipped, ToolMessage with rejection (REQ-BRF-1)
- _detect_confirmation_exchange: premature confirmation_shown prevention
- _detect_confirmation_exchange: confirmation_shown set when data is complete

All LLM calls are mocked — tests do NOT require a real LLM or DB.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.base import ToolCallRejection
from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import BookingMode, _detect_confirmation_exchange

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
# Guard 1: reject book() when offered_slots is empty (REQ-BSI-1)
# =============================================================================


class TestGuardEmptyOfferedSlots:
    """REQ-BSI-1: _pre_tool_call rejects book() when offered_slots is None/empty."""

    @pytest.mark.asyncio
    async def test_rejects_book_when_offered_slots_none(self):
        """Scenario 1: offered_slots=None -> ToolCallRejection."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            offered_slots=None,
            selected_services=["Corte Caballero"],
            customer_name="Pedro",
        )
        args = {"customer_id": "cust-1", "slot_index": 1}

        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_OFFERED_SLOTS"

    @pytest.mark.asyncio
    async def test_rejects_book_when_offered_slots_empty_list(self):
        """Scenario 1 variant: offered_slots=[] (falsy) -> ToolCallRejection."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            offered_slots=[],
            selected_services=["Corte Caballero"],
            customer_name="Pedro",
        )
        args = {"customer_id": "cust-1", "slot_index": 1}

        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_OFFERED_SLOTS"

    @pytest.mark.asyncio
    async def test_allows_book_when_offered_slots_populated(self):
        """Scenario 2: offered_slots has slots -> no guard rejection."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            offered_slots=[
                {
                    "stylist_id": "s1",
                    "time": "10:00",
                    "full_datetime": "2026-03-27T10:00:00+01:00",
                    "stylist_name": "Maria",
                },
                {
                    "stylist_id": "s1",
                    "time": "11:00",
                    "full_datetime": "2026-03-27T11:00:00+01:00",
                    "stylist_name": "Maria",
                },
                {
                    "stylist_id": "s2",
                    "time": "12:00",
                    "full_datetime": "2026-03-27T12:00:00+01:00",
                    "stylist_name": "Ana",
                },
            ],
            selected_services=["Corte Caballero"],
            customer_name="Pedro",
            customer_id="cust-1",
            needs_availability_refresh=False,
            confirmation_shown=True,
            notes_asked=True,  # notes gate already cleared in a real booking flow
        )
        args = {"customer_id": "cust-1", "slot_index": 2}

        result = await mode._pre_tool_call("book", args)

        # Guard did NOT fire — slot_index was resolved, result is a dict
        assert not isinstance(result, ToolCallRejection)


# =============================================================================
# Guard 2: reject book() when needs_availability_refresh=True (REQ-BSI-2)
# =============================================================================


class TestGuardNeedsAvailabilityRefresh:
    """REQ-BSI-2 scenario 3: _pre_tool_call rejects book() when refresh flag is True."""

    @pytest.mark.asyncio
    async def test_rejects_book_when_refresh_needed(self):
        """needs_availability_refresh=True -> ToolCallRejection."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            offered_slots=[
                {"stylist_id": "s1", "time": "10:00", "full_datetime": "2026-03-27T10:00:00+01:00"}
            ],
            needs_availability_refresh=True,
            selected_services=["Corte Caballero"],
            customer_name="Pedro",
        )
        args = {"customer_id": "cust-1", "slot_index": 1}

        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NEEDS_AVAILABILITY_REFRESH"

    @pytest.mark.asyncio
    async def test_allows_book_when_refresh_not_needed(self):
        """needs_availability_refresh=False -> guard does not fire."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            offered_slots=[
                {
                    "stylist_id": "s1",
                    "time": "10:00",
                    "full_datetime": "2026-03-27T10:00:00+01:00",
                    "stylist_name": "Maria",
                }
            ],
            needs_availability_refresh=False,
            selected_services=["Corte Caballero"],
            customer_name="Pedro",
            customer_id="cust-1",
            confirmation_shown=True,
            notes_asked=True,  # notes gate already cleared in a real booking flow
        )
        args = {"customer_id": "cust-1", "slot_index": 1}

        result = await mode._pre_tool_call("book", args)

        assert not isinstance(result, ToolCallRejection)


# =============================================================================
# Guard 3: reject book() when selected_services is empty (REQ-BSI-4)
# =============================================================================


class TestGuardEmptyServices:
    """REQ-BSI-4: _pre_tool_call rejects book() when selected_services is empty."""

    @pytest.mark.asyncio
    async def test_rejects_book_when_services_empty(self):
        """Scenario 1: selected_services=[] -> ToolCallRejection."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            offered_slots=[
                {"stylist_id": "s1", "time": "10:00", "full_datetime": "2026-03-27T10:00:00+01:00"}
            ],
            selected_services=[],
            needs_availability_refresh=False,
            customer_name="Pedro",
        )
        args = {"customer_id": "cust-1", "slot_index": 1}

        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_SELECTED_SERVICES"

    @pytest.mark.asyncio
    async def test_allows_book_when_services_populated(self):
        """Scenario 2: selected_services has items -> guard does not fire."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            offered_slots=[
                {
                    "stylist_id": "s1",
                    "time": "10:00",
                    "full_datetime": "2026-03-27T10:00:00+01:00",
                    "stylist_name": "Maria",
                }
            ],
            selected_services=["Corte Caballero"],
            needs_availability_refresh=False,
            customer_name="Pedro",
            customer_id="cust-1",
            confirmation_shown=True,
            notes_asked=True,  # notes gate already cleared in a real booking flow
        )
        args = {"customer_id": "cust-1", "slot_index": 1}

        result = await mode._pre_tool_call("book", args)

        assert not isinstance(result, ToolCallRejection)


# =============================================================================
# Guard 4: reject book() when customer_name missing (REQ-BRF-1)
# =============================================================================


class TestGuardNoCustomerName:
    """REQ-BRF-1: _pre_tool_call rejects book() when customer_name is None/empty."""

    @pytest.mark.asyncio
    async def test_rejects_book_when_customer_name_none(self):
        mode = _make_mode()
        mode._ctx = BookingContext(
            offered_slots=[
                {"stylist_id": "s1", "time": "10:00", "full_datetime": "2026-03-27T10:00:00+01:00"}
            ],
            selected_services=["Corte Caballero"],
            needs_availability_refresh=False,
            customer_name=None,
        )
        args = {"customer_id": "cust-1", "slot_index": 1}

        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_CUSTOMER_NAME"

    @pytest.mark.asyncio
    async def test_rejects_book_when_customer_name_is_cliente(self):
        """'Cliente' placeholder is treated as missing name."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            offered_slots=[
                {"stylist_id": "s1", "time": "10:00", "full_datetime": "2026-03-27T10:00:00+01:00"}
            ],
            selected_services=["Corte Caballero"],
            needs_availability_refresh=False,
            customer_name="Cliente",
        )
        args = {"customer_id": "cust-1", "slot_index": 1}

        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_CUSTOMER_NAME"


# =============================================================================
# Guard 5: reject book() when customer_id missing (REQ-BRF-1)
# =============================================================================


class TestGuardNoCustomerId:
    """REQ-BRF-1: _pre_tool_call rejects book() when customer_id is None."""

    @pytest.mark.asyncio
    async def test_rejects_book_when_customer_id_none(self):
        mode = _make_mode()
        mode._ctx = BookingContext(
            offered_slots=[
                {"stylist_id": "s1", "time": "10:00", "full_datetime": "2026-03-27T10:00:00+01:00"}
            ],
            selected_services=["Corte Caballero"],
            needs_availability_refresh=False,
            customer_name="Pedro",
            customer_id=None,
        )
        args = {"customer_id": "cust-1", "slot_index": 1}

        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_CUSTOMER_ID"


# =============================================================================
# Non-book tools pass through unmodified
# =============================================================================


class TestNonBookToolsPassthrough:
    """Non-book tools should not be intercepted by any guard."""

    @pytest.mark.asyncio
    async def test_search_services_passthrough(self):
        mode = _make_mode()
        mode._ctx = BookingContext(offered_slots=None, selected_services=[])
        args = {"query": "corte"}

        result = await mode._pre_tool_call("search_services", args)

        assert result == {"query": "corte"}

    @pytest.mark.asyncio
    async def test_check_availability_passthrough(self):
        mode = _make_mode()
        mode._ctx = BookingContext(offered_slots=None, needs_availability_refresh=True)
        args = {"date": "2026-03-27", "stylist_id": "s1"}

        result = await mode._pre_tool_call("check_availability", args)

        assert result == {"date": "2026-03-27", "stylist_id": "s1"}

    @pytest.mark.asyncio
    async def test_manage_customer_passthrough(self):
        mode = _make_mode()
        mode._ctx = BookingContext()
        args = {"action": "get", "phone": "+34612345678"}

        result = await mode._pre_tool_call("manage_customer", args)

        assert result == {"action": "get", "phone": "+34612345678"}


# =============================================================================
# Circuit breaker: get_tools() excludes book when book_failure_count >= 3
# =============================================================================


class TestCircuitBreakerGetTools:
    """REQ-BSI-3: get_tools() excludes book when book_failure_count >= 3."""

    def test_excludes_book_at_failure_count_3(self):
        """Scenario 1: book_failure_count=3 -> book tool removed."""
        mode = _make_mode()
        mode._ctx = BookingContext(book_failure_count=3)

        tools = mode.get_tools()
        tool_names = [t.name for t in tools]

        assert "book" not in tool_names

    def test_excludes_book_at_failure_count_above_3(self):
        """Scenario 1 variant: book_failure_count=5 -> book tool still removed."""
        mode = _make_mode()
        mode._ctx = BookingContext(book_failure_count=5)

        tools = mode.get_tools()
        tool_names = [t.name for t in tools]

        assert "book" not in tool_names

    def test_includes_book_at_failure_count_below_3(self):
        """Scenario 2: book_failure_count=1 -> book tool present."""
        mode = _make_mode()
        mode._ctx = BookingContext(book_failure_count=1)

        tools = mode.get_tools()
        tool_names = [t.name for t in tools]

        assert "book" in tool_names

    def test_includes_book_at_failure_count_0(self):
        """Scenario 2 variant: fresh context (count=0) -> book tool present."""
        mode = _make_mode()
        mode._ctx = BookingContext(book_failure_count=0)

        tools = mode.get_tools()
        tool_names = [t.name for t in tools]

        assert "book" in tool_names

    def test_includes_book_at_failure_count_2(self):
        """Scenario 2 edge case: count=2 (prompt warning fires, but tool stays)."""
        mode = _make_mode()
        mode._ctx = BookingContext(book_failure_count=2)

        tools = mode.get_tools()
        tool_names = [t.name for t in tools]

        assert "book" in tool_names

    def test_includes_book_when_no_ctx(self):
        """No _ctx attribute at all -> all tools returned (safe fallback)."""
        mode = _make_mode()
        # Don't set _ctx at all

        tools = mode.get_tools()
        tool_names = [t.name for t in tools]

        assert "book" in tool_names

    def test_other_tools_always_present(self):
        """Even when book is excluded, other booking tools remain."""
        mode = _make_mode()
        mode._ctx = BookingContext(book_failure_count=3)

        tools = mode.get_tools()
        tool_names = [t.name for t in tools]

        assert "check_availability" in tool_names
        assert "search_services" in tool_names
        assert "manage_customer" in tool_names


# =============================================================================
# Guard priority: first matching guard wins
# =============================================================================


class TestGuardPriority:
    """Guards fire in order: empty slots > refresh needed > empty services > name > id."""

    @pytest.mark.asyncio
    async def test_empty_slots_takes_priority_over_refresh(self):
        """Both empty slots AND refresh=True -> NO_OFFERED_SLOTS wins."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            offered_slots=None,
            needs_availability_refresh=True,
            selected_services=[],
            customer_name="Pedro",
        )
        args = {"customer_id": "cust-1"}

        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_OFFERED_SLOTS"

    @pytest.mark.asyncio
    async def test_refresh_takes_priority_over_empty_services(self):
        """Slots exist, refresh=True, services empty -> NEEDS_AVAILABILITY_REFRESH wins."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            offered_slots=[{"stylist_id": "s1", "time": "10:00"}],
            needs_availability_refresh=True,
            selected_services=[],
            customer_name="Pedro",
        )
        args = {"customer_id": "cust-1"}

        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NEEDS_AVAILABILITY_REFRESH"


# =============================================================================
# ToolCallRejection in agentic loop (REQ-BRF-1)
# =============================================================================


class TestToolCallRejectionInAgenticLoop:
    """REQ-BRF-1: ToolCallRejection skips ainvoke, produces structured ToolMessage."""

    @pytest.mark.asyncio
    async def test_rejection_skips_ainvoke_and_produces_tool_message(self):
        """When _pre_tool_call returns ToolCallRejection, tool.ainvoke is NOT called
        and the loop produces a ToolMessage with the rejection dict."""
        mode = _make_mode()

        # Set up context that will cause NO_OFFERED_SLOTS rejection
        mode._ctx = BookingContext(
            offered_slots=None,
            selected_services=["Corte Caballero"],
            customer_name="Pedro",
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
        assert rejection_result["error_code"] == "NO_OFFERED_SLOTS"
        assert rejection_result["tool_name"] == "book"

    @pytest.mark.asyncio
    async def test_non_rejected_tool_still_invoked(self):
        """When _pre_tool_call returns modified args (not rejection), ainvoke IS called."""
        mode = _make_mode()

        # Set up context that will NOT trigger rejection
        mode._ctx = BookingContext(
            offered_slots=[
                {
                    "stylist_id": "s1",
                    "time": "10:00",
                    "full_datetime": "2026-03-27T10:00:00+01:00",
                    "stylist_name": "Maria",
                }
            ],
            selected_services=["Corte Caballero"],
            customer_name="Pedro",
            customer_id="cust-1",
            needs_availability_refresh=False,
        )

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
# Guard 6: reject book() when confirmation_shown is False
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
                    "full_datetime": "2026-03-27T10:00:00+01:00",
                    "stylist_name": "Maria",
                }
            ],
            selected_services=["Corte Dama"],
            customer_name="Laura García",
            customer_id="cust-123",
            needs_availability_refresh=False,
            confirmation_shown=False,
            notes_asked=True,  # notes gate already cleared; testing confirmation guard specifically
        )
        args = {"customer_id": "cust-123", "slot_index": 1}

        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "CONFIRMATION_NOT_SHOWN"

    @pytest.mark.asyncio
    async def test_confirmation_gate_allows_book_after_confirmation(self):
        """confirmation_shown=True -> book() proceeds (no rejection)."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            offered_slots=[
                {
                    "stylist_id": "s1",
                    "time": "10:00",
                    "full_datetime": "2026-03-27T10:00:00+01:00",
                    "stylist_name": "Maria",
                }
            ],
            selected_services=["Corte Dama"],
            customer_name="Laura García",
            customer_id="cust-123",
            needs_availability_refresh=False,
            confirmation_shown=True,
            notes_asked=True,  # notes gate already cleared in a real booking flow
        )
        args = {"customer_id": "cust-123", "slot_index": 1}

        result = await mode._pre_tool_call("book", args)

        # No rejection — returned modified args dict
        assert not isinstance(result, ToolCallRejection)
        assert isinstance(result, dict)


# =============================================================================
# Confirmation detection: premature vs correct confirmation_shown
# =============================================================================


class TestDetectConfirmationExchange:
    """_detect_confirmation_exchange must guard against premature confirmation_shown."""

    def test_confirmation_shown_not_set_on_early_si(self):
        """User says 'sí' but booking data is incomplete (no stylist_id) ->
        confirmation_shown stays False."""
        ctx = BookingContext(
            service_id="svc-1",
            service_name="Corte Dama",
            selected_services=["Corte Dama"],
            stylist_id=None,  # <-- missing
            offered_slots=None,  # <-- missing
            customer_name="Laura",
            customer_id="cust-1",
            confirmation_shown=False,
        )
        state = {
            "messages": [
                {"role": "assistant", "content": "¿Para dama o caballero?"},
                {"role": "user", "content": "sí"},
            ],
        }

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is False

    def test_confirmation_shown_not_set_when_no_customer(self):
        """All data except customer -> confirmation_shown stays False."""
        ctx = BookingContext(
            service_id="svc-1",
            selected_services=["Corte Dama"],
            stylist_id="stylist-1",
            offered_slots=[{"stylist_id": "stylist-1", "time": "10:00"}],
            customer_name=None,  # <-- missing
            customer_id=None,  # <-- missing
            confirmation_shown=False,
        )
        state = {
            "messages": [
                {"role": "assistant", "content": "¿Confirmo la cita?"},
                {"role": "user", "content": "sí, dale"},
            ],
        }

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is False

    def test_confirmation_shown_not_set_when_no_services(self):
        """All data except services -> confirmation_shown stays False."""
        ctx = BookingContext(
            service_id=None,
            selected_services=[],  # <-- missing
            stylist_id="stylist-1",
            offered_slots=[{"stylist_id": "stylist-1", "time": "10:00"}],
            customer_name="Laura",
            customer_id="cust-1",
            confirmation_shown=False,
        )
        state = {
            "messages": [
                {"role": "assistant", "content": "¿Confirmo la cita?"},
                {"role": "user", "content": "dale"},
            ],
        }

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is False

    def test_confirmation_shown_set_on_complete_data_si(self):
        """All booking data complete + confirmation_summary_sent=True + user 'sí' ->
        confirmation_shown = True (F-2: uses deterministic flag, not message scanning)."""
        ctx = BookingContext(
            service_id="svc-1",
            service_name="Corte Dama",
            selected_services=["Corte Dama"],
            stylist_id="stylist-1",
            stylist_name="María",
            offered_slots=[
                {
                    "stylist_id": "stylist-1",
                    "time": "10:00",
                    "full_datetime": "2026-03-27T10:00:00+01:00",
                }
            ],
            customer_name="Laura García",
            customer_id="cust-123",
            confirmation_shown=False,
            confirmation_summary_sent=True,  # F-2: flag set by _build_response()
        )
        state = {
            "messages": [
                {
                    "role": "assistant",
                    "content": (
                        "Aquí tienes el resumen de tu cita:\n"
                        "- Servicio: Corte Dama\n"
                        "- Estilista: María\n"
                        "- Fecha: jueves 27 de marzo a las 10:00\n"
                        "¿Confirmo la cita?"
                    ),
                },
                {"role": "user", "content": "sí, dale"},
            ],
        }

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is True

    def test_confirmation_shown_set_with_confirmamos_marker(self):
        """Summary sent (confirmation_summary_sent=True) + user 'perfecto' -> True.
        F-2: flag-based detection replaces message marker scanning."""
        ctx = BookingContext(
            service_id="svc-2",
            selected_services=["Tinte"],
            stylist_id="stylist-2",
            offered_slots=[{"stylist_id": "stylist-2", "time": "14:00"}],
            customer_name="Ana",
            customer_id="cust-456",
            confirmation_shown=False,
            confirmation_summary_sent=True,  # F-2: flag set by _build_response()
        )
        state = {
            "messages": [
                {
                    "role": "assistant",
                    "content": "Tinte con Lucía el viernes a las 14:00. ¿Confirmamos?",
                },
                {"role": "user", "content": "perfecto"},
            ],
        }

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is True

    def test_confirmation_not_set_when_no_summary_marker(self):
        """All data complete but assistant message has NO summary marker ->
        confirmation_shown stays False even if user says 'sí'."""
        ctx = BookingContext(
            service_id="svc-1",
            selected_services=["Corte Dama"],
            stylist_id="stylist-1",
            offered_slots=[{"stylist_id": "stylist-1", "time": "10:00"}],
            customer_name="Laura",
            customer_id="cust-1",
            confirmation_shown=False,
        )
        state = {
            "messages": [
                {"role": "assistant", "content": "¿Para qué día te gustaría la cita?"},
                {"role": "user", "content": "sí"},
            ],
        }

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is False

    def test_confirmation_not_set_when_user_not_affirmative(self):
        """All data complete, summary shown, but user says something non-affirmative ->
        confirmation_shown stays False."""
        ctx = BookingContext(
            service_id="svc-1",
            selected_services=["Corte Dama"],
            stylist_id="stylist-1",
            offered_slots=[{"stylist_id": "stylist-1", "time": "10:00"}],
            customer_name="Laura",
            customer_id="cust-1",
            confirmation_shown=False,
        )
        state = {
            "messages": [
                {
                    "role": "assistant",
                    "content": "Resumen de tu cita: Corte Dama. ¿Confirmo?",
                },
                {"role": "user", "content": "espera, puedo cambiar la hora?"},
            ],
        }

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is False


# =============================================================================
# M-4: tool_choice='required' pending-state guard
# =============================================================================


def _make_state_with_mode_context(mode_context: dict | None = None) -> dict:
    """Build a minimal ConversationState for TestToolChoicePendingGuard tests."""
    from agent.state.schemas import create_initial_state

    state = create_initial_state("conv-001", "+34612345678")
    state["customer_name"] = "María"
    state["customer_id"] = "cust-001"
    state["is_first_interaction"] = False
    state["current_mode"] = "BOOKING"
    state["mode_context"] = mode_context or {}
    state["messages"] = [{"role": "user", "content": "quiero reservar"}]
    return state


def _make_agentic_result():
    """Return a minimal AgenticLoopResult for _run_agentic_loop mocks."""
    from agent.modes.base import AgenticLoopResult

    return AgenticLoopResult(response_text="ok", tool_results={})


class TestToolChoicePendingGuard:
    """M-4: tool_choice='required' when pending_clarifications or candidate_services is set.

    Tests are integration-style: they call handle() with all heavy methods mocked
    so we can assert on the tool_choice kwarg passed to _run_agentic_loop.
    """

    @pytest.mark.asyncio
    async def test_tool_choice_required_with_pending_clarifications_and_partial_service(self):
        """S1: selected_services populated + pending_clarifications non-empty -> 'required'."""
        mode = _make_mode()
        state = _make_state_with_mode_context(
            {
                "selected_services": ["Corte Dama"],
                "pending_clarifications": [{"question": "¿Para dama o caballero?"}],
                "confirmation_shown": False,
            }
        )
        intent = MagicMock()

        loop_mock = AsyncMock(return_value=_make_agentic_result())
        with (
            patch.object(mode, "_run_agentic_loop", loop_mock),
            patch.object(mode, "_build_messages", AsyncMock(return_value=[])),
            patch.object(mode, "_maybe_prefetch_stylists", AsyncMock()),
            patch.object(mode, "_detect_tool_skips", AsyncMock()),
            patch.object(mode, "_detect_stylist_hallucination", MagicMock()),
            patch.object(mode, "_check_special_intents", MagicMock(return_value=None)),
            patch.object(mode, "_build_response", MagicMock(return_value={"last_node": "booking"})),
        ):
            await mode.handle(state, intent)

        _args, _kwargs = loop_mock.call_args
        assert _kwargs.get("tool_choice") == "required"

    @pytest.mark.asyncio
    async def test_tool_choice_required_with_candidate_services_and_partial_service(self):
        """S2: selected_services populated + candidate_services non-empty -> 'required'."""
        mode = _make_mode()
        state = _make_state_with_mode_context(
            {
                "selected_services": ["Corte Dama"],
                "candidate_services": [{"name": "Tinte", "id": "svc-2"}],
                "confirmation_shown": False,
            }
        )
        intent = MagicMock()

        loop_mock = AsyncMock(return_value=_make_agentic_result())
        with (
            patch.object(mode, "_run_agentic_loop", loop_mock),
            patch.object(mode, "_build_messages", AsyncMock(return_value=[])),
            patch.object(mode, "_maybe_prefetch_stylists", AsyncMock()),
            patch.object(mode, "_detect_tool_skips", AsyncMock()),
            patch.object(mode, "_detect_stylist_hallucination", MagicMock()),
            patch.object(mode, "_check_special_intents", MagicMock(return_value=None)),
            patch.object(mode, "_build_response", MagicMock(return_value={"last_node": "booking"})),
        ):
            await mode.handle(state, intent)

        _args, _kwargs = loop_mock.call_args
        assert _kwargs.get("tool_choice") == "required"

    @pytest.mark.asyncio
    async def test_tool_choice_not_forced_after_pre_resolver_clears_pending_clarifications(self):
        """S3: pending_clarifications cleared by pre-resolver -> NOT forced (only original guard).

        When pre-resolver _resolve_user_clarification_selection runs and empties
        pending_clarifications, the guard sees an empty list and should NOT force
        tool_choice solely due to FR-1. Here we simulate this by providing a state
        where selected_services is set and pending_clarifications will be cleared
        (we mock it directly via mode_context with empty list after resolution).
        """
        mode = _make_mode()
        # Simulate the state AFTER pre-resolver has already cleared pending_clarifications:
        # selected_services is set, pending_clarifications is empty → no force
        state = _make_state_with_mode_context(
            {
                "selected_services": ["Corte Dama"],
                "pending_clarifications": [],  # already cleared
                "confirmation_shown": False,
            }
        )
        intent = MagicMock()

        loop_mock = AsyncMock(return_value=_make_agentic_result())
        with (
            patch.object(mode, "_run_agentic_loop", loop_mock),
            patch.object(mode, "_build_messages", AsyncMock(return_value=[])),
            patch.object(mode, "_maybe_prefetch_stylists", AsyncMock()),
            patch.object(mode, "_detect_tool_skips", AsyncMock()),
            patch.object(mode, "_detect_stylist_hallucination", MagicMock()),
            patch.object(mode, "_check_special_intents", MagicMock(return_value=None)),
            patch.object(mode, "_build_response", MagicMock(return_value={"last_node": "booking"})),
        ):
            await mode.handle(state, intent)

        _args, _kwargs = loop_mock.call_args
        assert _kwargs.get("tool_choice") is None

    @pytest.mark.asyncio
    async def test_tool_choice_not_forced_after_pre_resolver_clears_candidate_services(self):
        """S4: candidate_services cleared by pre-resolver -> NOT forced (only original guard).

        When pre-resolver _resolve_user_candidate_selection runs and empties
        candidate_services, the guard sees an empty list and should NOT force
        tool_choice solely due to FR-2.
        """
        mode = _make_mode()
        # Simulate state AFTER pre-resolver has already cleared candidate_services
        state = _make_state_with_mode_context(
            {
                "selected_services": ["Corte Dama"],
                "candidate_services": [],  # already cleared
                "confirmation_shown": False,
            }
        )
        intent = MagicMock()

        loop_mock = AsyncMock(return_value=_make_agentic_result())
        with (
            patch.object(mode, "_run_agentic_loop", loop_mock),
            patch.object(mode, "_build_messages", AsyncMock(return_value=[])),
            patch.object(mode, "_maybe_prefetch_stylists", AsyncMock()),
            patch.object(mode, "_detect_tool_skips", AsyncMock()),
            patch.object(mode, "_detect_stylist_hallucination", MagicMock()),
            patch.object(mode, "_check_special_intents", MagicMock(return_value=None)),
            patch.object(mode, "_build_response", MagicMock(return_value={"last_node": "booking"})),
        ):
            await mode.handle(state, intent)

        _args, _kwargs = loop_mock.call_args
        assert _kwargs.get("tool_choice") is None

    @pytest.mark.asyncio
    async def test_tool_choice_required_original_behavior_no_service(self):
        """S5 (regression): no service + no pending state -> still forced (FR-4 original guard).

        Ensures the original behavior is preserved when pending state is empty
        but service is not yet resolved.
        """
        mode = _make_mode()
        state = _make_state_with_mode_context(
            {
                "selected_services": [],
                "service_id": None,
                "confirmation_shown": False,
                "pending_clarifications": [],
                "candidate_services": [],
            }
        )
        intent = MagicMock()

        loop_mock = AsyncMock(return_value=_make_agentic_result())
        with (
            patch.object(mode, "_run_agentic_loop", loop_mock),
            patch.object(mode, "_build_messages", AsyncMock(return_value=[])),
            patch.object(mode, "_maybe_prefetch_stylists", AsyncMock()),
            patch.object(mode, "_detect_tool_skips", AsyncMock()),
            patch.object(mode, "_detect_stylist_hallucination", MagicMock()),
            patch.object(mode, "_check_special_intents", MagicMock(return_value=None)),
            patch.object(mode, "_build_response", MagicMock(return_value={"last_node": "booking"})),
        ):
            await mode.handle(state, intent)

        _args, _kwargs = loop_mock.call_args
        assert _kwargs.get("tool_choice") == "required"

    @pytest.mark.asyncio
    async def test_tool_choice_not_forced_with_complete_service_no_pending(self):
        """S6 (regression): service complete + no pending state -> NOT forced (FR-4).

        Ensures normal flow is not disrupted when service is resolved and
        there is no disambiguation state.
        """
        mode = _make_mode()
        state = _make_state_with_mode_context(
            {
                "selected_services": ["Corte Dama"],
                "service_id": "svc-001",
                "confirmation_shown": False,
                "pending_clarifications": [],
                "candidate_services": [],
            }
        )
        intent = MagicMock()

        loop_mock = AsyncMock(return_value=_make_agentic_result())
        with (
            patch.object(mode, "_run_agentic_loop", loop_mock),
            patch.object(mode, "_build_messages", AsyncMock(return_value=[])),
            patch.object(mode, "_maybe_prefetch_stylists", AsyncMock()),
            patch.object(mode, "_detect_tool_skips", AsyncMock()),
            patch.object(mode, "_detect_stylist_hallucination", MagicMock()),
            patch.object(mode, "_check_special_intents", MagicMock(return_value=None)),
            patch.object(mode, "_build_response", MagicMock(return_value={"last_node": "booking"})),
        ):
            await mode.handle(state, intent)

        _args, _kwargs = loop_mock.call_args
        assert _kwargs.get("tool_choice") is None

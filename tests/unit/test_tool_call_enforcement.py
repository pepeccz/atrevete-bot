"""Unit tests for tool-call-enforcement requirements (R2, R3, R4, R5, R6).

Covers:
- R2: Stylist hallucination detection via _pre_tool_call (tool-result-based, not text-scanning)
- R3: Tool-skip telemetry in base.py (_run_agentic_loop)
- R4/R6: Tool-skip detection for search_services and list_stylists
- R5: Tool description closed-world language enforcement

Tests validate that the guardrails correctly detect and respond to LLM
deviations from the tool-first mandate.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.modes.base import AgenticLoopResult, BaseModeNode
from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import BookingMode
from agent.tools.availability_tools import check_availability, find_next_available
from agent.tools.info_tools import list_stylists
from agent.tools.search_services import search_services

# ═══════════════════════════════════════════════════════════════════════
# R5: Tool Docstring Enforcement
# ═══════════════════════════════════════════════════════════════════════


class TestR5ToolDocstrings:
    """R5: Verify closed-world language in tool descriptions.

    LangChain StructuredTool wraps the function and exposes the docstring via
    the .description attribute, NOT .__doc__ (which returns a generic LangChain
    message). Tests must check .description instead.
    """

    def test_list_stylists_contains_required_language(self):
        """list_stylists description must contain 'ONLY VALID SOURCE' and 'MUST NOT'."""
        desc = list_stylists.description
        assert desc is not None
        assert "ONLY VALID SOURCE" in desc or "ONLY valid source" in desc
        assert "MUST NOT" in desc

    def test_search_services_contains_required_language(self):
        """search_services description must contain 'ONLY valid source'."""
        desc = search_services.description
        assert desc is not None
        assert "ONLY valid source" in desc or "ONLY VALID SOURCE" in desc
        assert "MUST NOT" in desc

    def test_check_availability_contains_required_language(self):
        """check_availability description must contain 'ONLY valid source'."""
        desc = check_availability.description
        assert desc is not None
        assert "ONLY valid source" in desc or "ONLY VALID SOURCE" in desc

    def test_find_next_available_contains_required_language(self):
        """find_next_available description must contain 'ONLY valid source'."""
        desc = find_next_available.description
        assert desc is not None
        assert "ONLY valid source" in desc or "ONLY VALID SOURCE" in desc


# ═══════════════════════════════════════════════════════════════════════
# R3: Base Mode Tool-Skip Telemetry
# ═══════════════════════════════════════════════════════════════════════


class _DummyMode(BaseModeNode):
    """Test harness for base agentic loop."""

    @property
    def mode_name(self) -> str:
        return "TEST"

    async def handle(self, state, intent):  # pragma: no cover
        return {"last_node": "dummy"}


def _make_response(content: str = "", tool_calls: list[dict] | None = None) -> SimpleNamespace:
    """Create a mock LLM response."""
    return SimpleNamespace(content=content, tool_calls=tool_calls or [])


def _make_tool(name: str, result: dict | None = None):
    """Create a mock tool."""
    tool = MagicMock()
    tool.name = name
    tool.ainvoke = AsyncMock(return_value=result or {"ok": name})
    return tool


@pytest.mark.asyncio
async def test_r3_tool_skip_telemetry_logs_warning_when_no_tools_called():
    """R3: When LLM skips all available tools, WARNING log with event=tool_skip."""
    llm = MagicMock()
    llm_with_tools = MagicMock()
    llm.bind_tools.return_value = llm_with_tools
    # LLM response with no tool calls (skip)
    llm_with_tools.ainvoke = AsyncMock(return_value=_make_response(content="Hola"))

    mode = _DummyMode(tools=[], llm_client=llm)
    mode.logger = MagicMock()

    result = await mode._run_agentic_loop(
        messages=[SimpleNamespace(content="hola")],
        tools=[_make_tool("search_services"), _make_tool("check_availability")],
    )

    assert result.response_text == "Hola"
    # Check for tool_skip warning
    warning_calls = mode.logger.warning.call_args_list
    tool_skip_found = any(
        call[0][0] == "tool_skip" or "tool_skip" in str(call) for call in warning_calls
    )
    assert tool_skip_found, f"Expected tool_skip warning but got: {warning_calls}"


@pytest.mark.asyncio
async def test_r3_no_warning_when_tools_are_called():
    """R3: When LLM calls tools, no tool_skip warning is logged."""
    llm = MagicMock()
    llm_with_tools = MagicMock()
    llm.bind_tools.return_value = llm_with_tools
    # LLM response WITH tool calls
    llm_with_tools.ainvoke = AsyncMock(
        side_effect=[
            _make_response(tool_calls=[{"id": "tc-1", "name": "search_services", "args": {}}]),
            _make_response(content="Encontré servicios"),
        ]
    )

    mode = _DummyMode(tools=[], llm_client=llm)
    mode.logger = MagicMock()

    result = await mode._run_agentic_loop(
        messages=[SimpleNamespace(content="hola")],
        tools=[_make_tool("search_services")],
    )

    assert result.response_text == "Encontré servicios"
    # Check that NO tool_skip warning was logged
    warning_calls = mode.logger.warning.call_args_list
    tool_skip_found = any("tool_skip" in str(call) for call in warning_calls)
    assert not tool_skip_found


@pytest.mark.asyncio
async def test_r3_no_warning_when_no_tools_available():
    """R3: When no tools available, no tool_skip warning (tools=None)."""
    llm = MagicMock()
    llm.bind_tools.return_value = llm
    llm.ainvoke = AsyncMock(return_value=_make_response(content="Sin herramientas"))

    mode = _DummyMode(tools=[], llm_client=llm)
    mode.logger = MagicMock()

    result = await mode._run_agentic_loop(
        messages=[SimpleNamespace(content="hola")],
        tools=None,  # No tools available
    )

    assert result.response_text == "Sin herramientas"
    warning_calls = mode.logger.warning.call_args_list
    tool_skip_found = any("tool_skip" in str(call) for call in warning_calls)
    assert not tool_skip_found


# ═══════════════════════════════════════════════════════════════════════
# R2: Stylist Hallucination Detection (via _pre_tool_call)
# ═══════════════════════════════════════════════════════════════════════


class TestR2StylistHallucination:
    """R2: force_stylist_correction is set via _pre_tool_call when book() has an invalid
    stylist_id (not in prefetched_stylists). The old text-scanning approach via
    _detect_stylist_hallucination() was removed in booking-mode-restrictor-cleanup.

    New behavior: detection is tool-result-based — fires when book() passes a
    stylist_id that is NOT in {s['id'] for s in ctx.prefetched_stylists}.
    """

    @pytest.mark.asyncio
    async def test_invalid_stylist_id_sets_correction_flag(self):
        """book(slot_index=1) where offered_slots[0].stylist_id not in prefetched → flag set.

        Uses the slot_index path: _pre_tool_call resolves slot_index=1 to offered_slots[0],
        then checks if the resolved stylist_id is in prefetched_stylists. If not, it sets
        force_stylist_correction=True (lines 1244-1256 of booking_mode.py).
        """
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana", "id": "valid-id-1"},
                {"name": "Pilar", "id": "valid-id-2"},
            ],
            offered_slots=[
                {
                    "stylist_id": "invalid-id-99",  # NOT in prefetched_stylists
                    "stylist": "InventadaXYZ",
                    "time": "10:00",
                    "date": "2026-04-10",
                    "full_datetime": "2026-04-10T10:00:00+02:00",
                }
            ],
            customer_id="cust-1",
            customer_name="Laura",
            service_id="svc-1",
            selected_services=["Corte de Dama"],
            notes="ninguna",
            notes_asked=True,
            confirmation_shown=True,
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._ctx = ctx
        mode._current_state = {}

        # Use slot_index path — resolves to offered_slots[0] with invalid-id-99
        tool_args = {"slot_index": 1}
        await mode._pre_tool_call("book", tool_args)

        # invalid-id-99 not in prefetched_stylists → correction flag set
        assert ctx.force_stylist_correction is True

    @pytest.mark.asyncio
    async def test_valid_stylist_id_does_not_set_correction_flag(self):
        """book() with stylist_id IN prefetched_stylists → force_stylist_correction=False."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana", "id": "valid-id-1"},
                {"name": "Pilar", "id": "valid-id-2"},
            ],
            offered_slots=[
                {
                    "stylist_id": "valid-id-1",
                    "time": "10:00",
                    "date": "2026-04-10",
                    "full_datetime": "2026-04-10T10:00:00+02:00",
                }
            ],
            customer_id="cust-1",
            customer_name="Laura",
            service_id="svc-1",
            selected_services=["Corte de Dama"],
            notes="ninguna",
            notes_asked=True,
            confirmation_shown=True,
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._ctx = ctx
        mode._current_state = {}

        tool_args = {
            "stylist_id": "valid-id-1",
            "start_time": "2026-04-10T10:00:00+02:00",
        }
        await mode._pre_tool_call("book", tool_args)

        assert ctx.force_stylist_correction is False

    @pytest.mark.asyncio
    async def test_no_prefetched_stylists_no_flag(self):
        """book() with empty prefetched_stylists → force_stylist_correction stays False."""
        ctx = BookingContext(
            prefetched_stylists=[],
            offered_slots=[
                {
                    "stylist_id": "some-id",
                    "time": "10:00",
                    "date": "2026-04-10",
                    "full_datetime": "2026-04-10T10:00:00+02:00",
                }
            ],
            customer_id="cust-1",
            customer_name="Laura",
            service_id="svc-1",
            selected_services=["Corte de Dama"],
            notes="ninguna",
            notes_asked=True,
            confirmation_shown=True,
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._ctx = ctx
        mode._current_state = {}

        tool_args = {
            "stylist_id": "some-id",
            "start_time": "2026-04-10T10:00:00+02:00",
        }
        await mode._pre_tool_call("book", tool_args)

        # No prefetched stylists → guard doesn't activate → False
        assert ctx.force_stylist_correction is False

    @pytest.mark.asyncio
    async def test_slot_index_path_invalid_stylist_sets_flag(self):
        """slot_index path: resolved stylist_id not in prefetched → force_stylist_correction=True."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana", "id": "valid-id-1"},
            ],
            offered_slots=[
                {
                    "stylist_id": "hallucinated-id-99",
                    "stylist": "LauraInventada",
                    "time": "10:00",
                    "date": "2026-04-10",
                    "full_datetime": "2026-04-10T10:00:00+02:00",
                }
            ],
            customer_id="cust-1",
            customer_name="Laura",
            service_id="svc-1",
            selected_services=["Corte de Dama"],
            notes="ninguna",
            notes_asked=True,
            confirmation_shown=True,
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._ctx = ctx
        mode._current_state = {}

        # LLM passes slot_index=1 — resolved from offered_slots[0]
        tool_args = {"slot_index": 1}
        await mode._pre_tool_call("book", tool_args)

        # Resolved stylist_id is hallucinated-id-99, not in prefetched → flag set
        assert ctx.force_stylist_correction is True

    @pytest.mark.asyncio
    async def test_correction_flag_false_after_list_stylists_resolves(self):
        """After _post_tool_result processes list_stylists, force_stylist_correction=False."""
        ctx = BookingContext(
            prefetched_stylists=[],
            force_stylist_correction=True,
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._ctx = ctx
        mode._current_state = {}

        # Simulate list_stylists returning a fresh stylist list
        list_result = {
            "stylists": [{"id": "real-id-1", "name": "Ana", "category": "HAIRDRESSING"}],
            "count": 1,
        }
        await mode._post_tool_result("list_stylists", {}, list_result)

        # list_stylists resolves → correction flag cleared
        assert ctx.force_stylist_correction is False
        assert len(ctx.prefetched_stylists) == 1


# ═══════════════════════════════════════════════════════════════════════
# R4/R6: Tool-Skip Detection (list_stylists, search_services)
# ═══════════════════════════════════════════════════════════════════════


class TestR4R6ToolSkipDetection:
    """R4/R6: _detect_tool_skips detects when LLM skips list_stylists or search_services.

    Note: _detect_tool_skips is async (it may call _f7_auto_recover internally).
    Tests must use @pytest.mark.asyncio and await the call.
    """

    @pytest.mark.asyncio
    async def test_r4_list_stylists_skip_detected(self):
        """R4/R6: service resolved, no list_stylists call → force_list_stylists_reminder=True."""
        ctx = BookingContext(
            service_id="svc-001",  # Service is resolved
            stylist_id=None,  # But stylist not selected
            prefetched_stylists=[],  # And stylists not fetched
        )
        result = AgenticLoopResult(response_text="Hola", tool_results={})  # No list_stylists call

        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._last_user_message = ""
        mode._f7_recovered_this_turn = False
        await mode._detect_tool_skips(result, ctx)

        assert ctx.force_list_stylists_reminder is True
        assert ctx.force_search_services_reminder is False

    @pytest.mark.asyncio
    async def test_r4_list_stylists_called_no_reminder(self):
        """R4/R6: service resolved + list_stylists called → no reminder."""
        ctx = BookingContext(
            service_id="svc-001",
            stylist_id=None,
            prefetched_stylists=[],
        )
        result = AgenticLoopResult(
            response_text="Estos son los estilistas",
            tool_results={"list_stylists": [{"name": "Ana"}]},
        )

        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._last_user_message = ""
        mode._f7_recovered_this_turn = False
        await mode._detect_tool_skips(result, ctx)

        assert ctx.force_list_stylists_reminder is False

    @pytest.mark.asyncio
    async def test_r4_stylist_already_selected_no_reminder(self):
        """R4/R6: service resolved + stylist already selected → no reminder."""
        ctx = BookingContext(
            service_id="svc-001",
            stylist_id="sty-001",  # Already selected
            prefetched_stylists=[],
        )
        result = AgenticLoopResult(response_text="Listo", tool_results={})

        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._last_user_message = ""
        mode._f7_recovered_this_turn = False
        await mode._detect_tool_skips(result, ctx)

        assert ctx.force_list_stylists_reminder is False

    @pytest.mark.asyncio
    async def test_r4_stylists_already_prefetched_no_reminder(self):
        """R4/R6: stylists prefetched AND already presented → no reminder needed.

        Condition B in _detect_tool_skips fires when stylists are prefetched but
        stylists_presented=False and no stylist name appears in the response. To
        suppress the reminder, set stylists_presented=True (presented in a prior turn).
        """
        ctx = BookingContext(
            service_id="svc-001",
            stylist_id=None,
            prefetched_stylists=[{"name": "Ana", "id": "1"}],  # Already fetched
            stylists_presented=True,  # Already shown to user in a prior turn
        )
        result = AgenticLoopResult(response_text="Elige estilista", tool_results={})

        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._last_user_message = ""
        mode._f7_recovered_this_turn = False
        await mode._detect_tool_skips(result, ctx)

        assert ctx.force_list_stylists_reminder is False

    @pytest.mark.asyncio
    async def test_f7_search_services_skip_detected(self):
        """F-7: service unresolved, search_services not called → force_search_services_reminder=True."""
        ctx = BookingContext(
            service_id=None,  # Service NOT resolved
            selected_services=[],
            pending_clarifications=[],
        )
        # Empty response so F-7 auto-recovery won't fire (message too short)
        result = AgenticLoopResult(response_text="¿Qué servicio?", tool_results={})

        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._last_user_message = ""  # Short → auto-recovery skipped
        mode._f7_recovered_this_turn = False
        await mode._detect_tool_skips(result, ctx)

        assert ctx.force_search_services_reminder is True
        assert ctx.force_list_stylists_reminder is False

    @pytest.mark.asyncio
    async def test_f7_search_services_called_no_reminder(self):
        """F-7: service unresolved + search_services called → no reminder."""
        ctx = BookingContext(
            service_id=None,
            selected_services=[],
            pending_clarifications=[],
        )
        result = AgenticLoopResult(
            response_text="Encontré servicios",
            tool_results={"search_services": [{"name": "Corte"}]},
        )

        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._last_user_message = ""
        mode._f7_recovered_this_turn = False
        await mode._detect_tool_skips(result, ctx)

        assert ctx.force_search_services_reminder is False

    @pytest.mark.asyncio
    async def test_f7_service_already_selected_no_reminder(self):
        """F-7: service already selected → no reminder."""
        ctx = BookingContext(
            service_id=None,
            selected_services=["Corte"],  # Service selected
            pending_clarifications=[],
        )
        result = AgenticLoopResult(response_text="Listo", tool_results={})

        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._last_user_message = ""
        mode._f7_recovered_this_turn = False
        await mode._detect_tool_skips(result, ctx)

        assert ctx.force_search_services_reminder is False

    @pytest.mark.asyncio
    async def test_f7_pending_clarification_still_triggers_reminder(self):
        """F-7: pending_clarifications do NOT suppress the reminder.

        The F-7 condition checks only: service_id is None, selected_services empty,
        and search_services not called. pending_clarifications does NOT suppress F-7.
        This test documents the actual behavior to prevent mismatched expectations.
        """
        ctx = BookingContext(
            service_id=None,
            selected_services=[],
            pending_clarifications=[{"axis": "hair_density"}],  # Clarification pending
        )
        result = AgenticLoopResult(response_text="¿Cabello normal o denso?", tool_results={})

        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._last_user_message = ""  # Short → auto-recovery skipped
        mode._f7_recovered_this_turn = False
        await mode._detect_tool_skips(result, ctx)

        # F-7 condition fires regardless of pending_clarifications
        assert ctx.force_search_services_reminder is True

    @pytest.mark.asyncio
    async def test_both_reminders_set_simultaneously(self):
        """Both R4 and F-7 conditions can be true simultaneously."""
        ctx = BookingContext(
            service_id="svc-001",  # R4: service resolved but no stylists
            stylist_id=None,
            prefetched_stylists=[],
            # But also simulate a weird state where service_id is set AND
            # we're checking F-7 (shouldn't happen, but test both flags)
        )
        result = AgenticLoopResult(response_text="Hola", tool_results={})

        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._last_user_message = ""
        mode._f7_recovered_this_turn = False
        await mode._detect_tool_skips(result, ctx)

        # R4 condition is true
        assert ctx.force_list_stylists_reminder is True
        # F-7 condition is false (service_id is set)
        assert ctx.force_search_services_reminder is False


# ═══════════════════════════════════════════════════════════════════════
# Integration: Dynamic Context Injection
# ═══════════════════════════════════════════════════════════════════════


class TestDynamicContextInjection:
    """Verify that reminder flags are injected into dynamic context."""

    def test_force_search_services_reminder_injected(self):
        """When force_search_services_reminder=True, reminder is in dynamic context."""
        ctx = BookingContext(force_search_services_reminder=True)
        mode = BookingMode(tools=[], llm_client=MagicMock())

        dynamic_context = mode._build_dynamic_context({"mode_context": {}, "history": []}, ctx)

        assert "search_services" in dynamic_context
        assert "DEBES llamar search_services" in dynamic_context

    def test_force_list_stylists_reminder_injected(self):
        """When force_list_stylists_reminder=True, reminder is in dynamic context."""
        ctx = BookingContext(force_list_stylists_reminder=True)
        mode = BookingMode(tools=[], llm_client=MagicMock())

        dynamic_context = mode._build_dynamic_context({"mode_context": {}, "history": []}, ctx)

        assert "list_stylists" in dynamic_context or "estilista" in dynamic_context
        assert "DEBES" in dynamic_context

    def test_force_stylist_correction_injected(self):
        """When force_stylist_correction=True, correction is in dynamic context."""
        ctx = BookingContext(force_stylist_correction=True)
        mode = BookingMode(tools=[], llm_client=MagicMock())

        dynamic_context = mode._build_dynamic_context({"mode_context": {}, "history": []}, ctx)

        assert "CORRECCIÓN" in dynamic_context
        assert "nombres" in dynamic_context.lower()

    def test_no_reminders_when_flags_false(self):
        """When all reminder flags are False, no warnings injected."""
        ctx = BookingContext(
            force_search_services_reminder=False,
            force_list_stylists_reminder=False,
            force_stylist_correction=False,
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())

        dynamic_context = mode._build_dynamic_context({"mode_context": {}, "history": []}, ctx)

        # Should not contain warning markers
        assert "⚠️ Recordatorio" not in dynamic_context
        assert "⚠️ CORRECCIÓN" not in dynamic_context


# ═══════════════════════════════════════════════════════════════════════
# T-10: Hallucination Guard — Valid stylist_id passes without correction
# ═══════════════════════════════════════════════════════════════════════


class TestHallucinationGuardAffirmationWords:
    """T-10: When book() is called with a valid stylist_id (in prefetched_stylists),
    force_stylist_correction must NOT be set.

    Old behavior tested text-scanning with _detect_stylist_hallucination().
    New behavior: detection is purely tool-result-based via _pre_tool_call.
    force_stylist_correction=False is the correct state when stylist_id is valid.
    """

    @pytest.mark.asyncio
    async def test_valid_id_does_not_set_correction(self):
        """book() with a valid stylist_id → force_stylist_correction stays False."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana", "id": "known-id-1"},
            ],
            offered_slots=[
                {
                    "stylist_id": "known-id-1",
                    "time": "10:00",
                    "date": "2026-04-10",
                    "full_datetime": "2026-04-10T10:00:00+02:00",
                }
            ],
            customer_id="cust-1",
            customer_name="María",
            service_id="svc-1",
            selected_services=["Corte de Dama"],
            notes="ninguna",
            notes_asked=True,
            confirmation_shown=True,
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._ctx = ctx
        mode._current_state = {}

        tool_args = {
            "stylist_id": "known-id-1",
            "start_time": "2026-04-10T10:00:00+02:00",
        }
        await mode._pre_tool_call("book", tool_args)

        # Valid stylist_id → no correction needed
        assert ctx.force_stylist_correction is False

    @pytest.mark.asyncio
    async def test_slot_index_with_valid_stylist_no_correction(self):
        """slot_index path: resolved stylist_id in prefetched → force_stylist_correction=False."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana", "id": "known-id-1"},
                {"name": "Pilar", "id": "known-id-2"},
            ],
            offered_slots=[
                {
                    "stylist_id": "known-id-2",
                    "stylist": "Pilar",
                    "time": "11:00",
                    "date": "2026-04-10",
                    "full_datetime": "2026-04-10T11:00:00+02:00",
                }
            ],
            customer_id="cust-1",
            customer_name="María",
            service_id="svc-1",
            selected_services=["Corte de Dama"],
            notes="ninguna",
            notes_asked=True,
            confirmation_shown=True,
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._ctx = ctx
        mode._current_state = {}

        # LLM passes slot_index=1 (1-based) → offered_slots[0] with known-id-2
        tool_args = {"slot_index": 1}
        await mode._pre_tool_call("book", tool_args)

        # Resolved stylist_id is known-id-2, which IS in prefetched → no correction
        assert ctx.force_stylist_correction is False

    @pytest.mark.asyncio
    async def test_correction_flag_false_by_default_no_book_call(self):
        """force_stylist_correction defaults to False on a fresh BookingContext."""
        ctx = BookingContext()
        assert ctx.force_stylist_correction is False

    @pytest.mark.asyncio
    async def test_correction_flag_not_set_by_non_book_tools(self):
        """_pre_tool_call for search_services does NOT touch force_stylist_correction."""
        ctx = BookingContext(
            prefetched_stylists=[{"name": "Ana", "id": "1"}],
            force_stylist_correction=False,
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._ctx = ctx
        mode._current_state = {}

        # Calling search_services via _pre_tool_call should not touch the flag
        tool_args = {"query": "corte de dama"}
        await mode._pre_tool_call("search_services", tool_args)

        assert ctx.force_stylist_correction is False

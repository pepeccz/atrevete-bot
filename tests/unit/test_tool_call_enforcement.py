"""Unit tests for tool-call-enforcement requirements (R2, R3, R4, R5, R6).

Covers:
- R2: Stylist hallucination detection (_detect_stylist_hallucination)
- R3: Tool-skip telemetry in base.py (_run_agentic_loop)
- R4/R6: Tool-skip detection for search_services and list_stylists
- R5: Tool docstring closed-world language enforcement

Tests validate that the guardrails correctly detect and respond to LLM
deviations from the tool-first mandate.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.base import AgenticLoopResult, BaseModeNode
from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import BookingMode
from agent.tools.availability_tools import check_availability, find_next_available
from agent.tools.info_tools import list_stylists, query_info
from agent.tools.search_services import search_services


# ═══════════════════════════════════════════════════════════════════════
# R5: Tool Docstring Enforcement
# ═══════════════════════════════════════════════════════════════════════


class TestR5ToolDocstrings:
    """R5: Verify closed-world language in tool descriptions."""

    def test_list_stylists_contains_required_language(self):
        """list_stylists docstring must contain 'ONLY VALID SOURCE' and 'MUST NOT'."""
        doc = list_stylists.__doc__
        assert doc is not None
        assert "ONLY VALID SOURCE" in doc
        assert "MUST NOT" in doc

    def test_search_services_contains_required_language(self):
        """search_services docstring must contain 'ONLY valid source'."""
        doc = search_services.__doc__
        assert doc is not None
        assert "ONLY valid source" in doc or "ONLY VALID SOURCE" in doc
        assert "MUST NOT" in doc

    def test_check_availability_contains_required_language(self):
        """check_availability docstring must contain 'ONLY valid source'."""
        doc = check_availability.__doc__
        assert doc is not None
        assert "ONLY valid source" in doc or "ONLY VALID SOURCE" in doc

    def test_find_next_available_contains_required_language(self):
        """find_next_available docstring must contain 'ONLY valid source'."""
        doc = find_next_available.__doc__
        assert doc is not None
        assert "ONLY valid source" in doc or "ONLY VALID SOURCE" in doc


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
# R2: Stylist Hallucination Detection
# ═══════════════════════════════════════════════════════════════════════


class TestR2StylistHallucination:
    """R2: _detect_stylist_hallucination detects invented names."""

    def test_hallucinated_name_detected(self):
        """Given stylists=['Ana', 'Pilar'], response='Laura te atiende' → warning + flag."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana", "id": "1"},
                {"name": "Pilar", "id": "2"},
            ]
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())
        response = "Te atenderá Laura con mucho gusto"

        mode._detect_stylist_hallucination(response, ctx)

        assert ctx.force_stylist_correction is True

    def test_valid_name_no_warning(self):
        """Given stylists=['Ana', 'Pilar'], response='Ana te atiende' → no warning."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana", "id": "1"},
                {"name": "Pilar", "id": "2"},
            ]
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())
        response = "Te atenderá Ana con mucho gusto"

        mode._detect_stylist_hallucination(response, ctx)

        assert ctx.force_stylist_correction is False

    def test_multiple_hallucinated_names(self):
        """Given stylists=['Ana'], response mentions 'Laura' and 'Sofia' → flag set."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana", "id": "1"},
            ]
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())
        response = "Laura o Sofia pueden atenderte, pero sugiero Laura"

        mode._detect_stylist_hallucination(response, ctx)

        assert ctx.force_stylist_correction is True

    def test_empty_prefetched_stylists_no_check(self):
        """If prefetched_stylists is empty, no hallucination check needed."""
        ctx = BookingContext(prefetched_stylists=[])
        mode = BookingMode(tools=[], llm_client=MagicMock())
        response = "Laura te atiende"

        mode._detect_stylist_hallucination(response, ctx)

        assert ctx.force_stylist_correction is False

    def test_empty_response_no_check(self):
        """If response is empty, force_stylist_correction=False."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana", "id": "1"},
            ]
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())

        mode._detect_stylist_hallucination("", ctx)

        assert ctx.force_stylist_correction is False

    def test_common_words_not_flagged(self):
        """Common Spanish words like 'La' or 'Del' are not treated as hallucinated names."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana", "id": "1"},
            ]
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())
        # Response with capitalized common words
        response = "La estilista Del salón es Ana, especialista en peinados"

        mode._detect_stylist_hallucination(response, ctx)

        # These common words should not trigger hallucination flag
        assert ctx.force_stylist_correction is False

    def test_accent_normalization(self):
        """Names with accents like 'María' should match 'Maria'."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "María", "id": "1"},
            ]
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())
        # Response uses name without accent
        response = "Maria te atenderá"

        mode._detect_stylist_hallucination(response, ctx)

        # Should NOT flag as hallucination (accent-normalized match)
        assert ctx.force_stylist_correction is False


# ═══════════════════════════════════════════════════════════════════════
# R4/R6: Tool-Skip Detection (list_stylists, search_services)
# ═══════════════════════════════════════════════════════════════════════


class TestR4R6ToolSkipDetection:
    """R4/R6: _detect_tool_skips detects when LLM skips list_stylists or search_services."""

    def test_r4_list_stylists_skip_detected(self):
        """R4/R6: service resolved, no list_stylists call → force_list_stylists_reminder=True."""
        ctx = BookingContext(
            service_id="svc-001",  # Service is resolved
            stylist_id=None,  # But stylist not selected
            prefetched_stylists=[],  # And stylists not fetched
        )
        result = AgenticLoopResult(response_text="Hola", tool_results={})  # No list_stylists call

        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._detect_tool_skips(result, ctx)

        assert ctx.force_list_stylists_reminder is True
        assert ctx.force_search_services_reminder is False

    def test_r4_list_stylists_called_no_reminder(self):
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
        mode._detect_tool_skips(result, ctx)

        assert ctx.force_list_stylists_reminder is False

    def test_r4_stylist_already_selected_no_reminder(self):
        """R4/R6: service resolved + stylist already selected → no reminder."""
        ctx = BookingContext(
            service_id="svc-001",
            stylist_id="sty-001",  # Already selected
            prefetched_stylists=[],
        )
        result = AgenticLoopResult(response_text="Listo", tool_results={})

        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._detect_tool_skips(result, ctx)

        assert ctx.force_list_stylists_reminder is False

    def test_r4_stylists_already_prefetched_no_reminder(self):
        """R4/R6: stylists already prefetched → no reminder needed."""
        ctx = BookingContext(
            service_id="svc-001",
            stylist_id=None,
            prefetched_stylists=[{"name": "Ana", "id": "1"}],  # Already fetched
        )
        result = AgenticLoopResult(response_text="Elige estilista", tool_results={})

        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._detect_tool_skips(result, ctx)

        assert ctx.force_list_stylists_reminder is False

    def test_f7_search_services_skip_detected(self):
        """F-7: service unresolved, search_services not called → force_search_services_reminder=True."""
        ctx = BookingContext(
            service_id=None,  # Service NOT resolved
            selected_services=[],
            pending_clarifications=[],
        )
        result = AgenticLoopResult(response_text="¿Qué servicio?", tool_results={})

        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._detect_tool_skips(result, ctx)

        assert ctx.force_search_services_reminder is True
        assert ctx.force_list_stylists_reminder is False

    def test_f7_search_services_called_no_reminder(self):
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
        mode._detect_tool_skips(result, ctx)

        assert ctx.force_search_services_reminder is False

    def test_f7_service_already_selected_no_reminder(self):
        """F-7: service already selected → no reminder."""
        ctx = BookingContext(
            service_id=None,
            selected_services=["Corte"],  # Service selected
            pending_clarifications=[],
        )
        result = AgenticLoopResult(response_text="Listo", tool_results={})

        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._detect_tool_skips(result, ctx)

        assert ctx.force_search_services_reminder is False

    def test_f7_pending_clarification_no_reminder(self):
        """F-7: pending_clarifications exist → no reminder."""
        ctx = BookingContext(
            service_id=None,
            selected_services=[],
            pending_clarifications=[{"axis": "hair_density"}],  # Clarification pending
        )
        result = AgenticLoopResult(response_text="¿Cabello normal o denso?", tool_results={})

        mode = BookingMode(tools=[], llm_client=MagicMock())
        mode._detect_tool_skips(result, ctx)

        assert ctx.force_search_services_reminder is False

    def test_both_reminders_set_simultaneously(self):
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
        mode._detect_tool_skips(result, ctx)

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

        assert "list_stylists" in dynamic_context
        assert "DEBES llamar list_stylists" in dynamic_context

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
# T-10: Hallucination Guard — Affirmation Words and Min-Length Filter
# ═══════════════════════════════════════════════════════════════════════


class TestHallucinationGuardAffirmationWords:
    """T-10: Affirmation words and short tokens should not trigger hallucination."""

    def test_affirmation_word_si_not_flagged(self):
        """'Si' as capitalized response should NOT trigger hallucination detection."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana", "id": "1"},
            ]
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())
        # "Si" is in blocklist AND len < 3 — should not be a hallucinated name
        response = "Si, claro, con mucho gusto"

        mode._detect_stylist_hallucination(response, ctx)

        assert ctx.force_stylist_correction is False

    def test_affirmation_word_sip_not_flagged(self):
        """'Sip' (3 chars, in blocklist) should NOT trigger hallucination detection."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana", "id": "1"},
            ]
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())
        response = "Sip, perfecto"

        mode._detect_stylist_hallucination(response, ctx)

        assert ctx.force_stylist_correction is False

    def test_affirmation_word_ok_not_flagged(self):
        """'Ok' (2 chars, filtered by min-length guard) should NOT trigger hallucination."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana", "id": "1"},
            ]
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())
        response = "Ok, te lo agendo ahora"

        mode._detect_stylist_hallucination(response, ctx)

        assert ctx.force_stylist_correction is False

    def test_min_length_guard_two_char_word_skipped(self):
        """2-char capitalized words like 'Si' are not considered candidates (len < 3)."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana", "id": "1"},
            ]
        )
        mode = BookingMode(tools=[], llm_client=MagicMock())
        # "Ok Ana" — "Ok" filtered by min-length, "Ana" is a known stylist
        response = "Ok Ana te atenderá"

        mode._detect_stylist_hallucination(response, ctx)

        # "Ok" filtered out, "Ana" is known → no hallucination
        assert ctx.force_stylist_correction is False

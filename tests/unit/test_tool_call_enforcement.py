"""Unit tests for tool-call-enforcement requirements (R3, R5).

Covers:
- R3: Tool-skip telemetry in base.py (_run_agentic_loop)
- R5: Tool description closed-world language enforcement

Tests R2, R4, R6 were removed in booking-mode-simplification Phase 4 —
they tested _detect_tool_skips and fields (notes_asked, force_stylist_correction,
force_list_stylists_reminder, force_search_services_reminder, stylists_presented)
that no longer exist in the simplified BookingContext.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.modes.base import AgenticLoopResult, BaseModeNode
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

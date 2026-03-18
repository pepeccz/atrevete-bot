"""Unit tests for the BaseModeNode agentic loop."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.modes.base import MAX_TOOL_ROUNDS, BaseModeNode
from agent.state.schemas import create_initial_state


class _DummyMode(BaseModeNode):
    @property
    def mode_name(self) -> str:
        return "GENERAL"

    async def handle(self, state, intent):  # pragma: no cover - not used in these tests
        return {"last_node": "dummy"}


def _make_response(content: str = "", tool_calls: list[dict] | None = None) -> SimpleNamespace:
    return SimpleNamespace(content=content, tool_calls=tool_calls or [])


def _make_tool(name: str, result: dict | None = None):
    tool = MagicMock()
    tool.name = name
    tool.ainvoke = AsyncMock(return_value=result or {"ok": name})
    return tool


@pytest.mark.asyncio
async def test_run_agentic_loop_binds_tools_on_every_round():
    llm = MagicMock()
    llm_with_tools = MagicMock()
    llm.bind_tools.return_value = llm_with_tools
    llm_with_tools.ainvoke = AsyncMock(
        side_effect=[
            _make_response(tool_calls=[{"id": "tc-1", "name": "check_availability", "args": {}}]),
            _make_response(tool_calls=[{"id": "tc-2", "name": "find_next_available", "args": {}}]),
            _make_response(content="Listo, te propongo este horario."),
        ]
    )

    mode = _DummyMode(
        tools=[],
        llm_client=llm,
    )
    result = await mode._run_agentic_loop(
        messages=[SimpleNamespace(content="hola")],
        tools=[
            _make_tool("check_availability", {"slots": []}),
            _make_tool("find_next_available", {"slot": "2026-03-20T10:00:00+01:00"}),
        ],
    )

    assert result.response_text == "Listo, te propongo este horario."
    assert llm.bind_tools.call_count == 3
    assert llm_with_tools.ainvoke.await_count == 3


@pytest.mark.asyncio
async def test_run_agentic_loop_stops_after_max_tool_rounds():
    llm = MagicMock()
    llm_with_tools = MagicMock()
    llm.bind_tools.return_value = llm_with_tools
    llm_with_tools.ainvoke = AsyncMock(
        side_effect=[
            _make_response(tool_calls=[{"id": f"tc-{idx}", "name": "loop_tool", "args": {}}])
            for idx in range(MAX_TOOL_ROUNDS)
        ]
    )

    mode = _DummyMode(tools=[], llm_client=llm)
    mode.logger = MagicMock()

    result = await mode._run_agentic_loop(
        messages=[SimpleNamespace(content="hola")],
        tools=[_make_tool("loop_tool", {"round": "ok"})],
    )

    assert result.tool_results["loop_tool"] == {"round": "ok"}
    assert llm_with_tools.ainvoke.await_count == MAX_TOOL_ROUNDS
    mode.logger.warning.assert_called_once()


def test_create_initial_state_default_is_first_interaction():
    state = create_initial_state("conv-base-001", "+34600000000")
    assert state["is_first_interaction"] is True

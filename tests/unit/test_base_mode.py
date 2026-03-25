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
    # Use DIFFERENT args per round to avoid dedup guard caching
    llm_with_tools.ainvoke = AsyncMock(
        side_effect=[
            _make_response(
                tool_calls=[{"id": f"tc-{idx}", "name": "loop_tool", "args": {"round": idx}}]
            )
            for idx in range(MAX_TOOL_ROUNDS)
        ]
    )

    mode = _DummyMode(tools=[], llm_client=llm)
    mode.logger = MagicMock()

    result = await mode._run_agentic_loop(
        messages=[SimpleNamespace(content="hola")],
        tools=[_make_tool("loop_tool", {"round": "ok"})],
    )

    # tool_results accumulates results as lists (BUG-1 fix: multiple calls append)
    assert result.tool_results["loop_tool"][-1] == {"round": "ok"}
    assert llm_with_tools.ainvoke.await_count == MAX_TOOL_ROUNDS
    # Check that the MAX_TOOL_ROUNDS warning was logged (among other potential warnings)
    warning_calls = [
        call for call in mode.logger.warning.call_args_list if "MAX_TOOL_ROUNDS" in str(call)
    ]
    assert len(warning_calls) == 1


def test_create_initial_state_default_is_first_interaction():
    state = create_initial_state("conv-base-001", "+34600000000")
    assert state["is_first_interaction"] is True


# =============================================================================
# Dedup guard: identical tool calls in same loop return cached result
# =============================================================================


class TestDedupGuard:
    """R3: Tool-call dedup guard caches identical calls within one agentic loop."""

    @pytest.mark.asyncio
    async def test_dedup_guard_caches_identical_calls(self):
        """Identical tool calls in the same loop -> tool executed once, cached result reused."""
        llm = MagicMock()
        llm_with_tools = MagicMock()
        llm.bind_tools.return_value = llm_with_tools

        # LLM calls the same tool twice with identical args, then returns text
        llm_with_tools.ainvoke = AsyncMock(
            side_effect=[
                _make_response(
                    tool_calls=[
                        {
                            "id": "tc-1",
                            "name": "check_availability",
                            "args": {"date": "2026-03-27"},
                        },
                        {
                            "id": "tc-2",
                            "name": "check_availability",
                            "args": {"date": "2026-03-27"},
                        },
                    ]
                ),
                _make_response(content="Listo, revisé la disponibilidad."),
            ]
        )

        tool = _make_tool("check_availability", {"slots": ["10:00", "11:00"]})
        mode = _DummyMode(tools=[], llm_client=llm)

        result = await mode._run_agentic_loop(
            messages=[SimpleNamespace(content="¿hay disponibilidad?")],
            tools=[tool],
        )

        # Tool was invoked only ONCE despite being called twice
        assert tool.ainvoke.await_count == 1
        # Both results are present in tool_results (list of 2, both identical)
        assert len(result.tool_results["check_availability"]) == 2
        assert result.tool_results["check_availability"][0] == {"slots": ["10:00", "11:00"]}
        assert result.tool_results["check_availability"][1] == {"slots": ["10:00", "11:00"]}

    @pytest.mark.asyncio
    async def test_dedup_guard_allows_different_args(self):
        """Same tool with different args -> both calls execute normally."""
        llm = MagicMock()
        llm_with_tools = MagicMock()
        llm.bind_tools.return_value = llm_with_tools

        # LLM calls same tool twice with DIFFERENT args
        llm_with_tools.ainvoke = AsyncMock(
            side_effect=[
                _make_response(
                    tool_calls=[
                        {
                            "id": "tc-1",
                            "name": "check_availability",
                            "args": {"date": "2026-03-27"},
                        },
                        {
                            "id": "tc-2",
                            "name": "check_availability",
                            "args": {"date": "2026-03-28"},
                        },
                    ]
                ),
                _make_response(content="Te muestro disponibilidad para ambos días."),
            ]
        )

        call_count = 0
        results_by_date = {
            "2026-03-27": {"slots": ["10:00"]},
            "2026-03-28": {"slots": ["14:00"]},
        }

        async def _side_effect(args):
            nonlocal call_count
            call_count += 1
            return results_by_date.get(args.get("date"), {"slots": []})

        tool = _make_tool("check_availability")
        tool.ainvoke = AsyncMock(side_effect=_side_effect)

        mode = _DummyMode(tools=[], llm_client=llm)

        result = await mode._run_agentic_loop(
            messages=[SimpleNamespace(content="¿disponibilidad jueves y viernes?")],
            tools=[tool],
        )

        # Both calls executed (different args = different dedup keys)
        assert call_count == 2
        assert len(result.tool_results["check_availability"]) == 2

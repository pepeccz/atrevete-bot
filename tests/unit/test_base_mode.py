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
    # Final text recovery: LLM called without tools after MAX_TOOL_ROUNDS
    llm.ainvoke = AsyncMock(return_value=_make_response(content="Recovery text."))

    mode = _DummyMode(tools=[], llm_client=llm)
    mode.logger = MagicMock()

    result = await mode._run_agentic_loop(
        messages=[SimpleNamespace(content="hola")],
        tools=[_make_tool("loop_tool", {"round": "ok"})],
    )

    # tool_results accumulates results as lists (BUG-1 fix: multiple calls append)
    assert result.tool_results["loop_tool"][-1] == {"round": "ok"}
    assert llm_with_tools.ainvoke.await_count == MAX_TOOL_ROUNDS
    # Final recovery call happened
    assert llm.ainvoke.await_count == 1
    assert result.response_text == "Recovery text."
    # Check that the MAX_TOOL_ROUNDS warning was logged
    warning_calls = [
        call for call in mode.logger.warning.call_args_list if "MAX_TOOL_ROUNDS" in str(call)
    ]
    assert len(warning_calls) == 1


@pytest.mark.asyncio
async def test_final_text_recovery_not_triggered_when_text_present():
    """When loop exits normally with text, no recovery call is made."""
    llm = MagicMock()
    llm_with_tools = MagicMock()
    llm.bind_tools.return_value = llm_with_tools
    llm_with_tools.ainvoke = AsyncMock(
        side_effect=[
            _make_response(tool_calls=[{"id": "tc-1", "name": "t1", "args": {}}]),
            _make_response(content="Normal response."),
        ]
    )
    llm.ainvoke = AsyncMock()  # Should NOT be called

    mode = _DummyMode(tools=[], llm_client=llm)

    result = await mode._run_agentic_loop(
        messages=[SimpleNamespace(content="hola")],
        tools=[_make_tool("t1")],
    )

    assert result.response_text == "Normal response."
    llm.ainvoke.assert_not_called()


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


# =============================================================================
# Batch 2 — ToolCallRejection type bug: original_tool_args preserved
# =============================================================================


class TestOriginalToolArgsPreservation:
    """Spec Domain B: original tool_args must reach _post_tool_result regardless
    of what _pre_tool_call returns (ToolCallRejection, enriched dict, or exception)."""

    @pytest.mark.asyncio
    async def test_post_tool_result_receives_original_args_when_rejection(self):
        """When _pre_tool_call returns ToolCallRejection, _post_tool_result gets original dict.

        Spec: Domain B — Scenario: _pre_tool_call returns ToolCallRejection.
        """
        from agent.modes.base import ToolCallRejection

        captured_post_args = {}

        class _RejectorMode(_DummyMode):
            async def _pre_tool_call(self, tool_name, tool_args):
                return ToolCallRejection(
                    name=tool_name,
                    error_code="TEST_REJECT",
                    error_message="test rejection",
                )

            async def _post_tool_result(self, tool_name, tool_args, result):
                captured_post_args["args"] = dict(tool_args)
                return result

        llm = MagicMock()
        llm_with_tools = MagicMock()
        llm.bind_tools.return_value = llm_with_tools
        llm_with_tools.ainvoke = AsyncMock(
            side_effect=[
                _make_response(
                    tool_calls=[{"id": "tc-1", "name": "book", "args": {"slot_index": 2}}]
                ),
                _make_response(content="La llamada fue rechazada."),
            ]
        )

        mode = _RejectorMode(tools=[], llm_client=llm)
        await mode._run_agentic_loop(
            messages=[SimpleNamespace(content="confirmar")],
            tools=[_make_tool("book")],
        )

        assert captured_post_args.get("args") == {"slot_index": 2}, (
            "_post_tool_result must receive original tool_args dict, not ToolCallRejection"
        )

    @pytest.mark.asyncio
    async def test_post_tool_result_receives_enriched_args_on_success(self):
        """When _pre_tool_call returns enriched dict, _post_tool_result gets enriched dict.

        Spec: Domain B — Scenario: _pre_tool_call returns transformed dict.
        """
        captured_post_args = {}

        class _EnricherMode(_DummyMode):
            async def _pre_tool_call(self, tool_name, tool_args):
                enriched = dict(tool_args)
                enriched["slot_id"] = "uuid-abc-123"
                return enriched

            async def _post_tool_result(self, tool_name, tool_args, result):
                captured_post_args["args"] = dict(tool_args)
                return result

        llm = MagicMock()
        llm_with_tools = MagicMock()
        llm.bind_tools.return_value = llm_with_tools
        llm_with_tools.ainvoke = AsyncMock(
            side_effect=[
                _make_response(
                    tool_calls=[{"id": "tc-1", "name": "book", "args": {"slot_index": 1}}]
                ),
                _make_response(content="Cita reservada."),
            ]
        )

        mode = _EnricherMode(tools=[], llm_client=llm)
        await mode._run_agentic_loop(
            messages=[SimpleNamespace(content="confirmar")],
            tools=[_make_tool("book")],
        )

        # _post_tool_result should get the enriched dict (with slot_id)
        assert captured_post_args.get("args", {}).get("slot_id") == "uuid-abc-123", (
            "_post_tool_result must receive enriched dict when _pre_tool_call transforms args"
        )

    @pytest.mark.asyncio
    async def test_post_tool_result_receives_original_args_on_exception(self):
        """When _pre_tool_call raises exception, _post_tool_result gets original dict.

        Spec: Domain B — Scenario: _pre_tool_call raises exception.
        """
        captured_post_args = {}

        class _RaiserMode(_DummyMode):
            async def _pre_tool_call(self, tool_name, tool_args):
                raise RuntimeError("unexpected hook failure")

            async def _post_tool_result(self, tool_name, tool_args, result):
                captured_post_args["args"] = dict(tool_args)
                return result

        llm = MagicMock()
        llm_with_tools = MagicMock()
        llm.bind_tools.return_value = llm_with_tools
        llm_with_tools.ainvoke = AsyncMock(
            side_effect=[
                _make_response(
                    tool_calls=[{"id": "tc-1", "name": "check_availability", "args": {"x": 42}}]
                ),
                _make_response(content="Algo salió mal."),
            ]
        )

        mode = _RaiserMode(tools=[], llm_client=llm)
        mode.logger = MagicMock()
        await mode._run_agentic_loop(
            messages=[SimpleNamespace(content="hola")],
            tools=[_make_tool("check_availability")],
        )

        assert captured_post_args.get("args") == {"x": 42}, (
            "_post_tool_result must receive original dict when _pre_tool_call raises"
        )
        # Warning log must be emitted
        warning_calls = [
            c for c in mode.logger.warning.call_args_list if "_pre_tool_call failed" in str(c)
        ]
        assert len(warning_calls) == 1, "A warning must be logged when _pre_tool_call raises"

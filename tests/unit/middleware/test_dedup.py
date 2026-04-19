"""Unit tests for ``DedupToolCallMiddleware``."""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from agent.middleware.dedup import DedupToolCallMiddleware, _tool_call_key
from tests.unit.middleware._offline import ScriptedModel


# Global counter so @tool functions can track real executions across tests.
_counter = {"exec": 0}


def _reset() -> None:
    _counter["exec"] = 0


@tool
def _instrumented(day: str = "mon") -> str:
    """instrumented stub"""
    _counter["exec"] += 1
    return f"result for {day}"


def test_tool_call_key_sorts_args_deterministically():
    k1 = _tool_call_key({"name": "x", "args": {"a": 1, "b": 2}})
    k2 = _tool_call_key({"name": "x", "args": {"b": 2, "a": 1}})
    assert k1 == k2


def test_tool_call_key_distinguishes_different_args():
    k1 = _tool_call_key({"name": "x", "args": {"a": 1}})
    k2 = _tool_call_key({"name": "x", "args": {"a": 2}})
    assert k1 != k2


def test_duplicate_tool_call_short_circuits_and_skips_execution():
    _reset()
    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "_instrumented", "args": {"day": "mon"}, "id": "a1"}],
        ),
        AIMessage(
            content="",
            tool_calls=[{"name": "_instrumented", "args": {"day": "mon"}, "id": "a2"}],
        ),
        AIMessage(content="done"),
    ]
    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_instrumented],
        middleware=[DedupToolCallMiddleware()],
    )
    agent.invoke({"messages": [HumanMessage("check twice")]})

    assert _counter["exec"] == 1


def test_distinct_args_still_execute_each_time():
    _reset()
    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "_instrumented", "args": {"day": "mon"}, "id": "b1"}],
        ),
        AIMessage(
            content="",
            tool_calls=[{"name": "_instrumented", "args": {"day": "tue"}, "id": "b2"}],
        ),
        AIMessage(content="done"),
    ]
    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_instrumented],
        middleware=[DedupToolCallMiddleware()],
    )
    agent.invoke({"messages": [HumanMessage("check two days")]})

    assert _counter["exec"] == 2


def test_cached_result_carries_current_call_id():
    """The returned ToolMessage must use the CURRENT tool_call's id — ``create_agent``
    pairs ``ToolMessage.tool_call_id`` against pending call ids to route results."""
    _reset()
    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "_instrumented", "args": {"day": "mon"}, "id": "first"}],
        ),
        AIMessage(
            content="",
            tool_calls=[{"name": "_instrumented", "args": {"day": "mon"}, "id": "second"}],
        ),
        AIMessage(content="done"),
    ]
    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_instrumented],
        middleware=[DedupToolCallMiddleware()],
    )
    result = agent.invoke({"messages": [HumanMessage("check")]})

    from langchain_core.messages import ToolMessage

    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 2
    assert {m.tool_call_id for m in tool_msgs} == {"first", "second"}
    # Both carry the same content (the cached one).
    assert tool_msgs[0].content == tool_msgs[1].content

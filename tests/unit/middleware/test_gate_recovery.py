"""Unit tests for ``GateRecoveryMiddleware``."""

from __future__ import annotations

from typing import Callable

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from agent.middleware.gate_recovery import GateRecoveryMiddleware
from tests.unit.middleware._offline import ScriptedModel


@tool
def _book(day: str = "mon") -> str:
    """book stub"""
    return f"booked {day}"


class _RejectingBook(AgentMiddleware):
    """Force every ``_book`` call to return a marker-tagged error ToolMessage."""

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage],
    ) -> ToolMessage:
        tc = request.tool_call
        if tc["name"] == "_book":
            return ToolMessage(
                content="error_code=GATE_REJECTED",
                tool_call_id=tc["id"],
                name="_book",
                status="error",
            )
        return handler(request)


_RECOVERY = "No puedo procesar la reserva ahora. Intentá más tarde."


def test_threshold_two_aborts_on_second_rejection():
    responses = [
        AIMessage(content="", tool_calls=[{"name": "_book", "args": {"day": "mon"}, "id": "r1"}]),
        AIMessage(content="", tool_calls=[{"name": "_book", "args": {"day": "mon"}, "id": "r2"}]),
        AIMessage(content="", tool_calls=[{"name": "_book", "args": {"day": "mon"}, "id": "r3"}]),
        AIMessage(content="should never appear"),
    ]
    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_book],
        middleware=[
            _RejectingBook(),
            GateRecoveryMiddleware(
                marker="GATE_REJECTED",
                recovery_text=_RECOVERY,
                threshold=2,
            ),
        ],
    )
    result = agent.invoke(
        {"messages": [HumanMessage("book please")]},
        config={"recursion_limit": 20},
    )

    last_ai = [m for m in result["messages"] if isinstance(m, AIMessage)][-1]
    assert last_ai.content == _RECOVERY
    assert not last_ai.tool_calls


def test_below_threshold_does_not_trigger_recovery():
    # Threshold 3, only two rejections present, THEN the model writes plain
    # text — recovery must NOT fire; the model's text wins.
    responses = [
        AIMessage(content="", tool_calls=[{"name": "_book", "args": {"day": "mon"}, "id": "r1"}]),
        AIMessage(content="", tool_calls=[{"name": "_book", "args": {"day": "mon"}, "id": "r2"}]),
        AIMessage(content="ok I will stop trying"),
    ]
    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_book],
        middleware=[
            _RejectingBook(),
            GateRecoveryMiddleware(
                marker="GATE_REJECTED",
                recovery_text=_RECOVERY,
                threshold=3,
            ),
        ],
    )
    result = agent.invoke({"messages": [HumanMessage("book please")]})

    last_ai = [m for m in result["messages"] if isinstance(m, AIMessage)][-1]
    assert last_ai.content == "ok I will stop trying"


def test_marker_mismatch_does_not_trigger_recovery():
    @tool
    def _ok_tool(x: str | None = None) -> str:
        """ok tool"""
        return "all good"  # NO GATE_REJECTED marker

    responses = [
        AIMessage(content="", tool_calls=[{"name": "_ok_tool", "args": {}, "id": "s1"}]),
        AIMessage(content="", tool_calls=[{"name": "_ok_tool", "args": {}, "id": "s2"}]),
        AIMessage(content="plain final"),
    ]
    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_ok_tool],
        middleware=[
            GateRecoveryMiddleware(
                marker="GATE_REJECTED",
                recovery_text=_RECOVERY,
                threshold=1,
            )
        ],
    )
    result = agent.invoke({"messages": [HumanMessage("x")]})

    last_ai = [m for m in result["messages"] if isinstance(m, AIMessage)][-1]
    assert last_ai.content == "plain final"


def test_recovery_overwrites_in_place_without_adding_new_message():
    """After the recovery fires, the final AIMessage carries ``recovery_text``
    and has no tool calls — proving the reducer updated the offending message
    in place (via its ``id``) rather than appending a separate entry."""
    responses = [
        AIMessage(content="", tool_calls=[{"name": "_book", "args": {"day": "mon"}, "id": "r1"}]),
        AIMessage(content="", tool_calls=[{"name": "_book", "args": {"day": "mon"}, "id": "r2"}]),
        AIMessage(content="", tool_calls=[{"name": "_book", "args": {"day": "mon"}, "id": "r3"}]),
        AIMessage(content="should never appear"),
    ]
    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_book],
        middleware=[
            _RejectingBook(),
            GateRecoveryMiddleware(
                marker="GATE_REJECTED",
                recovery_text=_RECOVERY,
                threshold=2,
            ),
        ],
    )
    result = agent.invoke(
        {"messages": [HumanMessage("x")]},
        config={"recursion_limit": 20},
    )

    ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
    replaced = [m for m in ai_messages if m.content == _RECOVERY]
    # Exactly one AIMessage carries the recovery text.
    assert len(replaced) == 1
    # It has no tool_calls.
    assert not replaced[0].tool_calls
    # And the "should never appear" text is absent — the jump_to ended the loop.
    assert not any(
        isinstance(m, AIMessage) and m.content == "should never appear"
        for m in result["messages"]
    )

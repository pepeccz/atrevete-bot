"""Unit tests for ``FinalTextRecoveryMiddleware``.

The middleware fires at ``after_agent`` — once, when the agent loop ends —
rather than ``after_model`` (which would hijack every mid-loop tool call
that naturally has empty content). Tests assert the recovery only kicks in
when the AGENT terminates with an empty final AIMessage.
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from agent.middleware.final_text_recovery import FinalTextRecoveryMiddleware
from tests.unit.middleware._offline import ScriptedModel


@tool
def _noop(x: str | None = None) -> str:
    """noop stub"""
    return "ok"


_FALLBACK = "Perdoná, tuve un problema. ¿Podés repetirlo?"


def test_empty_final_content_is_rewritten():
    """When the agent ends with an AIMessage of empty content, recovery fires."""
    responses = [AIMessage(content="")]
    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_noop],
        middleware=[FinalTextRecoveryMiddleware(fallback_text=_FALLBACK)],
    )
    result = agent.invoke({"messages": [HumanMessage("x")]})

    ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
    assert ai_messages[-1].content == _FALLBACK


def test_nonempty_final_content_is_left_alone():
    responses = [AIMessage(content="an honest reply")]
    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_noop],
        middleware=[FinalTextRecoveryMiddleware(fallback_text=_FALLBACK)],
    )
    result = agent.invoke({"messages": [HumanMessage("x")]})

    ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
    assert ai_messages[-1].content == "an honest reply"


def test_tool_call_cycle_is_not_hijacked():
    """A mid-loop AIMessage with tool_calls + empty content (the normal tool
    invocation shape) must NOT be rewritten. Regression test for the bug that
    caused every booking flow to fall back on its first tool call."""
    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "_noop", "args": {}, "id": "tc1"}],
        ),
        AIMessage(content="real final answer"),
    ]
    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_noop],
        middleware=[FinalTextRecoveryMiddleware(fallback_text=_FALLBACK)],
    )
    result = agent.invoke({"messages": [HumanMessage("x")]})

    ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
    # The tool-call AIMessage survived (the loop continued past it).
    tool_call_ai = [m for m in ai_messages if m.tool_calls]
    assert len(tool_call_ai) == 1
    # Final AIMessage is the real final answer — recovery did NOT fire.
    assert ai_messages[-1].content == "real final answer"


def test_whitespace_only_final_content_is_treated_as_empty():
    responses = [AIMessage(content="   \n  ")]
    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_noop],
        middleware=[FinalTextRecoveryMiddleware(fallback_text=_FALLBACK)],
    )
    result = agent.invoke({"messages": [HumanMessage("x")]})

    ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
    assert ai_messages[-1].content == _FALLBACK

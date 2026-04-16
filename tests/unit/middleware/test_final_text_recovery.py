"""Unit tests for ``FinalTextRecoveryMiddleware``."""

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


def test_empty_content_with_tool_calls_is_rewritten():
    # First AI has tool_calls + empty content; second is plain text to terminate.
    # The middleware should overwrite the FIRST message in place.
    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "_noop", "args": {}, "id": "tc1"}],
        ),
        AIMessage(content="real final"),
    ]
    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_noop],
        middleware=[FinalTextRecoveryMiddleware(fallback_text=_FALLBACK)],
    )
    result = agent.invoke({"messages": [HumanMessage("x")]})

    # The first AIMessage with tool_calls should have been overwritten — no
    # AIMessage in the final history should still carry the empty-content +
    # tool_calls shape.
    ai_with_empty_and_calls = [
        m
        for m in result["messages"]
        if isinstance(m, AIMessage) and m.tool_calls and not (m.content or "").strip()
    ]
    assert ai_with_empty_and_calls == []


def test_nonempty_content_is_left_alone():
    responses = [AIMessage(content="an honest reply")]
    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_noop],
        middleware=[FinalTextRecoveryMiddleware(fallback_text=_FALLBACK)],
    )
    result = agent.invoke({"messages": [HumanMessage("x")]})

    ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
    assert ai_messages[-1].content == "an honest reply"


def test_empty_content_without_tool_calls_is_left_alone():
    # No tool_calls → recovery does NOT apply; create_agent will just stop.
    responses = [AIMessage(content="")]
    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_noop],
        middleware=[FinalTextRecoveryMiddleware(fallback_text=_FALLBACK)],
    )
    result = agent.invoke({"messages": [HumanMessage("x")]})

    ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
    # Not replaced — the middleware only fires when there are pending tool_calls.
    assert ai_messages[-1].content == ""


def test_whitespace_only_content_is_treated_as_empty():
    responses = [
        AIMessage(
            content="   \n  ",
            tool_calls=[{"name": "_noop", "args": {}, "id": "tc1"}],
        ),
        AIMessage(content="next"),
    ]
    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_noop],
        middleware=[FinalTextRecoveryMiddleware(fallback_text=_FALLBACK)],
    )
    result = agent.invoke({"messages": [HumanMessage("x")]})

    ai_with_empty_and_calls = [
        m
        for m in result["messages"]
        if isinstance(m, AIMessage) and m.tool_calls and not (m.content or "").strip()
    ]
    assert ai_with_empty_and_calls == []

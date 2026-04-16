"""Unit tests for ``ToolChoiceMiddleware``."""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from agent.middleware.tool_choice import ToolChoiceMiddleware
from tests.unit.middleware._offline import ScriptedModel


@tool
def _noop(x: str | None = None) -> str:
    """noop stub"""
    return "ok"


def test_forces_tool_choice_when_predicate_true():
    captured: list[object] = []

    class _Spy(ToolChoiceMiddleware):
        def wrap_model_call(self, request, handler):
            from dataclasses import replace

            choice = self._choice if self._when(request.state) else None
            captured.append(choice)
            return handler(replace(request, tool_choice=choice))

    agent = create_agent(
        model=ScriptedModel(responses=[AIMessage(content="done")]),
        tools=[_noop],
        middleware=[_Spy(when=lambda _state: True, choice="required")],
    )
    agent.invoke({"messages": [HumanMessage("x")]})

    assert captured == ["required"]


def test_clears_tool_choice_when_predicate_false():
    captured: list[object] = []

    class _Spy(ToolChoiceMiddleware):
        def wrap_model_call(self, request, handler):
            from dataclasses import replace

            choice = self._choice if self._when(request.state) else None
            captured.append(choice)
            return handler(replace(request, tool_choice=choice))

    agent = create_agent(
        model=ScriptedModel(responses=[AIMessage(content="done")]),
        tools=[_noop],
        middleware=[_Spy(when=lambda _state: False, choice="required")],
    )
    agent.invoke({"messages": [HumanMessage("x")]})

    assert captured == [None]


def test_human_message_predicate_fires_on_first_turn_only():
    """Typical booking usage: required on the initial HumanMessage, clear after."""
    captured: list[object] = []

    def on_human(state) -> bool:
        msgs = state.get("messages") or []
        return bool(msgs) and isinstance(msgs[-1], HumanMessage)

    class _Spy(ToolChoiceMiddleware):
        def wrap_model_call(self, request, handler):
            from dataclasses import replace

            choice = self._choice if self._when(request.state) else None
            captured.append(choice)
            return handler(replace(request, tool_choice=choice))

    agent = create_agent(
        model=ScriptedModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "_noop", "args": {}, "id": "tc1"}],
                ),
                AIMessage(content="done"),
            ]
        ),
        tools=[_noop],
        middleware=[_Spy(when=on_human, choice="required")],
    )
    agent.invoke({"messages": [HumanMessage("x")]})

    # First call: last message is HumanMessage → required.
    # Second call: last message is ToolMessage → cleared.
    assert captured[0] == "required"
    assert captured[1] is None


def test_custom_choice_value_is_forwarded():
    captured: list[object] = []

    class _Spy(ToolChoiceMiddleware):
        def wrap_model_call(self, request, handler):
            from dataclasses import replace

            choice = self._choice if self._when(request.state) else None
            captured.append(choice)
            return handler(replace(request, tool_choice=choice))

    agent = create_agent(
        model=ScriptedModel(responses=[AIMessage(content="done")]),
        tools=[_noop],
        middleware=[_Spy(when=lambda _state: True, choice="any")],
    )
    agent.invoke({"messages": [HumanMessage("x")]})

    assert captured == ["any"]

"""Unit tests for ``DynamicToolsMiddleware``."""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from agent.middleware.dynamic_tools import DynamicToolsMiddleware
from tests.unit.middleware._offline import ScriptedModel


@tool
def _fake_update(x: str | None = None) -> str:
    """update stub"""
    return f"updated {x}"


@tool
def _fake_check(x: str | None = None) -> str:
    """check stub"""
    return f"checked {x}"


@tool
def _fake_book(x: str | None = None) -> str:
    """book stub"""
    return f"booked {x}"


_allow_ref: dict[str, set[str]] = {"current": set()}


def _bind_set(_state) -> set[str]:
    """Test hook — closure-backed allow-set (independent of state schema)."""
    return _allow_ref["current"]


def test_filters_out_disallowed_tools_from_model_request():
    _allow_ref["current"] = {"_fake_update"}
    captured: list[list[str]] = []

    class _Recorder(DynamicToolsMiddleware):
        def wrap_model_call(self, request, handler):
            from dataclasses import replace

            allowed = set(self._allowed_names(request.state))
            filtered = [t for t in request.tools if getattr(t, "name", None) in allowed]
            captured.append([t.name for t in filtered])
            return handler(replace(request, tools=filtered))

    agent = create_agent(
        model=ScriptedModel(responses=[AIMessage(content="done")]),
        tools=[_fake_update, _fake_check, _fake_book],
        middleware=[_Recorder(_bind_set)],
    )
    agent.invoke({"messages": [HumanMessage("x")]})

    assert captured == [["_fake_update"]]


def test_returns_empty_tool_list_when_no_names_allowed():
    _allow_ref["current"] = set()
    captured_lists: list[list[str]] = []

    class _Recorder(DynamicToolsMiddleware):
        def wrap_model_call(self, request, handler):
            from dataclasses import replace

            allowed = set(self._allowed_names(request.state))
            filtered = [t for t in request.tools if getattr(t, "name", None) in allowed]
            captured_lists.append([t.name for t in filtered])
            return handler(replace(request, tools=filtered))

    agent = create_agent(
        model=ScriptedModel(responses=[AIMessage(content="done")]),
        tools=[_fake_update, _fake_check, _fake_book],
        middleware=[_Recorder(_bind_set)],
    )
    agent.invoke({"messages": [HumanMessage("x")]})

    assert captured_lists == [[]]


def test_all_tools_pass_through_when_all_names_allowed():
    _allow_ref["current"] = {"_fake_update", "_fake_check", "_fake_book"}
    captured: list[list[str]] = []

    class _Recorder(DynamicToolsMiddleware):
        def wrap_model_call(self, request, handler):
            from dataclasses import replace

            allowed = set(self._allowed_names(request.state))
            filtered = [t for t in request.tools if getattr(t, "name", None) in allowed]
            captured.append([t.name for t in filtered])
            return handler(replace(request, tools=filtered))

    agent = create_agent(
        model=ScriptedModel(responses=[AIMessage(content="done")]),
        tools=[_fake_update, _fake_check, _fake_book],
        middleware=[_Recorder(_bind_set)],
    )
    agent.invoke({"messages": [HumanMessage("x")]})

    assert set(captured[0]) == {"_fake_update", "_fake_check", "_fake_book"}


def test_state_driven_filter_reacts_to_state_change_mid_run():
    """The filter callable receives live state on every call — it must see
    updates that earlier middleware writes into state."""

    sequence: list[list[str]] = []

    class _Recorder(DynamicToolsMiddleware):
        def wrap_model_call(self, request, handler):
            from dataclasses import replace

            allowed = set(self._allowed_names(request.state))
            filtered = [t for t in request.tools if getattr(t, "name", None) in allowed]
            sequence.append([t.name for t in filtered])
            return handler(replace(request, tools=filtered))

    # Two model turns: first emits a tool_call to _fake_update, second ends.
    # The filter returns {_fake_update} initially, then {_fake_update, _fake_book}.
    state_toggle = {"turn": 0}

    def dynamic_allow(state) -> set[str]:
        state_toggle["turn"] += 1
        if state_toggle["turn"] == 1:
            return {"_fake_update"}
        return {"_fake_update", "_fake_book"}

    agent = create_agent(
        model=ScriptedModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "_fake_update", "args": {"x": "a"}, "id": "t1"}
                    ],
                ),
                AIMessage(content="done"),
            ]
        ),
        tools=[_fake_update, _fake_check, _fake_book],
        middleware=[_Recorder(dynamic_allow)],
    )
    agent.invoke({"messages": [HumanMessage("x")]})

    assert sequence[0] == ["_fake_update"]
    assert set(sequence[1]) == {"_fake_update", "_fake_book"}

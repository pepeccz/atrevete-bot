"""Unit tests for ``NodeBridgeMiddleware``.

Covers acceptance criteria 4 & 5 of the fix-booking-async-middleware-hook
change: the sync ``wrap_tool_call`` hook must forward through the node's
async ``_pre_tool_call`` / ``_post_tool_result`` hooks (including patched
args) and must short-circuit when ``_pre_tool_call`` returns a
``ToolCallRejection`` — emitting a ``ToolMessage(status="error")`` carrying
``rejected: True``, ``error_code`` and ``error_message``.

End-to-end drive is via ``agent.invoke`` (sync) — the bridge still works in
that mode via the ``asyncio.run`` fallback when no running loop is captured.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from agent.middleware.node_bridge import NodeBridgeMiddleware
from agent.modes.base import ToolCallRejection
from tests.unit.middleware._offline import ScriptedModel


class _FakeNode:
    """Minimal node stub with async ``_pre_tool_call`` / ``_post_tool_result``.

    Records every hook invocation and optionally patches args or rejects.
    """

    def __init__(
        self,
        *,
        patched_args: dict[str, Any] | None = None,
        rejection: ToolCallRejection | None = None,
    ) -> None:
        self._patched_args = patched_args
        self._rejection = rejection
        self.pre_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any], Any]] = []

    async def _pre_tool_call(
        self, tool_name: str, tool_args: dict[str, Any]
    ) -> Any:
        self.pre_calls.append((tool_name, dict(tool_args)))
        if self._rejection is not None:
            return self._rejection
        if self._patched_args is not None:
            return dict(self._patched_args)
        return dict(tool_args)

    async def _post_tool_result(
        self, tool_name: str, tool_args: dict[str, Any], result: Any
    ) -> None:
        self.post_calls.append((tool_name, dict(tool_args), result))


# ---------------------------------------------------------------------------
# Tool stubs
# ---------------------------------------------------------------------------

_last_seen_args: dict[str, Any] = {}


@tool
def _echo(day: str = "mon", note: str = "") -> str:
    """echo stub — records args it was invoked with."""
    _last_seen_args.clear()
    _last_seen_args.update({"day": day, "note": note})
    return json.dumps({"ok": True, "echoed": {"day": day, "note": note}})


def _reset_echo() -> None:
    _last_seen_args.clear()


# ---------------------------------------------------------------------------
# T4 — sync wrap_tool_call forwards pre + post hooks and patched args
# ---------------------------------------------------------------------------


def test_wrap_tool_call_forwards_pre_and_post_hooks() -> None:
    """Normal path: pre runs → patched args reach tool → post runs with parsed JSON."""
    _reset_echo()
    node = _FakeNode(patched_args={"day": "tue", "note": "PATCHED"})

    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "_echo", "args": {"day": "mon"}, "id": "c1"}],
        ),
        AIMessage(content="done"),
    ]

    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_echo],
        middleware=[NodeBridgeMiddleware(node)],
    )
    result = agent.invoke({"messages": [HumanMessage("ping")]})

    # Pre-hook fired exactly once with the original args.
    assert node.pre_calls == [("_echo", {"day": "mon"})]

    # The tool received the PATCHED args (not the original).
    assert _last_seen_args == {"day": "tue", "note": "PATCHED"}

    # Post-hook fired once with the patched args and the parsed JSON result.
    assert len(node.post_calls) == 1
    post_name, post_args, post_result = node.post_calls[0]
    assert post_name == "_echo"
    assert post_args == {"day": "tue", "note": "PATCHED"}
    assert isinstance(post_result, dict)
    assert post_result == {"ok": True, "echoed": {"day": "tue", "note": "PATCHED"}}

    # ToolMessage flows through unchanged.
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_call_id == "c1"


# ---------------------------------------------------------------------------
# T4 — short-circuit on ToolCallRejection
# ---------------------------------------------------------------------------


def test_wrap_tool_call_short_circuits_on_rejection() -> None:
    """When ``_pre_tool_call`` returns a ``ToolCallRejection``, the tool
    MUST NOT execute, and a ``ToolMessage(status="error")`` MUST be emitted
    carrying ``rejected: True``, ``error_code`` and ``error_message``.
    """
    _reset_echo()
    rejection = ToolCallRejection(
        name="_echo",
        error_code="GATE_REJECTED",
        error_message="no puedo ahora, falta info",
    )
    node = _FakeNode(rejection=rejection)

    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "_echo", "args": {"day": "mon"}, "id": "r1"}],
        ),
        AIMessage(content="ok, stopping"),
    ]

    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_echo],
        middleware=[NodeBridgeMiddleware(node)],
    )
    result = agent.invoke({"messages": [HumanMessage("go")]})

    # Tool body NEVER ran.
    assert _last_seen_args == {}
    # Post hook NEVER fired.
    assert node.post_calls == []
    # Pre hook fired once.
    assert len(node.pre_calls) == 1

    # Emitted ToolMessage has error status and rejection payload.
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    tm = tool_msgs[0]
    assert tm.status == "error"
    assert tm.tool_call_id == "r1"
    payload = json.loads(tm.content)
    assert payload == {
        "rejected": True,
        "error_code": "GATE_REJECTED",
        "error_message": "no puedo ahora, falta info",
    }


# ---------------------------------------------------------------------------
# T4 — async driver (ainvoke) must also work — this is the real bug we fixed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrap_tool_call_works_under_ainvoke() -> None:
    """Regression: under ``ainvoke`` the middleware runs in a worker thread
    and LangChain 1.2.x calls the SYNC hook. The bridge must marshal the
    async node coroutines back to the running loop via
    ``run_coroutine_threadsafe``. If the hook were async-only
    (``awrap_tool_call``), LangChain 1.2.x raises
    "Asynchronous implementation of awrap_tool_call is not available".
    """
    _reset_echo()
    node = _FakeNode(patched_args={"day": "fri", "note": "ASYNC"})

    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "_echo", "args": {"day": "mon"}, "id": "a1"}],
        ),
        AIMessage(content="done"),
    ]

    agent = create_agent(
        model=ScriptedModel(responses=responses),
        tools=[_echo],
        middleware=[NodeBridgeMiddleware(node)],
    )

    result = await agent.ainvoke({"messages": [HumanMessage("ping async")]})

    # Tool ran with patched args exactly once.
    assert _last_seen_args == {"day": "fri", "note": "ASYNC"}
    # Both hooks fired.
    assert len(node.pre_calls) == 1
    assert len(node.post_calls) == 1

    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1

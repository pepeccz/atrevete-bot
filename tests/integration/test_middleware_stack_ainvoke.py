"""Integration test: BOOKING middleware stack must not raise NotImplementedError under ainvoke.

This test is the REGRESSION CANARY for REQ-4.
It FAILED on master before fix T1-T3 with:
    NotImplementedError: Asynchronous implementation of awrap_tool_call is not available

The test mirrors the middleware composition at booking_mode.py:650-655 verbatim.
If that section changes, update the mirror here and add a comment.
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from agent.middleware.dedup import DedupToolCallMiddleware
from agent.middleware.final_text_recovery import FinalTextRecoveryMiddleware
from agent.middleware.node_bridge import NodeBridgeMiddleware
from agent.middleware.token_tracking import TokenTrackingMiddleware
from agent.middleware.tool_choice import ToolChoiceMiddleware
from tests.unit.middleware._offline import ScriptedModel


# ---------------------------------------------------------------------------
# Minimal fake node — satisfies NodeBridgeMiddleware's duck-type contract.
# NodeBridgeMiddleware only needs _pre_tool_call and _post_tool_result.
# ---------------------------------------------------------------------------


class _FakeNode:
    """Minimal stand-in for BookingModeNode, satisfying NodeBridgeMiddleware."""

    mode_name = "BOOKING"

    async def _pre_tool_call(self, tool_name: str, tool_args: dict) -> dict:
        """Pass-through: return args unchanged (no rejection, no patching)."""
        return tool_args

    async def _post_tool_result(self, tool_name: str, tool_args: dict, result: object) -> None:
        """No-op post-hook."""


# ---------------------------------------------------------------------------
# A real LangChain @tool so the agent can actually execute it
# ---------------------------------------------------------------------------


@tool
def echo(text: str) -> str:
    """Echo back the input text."""
    return f"ECHO: {text}"


# ---------------------------------------------------------------------------
# ScriptedModel responses:
#   Turn 1 — model calls the echo tool
#   Turn 2 — model produces a final text response
# ---------------------------------------------------------------------------

_SCRIPTED_RESPONSES = [
    AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_001",
                "name": "echo",
                "args": {"text": "hola"},
                "type": "tool_call",
            }
        ],
    ),
    AIMessage(content="Hola, ¿en qué te puedo ayudar?"),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_booking_stack_ainvoke_no_notimplementederror() -> None:
    """BOOKING middleware stack must complete ainvoke without NotImplementedError.

    This test FAILED on master before fix T1-T3 because DedupToolCallMiddleware
    only defined wrap_tool_call (sync), not awrap_tool_call (async). Under
    ainvoke, LangChain 1.2.x pulls both hooks into the async dispatch chain
    and the base-class awrap_tool_call raises NotImplementedError.

    Mirror of booking_mode.py:650-655 (update comment if source changes):
    """
    model = ScriptedModel(responses=_SCRIPTED_RESPONSES)
    node = _FakeNode()

    # Mirror of booking_mode.py:650-655
    middleware = [
        NodeBridgeMiddleware(node),
        DedupToolCallMiddleware(),
        FinalTextRecoveryMiddleware(fallback_text="fallback"),
        TokenTrackingMiddleware(mode_name="BOOKING"),
    ]

    agent = create_agent(model=model, tools=[echo], middleware=middleware)
    result = await agent.ainvoke({"messages": [HumanMessage("Hola, quiero cortarme el pelo")]})

    messages = result["messages"]
    # A ToolMessage proves the tool was executed (awrap_tool_call ran, no NotImplementedError)
    assert any(isinstance(m, ToolMessage) for m in messages), (
        "Expected a ToolMessage from echo tool execution — awrap_tool_call must have run"
    )
    # Final message must have non-empty content
    final = messages[-1]
    assert isinstance(final, AIMessage), f"Expected final AIMessage, got {type(final)}"
    assert final.content, f"Final AIMessage must have non-empty content, got: {final.content!r}"


async def test_booking_stack_with_tool_choice_ainvoke() -> None:
    """ToolChoiceMiddleware.awrap_model_call must not raise NotImplementedError.

    Covers REQ-2 Scenario: model-call hook parity under ainvoke when
    ToolChoiceMiddleware is composed at index 0 (as booking_mode.py:656-663 does
    when tool_choice is truthy).
    """
    model = ScriptedModel(responses=_SCRIPTED_RESPONSES[:])
    node = _FakeNode()

    middleware_with_choice = [
        ToolChoiceMiddleware(when=lambda state: True, choice="required"),
        NodeBridgeMiddleware(node),
        DedupToolCallMiddleware(),
        FinalTextRecoveryMiddleware(fallback_text="fallback"),
        TokenTrackingMiddleware(mode_name="BOOKING"),
    ]

    agent = create_agent(model=model, tools=[echo], middleware=middleware_with_choice)
    result = await agent.ainvoke({"messages": [HumanMessage("Hola, quiero cortarme el pelo")]})

    messages = result["messages"]
    final = messages[-1]
    assert isinstance(final, AIMessage), f"Expected final AIMessage, got {type(final)}"
    assert final.content, f"Final AIMessage must have non-empty content, got: {final.content!r}"

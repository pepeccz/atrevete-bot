"""Turn-1 audience ambiguity delivery via ToolMessage fields.

REQ: When update_booking resolves a service with audience ambiguity on turn 1,
the ToolMessage returned to the LLM on the SAME turn must contain either:
  - "audiencia" in the `missing` list (serialised into ToolMessage content), OR
  - "Audiencia ambigua" in the `next_step` field

This verifies the FIX path, NOT the XML render path (<audience_ambiguity> tag
is a secondary signal for turn N+1 via dynamic context refresh).

Architecture under test
-----------------------
The create_agent system_message is cached at construction. The <audience_ambiguity>
XML tag only propagates on turn N+1 via _refresh_dynamic_context. The fix routes
the signal through the ToolMessage fields (next_step / missing) so it reaches the
LLM on the SAME turn the ambiguity is detected.

Test strategy: scripted model at the LLM level
-----------------------------------------------
We mock at the LLM object level (node.llm), NOT at create_agent level.
This ensures the real create_agent + real middleware stack (NodeBridgeMiddleware,
DynamicToolsMiddleware, etc.) runs, so _pre_tool_call / _post_tool_result /
real tool execution all occur. The model receives:
  - Call #1: returns AIMessage with tool_call → update_booking fires for real
  - Call #2: a spy captures the messages (which include the real ToolMessage)
              then returns a final AIMessage

We then inspect the captured messages to find the ToolMessage content.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


# ---------------------------------------------------------------------------
# Scripted LLM that captures the second call's messages
# ---------------------------------------------------------------------------


class _ScriptedAndCapturingLLM:
    """
    LLM stand-in that:
    - Call #1: returns an AIMessage with a tool call to update_booking
    - Call #2+: records messages and returns a fixed AIMessage (no tool calls)
    """

    def __init__(self):
        self._call_count = 0
        self.captured_calls: list[list] = []  # messages per call
        self.model_name = "fake-scripted-model"

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages, **kwargs) -> AIMessage:
        return self._handle(messages)

    def invoke(self, messages, **kwargs) -> AIMessage:
        return self._handle(messages)

    def _handle(self, messages) -> AIMessage:
        n = self._call_count
        self._call_count += 1
        self.captured_calls.append(list(messages))

        if n == 0:
            # First call: emit a tool call to update_booking
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "update_booking",
                        "args": {"services": ["Corte Señora"]},
                        "id": "tc_audience_delivery_001",
                        "type": "tool_call",
                    }
                ],
            )
        # Subsequent calls: final text reply (terminates the agent loop)
        return AIMessage(content="Perfecto, ¿para quién es el corte?")


# ---------------------------------------------------------------------------
# Node + state factory
# ---------------------------------------------------------------------------


def _make_node() -> tuple[Any, _ScriptedAndCapturingLLM]:
    from agent.modes.booking_mode import BookingModeNode

    with patch("agent.modes.booking_mode.BaseModeNode.__init__", return_value=None):
        node = BookingModeNode.__new__(BookingModeNode)

    llm = _ScriptedAndCapturingLLM()
    node.llm = llm
    node._cached_stylists_by_category = {}
    node._cached_service_names = {}
    node._booking_context = {}
    node._mode_context = {}
    node._current_state = {}
    return node, llm


def _make_state(user_message: str) -> dict:
    from agent.state.schemas import create_initial_state

    state = create_initial_state("audience-turn1-delivery-test", "+34600000001")
    state["user_message"] = user_message
    state["current_mode"] = "BOOKING"
    state["customer_name"] = "Test Customer"
    state["is_first_interaction"] = False
    state["error_count"] = 0
    state["escalation_triggered"] = False
    state["ai_disclosure_sent"] = True
    state["booking_context"] = {}
    state["mode_context"] = {}
    state["messages"] = [{"role": "user", "content": user_message}]
    return state


# ---------------------------------------------------------------------------
# Mock service fixtures
# ---------------------------------------------------------------------------


def _mock_svc():
    svc = MagicMock()
    svc.name = "Corte Señora"
    svc.audience = "adult_female"
    svc.category = MagicMock(value="HAIRDRESSING")
    svc.duration_minutes = 45
    return svc


_SIBLINGS = ["Corte Caballero", "Corte Niño"]


# ---------------------------------------------------------------------------
# Common patches — mirrors test_booking_audience_turn2.py
# ---------------------------------------------------------------------------


@pytest.fixture
def _common_patches():
    with (
        patch(
            "agent.modes.booking_mode.BookingModeNode._load_stylists_by_category",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "agent.modes.booking_mode.BookingModeNode._load_service_names",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "agent.modes.booking_mode.build_layered_messages",
            new_callable=AsyncMock,
            return_value=([HumanMessage(content="system stub")], 0),
        ),
        patch(
            "agent.modes.booking_mode.get_booking_config",
            new_callable=AsyncMock,
            return_value=MagicMock(tool_choice_policy=MagicMock(value="NEVER_FORCE")),
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# THE TEST
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audience_ambiguity_delivered_via_tool_message(_common_patches):
    """Turn-1 ToolMessage must carry the audience ambiguity signal in next_step or missing.

    Assertion (a): The ToolMessage content in the second LLM call contains
      "audiencia" (in missing list) OR "Audiencia ambigua" (in next_step).

    Assertion (b): booking_context["_audience_ambiguity"] is set (regression guard).

    Expected RED before fix: ToolMessage does NOT contain either signal because
    _build_response() in booking_data_tools.py does not yet inject the audience
    ambiguity into next_step/missing.
    """
    node, llm = _make_node()
    state = _make_state("Hola, quiero cortarme el pelo")

    with (
        patch(
            "agent.tools.availability_tools._resolve_service_by_name",
            new_callable=AsyncMock,
            return_value=_mock_svc(),
        ),
        patch(
            "agent.tools.availability_tools._get_active_stylists_for_category",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "agent.tools.booking_data_tools._find_audience_siblings_for_signal",
            new_callable=AsyncMock,
            return_value=_SIBLINGS,
        ),
    ):
        result = await node.handle(state, intent=None)

    # ── Assertion (b): booking_context has _audience_ambiguity ───────────────
    booking_ctx = result.get("booking_context", {})
    ambiguity = booking_ctx.get("_audience_ambiguity")
    assert ambiguity is not None, (
        "Expected booking_context['_audience_ambiguity'] to be set after turn-1. "
        f"Got booking_context keys={list(booking_ctx.keys())!r}. "
        "Regression guard for the detection block in update_booking."
    )

    # ── Assertion (a): ToolMessage content carries the ambiguity signal ──────
    # The second call to the LLM should have the ToolMessage in its messages.
    assert llm._call_count >= 2, (
        f"Expected at least 2 LLM calls (tool call + response), got {llm._call_count}. "
        "The agent may have terminated without executing the tool."
    )

    # Find the ToolMessage in the second captured call's messages
    second_call_msgs = llm.captured_calls[1]  # messages the LLM saw on call #2
    tool_message_content: str | None = None
    for msg in second_call_msgs:
        if isinstance(msg, ToolMessage):
            content = msg.content
            tool_message_content = content if isinstance(content, str) else json.dumps(content)
            break

    assert tool_message_content is not None, (
        "No ToolMessage found in the second LLM call messages. "
        f"Message types in call #2: {[type(m).__name__ for m in second_call_msgs]}"
    )

    has_signal = (
        "audiencia" in tool_message_content.lower()
        or "audiencia ambigua" in tool_message_content.lower()
    )
    assert has_signal, (
        "ToolMessage content does NOT contain audience ambiguity signal. "
        "Expected 'audiencia' in missing list OR 'Audiencia ambigua' in next_step. "
        f"Actual ToolMessage content:\n{tool_message_content}\n\n"
        "FAILS before fix: _build_response() in booking_data_tools.py does not "
        "yet inject audience ambiguity into next_step/missing."
    )

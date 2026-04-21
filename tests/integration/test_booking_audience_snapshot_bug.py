"""Regression test — conv_id=5 audience disambiguation snapshot bug.

The bug (explore §Part 1, whack-a-mole #7):
  - update_booking used to write ``patch["_audience_ambiguity"]`` (booking_data_tools.py:380)
  - compute_next_prompt reads ``bc.get("pending_disambiguations")`` (grounding.py:246)
  - These are completely different fields. ``pending_disambiguations`` has zero
    production writers → Branch 4 (ASK_AUDIENCE) NEVER fires → bot offers stylists
    directly without asking señora/caballero/niño.

Expected flow (post-fix):
  user: "quiero cortarme el pelo"
  → LLM calls update_booking(services=["Corte"])  [or similar]
  → booking_context["pending_disambiguations"] is populated
  → compute_next_prompt returns action="ASK_AUDIENCE"
  → bot asks ¿es para señora, caballero o niño?

This test must be RED on master (no rename, no rebind).
It turns GREEN after Phase 2 (rename) lands, because that commit
wires the writer to produce ``pending_disambiguations``.

Phase 3 (snapshot rebind) is a different fix — it ensures same-turn
visibility of pre-loop resolver patches to the grounding middleware.
That is tested in tests/unit/booking/test_grounding_sees_pre_loop_patches.py.

Placement:   tests/integration/test_booking_audience_snapshot_bug.py
Marker:      @pytest.mark.audience_regression
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

# ---------------------------------------------------------------------------
# Scripted LLM
# ---------------------------------------------------------------------------


class _ScriptedLLM:
    """
    LLM stand-in for the audience disambiguation regression.

    Call #1: emits a tool call to update_booking with an audience-ambiguous service.
    Call #2+: captures messages (so we can inspect the grounding directive) and
              returns a final AIMessage with no tool calls.
    """

    def __init__(self):
        self._call_count = 0
        self.captured_calls: list[list] = []
        self.model_name = "fake-audience-regression-model"

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
            # First call: emit tool call to update_booking with the ambiguous service.
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "update_booking",
                        "args": {"services": ["Corte"]},
                        "id": "tc_audience_regression_001",
                        "type": "tool_call",
                    }
                ],
            )
        # Subsequent calls: final reply, terminates the agent loop.
        return AIMessage(content="Perfecto, ¿para quién es el corte?")


# ---------------------------------------------------------------------------
# Node + state helpers
# ---------------------------------------------------------------------------


def _make_node() -> tuple[Any, _ScriptedLLM]:
    from agent.modes.booking_mode import BookingModeNode

    with patch("agent.modes.booking_mode.BaseModeNode.__init__", return_value=None):
        node = BookingModeNode.__new__(BookingModeNode)

    llm = _ScriptedLLM()
    node.llm = llm
    node._cached_stylists_by_category = {}
    node._cached_service_names = {}
    node._booking_context = {}
    node._mode_context = {}
    node._current_state = {}
    return node, llm


def _make_state(user_message: str) -> dict:
    from agent.state.schemas import create_initial_state

    state = create_initial_state("audience-snapshot-regression-test", "+34600000005")
    state["user_message"] = user_message
    state["current_mode"] = "BOOKING"
    state["customer_name"] = "Test Customer"
    state["is_first_interaction"] = False
    state["error_count"] = 0
    state["escalation_triggered"] = False
    state["ai_disclosure_sent"] = True
    # Empty booking_context — no pre-existing data, clean start.
    state["booking_context"] = {}
    state["mode_context"] = {}
    state["messages"] = [{"role": "user", "content": user_message}]
    return state


# ---------------------------------------------------------------------------
# Mock service fixtures — "Corte" is audience-ambiguous (has siblings)
# ---------------------------------------------------------------------------


def _mock_corte_svc() -> MagicMock:
    """A haircut service with audience variants (adult_female) and sibling services."""
    svc = MagicMock()
    svc.name = "Corte Señora"
    svc.audience = "adult_female"
    svc.category = MagicMock(value="HAIRDRESSING")
    svc.duration_minutes = 45
    return svc


_CORTE_SIBLINGS = ["Corte Caballero", "Corte Niño"]


# ---------------------------------------------------------------------------
# Common patches
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
# THE REGRESSION TEST
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.audience_regression
async def test_audience_disambiguation_grounding_fires_ask_audience(_common_patches):
    """conv_id=5 regression: after update_booking with audience-ambiguous service,
    the grounding directive injected into the second LLM call MUST be ASK_AUDIENCE.

    Pre-fix (master): grounding injects ASK_MORE_SERVICES or ASK_SERVICE because
      ``pending_disambiguations`` is never populated (writer uses ``_audience_ambiguity``).

    Post-fix (Phase 2 rename): grounding injects ASK_AUDIENCE because
      ``pending_disambiguations`` is now populated by the writer.

    The test reads the ``[grounding]`` HumanMessage injected before LLM call #2
    and asserts its action == "ASK_AUDIENCE".
    """
    node, llm = _make_node()
    state = _make_state("quiero cortarme el pelo")

    with (
        patch(
            "agent.tools.availability_tools._resolve_service_by_name",
            new_callable=AsyncMock,
            return_value=_mock_corte_svc(),
        ),
        patch(
            "agent.tools.availability_tools._get_active_stylists_for_category",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "agent.tools.booking_data_tools._find_audience_siblings_for_signal",
            new_callable=AsyncMock,
            return_value=_CORTE_SIBLINGS,
        ),
    ):
        result = await node.handle(state, intent=None)

    # ── Assertion 1: booking_context has pending_disambiguations populated ───
    booking_ctx = result.get("booking_context", {})
    pending = booking_ctx.get("pending_disambiguations")
    assert pending, (
        "Expected booking_context['pending_disambiguations'] to be non-empty after "
        "update_booking resolved an audience-ambiguous service. "
        f"Got booking_context keys={list(booking_ctx.keys())!r}. "
        "FAILS on master because writer emits '_audience_ambiguity', not "
        "'pending_disambiguations'. Turns GREEN after Phase 2 rename."
    )

    # ── Assertion 2: grounding directive in second LLM call is ASK_AUDIENCE ─
    assert llm._call_count >= 2, (
        f"Expected ≥2 LLM calls (tool call + response), got {llm._call_count}. "
        "The agent may have terminated without executing the tool."
    )

    second_call_msgs = llm.captured_calls[1]
    grounding_content: str | None = None
    for msg in second_call_msgs:
        if (
            isinstance(msg, HumanMessage)
            and hasattr(msg, "content")
            and isinstance(msg.content, str)
            and msg.content.startswith("[grounding]")
        ):
            grounding_content = msg.content
            break

    assert grounding_content is not None, (
        "No [grounding] HumanMessage found in the second LLM call messages. "
        f"Message types in call #2: {[type(m).__name__ for m in second_call_msgs]}"
    )

    assert "action=ASK_AUDIENCE" in grounding_content, (
        "Expected grounding directive action=ASK_AUDIENCE in second LLM call, "
        "meaning the bot should ask señora/caballero/niño BEFORE offering stylists. "
        f"Actual grounding content:\n{grounding_content}\n\n"
        "FAILS on master: grounding does not see 'pending_disambiguations' because "
        "the writer stores '_audience_ambiguity' instead. "
        "Turns GREEN after Phase 2 (rename _audience_ambiguity → pending_disambiguations)."
    )

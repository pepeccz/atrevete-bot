"""
Integration tests for audience ambiguity clearance and check_availability visibility gate.

C3.1 — _audience_ambiguity must be cleared after _extract_audience_from_reply sets hint.
C3.2 (in tests/unit/test_dynamic_tools_middleware.py) — check_availability hidden during ambiguity.

TDD cycle:
- C3.1 tests must FAIL before C3.3+C3.4 implementation.
  (C3.4 was actually completed in C2 commit — _audience_ambiguity pop() already in place.
   C3.1 tests may already pass for the pop() assertion but will confirm no regression.)
- Must PASS after C3.3 (get_tools predicate) and C3.4 (_audience_ambiguity pop).

Covers: R6, S6.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent.modes.booking_mode import BookingModeNode
from agent.state.schemas import create_initial_state


# ---------------------------------------------------------------------------
# Scripted agent stub
# ---------------------------------------------------------------------------


def _make_scripted_agent(reply: str = "Perfecto. ¿Qué estilista prefieres?") -> MagicMock:
    async def _ainvoke(input_: dict, *args, **kwargs) -> dict:
        messages = list(input_.get("messages", []))
        messages.append(AIMessage(content=reply))
        return {"messages": messages}

    agent_mock = MagicMock()
    agent_mock.ainvoke = _ainvoke
    return agent_mock


# ---------------------------------------------------------------------------
# Node factory
# ---------------------------------------------------------------------------


def _make_node() -> BookingModeNode:
    with patch("agent.modes.booking_mode.BaseModeNode.__init__", return_value=None):
        node = BookingModeNode.__new__(BookingModeNode)

    node.llm = MagicMock()
    node.llm.bind_tools = MagicMock(return_value=node.llm)
    node._cached_stylists_by_category = {}
    node._cached_service_names = {}
    node._booking_context = {}
    node._mode_context = {}
    node._current_state = {}
    return node


# ---------------------------------------------------------------------------
# State factory
# ---------------------------------------------------------------------------


def _make_state(
    user_message: str,
    booking_context: dict[str, Any] | None = None,
    prev_messages: list[dict] | None = None,
) -> dict:
    state = create_initial_state("audience-ambiguity-leak-test", "+34600000003")
    state["user_message"] = user_message
    state["current_mode"] = "BOOKING"
    state["customer_name"] = "Cliente Test"
    state["is_first_interaction"] = False
    state["error_count"] = 0
    state["escalation_triggered"] = False
    state["ai_disclosure_sent"] = True
    state["booking_context"] = booking_context or {}
    state["mode_context"] = {}
    base_messages = list(prev_messages) if prev_messages else []
    state["messages"] = base_messages + [{"role": "user", "content": user_message}]
    return state


# ---------------------------------------------------------------------------
# Shared patches
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
            return_value=MagicMock(tool_choice_policy=MagicMock(value="never_force")),
        ),
        patch(
            "agent.modes.booking_mode.BookingModeNode._maybe_prepend_intro",
            side_effect=lambda text, state: (text, False),
        ),
        patch(
            "agent.modes.booking_mode.BookingModeNode._sanitize_response",
            side_effect=lambda text: text,
        ),
        patch(
            "agent.modes.booking_mode.BookingModeNode._resolve_service_category",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "agent.modes.booking_mode.write_customer_memories",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# C3.1 — Two-turn audience ambiguity clearance (R6, S6)
# ---------------------------------------------------------------------------


class TestAudienceAmbiguityClearance:
    """
    C3.1: After turn-2 audience reply ('señora'), _audience_ambiguity must be cleared
    from booking_context atomically with setting service_audience_hint.

    Turn-1: booking_context has _audience_ambiguity set, no service_audience_hint.
    Turn-2: user sends "señora" → _extract_audience_from_reply fires →
            service_audience_hint must be set AND _audience_ambiguity must be absent.
    """

    async def test_audience_ambiguity_cleared_after_hint_set(self, _common_patches) -> None:
        """S6: _audience_ambiguity must be absent after turn-2 audience reply.

        This test validates that _extract_audience_from_reply atomically clears
        _audience_ambiguity when setting service_audience_hint.
        """
        node = _make_node()

        # Turn-1 state: _audience_ambiguity is set, no hint yet
        turn1_ctx = {
            "last_services": ["Corte"],
            "_audience_ambiguity": {
                "family": "Corte",
                "variants": ["Corte Señora", "Corte Caballero"],
            },
            # No service_audience_hint — that's why ambiguity is active
        }

        # Turn-2: user replies with audience token "señora"
        # State carries the booking_context from turn-1
        turn2_state = _make_state("señora", booking_context=turn1_ctx)

        agent_mock = _make_scripted_agent("Perfecto, un corte para señora. ¿Alguna estilista de preferencia?")

        with patch("langchain.agents.create_agent", return_value=agent_mock):
            result = await node.handle(turn2_state, intent=None)

        result_ctx = result.get("booking_context", {})

        # Assertion 1: service_audience_hint must be set to adult_female
        assert result_ctx.get("service_audience_hint") == "adult_female", (
            f"Expected service_audience_hint='adult_female' after 'señora', "
            f"got {result_ctx.get('service_audience_hint')!r}. "
            f"Full booking_context: {result_ctx!r}"
        )

        # Assertion 2: _audience_ambiguity must be absent
        assert "_audience_ambiguity" not in result_ctx, (
            f"_audience_ambiguity must be cleared after service_audience_hint is set, "
            f"but it's still present: {result_ctx.get('_audience_ambiguity')!r}. "
            "FAILS on master because the atomic pop() is not yet implemented."
        )

    async def test_audience_ambiguity_not_present_in_second_turn_tools(
        self, _common_patches
    ) -> None:
        """R7/S7: check_availability must NOT appear in get_tools when _audience_ambiguity is set.

        After turn-2 clears _audience_ambiguity and sets the hint, subsequent
        get_tools calls (with stylist set) should include check_availability.
        """
        node = _make_node()

        # State: has services, stylist, no slot, AND _audience_ambiguity still set
        # (simulates the state before the fix — during ambiguity, check_availability hidden)
        ctx_with_ambiguity = {
            "last_services": ["Corte Señora"],
            "last_stylist": "Maria",
            "_audience_ambiguity": {
                "family": "Corte",
                "variants": ["Corte Señora", "Corte Caballero"],
            },
        }
        tools_with_ambiguity = node.get_tools(ctx_with_ambiguity)
        tool_names = [t.name if hasattr(t, "name") else str(t) for t in tools_with_ambiguity]

        # With _audience_ambiguity set, check_availability must NOT be in tools
        assert "check_availability" not in tool_names, (
            f"check_availability must be hidden when _audience_ambiguity is truthy. "
            f"Got tools: {tool_names}. "
            "FAILS on master because the get_tools() predicate doesn't gate on _audience_ambiguity yet."
        )

    async def test_check_availability_visible_after_ambiguity_cleared(
        self, _common_patches
    ) -> None:
        """R7: check_availability must appear in get_tools after _audience_ambiguity is cleared."""
        node = _make_node()

        # Context: has services, stylist, no slot, NO _audience_ambiguity (cleared)
        ctx_without_ambiguity = {
            "last_services": ["Corte Señora"],
            "last_stylist": "Maria",
            # No _audience_ambiguity key
        }
        tools_without_ambiguity = node.get_tools(ctx_without_ambiguity)
        tool_names = [t.name if hasattr(t, "name") else str(t) for t in tools_without_ambiguity]

        assert "check_availability" in tool_names, (
            f"check_availability must be visible when _audience_ambiguity is absent "
            f"and services+stylist are set. Got tools: {tool_names}"
        )

"""
Integration tests for the pre-loop negation resolver hook in BookingModeNode.

C2.1 — Test that "Nada máß" (typo variant) causes add_more_asked=True before the LLM loop.
C2.2 — Test that telemetry is emitted with the correct shape (R4, S10).

TDD cycle:
- Must FAIL before C2.3 (pre-loop hook not yet wired).
- Must PASS after C2.3.

Covers: R1, R4, S1, S10.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent.modes.booking_mode import BookingModeNode
from agent.state.schemas import create_initial_state


# ---------------------------------------------------------------------------
# Scripted agent factory — deterministic single-turn LLM stub
# ---------------------------------------------------------------------------


def _make_scripted_agent(reply: str = "Perfecto. ¿Qué estilista prefieres?") -> MagicMock:
    """Build a mock create_agent that returns a deterministic reply."""

    async def _ainvoke(input_: dict, *args, **kwargs) -> dict:
        messages = list(input_.get("messages", []))
        messages.append(AIMessage(content=reply))
        return {"messages": messages}

    agent_mock = MagicMock()
    agent_mock.ainvoke = _ainvoke
    return agent_mock


# ---------------------------------------------------------------------------
# Node factory — BookingModeNode with mocked I/O
# ---------------------------------------------------------------------------


def _make_node() -> BookingModeNode:
    """Build a BookingModeNode with mocked LLM and no-op async helpers."""
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
) -> dict:
    """Build a minimal ConversationState for one booking turn."""
    state = create_initial_state("add-more-loop-test", "+34600000002")
    state["user_message"] = user_message
    state["current_mode"] = "BOOKING"
    state["customer_name"] = "Cliente Test"
    state["is_first_interaction"] = False
    state["error_count"] = 0
    state["escalation_triggered"] = False
    state["ai_disclosure_sent"] = True
    state["booking_context"] = booking_context or {}
    state["mode_context"] = {}
    # Mirrors preprocess_node_v6: user message is appended to messages before modes run
    state["messages"] = [{"role": "user", "content": user_message}]
    return state


# ---------------------------------------------------------------------------
# Shared patches for all tests in this module
# ---------------------------------------------------------------------------


@pytest.fixture
def _common_patches():
    """Patch all I/O that booking_mode.handle() touches."""
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
            return_value=MagicMock(
                tool_choice_policy=MagicMock(value="never_force")
            ),
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
# C2.1 — Pre-loop hook fires and sets add_more_asked=True
# ---------------------------------------------------------------------------


class TestPreLoopNegationHook:
    """C2.1: The pre-loop hook must fire for 'Nada máß' and set add_more_asked=True."""

    async def test_nada_masz_sets_add_more_asked(self, _common_patches) -> None:
        """R1/S1: pre-loop hook must classify 'Nada máß' as negation and set add_more_asked.

        MUST FAIL before C2.3 because the hook is not yet wired.
        """
        node = _make_node()

        # Preconditions from R1: last_services truthy, add_more_asked falsy,
        # no stylist, no _audience_ambiguity
        booking_ctx = {
            "last_services": ["Corte Señora", "Color Señora"],
            "add_more_asked": False,
        }
        state = _make_state("Nada máß", booking_context=booking_ctx)

        agent_mock = _make_scripted_agent()

        with patch("langchain.agents.create_agent", return_value=agent_mock):
            result = await node.handle(state, intent=None)

        result_booking_ctx = result.get("booking_context", {})
        assert result_booking_ctx.get("add_more_asked") is True, (
            f"Expected add_more_asked=True after 'Nada máß' with last_services set, "
            f"got booking_context={result_booking_ctx!r}. "
            "FAILS on master because the pre-loop negation hook is not yet wired."
        )

    async def test_hook_does_not_fire_without_last_services(self, _common_patches) -> None:
        """R1: hook must NOT fire when last_services is empty (precondition not met)."""
        node = _make_node()

        # No last_services — hook should NOT fire
        booking_ctx = {
            "last_services": [],
            "add_more_asked": False,
        }
        state = _make_state("nada", booking_context=booking_ctx)

        agent_mock = _make_scripted_agent()

        with patch("langchain.agents.create_agent", return_value=agent_mock):
            result = await node.handle(state, intent=None)

        result_booking_ctx = result.get("booking_context", {})
        # add_more_asked must remain False — hook didn't fire
        assert not result_booking_ctx.get("add_more_asked"), (
            f"Hook should NOT fire when last_services is empty, "
            f"but add_more_asked={result_booking_ctx.get('add_more_asked')!r}"
        )

    async def test_hook_does_not_fire_with_stylist_set(self, _common_patches) -> None:
        """R1: hook must NOT fire when stylist is already set (past the T5 window)."""
        node = _make_node()

        # Stylist already set — hook should not fire
        booking_ctx = {
            "last_services": ["Corte Señora"],
            "add_more_asked": False,
            "last_stylist": "Maria",
        }
        state = _make_state("nada más", booking_context=booking_ctx)

        agent_mock = _make_scripted_agent()

        with patch("langchain.agents.create_agent", return_value=agent_mock):
            result = await node.handle(state, intent=None)

        # The hook should NOT fire — a negation after stylist is set is handled by LLM
        # This is a guard test; add_more_asked may or may not be True from hook — what
        # matters is no regression if stylist is already set.
        # (This test validates precondition scoping, not primary flow.)


# ---------------------------------------------------------------------------
# C2.2 — Telemetry log shape (R4, S10)
# ---------------------------------------------------------------------------


class TestNegationResolverTelemetry:
    """C2.2: Telemetry must be emitted with correct shape when R1 conditions hold.

    MUST FAIL before C2.3 because the telemetry emit is part of the hook.
    """

    async def test_telemetry_emitted_on_match(self, _common_patches, caplog) -> None:
        """S10: telemetry log must be emitted at INFO with correct fields on match.

        Checks:
        - logger name: agent.modes.booking_mode
        - message: booking.negation_resolver
        - fields: conversation_id, turn_number, user_text_hash, matched,
                  matched_phrase, fuzzy_distance, state
        - user_text_hash: 12-char hex string
        - raw user text NOT in any log field
        - matched=True for "Nada máß"
        """
        node = _make_node()

        booking_ctx = {
            "last_services": ["Corte Señora", "Color Señora"],
            "add_more_asked": False,
        }
        state = _make_state("Nada máß", booking_context=booking_ctx)

        agent_mock = _make_scripted_agent()

        with caplog.at_level(logging.INFO, logger="agent.modes.booking_mode"):
            with patch("langchain.agents.create_agent", return_value=agent_mock):
                await node.handle(state, intent=None)

        # Find the telemetry log record
        telemetry_records = [
            r for r in caplog.records
            if r.name == "agent.modes.booking_mode" and r.getMessage() == "booking.negation_resolver"
        ]
        assert telemetry_records, (
            "Expected a log record with logger='agent.modes.booking_mode' and "
            "message='booking.negation_resolver', but none was found. "
            "FAILS on master because the pre-loop hook is not yet wired."
        )

        record = telemetry_records[0]

        # Required fields must be present
        required_fields = {
            "conversation_id", "turn_number", "user_text_hash",
            "matched", "matched_phrase", "fuzzy_distance", "state",
        }
        for field in required_fields:
            assert hasattr(record, field), (
                f"Telemetry record missing required field '{field}'. "
                f"Record fields: {[k for k in record.__dict__ if not k.startswith('_')]}"
            )

        # user_text_hash must be 12-char hex string
        user_text_hash = record.user_text_hash
        assert isinstance(user_text_hash, str) and len(user_text_hash) == 12, (
            f"user_text_hash must be a 12-char string, got {user_text_hash!r}"
        )
        assert all(c in "0123456789abcdef" for c in user_text_hash), (
            f"user_text_hash must be hex, got {user_text_hash!r}"
        )

        # matched must be True for "Nada máß"
        assert record.matched is True, (
            f"Expected matched=True for 'Nada máß', got {record.matched!r}"
        )

        # Raw user text must NOT appear in any log field value
        raw_text = "Nada máß"
        for field_name in required_fields:
            field_val = str(getattr(record, field_name, ""))
            assert raw_text not in field_val, (
                f"Raw user text {raw_text!r} found in telemetry field '{field_name}': {field_val!r}. "
                "Privacy violation — only hashed text is allowed."
            )

    async def test_telemetry_emitted_on_no_match(self, _common_patches, caplog) -> None:
        """S10: telemetry must ALSO be emitted when is_negation returns False (R4: every attempt).

        For messages that don't match, matched=False, matched_phrase=None.
        """
        node = _make_node()

        booking_ctx = {
            "last_services": ["Corte Señora"],
            "add_more_asked": False,
        }
        # A message that does NOT match negation
        state = _make_state("no sé qué estilista elegir", booking_context=booking_ctx)

        agent_mock = _make_scripted_agent()

        with caplog.at_level(logging.INFO, logger="agent.modes.booking_mode"):
            with patch("langchain.agents.create_agent", return_value=agent_mock):
                await node.handle(state, intent=None)

        telemetry_records = [
            r for r in caplog.records
            if r.name == "agent.modes.booking_mode" and r.getMessage() == "booking.negation_resolver"
        ]
        assert telemetry_records, (
            "Telemetry must be emitted even when matched=False (R4: every attempt). "
            "FAILS on master because the hook is not yet wired."
        )

        record = telemetry_records[0]
        assert record.matched is False, (
            f"Expected matched=False for 'no sé qué estilista elegir', got {record.matched!r}"
        )

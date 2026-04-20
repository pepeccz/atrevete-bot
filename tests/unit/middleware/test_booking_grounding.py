"""
RED tests for agent/booking/middleware/grounding.py::BookingGroundingMiddleware — Phase 1, tasks 1.11–1.15.

Expected fail mode: ModuleNotFoundError: No module named 'agent.booking.middleware'
(implementation does not exist yet — this is the expected TDD RED signal).

REQs covered: REQ-6, REQ-7, REQ-8, REQ-10, REQ-11, REQ-12, REQ-33
"""

from __future__ import annotations

import copy
from unittest.mock import MagicMock, patch

import pytest

# This import will raise ModuleNotFoundError in RED phase.
# Do NOT add @pytest.mark.xfail — the failure IS the test signal.
from agent.booking.middleware.grounding import BookingGroundingMiddleware

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_human_message(content: str) -> MagicMock:
    """Create a minimal mock HumanMessage."""
    msg = MagicMock()
    msg.content = content
    msg.__class__.__name__ = "HumanMessage"
    return msg


def _make_ai_message(content: str = "test") -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.__class__.__name__ = "AIMessage"
    return msg


def _complete_booking_context() -> dict:
    """Return a booking context with all fields populated for testing."""
    return {
        "_booking_completed": False,
        "confirmed": False,
        "_confirmation_shown": False,
        "pending_disambiguations": [],
        "last_services": ["Corte Largo"],
        "add_more_asked": False,
        "last_stylist": None,
        "no_preference_stylist": False,
        "stylist_id": None,
        "offered_slots": None,
        "selected_slot": None,
        "customer_name": None,
        "notes_state": "not_asked",
    }


def _make_state(booking_context: dict, mode: str = "BOOKING") -> dict:
    """Build a minimal ConversationState dict."""
    return {
        "current_mode": mode,
        "booking_context": booking_context,
        "conversation_id": "conv-test-001",
        "total_message_count": 1,
    }


# ---------------------------------------------------------------------------
# TestGroundingInjection — REQ-6, REQ-7 (task 1.11)
# ---------------------------------------------------------------------------


class TestGroundingInjection:
    """
    Given USE_CAPABILITY_BOOKING=True and agent in BOOKING mode
    When BookingGroundingMiddleware.before_model is invoked
    Then exactly one HumanMessage prefixed with '[grounding]' is injected
    """

    def test_grounding_message_injected(self) -> None:
        """
        Given: get_state_fn returns a complete booking context
        When: before_model (or wrap_model_call / inject equivalent) is invoked
        Then: the returned message list's last HumanMessage starts with '[grounding]'
        """
        state = _make_state(_complete_booking_context())
        middleware = BookingGroundingMiddleware(
            get_state_fn=lambda: state,
            mode_name="BOOKING",
        )

        messages = [_make_ai_message("previous context")]
        result_messages = middleware._inject(messages, state)

        # At least one [grounding] message must be present
        grounding_msgs = [
            m for m in result_messages
            if hasattr(m, "content") and isinstance(m.content, str) and m.content.startswith("[grounding]")
        ]
        assert len(grounding_msgs) >= 1, (
            "Expected at least one [grounding] HumanMessage in output"
        )

    def test_grounding_message_content_nonempty(self) -> None:
        """
        Given: get_state_fn returns a complete booking context
        When: grounding is injected
        Then: the [grounding] message content is non-empty
        """
        state = _make_state(_complete_booking_context())
        middleware = BookingGroundingMiddleware(
            get_state_fn=lambda: state,
            mode_name="BOOKING",
        )

        messages = [_make_ai_message()]
        result_messages = middleware._inject(messages, state)

        grounding_msgs = [
            m for m in result_messages
            if hasattr(m, "content") and isinstance(m.content, str) and m.content.startswith("[grounding]")
        ]
        assert grounding_msgs, "No [grounding] message found"
        content = grounding_msgs[-1].content
        assert len(content) > len("[grounding]"), "Grounding message body must be non-empty"


# ---------------------------------------------------------------------------
# TestGroundingDedup — REQ-12, REQ-11 (task 1.12)
# ---------------------------------------------------------------------------


class TestGroundingDedup:
    """
    Given an existing [grounding] message from a prior LLM round-trip
    When BookingGroundingMiddleware injects a new grounding message
    Then only ONE [grounding] message exists in the resulting list (dedup)
    """

    def test_dedup_removes_previous_grounding_message(self) -> None:
        """
        Given: message list already contains a [grounding] HumanMessage from a prior turn
        When: _inject is called again for a new turn
        Then: only one [grounding] message remains in the output
        """
        state = _make_state(_complete_booking_context())
        middleware = BookingGroundingMiddleware(
            get_state_fn=lambda: state,
            mode_name="BOOKING",
        )

        old_grounding = _make_human_message("[grounding] Old directive from prior turn.")
        messages = [_make_ai_message("context"), old_grounding, _make_ai_message("tool result")]

        result_messages = middleware._inject(messages, state)

        grounding_msgs = [
            m for m in result_messages
            if hasattr(m, "content") and isinstance(m.content, str) and m.content.startswith("[grounding]")
        ]
        assert len(grounding_msgs) == 1, (
            f"Expected exactly 1 [grounding] message after dedup, found {len(grounding_msgs)}: "
            f"{[m.content[:60] for m in grounding_msgs]}"
        )

    def test_new_grounding_replaces_old(self) -> None:
        """
        Given: an old [grounding] message exists
        When: injection runs
        Then: the surviving [grounding] message is the NEW one (not the old)
        """
        state = _make_state(_complete_booking_context())
        middleware = BookingGroundingMiddleware(
            get_state_fn=lambda: state,
            mode_name="BOOKING",
        )

        old_grounding = _make_human_message("[grounding] STALE_MARKER_OLD_DIRECTIVE")
        messages = [old_grounding]

        result_messages = middleware._inject(messages, state)
        grounding_msgs = [
            m for m in result_messages
            if hasattr(m, "content") and isinstance(m.content, str) and m.content.startswith("[grounding]")
        ]
        assert grounding_msgs, "No [grounding] message found"
        surviving_content = grounding_msgs[-1].content
        assert "STALE_MARKER_OLD_DIRECTIVE" not in surviving_content, (
            "Old grounding message was not replaced by the new one"
        )


# ---------------------------------------------------------------------------
# TestGroundingModeGuard — REQ-10, REQ-33 (task 1.13)
# ---------------------------------------------------------------------------


class TestGroundingModeGuard:
    """
    Given the agent is processing a turn in a non-BOOKING mode
    When BookingGroundingMiddleware._inject is called
    Then the message list is returned unchanged (no [grounding] injected)
    """

    @pytest.mark.parametrize("mode", ["GENERAL", "GREETING", "ESCALATION"])
    def test_non_booking_mode_passes_through(self, mode: str) -> None:
        """
        Given: state.current_mode != 'BOOKING'
        When: _inject is called
        Then: no [grounding] message is added; list returned unchanged
        """
        state = _make_state(_complete_booking_context(), mode=mode)
        middleware = BookingGroundingMiddleware(
            get_state_fn=lambda: state,
            mode_name="BOOKING",
        )

        original_messages = [_make_ai_message("user turn"), _make_human_message("some human msg")]
        result_messages = middleware._inject(original_messages, state)

        grounding_msgs = [
            m for m in result_messages
            if hasattr(m, "content") and isinstance(m.content, str) and m.content.startswith("[grounding]")
        ]
        assert len(grounding_msgs) == 0, (
            f"Expected no [grounding] in {mode} mode, found {len(grounding_msgs)}"
        )


# ---------------------------------------------------------------------------
# TestNoStateMutation — REQ-8 (task 1.14)
# ---------------------------------------------------------------------------


class TestNoStateMutation:
    """
    Given a BookingContext snapshot before calling _inject
    When BookingGroundingMiddleware._inject runs
    Then the snapshot is bit-for-bit identical after (no state mutation)
    """

    def test_booking_context_not_mutated(self) -> None:
        """
        Given: a booking_context dict snapshot
        When: middleware._inject is called
        Then: the booking_context dict is unchanged
        """
        bc = _complete_booking_context()
        state = _make_state(bc)
        snapshot_before = copy.deepcopy(bc)

        middleware = BookingGroundingMiddleware(
            get_state_fn=lambda: state,
            mode_name="BOOKING",
        )
        messages = [_make_ai_message()]
        _ = middleware._inject(messages, state)

        # Verify booking_context not mutated
        assert state["booking_context"] == snapshot_before, (
            "BookingGroundingMiddleware mutated the booking_context dict"
        )

    def test_state_dict_not_mutated(self) -> None:
        """
        Given: a full ConversationState snapshot
        When: middleware._inject is called
        Then: the state dict is unchanged (no new keys, no modified keys)
        """
        bc = _complete_booking_context()
        state = _make_state(bc)
        keys_before = set(state.keys())
        snapshot_before = copy.deepcopy(state)

        middleware = BookingGroundingMiddleware(
            get_state_fn=lambda: state,
            mode_name="BOOKING",
        )
        messages = [_make_ai_message()]
        _ = middleware._inject(messages, state)

        assert set(state.keys()) == keys_before, (
            f"State has new keys after middleware: {set(state.keys()) - keys_before}"
        )
        for key in keys_before:
            assert state[key] == snapshot_before[key], (
                f"State key {key!r} was mutated by middleware"
            )


# ---------------------------------------------------------------------------
# TestFailOpen — REQ-6 (task 1.15)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# TestBeforeModelHook — new AgentMiddleware-compatible hook (C1–C8)
# ---------------------------------------------------------------------------


class TestBeforeModelHook:
    """Tests for the new before_model(state, runtime) -> dict | None hook."""

    def test_before_model_returns_state_update_with_stable_id(self) -> None:
        """R4 — before_model returns {messages: [HumanMessage]} with stable id.

        RED: current before_model(messages, state) signature will fail with TypeError.
        GREEN after C2 ports the hook.
        """
        state = _make_state(_complete_booking_context())
        state["conversation_id"] = "abc"
        middleware = BookingGroundingMiddleware(
            get_state_fn=lambda: state,
            mode_name="BOOKING",
        )

        result = middleware.before_model(state, runtime=None)

        assert result is not None, "before_model must return a dict, not None, in BOOKING mode"
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "messages" in result, f"Expected 'messages' key in result, got {result.keys()}"

        messages = result["messages"]
        assert len(messages) == 1, f"Expected exactly 1 message, got {len(messages)}"

        msg = messages[0]
        assert hasattr(msg, "content"), "Message must have .content attribute"
        assert msg.content.startswith("[grounding]"), (
            f"Message content must start with '[grounding]', got: {msg.content[:50]!r}"
        )
        assert msg.id == "booking-grounding-abc", (
            f"Message id must be 'booking-grounding-abc', got: {msg.id!r}"
        )

    def test_before_model_stable_id_across_turns(self) -> None:
        """R5 — stable id means add_messages reducer deduplicates grounding messages.

        Two sequential before_model calls → both grounding messages have the same id →
        after add_messages reduce, only 1 grounding message remains in state.
        """

        state = _make_state(_complete_booking_context())
        state["conversation_id"] = "abc"
        middleware = BookingGroundingMiddleware(
            get_state_fn=lambda: state,
            mode_name="BOOKING",
        )

        result1 = middleware.before_model(state, runtime=None)
        result2 = middleware.before_model(state, runtime=None)

        assert result1 is not None and result2 is not None

        msg1 = result1["messages"][0]
        msg2 = result2["messages"][0]

        # Both must have the same stable id
        assert msg1.id == msg2.id, (
            f"Grounding ids must be identical across turns: {msg1.id!r} vs {msg2.id!r}"
        )
        assert msg1.id == "booking-grounding-abc"

        # Simulate add_messages reducer: messages with same id replace each other
        accumulated: list = []
        # Turn 1
        for m in result1["messages"]:
            # add_messages: if same id exists, replace; else append
            replaced = False
            for i, existing in enumerate(accumulated):
                if getattr(existing, "id", None) == getattr(m, "id", None):
                    accumulated[i] = m
                    replaced = True
                    break
            if not replaced:
                accumulated.append(m)
        # Turn 2
        for m in result2["messages"]:
            replaced = False
            for i, existing in enumerate(accumulated):
                if getattr(existing, "id", None) == getattr(m, "id", None):
                    accumulated[i] = m
                    replaced = True
                    break
            if not replaced:
                accumulated.append(m)

        grounding_count = sum(
            1 for m in accumulated
            if hasattr(m, "content")
            and isinstance(m.content, str)
            and m.content.startswith("[grounding]")
        )
        assert grounding_count == 1, (
            f"After two add_messages reduces, expected 1 grounding message, got {grounding_count}"
        )

    def test_before_model_returns_none_when_mode_not_booking(self) -> None:
        """R6 — before_model returns None when current_mode != BOOKING."""
        state = _make_state(_complete_booking_context(), mode="GENERAL")
        middleware = BookingGroundingMiddleware(
            get_state_fn=lambda: state,
            mode_name="BOOKING",
        )
        result = middleware.before_model(state, runtime=None)
        assert result is None, (
            f"Expected None for non-BOOKING mode, got {result!r}"
        )

    def test_before_model_returns_none_on_compute_next_prompt_error(self) -> None:
        """R7 — before_model returns None (fail-open) when compute_next_prompt raises."""
        state = _make_state(_complete_booking_context())
        middleware = BookingGroundingMiddleware(
            get_state_fn=lambda: state,
            mode_name="BOOKING",
        )
        with patch(
            "agent.booking.middleware.grounding.compute_next_prompt",
            side_effect=RuntimeError("boom"),
        ):
            result = middleware.before_model(state, runtime=None)

        assert result is None, (
            f"Expected None when compute_next_prompt raises, got {result!r}"
        )

    @pytest.mark.asyncio
    async def test_abefore_model_delegates_to_sync(self) -> None:
        """R4 — abefore_model async variant delegates to before_model."""
        state = _make_state(_complete_booking_context())
        state["conversation_id"] = "abc"
        middleware = BookingGroundingMiddleware(
            get_state_fn=lambda: state,
            mode_name="BOOKING",
        )

        async_result = await middleware.abefore_model(state, runtime=None)
        sync_result = middleware.before_model(state, runtime=None)

        assert async_result is not None, "abefore_model must return same as before_model"
        # Both should produce grounding messages with same id
        assert async_result["messages"][0].id == sync_result["messages"][0].id, (
            "abefore_model and before_model must produce the same grounding id"
        )

    def test_before_model_uses_closure_state_not_runtime_param(self) -> None:
        """R14 — the real ConversationState lives in the closure, NOT the runtime state param.

        LangChain 1.x passes its own AgentState (typically just ``messages``) to the hook.
        The BookingModeNode closure is the only source of truth for ``current_mode`` and
        ``booking_context``. Regression test for the production bug where the hook read
        ``current_mode`` from the runtime param (always None) and mode-guard silently
        rejected every invocation.
        """
        real_state = _make_state(_complete_booking_context())
        real_state["conversation_id"] = "real-conv"
        # Runtime state mimics LangChain's internal AgentState: no booking fields.
        runtime_state = {"messages": []}

        middleware = BookingGroundingMiddleware(
            get_state_fn=lambda: real_state,
            mode_name="BOOKING",
        )

        result = middleware.before_model(runtime_state, runtime=None)

        assert result is not None, (
            "Hook must resolve ConversationState via closure, not via runtime state param. "
            "If None, mode-guard is reading from runtime_state (which lacks current_mode)."
        )
        msg = result["messages"][0]
        assert msg.id == "booking-grounding-real-conv", (
            f"Grounding id must come from closure.conversation_id, got {msg.id!r}"
        )


class TestFailOpen:
    """
    Given compute_next_prompt raises a RuntimeError
    When BookingGroundingMiddleware._inject is invoked
    Then no exception propagates; messages are returned unchanged (fail-open)
    """

    def test_fail_open_on_compute_error(self) -> None:
        """
        Given: compute_next_prompt raises RuntimeError
        When: _inject is called
        Then: original message list is returned without raising
        """
        state = _make_state(_complete_booking_context())
        middleware = BookingGroundingMiddleware(
            get_state_fn=lambda: state,
            mode_name="BOOKING",
        )

        original_messages = [_make_ai_message("context")]

        with patch(
            "agent.booking.middleware.grounding.compute_next_prompt",
            side_effect=RuntimeError("Test error"),
        ):
            # Must NOT raise
            result_messages = middleware._inject(original_messages, state)

        # Pass-through: result should equal original (no grounding injected)
        assert result_messages is not None, "Expected message list back, got None"

    def test_fail_open_on_get_state_error(self) -> None:
        """
        Given: get_state_fn raises an exception
        When: _inject is called
        Then: no exception propagates; messages returned unchanged
        """

        def _raising_state_fn() -> dict:
            raise RuntimeError("State unavailable")

        middleware = BookingGroundingMiddleware(
            get_state_fn=_raising_state_fn,
            mode_name="BOOKING",
        )

        original_messages = [_make_ai_message("existing context")]
        state = _make_state(_complete_booking_context())

        # Must NOT raise even though get_state_fn raises
        result_messages = middleware._inject(original_messages, state)
        assert result_messages is not None

"""
Tests for BookingGroundingMiddleware.

TDD RED: All tests reference agent.booking.middleware.grounding which does NOT exist yet.
Design refs: design §5.1
Requirements: R4, R5
Scenarios: S9, S25, S26
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.booking.middleware.grounding import BookingGroundingMiddleware

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_GROUNDING_PREFIX = "[grounding]"


def _make_request(messages: list) -> ModelRequest:
    """Build a ModelRequest with the given messages."""
    req = MagicMock(spec=ModelRequest)
    req.messages = messages
    # override() returns a new mock with updated messages
    def _override(**kwargs):
        new_req = MagicMock(spec=ModelRequest)
        new_req.messages = kwargs.get("messages", messages)
        new_req.override = req.override  # allow chaining
        return new_req
    req.override = MagicMock(side_effect=_override)
    return req


def _make_state(booking_context: dict | None = None, current_mode: str = "BOOKING") -> dict:
    """Build a minimal ConversationState dict."""
    return {
        "current_mode": current_mode,
        "booking_context": booking_context or {},
    }


def _make_handler(response: Any = None) -> MagicMock:
    """Sync handler mock."""
    mock = MagicMock(return_value=response or MagicMock(spec=ModelResponse))
    return mock


def _make_async_handler(response: Any = None):
    """Async handler mock."""
    import asyncio
    resp = response or MagicMock(spec=ModelResponse)
    async def _handler(req):
        return resp
    return _handler


# ---------------------------------------------------------------------------
# T3.1-A: Class structure
# ---------------------------------------------------------------------------


class TestBookingGroundingMiddlewareStructure:
    """Middleware must inherit from AgentMiddleware and implement both hook variants."""

    def test_inherits_agent_middleware(self):
        mw = BookingGroundingMiddleware(get_state_fn=lambda: _make_state())
        assert isinstance(mw, AgentMiddleware)

    def test_has_wrap_model_call(self):
        mw = BookingGroundingMiddleware(get_state_fn=lambda: _make_state())
        assert callable(getattr(mw, "wrap_model_call", None))

    def test_has_awrap_model_call(self):
        mw = BookingGroundingMiddleware(get_state_fn=lambda: _make_state())
        assert callable(getattr(mw, "awrap_model_call", None))

    def test_default_mode_name_is_booking(self):
        mw = BookingGroundingMiddleware(get_state_fn=lambda: _make_state())
        assert mw._mode_name == "BOOKING"

    def test_custom_mode_name(self):
        mw = BookingGroundingMiddleware(get_state_fn=lambda: _make_state(), mode_name="OTHER")
        assert mw._mode_name == "OTHER"


# ---------------------------------------------------------------------------
# T3.1-B: Mode guard — non-BOOKING modes pass through unchanged (R4, S25)
# ---------------------------------------------------------------------------


class TestModeGuard:
    """Middleware must be a no-op outside its target mode."""

    def test_passthrough_when_not_booking_mode(self):
        state = _make_state(current_mode="GREETING")
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        messages = [HumanMessage(content="Hola")]
        req = _make_request(messages)
        handler = _make_handler()

        mw.wrap_model_call(req, handler)

        handler.assert_called_once_with(req)
        req.override.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_passthrough_when_not_booking_mode(self):
        state = _make_state(current_mode="ESCALATION")
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        messages = [HumanMessage(content="Help")]
        req = _make_request(messages)
        called_with = []
        async def handler(r):
            called_with.append(r)
            return MagicMock(spec=ModelResponse)

        await mw.awrap_model_call(req, handler)

        assert called_with == [req]
        req.override.assert_not_called()

    def test_passthrough_when_mode_is_none(self):
        state = {"current_mode": None, "booking_context": {}}
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        messages = []
        req = _make_request(messages)
        handler = _make_handler()

        mw.wrap_model_call(req, handler)

        handler.assert_called_once_with(req)


# ---------------------------------------------------------------------------
# T3.1-C: Grounding injection — BOOKING mode (R4, R5, S26)
# ---------------------------------------------------------------------------


class TestGroundingInjection:
    """In BOOKING mode, compute_next_prompt is called and directive is injected."""

    def test_grounding_message_appended_to_empty_messages(self):
        """When no [grounding] message exists, one is appended."""
        state = _make_state(booking_context={})
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        req = _make_request([HumanMessage(content="Hola")])
        handler = _make_handler()

        mw.wrap_model_call(req, handler)

        # override should have been called with messages containing [grounding]
        assert req.override.called
        injected_msgs = req.override.call_args[1]["messages"]
        grounding_msgs = [
            m for m in injected_msgs
            if isinstance(m, HumanMessage) and str(m.content).startswith(_GROUNDING_PREFIX)
        ]
        assert len(grounding_msgs) == 1

    @pytest.mark.asyncio
    async def test_async_grounding_message_appended(self):
        state = _make_state(booking_context={})
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        req = _make_request([HumanMessage(content="Hola")])
        handler = _make_async_handler()

        await mw.awrap_model_call(req, handler)

        assert req.override.called
        injected_msgs = req.override.call_args[1]["messages"]
        grounding_msgs = [
            m for m in injected_msgs
            if isinstance(m, HumanMessage) and str(m.content).startswith(_GROUNDING_PREFIX)
        ]
        assert len(grounding_msgs) == 1

    def test_grounding_message_contains_action(self):
        """Injected [grounding] message includes action= field."""
        state = _make_state(booking_context={})
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        req = _make_request([])
        handler = _make_handler()

        mw.wrap_model_call(req, handler)

        injected_msgs = req.override.call_args[1]["messages"]
        grounding_content = next(
            m.content for m in injected_msgs
            if isinstance(m, HumanMessage) and str(m.content).startswith(_GROUNDING_PREFIX)
        )
        assert "action=" in grounding_content

    def test_grounding_message_contains_directive_text(self):
        """Injected [grounding] message contains Spanish directive from GroundingDirective."""
        state = _make_state(booking_context={})
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        req = _make_request([])
        handler = _make_handler()

        mw.wrap_model_call(req, handler)

        injected_msgs = req.override.call_args[1]["messages"]
        grounding_content = next(
            m.content for m in injected_msgs
            if isinstance(m, HumanMessage) and str(m.content).startswith(_GROUNDING_PREFIX)
        )
        # When booking_context is empty, action=ASK_SERVICE — directive is Spanish
        assert len(grounding_content) > len(_GROUNDING_PREFIX)

    def test_mandatory_next_call_included_when_set(self):
        """When directive has mandatory_next_call, NEXT_TOOL_REQUIRED= appears in message."""
        # State that produces ASK_AVAILABILITY (has stylist, has services, add_more_asked, no slots)
        bc = {
            "last_services": ["Óleo"],
            "add_more_asked": True,
            "last_stylist": "Pilar",
        }
        state = _make_state(booking_context=bc)
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        req = _make_request([])
        handler = _make_handler()

        mw.wrap_model_call(req, handler)

        injected_msgs = req.override.call_args[1]["messages"]
        grounding_content = next(
            m.content for m in injected_msgs
            if isinstance(m, HumanMessage) and str(m.content).startswith(_GROUNDING_PREFIX)
        )
        assert "NEXT_TOOL_REQUIRED=check_availability" in grounding_content

    def test_no_mandatory_next_call_when_not_set(self):
        """When directive has no mandatory_next_call, NEXT_TOOL_REQUIRED is absent."""
        state = _make_state(booking_context={})  # → ASK_SERVICE (no mandatory_next_call)
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        req = _make_request([])
        handler = _make_handler()

        mw.wrap_model_call(req, handler)

        injected_msgs = req.override.call_args[1]["messages"]
        grounding_content = next(
            m.content for m in injected_msgs
            if isinstance(m, HumanMessage) and str(m.content).startswith(_GROUNDING_PREFIX)
        )
        assert "NEXT_TOOL_REQUIRED" not in grounding_content


# ---------------------------------------------------------------------------
# T3.1-D: Dedup — replace existing [grounding] message (R4, S9)
# ---------------------------------------------------------------------------


class TestGroundingDedup:
    """If a [grounding] message already exists, it should be replaced, not appended."""

    def test_replaces_existing_grounding_message(self):
        """Existing [grounding] message is replaced, not appended."""
        old_grounding = HumanMessage(content="[grounding]\naction=ASK_SERVICE\nold content")
        messages = [
            HumanMessage(content="User message"),
            old_grounding,
        ]
        state = _make_state(booking_context={})
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        req = _make_request(messages)
        handler = _make_handler()

        mw.wrap_model_call(req, handler)

        injected_msgs = req.override.call_args[1]["messages"]
        grounding_msgs = [
            m for m in injected_msgs
            if isinstance(m, HumanMessage) and str(m.content).startswith(_GROUNDING_PREFIX)
        ]
        # Exactly one grounding message (replaced, not appended)
        assert len(grounding_msgs) == 1

    def test_replaced_message_is_at_same_position(self):
        """Replacement happens in-place (preserves message order)."""
        old_grounding = HumanMessage(content="[grounding]\naction=OLD\nold content")
        normal_msg = HumanMessage(content="Some other message after grounding")
        messages = [
            HumanMessage(content="User message"),
            old_grounding,
            AIMessage(content="Bot response"),
            normal_msg,
        ]
        state = _make_state(booking_context={})
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        req = _make_request(messages)
        handler = _make_handler()

        mw.wrap_model_call(req, handler)

        injected_msgs = req.override.call_args[1]["messages"]
        # Same total length (replace, not append)
        assert len(injected_msgs) == len(messages)
        # The grounding message is still at index 1
        assert str(injected_msgs[1].content).startswith(_GROUNDING_PREFIX)
        # New content is different from old
        assert injected_msgs[1].content != old_grounding.content

    def test_non_grounding_messages_are_not_modified(self):
        """Non-[grounding] HumanMessages are not touched."""
        user_msg = HumanMessage(content="Quiero un oleo")
        sys_msg = SystemMessage(content="You are a booking assistant")
        messages = [sys_msg, user_msg]
        state = _make_state(booking_context={})
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        req = _make_request(messages)
        handler = _make_handler()

        mw.wrap_model_call(req, handler)

        injected_msgs = req.override.call_args[1]["messages"]
        # Non-grounding messages should still be there unchanged
        assert injected_msgs[0].content == sys_msg.content
        assert injected_msgs[1].content == user_msg.content

    def test_replaces_last_grounding_when_multiple_present(self):
        """When multiple [grounding] messages exist (edge case), last one is replaced."""
        old1 = HumanMessage(content="[grounding]\naction=FIRST")
        old2 = HumanMessage(content="[grounding]\naction=SECOND")
        messages = [old1, HumanMessage(content="User"), old2]
        state = _make_state(booking_context={})
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        req = _make_request(messages)
        handler = _make_handler()

        mw.wrap_model_call(req, handler)

        injected_msgs = req.override.call_args[1]["messages"]
        grounding_msgs = [
            m for m in injected_msgs
            if isinstance(m, HumanMessage) and str(m.content).startswith(_GROUNDING_PREFIX)
        ]
        # Still has 2 grounding messages (only last replaced, first untouched)
        assert len(grounding_msgs) == 2
        # The last one has been replaced with fresh content
        assert injected_msgs[2].content != old2.content


# ---------------------------------------------------------------------------
# T3.1-E: Observability — log events (design §9)
# ---------------------------------------------------------------------------


class TestObservability:
    """Middleware must emit structured log events."""

    def test_logs_booking_grounding_injected_event(self):
        state = _make_state(booking_context={})
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        req = _make_request([])
        handler = _make_handler()

        with patch("agent.booking.middleware.grounding.logger") as mock_logger:
            mw.wrap_model_call(req, handler)

        # Either debug or info call should carry the event name as message
        calls = mock_logger.debug.call_args_list + mock_logger.info.call_args_list
        assert len(calls) >= 1
        # At least one call uses the event name booking_grounding.injected
        event_calls = [c for c in calls if "booking_grounding.injected" in str(c)]
        assert len(event_calls) >= 1

    def test_log_extra_contains_required_fields(self):
        state = _make_state(booking_context={})
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        req = _make_request([])
        handler = _make_handler()

        with patch("agent.booking.middleware.grounding.logger") as mock_logger:
            mw.wrap_model_call(req, handler)

        calls = mock_logger.debug.call_args_list + mock_logger.info.call_args_list
        injected_calls = [c for c in calls if "booking_grounding.injected" in str(c)]
        assert injected_calls, "No booking_grounding.injected log event found"
        # Check the extra dict contains required fields
        call = injected_calls[0]
        extra = call.kwargs.get("extra", {}) or (call.args[1] if len(call.args) > 1 else {})
        # Required: action, next_action (mandatory_next_call), state_snapshot_keys
        extra_str = str(call)
        assert any(
            keyword in extra_str
            for keyword in ["action", "next_action", "mandatory_next_call", "state_snapshot"]
        )


# ---------------------------------------------------------------------------
# T3.1-F: Error handling — fail-open (design §5.1)
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Middleware must fail open when compute_next_prompt raises."""

    def test_passes_through_on_compute_next_prompt_error(self):
        """If compute_next_prompt raises, request passes through unchanged."""
        state = _make_state(booking_context={})
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        req = _make_request([HumanMessage(content="Hola")])
        handler = _make_handler()

        with patch("agent.booking.middleware.grounding.compute_next_prompt", side_effect=RuntimeError("boom")):
            mw.wrap_model_call(req, handler)

        # Handler called with ORIGINAL request (not a modified one)
        handler.assert_called_once()
        # override was NOT called (no injection happened)
        req.override.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_passes_through_on_compute_next_prompt_error(self):
        state = _make_state(booking_context={})
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        req = _make_request([HumanMessage(content="Hola")])
        called_with = []
        async def handler(r):
            called_with.append(r)
            return MagicMock(spec=ModelResponse)

        with patch("agent.booking.middleware.grounding.compute_next_prompt", side_effect=RuntimeError("boom")):
            await mw.awrap_model_call(req, handler)

        assert called_with == [req]
        req.override.assert_not_called()

    def test_logs_booking_grounding_error_on_exception(self):
        """booking_grounding.error event is logged on exception."""
        state = _make_state(booking_context={})
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)
        req = _make_request([])
        handler = _make_handler()

        with patch("agent.booking.middleware.grounding.compute_next_prompt", side_effect=RuntimeError("test error")):
            with patch("agent.booking.middleware.grounding.logger") as mock_logger:
                mw.wrap_model_call(req, handler)

        all_calls = (
            mock_logger.error.call_args_list
            + mock_logger.warning.call_args_list
            + mock_logger.exception.call_args_list
        )
        error_calls = [c for c in all_calls if "booking_grounding.error" in str(c)]
        assert len(error_calls) >= 1

    def test_get_state_fn_error_fails_open(self):
        """If get_state_fn itself raises, request passes through unchanged."""
        def bad_state_fn():
            raise ValueError("state unavailable")

        mw = BookingGroundingMiddleware(get_state_fn=bad_state_fn)
        req = _make_request([])
        handler = _make_handler()

        # Should not raise
        mw.wrap_model_call(req, handler)

        handler.assert_called_once()

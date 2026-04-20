"""
RED tests for agent/booking/middleware/invariants.py::BookingInvariantMiddleware — Phase 1, tasks 1.16–1.26.

Expected fail mode: ModuleNotFoundError: No module named 'agent.booking.middleware'
(implementation does not exist yet — this is the expected TDD RED signal).

REQs covered: REQ-13, REQ-14, REQ-15, REQ-16, REQ-17, REQ-18, REQ-19, REQ-20
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

# This import will raise ModuleNotFoundError in RED phase.
# Do NOT add @pytest.mark.xfail — the failure IS the test signal.
from agent.booking.middleware.invariants import BookingInvariantMiddleware

# ---------------------------------------------------------------------------
# Error code enum — must match REQ-20
# ---------------------------------------------------------------------------

VALID_ERROR_CODES = frozenset(
    {
        "AUDIENCE_REQUIRED",
        "SERVICES_MISSING",
        "STYLIST_MISSING",
        "SLOT_MISSING",
        "CUSTOMER_NAME_MISSING",
        "CONFIRMATION_REQUIRED",
        "CONFIRMATION_PENDING",
        "DISAMBIGUATION_PENDING",
        "SERVICES_REQUIRED_BEFORE_STYLIST",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(booking_context: dict, mode: str = "BOOKING") -> dict:
    """Build a minimal ConversationState dict."""
    return {
        "current_mode": mode,
        "booking_context": booking_context,
        "conversation_id": "conv-test-001",
    }


def _complete_booking_context(**overrides) -> dict:
    """Return a fully valid booking context (all preconditions met)."""
    base = {
        "_booking_completed": False,
        "confirmed": True,
        "_confirmation_shown": True,
        "pending_disambiguations": [],
        "last_services": ["Corte Largo"],
        "add_more_asked": True,
        "last_stylist": "Ana",
        "stylist_id": "stylist-uuid-001",
        "no_preference_stylist": False,
        "offered_slots": [{"start": "2026-04-21T10:00:00"}],
        "selected_slot": {"start": "2026-04-21T10:00:00"},
        "customer_name": "María García",
        "notes_state": "skipped",
    }
    base.update(overrides)
    return base


def _make_middleware(booking_context: dict, mode: str = "BOOKING") -> BookingInvariantMiddleware:
    """Create a middleware instance with a state fixture."""
    state = _make_state(booking_context)
    return BookingInvariantMiddleware(
        get_state_fn=lambda: state,
        get_catalog_fn=lambda: [],
        mode_name=mode,
    )


def _make_tool_call(name: str, args: dict | None = None) -> MagicMock:
    """Create a mock tool call request."""
    tc = MagicMock()
    tc.name = name
    tc.args = args or {}
    tc.id = "tool-call-id-001"
    return tc


def _extract_error_from_tool_message(tool_message: Any) -> dict:
    """Parse the JSON content of a ToolMessage to get the error dict."""
    if isinstance(tool_message.content, str):
        return json.loads(tool_message.content)
    return tool_message.content


# ---------------------------------------------------------------------------
# TestBookPreconditions — REQ-13, REQ-14, REQ-15, REQ-16, REQ-17, REQ-18 (tasks 1.16–1.21)
# ---------------------------------------------------------------------------


class TestBookPreconditions:
    """
    Tests that book() is blocked when preconditions are not met.
    Each test verifies one precondition check in BookingInvariantMiddleware.
    """

    def test_book_blocked_without_confirmation(self) -> None:
        """
        Given: BookingContext.confirmed=False (all other fields present)
        When: wrap_tool_call("book", ...) is called
        Then: a ToolMessage with error code CONFIRMATION_REQUIRED (or CONFIRMATION_PENDING) is returned
        And: actual book handler is NOT called (REQ-13)
        """
        bc = _complete_booking_context(confirmed=False)
        middleware = _make_middleware(bc)

        handler_called = []

        def _fake_handler(tool_call):
            handler_called.append(tool_call)
            return MagicMock(content=json.dumps({"success": True}))

        tc = _make_tool_call("book")
        result = middleware.wrap_tool_call(tc, _fake_handler)

        assert len(handler_called) == 0, "Handler should NOT be called when confirmed=False"
        error = _extract_error_from_tool_message(result)
        assert error.get("error") is True, f"Expected error=True in response: {error}"
        assert error.get("code") in {"CONFIRMATION_REQUIRED", "CONFIRMATION_PENDING"}, (
            f"Expected CONFIRMATION_REQUIRED/PENDING code, got {error.get('code')!r}"
        )

    def test_book_blocked_no_services(self) -> None:
        """
        Given: BookingContext.confirmed=True, last_services=[]
        When: wrap_tool_call("book", ...) is called
        Then: error code SERVICES_MISSING (REQ-14)
        """
        bc = _complete_booking_context(last_services=[])
        middleware = _make_middleware(bc)

        handler_called = []

        def _fake_handler(tc):
            handler_called.append(tc)
            return MagicMock(content=json.dumps({"success": True}))

        tc = _make_tool_call("book")
        result = middleware.wrap_tool_call(tc, _fake_handler)

        assert len(handler_called) == 0, "Handler should NOT be called with empty services"
        error = _extract_error_from_tool_message(result)
        assert error.get("code") == "SERVICES_MISSING", (
            f"Expected SERVICES_MISSING, got {error.get('code')!r}"
        )

    def test_book_blocked_no_stylist(self) -> None:
        """
        Given: BookingContext.stylist_id=None, no_preference_stylist=False
        When: wrap_tool_call("book", ...) is called
        Then: error code STYLIST_MISSING (REQ-15)
        """
        bc = _complete_booking_context(stylist_id=None, last_stylist=None, no_preference_stylist=False)
        middleware = _make_middleware(bc)

        handler_called = []

        def _fake_handler(tc):
            handler_called.append(tc)
            return MagicMock(content=json.dumps({"success": True}))

        tc = _make_tool_call("book")
        result = middleware.wrap_tool_call(tc, _fake_handler)

        assert len(handler_called) == 0
        error = _extract_error_from_tool_message(result)
        assert error.get("code") == "STYLIST_MISSING", (
            f"Expected STYLIST_MISSING, got {error.get('code')!r}"
        )

    def test_book_allowed_with_no_preference_stylist(self) -> None:
        """
        Given: no_preference_stylist=True (satisfies stylist requirement)
        When: wrap_tool_call("book", ...) is called with all other fields present
        Then: book handler IS called (no STYLIST_MISSING block) (REQ-15 inverse)
        """
        bc = _complete_booking_context(
            stylist_id=None,
            last_stylist=None,
            no_preference_stylist=True,
        )
        middleware = _make_middleware(bc)

        handler_called = []

        def _fake_handler(tc):
            handler_called.append(tc)
            return MagicMock(content=json.dumps({"success": True}))

        tc = _make_tool_call("book")
        middleware.wrap_tool_call(tc, _fake_handler)

        assert len(handler_called) == 1, (
            "Handler should be called when no_preference_stylist=True"
        )

    def test_book_blocked_no_slot(self) -> None:
        """
        Given: BookingContext.selected_slot=None
        When: wrap_tool_call("book", ...) is called
        Then: error code SLOT_MISSING (REQ-16)
        """
        bc = _complete_booking_context(selected_slot=None)
        middleware = _make_middleware(bc)

        handler_called = []

        def _fake_handler(tc):
            handler_called.append(tc)
            return MagicMock(content=json.dumps({"success": True}))

        tc = _make_tool_call("book")
        result = middleware.wrap_tool_call(tc, _fake_handler)

        assert len(handler_called) == 0
        error = _extract_error_from_tool_message(result)
        assert error.get("code") == "SLOT_MISSING", (
            f"Expected SLOT_MISSING, got {error.get('code')!r}"
        )

    def test_book_blocked_no_name(self) -> None:
        """
        Given: BookingContext.customer_name=None
        When: wrap_tool_call("book", ...) is called
        Then: error code CUSTOMER_NAME_MISSING (REQ-17)
        """
        bc = _complete_booking_context(customer_name=None)
        middleware = _make_middleware(bc)

        handler_called = []

        def _fake_handler(tc):
            handler_called.append(tc)
            return MagicMock(content=json.dumps({"success": True}))

        tc = _make_tool_call("book")
        result = middleware.wrap_tool_call(tc, _fake_handler)

        assert len(handler_called) == 0
        error = _extract_error_from_tool_message(result)
        assert error.get("code") == "CUSTOMER_NAME_MISSING", (
            f"Expected CUSTOMER_NAME_MISSING, got {error.get('code')!r}"
        )

    def test_book_blocked_empty_string_name(self) -> None:
        """
        Given: BookingContext.customer_name="" (empty string)
        When: wrap_tool_call("book", ...) is called
        Then: error code CUSTOMER_NAME_MISSING (REQ-17 edge case)
        """
        bc = _complete_booking_context(customer_name="")
        middleware = _make_middleware(bc)

        handler_called = []

        def _fake_handler(tc):
            handler_called.append(tc)
            return MagicMock(content=json.dumps({"success": True}))

        tc = _make_tool_call("book")
        result = middleware.wrap_tool_call(tc, _fake_handler)

        assert len(handler_called) == 0
        error = _extract_error_from_tool_message(result)
        assert error.get("code") == "CUSTOMER_NAME_MISSING"

    def test_book_blocked_pending_disambig(self) -> None:
        """
        Given: BookingContext.pending_disambiguations is non-empty
        When: wrap_tool_call("book", ...) is called
        Then: error code DISAMBIGUATION_PENDING (REQ-18)
        """
        bc = _complete_booking_context(
            pending_disambiguations=[{"family": "Corte", "variants": ["niña", "señora"]}]
        )
        middleware = _make_middleware(bc)

        handler_called = []

        def _fake_handler(tc):
            handler_called.append(tc)
            return MagicMock(content=json.dumps({"success": True}))

        tc = _make_tool_call("book")
        result = middleware.wrap_tool_call(tc, _fake_handler)

        assert len(handler_called) == 0
        error = _extract_error_from_tool_message(result)
        assert error.get("code") == "DISAMBIGUATION_PENDING", (
            f"Expected DISAMBIGUATION_PENDING, got {error.get('code')!r}"
        )


# ---------------------------------------------------------------------------
# TestAvailabilityPreconditions — REQ-19 (tasks 1.22–1.23)
# ---------------------------------------------------------------------------


class TestAvailabilityPreconditions:
    """
    Tests that check_availability is blocked when services are empty
    or when disambiguation is pending (REQ-19).
    """

    def test_availability_blocked_no_services(self) -> None:
        """
        Given: BookingContext.last_services=[]
        When: wrap_tool_call("check_availability", ...) is called
        Then: error code SERVICES_MISSING; check_availability NOT executed (REQ-19)
        """
        bc = _complete_booking_context(last_services=[], confirmed=False, _confirmation_shown=False)
        middleware = _make_middleware(bc)

        handler_called = []

        def _fake_handler(tc):
            handler_called.append(tc)
            return MagicMock(content=json.dumps({"slots": []}))

        tc = _make_tool_call("check_availability")
        result = middleware.wrap_tool_call(tc, _fake_handler)

        assert len(handler_called) == 0, (
            "check_availability handler should NOT be called with empty services"
        )
        error = _extract_error_from_tool_message(result)
        assert error.get("code") == "SERVICES_MISSING", (
            f"Expected SERVICES_MISSING, got {error.get('code')!r}"
        )

    def test_availability_blocked_pending_disambig(self) -> None:
        """
        Given: BookingContext.pending_disambiguations is non-empty
        When: wrap_tool_call("check_availability", ...) is called
        Then: error code DISAMBIGUATION_PENDING (REQ-19)
        """
        bc = _complete_booking_context(
            confirmed=False,
            _confirmation_shown=False,
            pending_disambiguations=[{"family": "Corte", "variants": ["niña", "señora"]}],
        )
        middleware = _make_middleware(bc)

        handler_called = []

        def _fake_handler(tc):
            handler_called.append(tc)
            return MagicMock(content=json.dumps({"slots": []}))

        tc = _make_tool_call("check_availability")
        result = middleware.wrap_tool_call(tc, _fake_handler)

        assert len(handler_called) == 0
        error = _extract_error_from_tool_message(result)
        assert error.get("code") == "DISAMBIGUATION_PENDING", (
            f"Expected DISAMBIGUATION_PENDING, got {error.get('code')!r}"
        )


# ---------------------------------------------------------------------------
# TestUpdateBookingAlwaysPasses — REQ-20 (task 1.24)
# ---------------------------------------------------------------------------


class TestUpdateBookingAlwaysPasses:
    """
    update_booking is ALWAYS allowed through — no blocking conditions (REQ-20).
    """

    def test_update_booking_passes_through(self) -> None:
        """
        Given: any BookingContext state (even with pending_disambiguations)
        When: wrap_tool_call("update_booking", ...) is called
        Then: the real handler is called and its result is returned
        """
        bc = _complete_booking_context(
            confirmed=False,
            pending_disambiguations=[{"family": "Corte", "variants": ["niña"]}],
        )
        middleware = _make_middleware(bc)

        expected_result = MagicMock(content=json.dumps({"updated": True}))
        handler_called = []

        def _fake_handler(tc):
            handler_called.append(tc)
            return expected_result

        tc = _make_tool_call("update_booking", args={"services": ["Corte"]})
        result = middleware.wrap_tool_call(tc, _fake_handler)

        assert len(handler_called) == 1, (
            "update_booking handler MUST always be called"
        )
        assert result is expected_result

    def test_update_booking_with_minimal_state_passes(self) -> None:
        """
        Given: a minimal/empty BookingContext
        When: wrap_tool_call("update_booking", ...) is called
        Then: handler is still called
        """
        bc = {}  # completely empty
        middleware = _make_middleware(bc)

        handler_called = []

        def _fake_handler(tc):
            handler_called.append(tc)
            return MagicMock(content=json.dumps({"updated": True}))

        tc = _make_tool_call("update_booking")
        middleware.wrap_tool_call(tc, _fake_handler)

        assert len(handler_called) == 1


# ---------------------------------------------------------------------------
# TestErrorSurface — REQ-20 (task 1.25)
# ---------------------------------------------------------------------------


class TestErrorSurface:
    """
    When BookingInvariantMiddleware short-circuits, errors MUST be structured
    ToolMessages (not exceptions), with error=True and a valid code.
    """

    def test_no_exception_propagates(self) -> None:
        """
        Given: CONFIRMATION_REQUIRED condition (confirmed=False)
        When: wrap_tool_call is called
        Then: no Python exception propagates (REQ-20)
        """
        bc = _complete_booking_context(confirmed=False)
        middleware = _make_middleware(bc)

        tc = _make_tool_call("book")
        # Must not raise
        result = middleware.wrap_tool_call(tc, lambda t: MagicMock())
        assert result is not None

    def test_error_is_true_in_response(self) -> None:
        """
        Given: a block condition is triggered
        When: the returned value is parsed
        Then: parsed_content["error"] is True
        """
        bc = _complete_booking_context(confirmed=False)
        middleware = _make_middleware(bc)

        tc = _make_tool_call("book")
        result = middleware.wrap_tool_call(tc, lambda t: MagicMock())

        error = _extract_error_from_tool_message(result)
        assert error.get("error") is True, f"Expected error=True in: {error}"

    def test_code_is_in_valid_enum(self) -> None:
        """
        Given: a block condition is triggered
        When: the returned ToolMessage is parsed
        Then: error["code"] is one of the 7+ valid codes
        """
        bc = _complete_booking_context(confirmed=False)
        middleware = _make_middleware(bc)

        tc = _make_tool_call("book")
        result = middleware.wrap_tool_call(tc, lambda t: MagicMock())

        error = _extract_error_from_tool_message(result)
        assert error.get("code") in VALID_ERROR_CODES, (
            f"error code {error.get('code')!r} not in valid set {VALID_ERROR_CODES}"
        )

    def test_result_is_tool_message(self) -> None:
        """
        Given: a block condition is triggered
        When: wrap_tool_call returns
        Then: the result has a .content attribute with JSON (ToolMessage contract)
        """
        bc = _complete_booking_context(confirmed=False)
        middleware = _make_middleware(bc)

        tc = _make_tool_call("book")
        result = middleware.wrap_tool_call(tc, lambda t: MagicMock())

        assert hasattr(result, "content"), "Result must have .content attribute (ToolMessage)"
        # Content must be valid JSON
        content = result.content
        if isinstance(content, str):
            parsed = json.loads(content)
            assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# TestInvariantFailOpen — REQ-20 (task 1.26)
# ---------------------------------------------------------------------------


class TestInvariantFailOpen:
    """
    When get_state_fn raises an exception, wrap_tool_call MUST NOT propagate it.
    Instead, the tool handler is called (pass-through / fail-open) (REQ-20).
    """

    def test_fail_open_when_get_state_raises(self) -> None:
        """
        Given: get_state_fn raises a RuntimeError
        When: wrap_tool_call is called
        Then: no exception propagates AND the real handler is called
        """
        def _raising_state_fn() -> dict:
            raise RuntimeError("State unavailable in test")

        middleware = BookingInvariantMiddleware(
            get_state_fn=_raising_state_fn,
            get_catalog_fn=lambda: [],
            mode_name="BOOKING",
        )

        expected_result = MagicMock(content=json.dumps({"success": True}))
        handler_called = []

        def _fake_handler(tc):
            handler_called.append(tc)
            return expected_result

        tc = _make_tool_call("book")
        # Must not raise, must call handler
        middleware.wrap_tool_call(tc, _fake_handler)

        assert len(handler_called) == 1, (
            "Tool handler must be called in fail-open mode when state raises"
        )

    def test_fail_open_preserves_original_result(self) -> None:
        """
        Given: get_state_fn raises
        When: wrap_tool_call is called
        Then: the handler's return value is what wrap_tool_call returns
        """

        def _raising_state_fn() -> dict:
            raise ValueError("State error")

        middleware = BookingInvariantMiddleware(
            get_state_fn=_raising_state_fn,
            get_catalog_fn=lambda: [],
            mode_name="BOOKING",
        )

        expected_result = MagicMock(content=json.dumps({"result": "passed-through"}))
        tc = _make_tool_call("book")
        result = middleware.wrap_tool_call(tc, lambda t: expected_result)

        assert result is expected_result


# ---------------------------------------------------------------------------
# TestToolCallRequestAPI — new AgentMiddleware-compatible hook (D2–D6)
# ---------------------------------------------------------------------------


def _make_request(tc, state, runtime=None):
    """Build a ToolCallRequest-shaped SimpleNamespace for the new wrap_tool_call API."""
    return SimpleNamespace(tool_call=tc, state=state, runtime=runtime)


def _booking_state_with_context(**bc_overrides) -> dict:
    """Return a minimal BOOKING state with a fully valid booking context."""
    bc = {
        "_booking_completed": False,
        "confirmed": True,
        "_confirmation_shown": True,
        "pending_disambiguations": [],
        "last_services": ["Corte Largo"],
        "add_more_asked": True,
        "last_stylist": "Ana",
        "stylist_id": "stylist-uuid-001",
        "no_preference_stylist": False,
        "offered_slots": [{"start": "2026-04-21T10:00:00"}],
        "selected_slot": {"start": "2026-04-21T10:00:00"},
        "customer_name": "María García",
        "notes_state": "skipped",
    }
    bc.update(bc_overrides)
    return {
        "current_mode": "BOOKING",
        "booking_context": bc,
        "conversation_id": "conv-new-api-001",
        "total_message_count": 2,
    }


class TestToolCallRequestAPI:
    """R8-R11 — new wrap_tool_call(request, handler) API with ToolCallRequest-shaped objects."""

    def _make_middleware(self, state: dict) -> BookingInvariantMiddleware:
        return BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: [],
            mode_name="BOOKING",
        )

    def test_wrap_tool_call_rejects_book_missing_confirmation(self) -> None:
        """D2/R8 — wrap_tool_call(ToolCallRequest, handler) rejects book when confirmed=False.

        RED: before D3, new-style requests fall into legacy path (no state dict) and
             won't use _enforce_core. After D3: _is_tool_call_request returns True
             for SimpleNamespace with state=dict.
        GREEN: confirmed rejection with CONFIRMATION_REQUIRED code.
        """
        state = _booking_state_with_context(confirmed=False)
        mw = self._make_middleware(state)

        tc = _make_tool_call("book")
        req = _make_request(tc, state)

        handler_called = []
        result = mw.wrap_tool_call(req, lambda r: handler_called.append(r))

        assert len(handler_called) == 0, "Handler must NOT be called when confirmed=False"
        error = _extract_error_from_tool_message(result)
        assert error.get("error") is True
        assert error.get("code") in {"CONFIRMATION_REQUIRED", "CONFIRMATION_PENDING"}, (
            f"Expected CONFIRMATION_REQUIRED/PENDING, got {error.get('code')!r}"
        )

    def test_wrap_tool_call_mode_guard_passes_through(self) -> None:
        """D4/R9 — when current_mode != BOOKING, handler is called (no rejection)."""
        state = _booking_state_with_context(confirmed=False)
        state["current_mode"] = "GENERAL"  # not BOOKING
        mw = self._make_middleware(state)

        tc = _make_tool_call("book")
        req = _make_request(tc, state)

        handler_called = []
        expected = MagicMock(content=json.dumps({"success": True}))
        result = mw.wrap_tool_call(req, lambda r: (handler_called.append(r), expected)[1])

        assert len(handler_called) == 1, (
            "Handler MUST be called when mode != BOOKING (mode guard pass-through)"
        )
        assert result is expected

    def test_wrap_tool_call_all_preconditions_pass(self) -> None:
        """All preconditions satisfied → handler is called, result propagated."""
        state = _booking_state_with_context()  # confirmed=True, all fields present
        mw = self._make_middleware(state)

        tc = _make_tool_call("book")
        req = _make_request(tc, state)

        handler_called = []
        expected = MagicMock(content=json.dumps({"booked": True}))
        result = mw.wrap_tool_call(req, lambda r: (handler_called.append(r), expected)[1])

        assert len(handler_called) == 1, "Handler must be called when all preconditions pass"
        assert result is expected

    @pytest.mark.asyncio
    async def test_awrap_tool_call_passes_through_on_no_rejection(self) -> None:
        """D5/R11 — awrap_tool_call awaits handler when all preconditions pass."""
        state = _booking_state_with_context()  # confirmed=True, all fields present
        mw = self._make_middleware(state)

        tc = _make_tool_call("book")
        req = _make_request(tc, state)

        handler_called = []
        expected = MagicMock(content=json.dumps({"booked": True}))

        async def _fake_async_handler(r):
            handler_called.append(r)
            return expected

        result = await mw.awrap_tool_call(req, _fake_async_handler)

        assert len(handler_called) == 1, "Async handler must be awaited when all preconditions pass"
        assert result is expected

    @pytest.mark.asyncio
    async def test_awrap_tool_call_rejects_when_precondition_fails(self) -> None:
        """D6/R8 — awrap_tool_call returns rejection ToolMessage without calling handler."""
        state = _booking_state_with_context(confirmed=False)
        mw = self._make_middleware(state)

        tc = _make_tool_call("book")
        req = _make_request(tc, state)

        handler_called = []

        async def _fake_async_handler(r):
            handler_called.append(r)
            return MagicMock(content=json.dumps({"booked": True}))

        result = await mw.awrap_tool_call(req, _fake_async_handler)

        assert len(handler_called) == 0, "Handler must NOT be called when precondition fails"
        error = _extract_error_from_tool_message(result)
        assert error.get("error") is True
        assert error.get("code") in {"CONFIRMATION_REQUIRED", "CONFIRMATION_PENDING"}

    def test_wrap_tool_call_uses_closure_state_not_request_state(self) -> None:
        """R14 — ConversationState lives in the closure, NOT ``request.state``.

        LangChain 1.x exposes its internal AgentState as ``request.state`` (typically
        just ``messages`` — no ``current_mode`` or ``booking_context``). The invariant
        middleware must resolve the real ConversationState via the closure. Regression
        test for the production bug where mode-guard read ``request.state.current_mode``
        (always None) and silently let every tool call through without enforcement.
        """
        # Closure state: BOOKING mode with missing confirmation — invariant MUST reject.
        closure_state = _booking_state_with_context(confirmed=False)
        mw = self._make_middleware(closure_state)

        # Request state: LangChain-style AgentState — just messages, no booking fields.
        tc = _make_tool_call("book")
        empty_runtime_state = {"messages": []}
        req = _make_request(tc, empty_runtime_state)

        handler_called = []
        result = mw.wrap_tool_call(req, lambda r: handler_called.append(r))

        assert len(handler_called) == 0, (
            "Handler MUST NOT be called — invariant must read closure_state (confirmed=False) "
            "and reject, not read request.state (empty AgentState, mode-guard pass-through)."
        )
        error = _extract_error_from_tool_message(result)
        assert error.get("error") is True
        assert error.get("code") in {"CONFIRMATION_REQUIRED", "CONFIRMATION_PENDING"}

"""
Tests for BookingInvariantMiddleware CONFIRMATION_REQUIRED path.

The _evaluate_confirmation_gate static method was removed in task 2.10.
Confirmation is now enforced by BookingInvariantMiddleware.wrap_tool_call("book", ...).

REQs covered: REQ-13, REQ-20 (confirmation gate behaviour)
"""

import json

import pytest


def _make_full_bc(**overrides) -> dict:
    """Return a fully complete booking context (all fields set, confirmed=True)."""
    base = {
        "_booking_completed": False,
        "confirmed": True,
        "_confirmation_shown": True,
        "pending_disambiguations": [],
        "last_services": ["Corte de pelo"],
        "last_stylist": "María",
        "no_preference_stylist": False,
        "stylist_id": "stylist-uuid-001",
        "selected_slot": {"start": "2026-04-20T10:00:00"},
        "customer_name": "Juan",
        "notes_state": "provided",
        "add_more_asked": True,
    }
    base.update(overrides)
    return base


def _make_middleware(bc: dict, mode: str = "BOOKING"):
    """Build a BookingInvariantMiddleware for the given booking context."""
    from agent.booking.middleware.invariants import BookingInvariantMiddleware

    state = {"current_mode": mode, "booking_context": bc, "conversation_id": "conv-test"}
    return BookingInvariantMiddleware(
        get_state_fn=lambda: state,
        get_catalog_fn=lambda: [],
        mode_name=mode,
    )


def _make_book_call():
    """Build a minimal book tool call mock."""
    from unittest.mock import MagicMock
    tc = MagicMock()
    tc.name = "book"
    tc.args = {}
    tc.id = "tc-book-001"
    return tc


def _parse_error(result) -> dict:
    if isinstance(result.content, str):
        return json.loads(result.content)
    return result.content


class TestConfirmationRequiredBlocks:
    """When confirmed=False, book() must be blocked with CONFIRMATION_REQUIRED."""

    def test_blocked_when_confirmed_false(self):
        """All fields present but confirmed=False → CONFIRMATION_REQUIRED."""
        bc = _make_full_bc(confirmed=False)
        mw = _make_middleware(bc)
        handler_called = []
        result = mw.wrap_tool_call(_make_book_call(), lambda tc: handler_called.append(tc))

        assert len(handler_called) == 0, "Handler must NOT be called when confirmed=False"
        error = _parse_error(result)
        assert error.get("error") is True
        assert error.get("code") in {"CONFIRMATION_REQUIRED", "CONFIRMATION_PENDING"}

    def test_blocked_with_no_preference_stylist(self):
        """no_preference_stylist=True but confirmed=False → still CONFIRMATION_REQUIRED."""
        bc = _make_full_bc(confirmed=False, last_stylist=None, no_preference_stylist=True)
        mw = _make_middleware(bc)
        handler_called = []
        result = mw.wrap_tool_call(_make_book_call(), lambda tc: handler_called.append(tc))

        assert len(handler_called) == 0
        error = _parse_error(result)
        assert error.get("code") in {"CONFIRMATION_REQUIRED", "CONFIRMATION_PENDING"}

    def test_blocked_with_confirmation_shown_false(self):
        """_confirmation_shown=False and confirmed=False → CONFIRMATION_REQUIRED."""
        bc = _make_full_bc(confirmed=False, _confirmation_shown=False)
        mw = _make_middleware(bc)
        handler_called = []
        result = mw.wrap_tool_call(_make_book_call(), lambda tc: handler_called.append(tc))

        assert len(handler_called) == 0
        error = _parse_error(result)
        assert error.get("code") in {"CONFIRMATION_REQUIRED", "CONFIRMATION_PENDING"}


class TestConfirmationAllows:
    """When confirmed=True and all fields present, book() MUST proceed."""

    def test_allowed_when_confirmed_true(self):
        """All fields present AND confirmed=True → handler is called."""
        from unittest.mock import MagicMock
        bc = _make_full_bc(confirmed=True)
        mw = _make_middleware(bc)
        handler_called = []
        expected = MagicMock(content=json.dumps({"success": True}))
        result = mw.wrap_tool_call(_make_book_call(), lambda tc: (handler_called.append(tc), expected)[1])

        assert len(handler_called) == 1, "Handler MUST be called when confirmed=True"

    def test_allowed_with_no_preference_stylist(self):
        """no_preference_stylist=True + confirmed=True → allowed."""
        from unittest.mock import MagicMock
        bc = _make_full_bc(confirmed=True, last_stylist=None, no_preference_stylist=True)
        mw = _make_middleware(bc)
        handler_called = []
        expected = MagicMock(content=json.dumps({"ok": True}))
        mw.wrap_tool_call(_make_book_call(), lambda tc: (handler_called.append(tc), expected)[1])

        assert len(handler_called) == 1

    def test_state_booking_complete_with_confirmed_true(self):
        """All fields present AND confirmed=True → handler called."""
        from unittest.mock import MagicMock
        bc = _make_full_bc(confirmed=True, notes_state="skipped")
        mw = _make_middleware(bc)
        handler_called = []
        expected = MagicMock(content=json.dumps({"ok": True}))
        mw.wrap_tool_call(_make_book_call(), lambda tc: (handler_called.append(tc), expected)[1])

        assert len(handler_called) == 1


class TestMissingFieldsBlock:
    """Various missing field conditions that block book() before reaching confirmation check."""

    def test_missing_services_returns_error(self):
        """Without last_services → error."""
        bc = _make_full_bc(last_services=[])
        mw = _make_middleware(bc)
        handler_called = []
        result = mw.wrap_tool_call(_make_book_call(), lambda tc: handler_called.append(tc))

        assert len(handler_called) == 0
        error = _parse_error(result)
        assert error.get("error") is True

    def test_missing_stylist_returns_error(self):
        """Without stylist → error."""
        bc = _make_full_bc(last_stylist=None, no_preference_stylist=False, stylist_id=None)
        mw = _make_middleware(bc)
        handler_called = []
        result = mw.wrap_tool_call(_make_book_call(), lambda tc: handler_called.append(tc))

        assert len(handler_called) == 0
        error = _parse_error(result)
        assert error.get("error") is True

    def test_missing_slot_returns_error(self):
        """Without selected_slot → error."""
        bc = _make_full_bc(selected_slot=None)
        mw = _make_middleware(bc)
        handler_called = []
        result = mw.wrap_tool_call(_make_book_call(), lambda tc: handler_called.append(tc))

        assert len(handler_called) == 0
        error = _parse_error(result)
        assert error.get("error") is True

    def test_missing_customer_name_returns_error(self):
        """Without customer_name → error."""
        bc = _make_full_bc(customer_name=None)
        mw = _make_middleware(bc)
        handler_called = []
        result = mw.wrap_tool_call(_make_book_call(), lambda tc: handler_called.append(tc))

        assert len(handler_called) == 0
        error = _parse_error(result)
        assert error.get("error") is True

    def test_notes_state_does_not_block_booking(self):
        """notes_state is NOT a blocking precondition — notes are optional (R8)."""
        from unittest.mock import MagicMock
        bc = _make_full_bc(confirmed=True, notes_state="not_asked")
        mw = _make_middleware(bc)
        handler_called = []
        expected = MagicMock(content=json.dumps({"ok": True}))
        mw.wrap_tool_call(_make_book_call(), lambda tc: (handler_called.append(tc), expected)[1])

        assert len(handler_called) == 1, (
            "notes_state must NOT block book() — notes are optional (R8)"
        )

    def test_add_more_not_asked_does_not_block(self):
        """add_more_asked is NOT a precondition in BookingInvariantMiddleware."""
        from unittest.mock import MagicMock
        bc = _make_full_bc(confirmed=True, add_more_asked=False)
        mw = _make_middleware(bc)
        handler_called = []
        expected = MagicMock(content=json.dumps({"ok": True}))
        mw.wrap_tool_call(_make_book_call(), lambda tc: (handler_called.append(tc), expected)[1])

        assert len(handler_called) == 1

    def test_empty_ctx_blocks_with_error(self):
        """Empty dict → all preconditions fail → error returned."""
        bc = {}
        mw = _make_middleware(bc)
        handler_called = []
        result = mw.wrap_tool_call(_make_book_call(), lambda tc: handler_called.append(tc))

        assert len(handler_called) == 0
        assert hasattr(result, "content")


class TestGatePurity:
    """BookingInvariantMiddleware must be a pure function — no side-effects on booking_context."""

    def test_does_not_mutate_bc_on_reject(self):
        """Calling wrap_tool_call on a rejected book() must NOT mutate the booking context."""
        import copy
        bc = _make_full_bc(confirmed=False)
        bc_snapshot = copy.deepcopy(bc)
        mw = _make_middleware(bc)
        mw.wrap_tool_call(_make_book_call(), lambda tc: None)

        assert bc == bc_snapshot, "Middleware must not mutate booking_context on rejection"

    def test_idempotent_multiple_calls(self):
        """Calling wrap_tool_call twice with same ctx returns consistent results."""
        bc = _make_full_bc(confirmed=False)
        mw = _make_middleware(bc)

        result1 = mw.wrap_tool_call(_make_book_call(), lambda tc: None)
        result2 = mw.wrap_tool_call(_make_book_call(), lambda tc: None)

        e1 = _parse_error(result1)
        e2 = _parse_error(result2)
        assert e1.get("code") == e2.get("code"), "Same input must produce same error code"

"""
Tests for BookingInvariantMiddleware precondition check ordering.

The _evaluate_confirmation_gate static method was removed in task 2.10.
Ordering and precedence are now enforced inside BookingInvariantMiddleware._check_book().

Verified ordering (priority top-to-bottom):
  1. DISAMBIGUATION_PENDING  (blocks everything)
  2. SERVICES_MISSING
  3. STYLIST_MISSING
  4. SLOT_MISSING
  5. CUSTOMER_NAME_MISSING
  6. CONFIRMATION_REQUIRED   (last — all data must be present first)

Zero xfail marks. All GREEN.
"""

import json

import pytest


def _make_full_bc(**overrides) -> dict:
    """Return a fully complete booking context."""
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


def _make_middleware(bc: dict):
    from agent.booking.middleware.invariants import BookingInvariantMiddleware
    state = {"current_mode": "BOOKING", "booking_context": bc, "conversation_id": "conv-order"}
    return BookingInvariantMiddleware(get_state_fn=lambda: state, get_catalog_fn=lambda: [], mode_name="BOOKING")


def _make_book_call():
    from unittest.mock import MagicMock
    tc = MagicMock()
    tc.name = "book"
    tc.args = {}
    tc.id = "tc-001"
    return tc


def _parse(result) -> dict:
    if isinstance(result.content, str):
        return json.loads(result.content)
    return result.content


class TestPreconditionOrdering:
    """Verify that preconditions are checked in the correct priority order."""

    def test_disambiguation_blocks_before_services(self):
        """DISAMBIGUATION_PENDING has highest priority — fires even when services missing."""
        bc = _make_full_bc(
            confirmed=False,
            last_services=[],
            pending_disambiguations=[{"family": "Corte", "variants": ["señora"]}],
        )
        mw = _make_middleware(bc)
        result = mw.wrap_tool_call(_make_book_call(), lambda tc: None)
        error = _parse(result)

        assert error.get("code") == "DISAMBIGUATION_PENDING", (
            f"DISAMBIGUATION_PENDING must fire before SERVICES_MISSING. Got: {error.get('code')!r}"
        )

    def test_services_blocks_before_stylist(self):
        """SERVICES_MISSING fires before STYLIST_MISSING when both are absent."""
        bc = _make_full_bc(
            confirmed=True,
            last_services=[],
            last_stylist=None,
            no_preference_stylist=False,
            pending_disambiguations=[],
        )
        mw = _make_middleware(bc)
        result = mw.wrap_tool_call(_make_book_call(), lambda tc: None)
        error = _parse(result)

        assert error.get("code") == "SERVICES_MISSING", (
            f"SERVICES_MISSING must fire before STYLIST_MISSING. Got: {error.get('code')!r}"
        )

    def test_stylist_blocks_before_slot(self):
        """STYLIST_MISSING fires before SLOT_MISSING when both are absent."""
        bc = _make_full_bc(
            confirmed=True,
            last_stylist=None,
            no_preference_stylist=False,
            stylist_id=None,
            selected_slot=None,
            pending_disambiguations=[],
        )
        mw = _make_middleware(bc)
        result = mw.wrap_tool_call(_make_book_call(), lambda tc: None)
        error = _parse(result)

        assert error.get("code") == "STYLIST_MISSING", (
            f"STYLIST_MISSING must fire before SLOT_MISSING. Got: {error.get('code')!r}"
        )

    def test_slot_blocks_before_name(self):
        """SLOT_MISSING fires before CUSTOMER_NAME_MISSING when both are absent."""
        bc = _make_full_bc(
            confirmed=True,
            selected_slot=None,
            customer_name=None,
            pending_disambiguations=[],
        )
        mw = _make_middleware(bc)
        result = mw.wrap_tool_call(_make_book_call(), lambda tc: None)
        error = _parse(result)

        assert error.get("code") == "SLOT_MISSING", (
            f"SLOT_MISSING must fire before CUSTOMER_NAME_MISSING. Got: {error.get('code')!r}"
        )

    def test_name_blocks_before_confirmation(self):
        """CUSTOMER_NAME_MISSING fires before CONFIRMATION_REQUIRED."""
        bc = _make_full_bc(
            confirmed=False,
            customer_name=None,
            pending_disambiguations=[],
        )
        mw = _make_middleware(bc)
        result = mw.wrap_tool_call(_make_book_call(), lambda tc: None)
        error = _parse(result)

        assert error.get("code") == "CUSTOMER_NAME_MISSING", (
            f"CUSTOMER_NAME_MISSING must fire before CONFIRMATION_REQUIRED. Got: {error.get('code')!r}"
        )

    def test_confirmation_is_last_check(self):
        """CONFIRMATION_REQUIRED fires only when all other data is present."""
        bc = _make_full_bc(confirmed=False)  # all data present, just not confirmed
        mw = _make_middleware(bc)
        result = mw.wrap_tool_call(_make_book_call(), lambda tc: None)
        error = _parse(result)

        assert error.get("code") in {"CONFIRMATION_REQUIRED", "CONFIRMATION_PENDING"}, (
            f"Last check must be CONFIRMATION_REQUIRED. Got: {error.get('code')!r}"
        )


class TestConfirmationConstant:
    """BookingInvariantMiddleware.CONFIRMATION_REQUIRED must be a stable class constant."""

    def test_confirmation_required_constant_exists(self):
        """BookingInvariantMiddleware.CONFIRMATION_REQUIRED class attribute must exist."""
        from agent.booking.middleware.invariants import BookingInvariantMiddleware
        assert hasattr(BookingInvariantMiddleware, "CONFIRMATION_REQUIRED")

    def test_confirmation_required_constant_value(self):
        """CONFIRMATION_REQUIRED must equal 'CONFIRMATION_REQUIRED'."""
        from agent.booking.middleware.invariants import BookingInvariantMiddleware
        assert BookingInvariantMiddleware.CONFIRMATION_REQUIRED == "CONFIRMATION_REQUIRED"

    def test_confirmation_code_matches_constant(self):
        """The error code in the rejection must match CONFIRMATION_REQUIRED constant."""
        from agent.booking.middleware.invariants import BookingInvariantMiddleware
        bc = _make_full_bc(confirmed=False)
        mw = _make_middleware(bc)
        result = mw.wrap_tool_call(_make_book_call(), lambda tc: None)
        error = _parse(result)

        assert error.get("code") == BookingInvariantMiddleware.CONFIRMATION_REQUIRED


class TestNoPendingConflict:
    """When booking is complete and confirmed=True, NO error code must fire."""

    def test_complete_booking_with_confirmed_passes(self):
        """All preconditions satisfied → handler is called (no rejection)."""
        from unittest.mock import MagicMock
        bc = _make_full_bc(confirmed=True)
        mw = _make_middleware(bc)
        handler_called = []
        expected = MagicMock(content=json.dumps({"booked": True}))
        mw.wrap_tool_call(_make_book_call(), lambda tc: (handler_called.append(tc), expected)[1])

        assert len(handler_called) == 1, "All preconditions met → handler must be called"

    def test_no_confirmation_spurious_on_non_book_tool(self):
        """Non-book tools (update_booking) must NOT trigger confirmation check."""
        from unittest.mock import MagicMock
        bc = _make_full_bc(confirmed=False)
        mw = _make_middleware(bc)
        handler_called = []
        expected = MagicMock(content=json.dumps({"updated": True}))

        tc = MagicMock()
        tc.name = "update_booking"
        tc.args = {}
        tc.id = "tc-upd-001"

        mw.wrap_tool_call(tc, lambda t: (handler_called.append(t), expected)[1])

        assert len(handler_called) == 1, (
            "update_booking must always pass through — no confirmation gate for it"
        )

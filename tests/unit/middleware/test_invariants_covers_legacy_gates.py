"""
B.4 smoke tests — confirm BookingInvariantMiddleware covers every precondition
previously enforced by the _pre_tool_call[book] Step B completeness gate.

These tests should PASS GREEN on master (the middleware already covers each path).
They serve as non-regression anchors that must stay GREEN after Step B is deleted.

Per task B.4.1: if ANY of these fail on master, do NOT delete the corresponding gate.
All 5 pass GREEN → deletion is safe.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from agent.booking.middleware.invariants import BookingInvariantMiddleware

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(booking_context: dict) -> dict:
    return {
        "current_mode": "BOOKING",
        "booking_context": booking_context,
        "conversation_id": "conv-b4-test",
    }


def _complete_bc(**overrides) -> dict:
    """Fully valid booking context — all preconditions met."""
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


def _make_middleware(bc: dict) -> BookingInvariantMiddleware:
    state = _make_state(bc)
    return BookingInvariantMiddleware(
        get_state_fn=lambda: state,
        get_catalog_fn=lambda: [],
        mode_name="BOOKING",
    )


def _make_tool_call(name: str, args: dict | None = None) -> MagicMock:
    tc = MagicMock()
    tc.name = name
    tc.args = args or {}
    tc.id = "tc-b4-001"
    return tc


def _error_code(result) -> str:
    content = result.content
    payload = json.loads(content) if isinstance(content, str) else content
    return payload.get("code", "")


# ---------------------------------------------------------------------------
# B.4.1 — five non-regression anchors (each maps to one deleted gate condition)
# ---------------------------------------------------------------------------


def test_book_without_confirmed_rejected_by_invariant() -> None:
    """
    Gate: CONFIRMATION_REQUIRED / CONFIRMATION_PENDING.
    Precondition previously enforced by Step B; now solely by middleware.
    """
    bc = _complete_bc(confirmed=False)
    middleware = _make_middleware(bc)
    called = []
    tc = _make_tool_call("book")

    result = middleware.wrap_tool_call(tc, lambda t: called.append(t) or MagicMock())

    assert len(called) == 0, "book handler must NOT fire when confirmed=False"
    assert _error_code(result) in {
        "CONFIRMATION_REQUIRED",
        "CONFIRMATION_PENDING",
    }, f"Expected CONFIRMATION_REQUIRED/PENDING, got {_error_code(result)!r}"


def test_book_without_services_rejected_by_invariant() -> None:
    """Gate: SERVICES_MISSING."""
    bc = _complete_bc(last_services=[])
    middleware = _make_middleware(bc)
    called = []
    tc = _make_tool_call("book")

    result = middleware.wrap_tool_call(tc, lambda t: called.append(t) or MagicMock())

    assert len(called) == 0, "book handler must NOT fire when last_services=[]"
    assert (
        _error_code(result) == "SERVICES_MISSING"
    ), f"Expected SERVICES_MISSING, got {_error_code(result)!r}"


def test_book_without_stylist_rejected_by_invariant() -> None:
    """Gate: STYLIST_MISSING."""
    bc = _complete_bc(last_stylist=None, stylist_id=None, no_preference_stylist=False)
    middleware = _make_middleware(bc)
    called = []
    tc = _make_tool_call("book")

    result = middleware.wrap_tool_call(tc, lambda t: called.append(t) or MagicMock())

    assert len(called) == 0, "book handler must NOT fire when no stylist is set"
    assert (
        _error_code(result) == "STYLIST_MISSING"
    ), f"Expected STYLIST_MISSING, got {_error_code(result)!r}"


def test_book_without_slot_rejected_by_invariant() -> None:
    """Gate: SLOT_MISSING."""
    bc = _complete_bc(selected_slot=None)
    middleware = _make_middleware(bc)
    called = []
    tc = _make_tool_call("book")

    result = middleware.wrap_tool_call(tc, lambda t: called.append(t) or MagicMock())

    assert len(called) == 0, "book handler must NOT fire when selected_slot=None"
    assert (
        _error_code(result) == "SLOT_MISSING"
    ), f"Expected SLOT_MISSING, got {_error_code(result)!r}"


def test_book_without_customer_name_rejected_by_invariant() -> None:
    """Gate: CUSTOMER_NAME_MISSING."""
    bc = _complete_bc(customer_name=None)
    middleware = _make_middleware(bc)
    called = []
    tc = _make_tool_call("book")

    result = middleware.wrap_tool_call(tc, lambda t: called.append(t) or MagicMock())

    assert len(called) == 0, "book handler must NOT fire when customer_name=None"
    assert (
        _error_code(result) == "CUSTOMER_NAME_MISSING"
    ), f"Expected CUSTOMER_NAME_MISSING, got {_error_code(result)!r}"

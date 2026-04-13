"""
Tests for BookingModeNode._resolve_digit_selection() — digit slot fast-path.

LLM-driven architecture: time, ordinal, affirmative, decline, notes-skip,
and sin-preferencia regex patterns were removed. Only the bare digit→slot
mapping remains as a deterministic fast-path.
"""

from __future__ import annotations

import pytest

from agent.modes.booking_mode import BookingModeNode


@pytest.fixture()
def booking_node() -> BookingModeNode:
    return BookingModeNode(tools=[])


def _make_state(user_message: str = "") -> dict:
    messages = [{"role": "user", "content": user_message}] if user_message else []
    return {"messages": messages, "user_message": None}


_OFFERED_SLOTS = [
    {"time": "10:00", "stylist_name": "Marta", "stylist_id": "a1"},
    {"time": "11:00", "stylist_name": "Pilar", "stylist_id": "b2"},
    {"time": "12:00", "stylist_name": "Victor", "stylist_id": "c3"},
]


def test_digit_selects_slot(booking_node):
    """User sends '2' → selects second slot."""
    ctx = {"offered_slots": _OFFERED_SLOTS}
    booking_node._resolve_digit_selection(_make_state("2"), ctx)
    assert ctx["selected_slot"] == _OFFERED_SLOTS[1]


def test_digit_sets_stylist_from_slot(booking_node):
    """Digit selection also sets last_stylist from the resolved slot."""
    ctx = {"offered_slots": _OFFERED_SLOTS}
    booking_node._resolve_digit_selection(_make_state("1"), ctx)
    assert ctx["last_stylist"] == "Marta"


def test_digit_does_not_overwrite_existing_stylist(booking_node):
    """If last_stylist already set, digit selection preserves it."""
    ctx = {"offered_slots": _OFFERED_SLOTS, "last_stylist": "Harolyn"}
    booking_node._resolve_digit_selection(_make_state("1"), ctx)
    assert ctx["last_stylist"] == "Harolyn"


def test_digit_out_of_range_no_effect(booking_node):
    """Digit outside slot range has no effect."""
    ctx = {"offered_slots": _OFFERED_SLOTS}
    booking_node._resolve_digit_selection(_make_state("5"), ctx)
    assert "selected_slot" not in ctx


def test_non_digit_no_effect(booking_node):
    """Non-digit message has no effect."""
    ctx = {"offered_slots": _OFFERED_SLOTS}
    booking_node._resolve_digit_selection(_make_state("la primera"), ctx)
    assert "selected_slot" not in ctx


def test_no_offered_slots_no_effect(booking_node):
    """No offered_slots → no resolution."""
    ctx = {}
    booking_node._resolve_digit_selection(_make_state("2"), ctx)
    assert "selected_slot" not in ctx


def test_already_selected_no_overwrite(booking_node):
    """If selected_slot already set, digit does not overwrite."""
    existing = {"time": "09:00", "stylist_name": "Ana"}
    ctx = {"offered_slots": _OFFERED_SLOTS, "selected_slot": existing}
    booking_node._resolve_digit_selection(_make_state("2"), ctx)
    assert ctx["selected_slot"] == existing


def test_empty_message_no_effect(booking_node):
    """Empty message has no effect."""
    ctx = {"offered_slots": _OFFERED_SLOTS}
    booking_node._resolve_digit_selection(_make_state(""), ctx)
    assert "selected_slot" not in ctx

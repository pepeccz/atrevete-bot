"""Tests for route_next dispatcher — Phase 5.10."""

from __future__ import annotations

import pytest
from langgraph.constants import END


def _state(step: str | None, offered_slots=None):
    booking = {"step": step} if step is not None else None
    if booking and offered_slots is not None:
        booking["offered_slots"] = offered_slots
    return {"booking": booking, "messages": []}


@pytest.mark.parametrize(
    "step,expected",
    [
        ("service", "ask_service"),
        ("audience", "ask_audience"),
        ("stylist", "ask_stylist"),
        ("date", "ask_date"),
        ("name", "ask_name"),
        ("notes", "ask_notes"),
        ("confirm", "await_confirmation"),
        ("done", END),
    ],
)
def test_step_to_node_mapping(step, expected):
    from agent.booking.route_next import route_next

    result = route_next(_state(step))
    assert result == expected


def test_slot_with_no_offered_slots_goes_to_fetch_availability():
    from agent.booking.route_next import route_next

    result = route_next(_state("slot", offered_slots=None))
    assert result == "fetch_availability"


def test_slot_with_offered_slots_goes_to_ask_slot():
    from agent.booking.route_next import route_next

    slots = [{"start": "10:00"}]
    result = route_next(_state("slot", offered_slots=slots))
    assert result == "ask_slot"


def test_missing_step_defaults_to_service():
    from agent.booking.route_next import route_next

    # booking with no step key
    result = route_next({"booking": {}, "messages": []})
    assert result == "ask_service"


def test_no_booking_defaults_to_service():
    from agent.booking.route_next import route_next

    result = route_next({"booking": None, "messages": []})
    assert result == "ask_service"

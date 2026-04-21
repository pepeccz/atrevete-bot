"""
Phase 2 — digit_selection resolver tests (RED).

R1.1: digit 1-9 maps to offered_slots[i]; no-match returns matched=False.
"""

from __future__ import annotations

import pytest


def _bc_with_slots(n: int = 3) -> dict:
    return {
        "offered_slots": [
            {"start_time": f"10:0{i}", "stylist_name": f"Stylist{i}"}
            for i in range(n)
        ]
    }


def test_digit_1_selects_first_slot():
    from agent.booking.resolvers.digit_selection import resolve

    bc = _bc_with_slots(3)
    result = resolve("1", bc, {})
    assert result["matched"] is True
    assert result["patch"]["selected_slot"] == bc["offered_slots"][0]


def test_digit_2_selects_second_slot():
    from agent.booking.resolvers.digit_selection import resolve

    bc = _bc_with_slots(3)
    result = resolve("2", bc, {})
    assert result["matched"] is True
    assert result["patch"]["selected_slot"] == bc["offered_slots"][1]


def test_no_offered_slots_returns_not_matched():
    from agent.booking.resolvers.digit_selection import resolve

    result = resolve("1", {}, {})
    assert result is None or not result.get("matched")


def test_non_digit_text_returns_not_matched():
    from agent.booking.resolvers.digit_selection import resolve

    bc = _bc_with_slots(3)
    result = resolve("mañana", bc, {})
    assert result is None or not result.get("matched")


def test_out_of_range_digit_not_matched():
    from agent.booking.resolvers.digit_selection import resolve

    bc = _bc_with_slots(2)
    result = resolve("5", bc, {})
    assert result is None or not result.get("matched")


def test_selected_slot_already_set_skips():
    from agent.booking.resolvers.digit_selection import resolve

    bc = _bc_with_slots(3)
    bc["selected_slot"] = bc["offered_slots"][0]
    result = resolve("2", bc, {})
    assert result is None or not result.get("matched")


def test_slot_stylist_written_to_last_stylist():
    from agent.booking.resolvers.digit_selection import resolve

    bc = _bc_with_slots(3)
    result = resolve("1", bc, {})
    assert result["matched"] is True
    assert result["patch"].get("last_stylist") == "Stylist0"


def test_user_action_is_provide_field():
    from agent.booking.resolvers.digit_selection import resolve

    bc = _bc_with_slots(3)
    result = resolve("1", bc, {})
    assert result.get("user_action") == "PROVIDE_FIELD"

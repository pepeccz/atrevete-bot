"""
Tests for diversify_slots() — pure slot diversification function.

All tests use plain dict fixtures. No DB or async needed.
"""

import pytest

from agent.tools.availability_tools import diversify_slots


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_slot(stylist: str, date: str, time: str) -> dict:
    """Build a minimal slot dict."""
    return {
        "stylist_name": stylist,
        "stylist_id": f"id-{stylist.lower()}",
        "date": date,
        "time": time,
        "end_time": time,  # not relevant for diversification
        "day_label": date,
        "full_datetime": f"{date}T{time}:00+02:00",
    }


def _make_slots(stylist: str, date: str, times: list[str]) -> list[dict]:
    return [_make_slot(stylist, date, t) for t in times]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_empty_input_returns_empty():
    """Empty input always returns empty list regardless of strategy."""
    assert diversify_slots([], strategy="one_per_stylist", max_slots=5) == []
    assert diversify_slots([], strategy="time_spread", max_slots=5) == []
    assert diversify_slots([], strategy="none", max_slots=5) == []


def test_none_strategy_sorts_and_caps():
    """'none' strategy: sort by (date, time) ascending, cap at max_slots."""
    slots = [
        _make_slot("A", "2026-04-10", "14:00"),
        _make_slot("B", "2026-04-10", "09:00"),
        _make_slot("A", "2026-04-10", "11:00"),
        _make_slot("C", "2026-04-10", "10:00"),
        _make_slot("D", "2026-04-10", "08:00"),
        _make_slot("E", "2026-04-10", "13:00"),
    ]
    result = diversify_slots(slots, strategy="none", max_slots=4)
    assert len(result) == 4
    times = [s["time"] for s in result]
    assert times == sorted(times), "slots must be sorted by time"
    # First 4 by time: 08:00, 09:00, 10:00, 11:00
    assert times == ["08:00", "09:00", "10:00", "11:00"]


def test_one_per_stylist_5_stylists_5_max():
    """5 stylists × 3 slots each → result has 5 slots, all different stylists."""
    stylists = ["Ana", "Bea", "Carla", "Dani", "Eva"]
    times = ["10:00", "11:00", "12:00"]
    slots = []
    for s in stylists:
        slots.extend(_make_slots(s, "2026-04-10", times))

    result = diversify_slots(slots, strategy="one_per_stylist", max_slots=5)

    assert len(result) == 5
    result_stylists = {s["stylist_name"] for s in result}
    assert result_stylists == set(stylists), "all 5 stylists must be represented"


def test_one_per_stylist_1_stylist_fills_by_time():
    """1 stylist with 10 slots → fills up to max_slots by time order."""
    times = [f"{h:02d}:00" for h in range(9, 19)]  # 09:00 … 18:00
    slots = _make_slots("Ana", "2026-04-10", times)

    result = diversify_slots(slots, strategy="one_per_stylist", max_slots=5)

    assert len(result) == 5
    # Should be the 5 earliest slots
    result_times = [s["time"] for s in result]
    assert result_times == sorted(result_times)
    assert result_times[0] == "09:00"
    assert result_times[-1] == "13:00"


def test_one_per_stylist_2_stylists_5_max():
    """2 stylists × 10 slots each → round-robin fills remaining 3 slots after first 2."""
    times_a = [f"{h:02d}:00" for h in range(9, 19)]   # Ana: 09:00–18:00
    times_b = [f"{h:02d}:30" for h in range(9, 19)]   # Bea: 09:30–18:30

    slots = _make_slots("Ana", "2026-04-10", times_a)
    slots += _make_slots("Bea", "2026-04-10", times_b)

    result = diversify_slots(slots, strategy="one_per_stylist", max_slots=5)

    assert len(result) == 5
    # Both stylists must appear
    result_stylists = [s["stylist_name"] for s in result]
    assert "Ana" in result_stylists
    assert "Bea" in result_stylists
    # Ana has 3 slots, Bea has 2 (or vice-versa depending on round-robin)
    ana_count = result_stylists.count("Ana")
    bea_count = result_stylists.count("Bea")
    assert ana_count + bea_count == 5
    # Round-robin should keep counts close
    assert abs(ana_count - bea_count) <= 1


def test_one_per_stylist_output_sorted_by_time():
    """Output of one_per_stylist is always sorted by (date, time) ascending."""
    slots = [
        _make_slot("Ana", "2026-04-10", "14:00"),
        _make_slot("Bea", "2026-04-10", "09:00"),
        _make_slot("Carla", "2026-04-11", "08:00"),
        _make_slot("Dani", "2026-04-10", "11:00"),
        _make_slot("Eva", "2026-04-10", "16:00"),
    ]
    result = diversify_slots(slots, strategy="one_per_stylist", max_slots=5)

    sort_keys = [(s["date"], s["time"]) for s in result]
    assert sort_keys == sorted(sort_keys), "result must be sorted by (date, time)"


def test_time_spread_distinct_buckets():
    """time_spread returns slots from different 1-hour buckets when available."""
    # 3 slots per hour, 4 different hours
    slots = []
    for hour in ["09", "10", "11", "12"]:
        for minute in ["00", "15", "30"]:
            slots.append(_make_slot("Ana", "2026-04-10", f"{hour}:{minute}"))

    result = diversify_slots(slots, strategy="time_spread", max_slots=4)

    assert len(result) == 4
    # Each slot should come from a distinct hour bucket
    hours = {s["time"][:2] for s in result}
    assert len(hours) == 4, f"expected 4 distinct hours, got {hours}"


def test_unknown_strategy_does_not_raise():
    """Unknown strategy logs a warning and returns sorted+capped result (no exception)."""
    slots = [
        _make_slot("Ana", "2026-04-10", "10:00"),
        _make_slot("Bea", "2026-04-10", "09:00"),
        _make_slot("Carla", "2026-04-10", "11:00"),
    ]
    # Must NOT raise
    result = diversify_slots(slots, strategy="banana_split", max_slots=2)

    # Falls back to 'none': sorted, capped
    assert len(result) == 2
    times = [s["time"] for s in result]
    assert times == sorted(times)

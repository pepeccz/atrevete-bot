"""Unit tests for post-loop slot resolver in BookingMode.

The slot resolver runs after the agentic loop (step 7b) to catch user
slot selections that the LLM didn't persist via tool calls (tool_skip).

It matches the user message against ctx.offered_slots using:
1. Bare digit (1-N index)
2. Time string ("a las 12:40", "12:40", "las 10")
3. Ordinal/positional ("la primera", "el tercero")
"""

from __future__ import annotations

import pytest

from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import _resolve_slot_from_message


# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════

SAMPLE_SLOTS = [
    {
        "stylist_id": "sty-001",
        "stylist_name": "Pilar",
        "time": "10:00",
        "date": "2026-04-08",
        "day_label": "Miércoles 8 de abril",
        "full_datetime": "2026-04-08T10:00:00+02:00",
    },
    {
        "stylist_id": "sty-001",
        "stylist_name": "Pilar",
        "time": "11:20",
        "date": "2026-04-08",
        "day_label": "Miércoles 8 de abril",
        "full_datetime": "2026-04-08T11:20:00+02:00",
    },
    {
        "stylist_id": "sty-001",
        "stylist_name": "Pilar",
        "time": "12:40",
        "date": "2026-04-08",
        "day_label": "Miércoles 8 de abril",
        "full_datetime": "2026-04-08T12:40:00+02:00",
    },
    {
        "stylist_id": "sty-001",
        "stylist_name": "Pilar",
        "time": "14:00",
        "date": "2026-04-08",
        "day_label": "Miércoles 8 de abril",
        "full_datetime": "2026-04-08T14:00:00+02:00",
    },
    {
        "stylist_id": "sty-001",
        "stylist_name": "Pilar",
        "time": "15:20",
        "date": "2026-04-08",
        "day_label": "Miércoles 8 de abril",
        "full_datetime": "2026-04-08T15:20:00+02:00",
    },
]


def _make_ctx_with_slots(slots=None, selected_slot=None):
    return BookingContext(
        offered_slots=slots or list(SAMPLE_SLOTS),
        selected_slot=selected_slot,
        service_id="svc-001",
        service_name="Corte",
    )


# ═══════════════════════════════════════════════════════════════════════
# Bare digit matching
# ═══════════════════════════════════════════════════════════════════════


class TestBareDigitMatching:
    def test_bare_digit_1(self):
        ctx = _make_ctx_with_slots()
        assert _resolve_slot_from_message("1", ctx) is True
        assert ctx.selected_slot == SAMPLE_SLOTS[0]
        assert ctx.stylist_id == "sty-001"
        assert ctx.stylist_name == "Pilar"

    def test_bare_digit_3(self):
        """The exact production scenario: user sends '3' for slot 12:40."""
        ctx = _make_ctx_with_slots()
        assert _resolve_slot_from_message("3", ctx) is True
        assert ctx.selected_slot["time"] == "12:40"

    def test_bare_digit_5(self):
        ctx = _make_ctx_with_slots()
        assert _resolve_slot_from_message("5", ctx) is True
        assert ctx.selected_slot["time"] == "15:20"

    def test_bare_digit_out_of_range(self):
        ctx = _make_ctx_with_slots()
        assert _resolve_slot_from_message("6", ctx) is False
        assert ctx.selected_slot is None

    def test_bare_digit_zero(self):
        ctx = _make_ctx_with_slots()
        assert _resolve_slot_from_message("0", ctx) is False

    def test_bare_digit_with_whitespace(self):
        ctx = _make_ctx_with_slots()
        assert _resolve_slot_from_message("  3  ", ctx) is True
        assert ctx.selected_slot["time"] == "12:40"


# ═══════════════════════════════════════════════════════════════════════
# Time string matching
# ═══════════════════════════════════════════════════════════════════════


class TestTimeStringMatching:
    def test_a_las_1240(self):
        ctx = _make_ctx_with_slots()
        assert _resolve_slot_from_message("a las 12:40", ctx) is True
        assert ctx.selected_slot["time"] == "12:40"

    def test_las_10(self):
        ctx = _make_ctx_with_slots()
        assert _resolve_slot_from_message("las 10", ctx) is True
        assert ctx.selected_slot["time"] == "10:00"

    def test_bare_time_1120(self):
        ctx = _make_ctx_with_slots()
        assert _resolve_slot_from_message("11:20", ctx) is True
        assert ctx.selected_slot["time"] == "11:20"

    def test_time_with_context(self):
        ctx = _make_ctx_with_slots()
        assert _resolve_slot_from_message("ponme a las 14:00", ctx) is True
        assert ctx.selected_slot["time"] == "14:00"

    def test_time_not_in_slots(self):
        ctx = _make_ctx_with_slots()
        assert _resolve_slot_from_message("a las 16:00", ctx) is False


# ═══════════════════════════════════════════════════════════════════════
# Guards
# ═══════════════════════════════════════════════════════════════════════


class TestSlotResolverGuards:
    def test_no_offered_slots(self):
        ctx = BookingContext()
        assert _resolve_slot_from_message("3", ctx) is False

    def test_empty_offered_slots(self):
        ctx = BookingContext(offered_slots=[])
        assert _resolve_slot_from_message("3", ctx) is False

    def test_already_selected(self):
        """If selected_slot is already set, resolver is a no-op."""
        ctx = _make_ctx_with_slots(selected_slot=SAMPLE_SLOTS[0])
        assert _resolve_slot_from_message("3", ctx) is False
        assert ctx.selected_slot == SAMPLE_SLOTS[0]  # unchanged

    def test_non_matching_message(self):
        ctx = _make_ctx_with_slots()
        assert _resolve_slot_from_message("me llamo María", ctx) is False
        assert ctx.selected_slot is None

    def test_empty_message(self):
        ctx = _make_ctx_with_slots()
        assert _resolve_slot_from_message("", ctx) is False

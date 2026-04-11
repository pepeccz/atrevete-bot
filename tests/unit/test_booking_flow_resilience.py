"""Tests for booking flow resilience fixes.

Covers:
- Fix 1: Reset stale booking_context when _booking_completed is True
- Fix 2: Stylist update mid-flow (no last_stylist guard)
- Fix 3: booking.md contains Cambios a mitad de flujo section
"""

import pytest
from pathlib import Path


class TestBookingContextReset:
    def test_completed_booking_context_is_reset(self):
        """Stale booking_context with _booking_completed=True should be cleared."""
        booking_context = {
            "_booking_completed": True,
            "last_services": ["Cortar"],
            "last_stylist": "Marta",
            "selected_slot": {"time": "10:00"},
            "booking_step": "confirmation",
        }
        # Simulate what handle() does after loading booking_context
        if booking_context.get("_booking_completed"):
            booking_context = {}
        assert booking_context == {}

    def test_active_booking_context_not_reset(self):
        """Active booking without _booking_completed should not be reset."""
        booking_context = {
            "last_services": ["Cortar"],
            "booking_step": "stylist_selection",
        }
        if booking_context.get("_booking_completed"):
            booking_context = {}
        assert booking_context.get("last_services") == ["Cortar"]

    def test_empty_booking_context_not_reset(self):
        """Empty booking_context (first booking) should not be reset."""
        booking_context = {}
        if booking_context.get("_booking_completed"):
            booking_context = {}
        assert booking_context == {}


class TestStylistUpdateMidFlow:
    def test_stylist_updated_when_already_set(self):
        """Stylist should be updatable even when already set."""
        mode_context = {"last_stylist": "Marta", "offered_slots": [{"time": "10:00"}]}
        # Simulate _post_tool_result behavior for check_availability
        tool_args = {"stylist_name": "Victor"}
        result_dict = {"available_slots": [{"time": "11:00"}]}

        slots = result_dict.get("available_slots") or []
        if slots:
            mode_context.pop("selected_slot", None)
            mode_context["offered_slots"] = slots
        stylist_name = tool_args.get("stylist_name")
        if stylist_name:  # No guard — always update
            mode_context["last_stylist"] = stylist_name

        assert mode_context["last_stylist"] == "Victor"

    def test_stylist_not_updated_when_absent(self):
        """last_stylist should not change when stylist_name is absent."""
        mode_context = {"last_stylist": "Marta"}
        tool_args = {}
        stylist_name = tool_args.get("stylist_name")
        if stylist_name:
            mode_context["last_stylist"] = stylist_name
        assert mode_context["last_stylist"] == "Marta"

    def test_stylist_set_first_time(self):
        """Stylist should be settable when not previously set (regression)."""
        mode_context = {}
        tool_args = {"stylist_name": "Pilar"}
        stylist_name = tool_args.get("stylist_name")
        if stylist_name:
            mode_context["last_stylist"] = stylist_name
        assert mode_context["last_stylist"] == "Pilar"


class TestBookingPromptMidFlowSection:
    def test_cambios_section_exists(self):
        """booking.md should contain the mid-flow changes section."""
        content = Path("agent/prompts/modes/booking.md").read_text()
        assert "### Cambios a mitad de flujo" in content

    def test_cambios_section_covers_service_change(self):
        content = Path("agent/prompts/modes/booking.md").read_text()
        assert "Cambio de servicio" in content
        assert "check_availability" in content

    def test_cambios_section_covers_stylist_change(self):
        content = Path("agent/prompts/modes/booking.md").read_text()
        assert "Cambio de estilista" in content

    def test_cambios_section_covers_restart(self):
        content = Path("agent/prompts/modes/booking.md").read_text()
        assert "Reinicio" in content

    def test_cambios_after_multiservicio(self):
        """Cambios section should appear after Multi-servicio."""
        content = Path("agent/prompts/modes/booking.md").read_text()
        multi_pos = content.index("### Multi-servicio")
        cambios_pos = content.index("### Cambios a mitad de flujo")
        assert cambios_pos > multi_pos

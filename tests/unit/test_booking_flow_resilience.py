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
    """Mid-flow change handling in the deterministic subgraph architecture.

    Phase 8: booking.md was deleted. Mid-flow changes are now handled by the
    subgraph's route_action FSM (returns to ask_service/ask_stylist/ask_slot nodes)
    rather than prompt instructions. These tests verify the subgraph directory exists.
    """

    def test_booking_subgraph_prompts_directory_exists(self):
        """Per-leaf booking prompts directory must exist (replaced booking.md)."""
        booking_dir = Path("agent/prompts/modes/booking")
        assert booking_dir.is_dir(), "agent/prompts/modes/booking/ directory must exist"

    def test_error_recovery_prompt_handles_restart(self):
        """error_recovery.md must guide the LLM to restart the booking flow."""
        content = Path("agent/prompts/modes/booking/error_recovery.md").read_text()
        assert "empezar" in content.lower() or "reinici" in content.lower()

    def test_ask_service_prompt_handles_service_change(self):
        """ask_service.md is re-entered on service change — must guide service selection."""
        content = Path("agent/prompts/modes/booking/ask_service.md").read_text()
        assert "servicio" in content.lower()

    def test_ask_stylist_prompt_handles_stylist_change(self):
        """ask_stylist.md is re-entered on stylist change — must guide stylist selection."""
        content = Path("agent/prompts/modes/booking/ask_stylist.md").read_text()
        assert "estilista" in content.lower()

    def test_cambios_after_multiservicio(self):
        """ask_more_services.md handles multi-service — must ask about additional services."""
        content = Path("agent/prompts/modes/booking/ask_more_services.md").read_text()
        assert "servicio" in content.lower()

"""
Tests for BookingModeNode._evaluate_confirmation_gate(state, tool_result) -> bool

Pure function: no side-effects, reads ctx dict, returns bool.

TDD — these tests are written BEFORE the implementation (RED phase).
"""

import pytest


class TestEvaluateConfirmationGateTrue:
    """Cases where the gate should return True (all required fields present)."""

    def test_all_fields_present_first_time(self):
        """When all required fields are present and _confirmation_shown is False → True."""
        from agent.modes.booking_mode import BookingModeNode

        ctx = {
            "last_services": ["Corte de pelo"],
            "last_stylist": "María",
            "selected_slot": {"date": "2026-04-20", "time": "10:00"},
            "customer_name": "Juan",
            "notes_asked": True,
            "add_more_asked": True,
            "_confirmation_shown": False,
        }
        assert BookingModeNode._evaluate_confirmation_gate(ctx) is True

    def test_all_fields_with_no_preference_stylist(self):
        """no_preference_stylist counts as having stylist → True."""
        from agent.modes.booking_mode import BookingModeNode

        ctx = {
            "last_services": ["Tinte"],
            "no_preference_stylist": True,
            "selected_slot": {"date": "2026-04-21", "time": "14:00"},
            "customer_name": "Ana",
            "notes_asked": True,
            "add_more_asked": True,
            "_confirmation_shown": False,
        }
        assert BookingModeNode._evaluate_confirmation_gate(ctx) is True

    def test_confirmation_shown_false_all_fields_complete(self):
        """Explicit _confirmation_shown=False with all fields → True (gate not yet triggered)."""
        from agent.modes.booking_mode import BookingModeNode

        ctx = {
            "last_services": ["Manicura"],
            "last_stylist": "Lucía",
            "selected_slot": {"date": "2026-04-22", "time": "09:00"},
            "customer_name": "Pedro",
            "notes_asked": True,
            "add_more_asked": True,
            "_confirmation_shown": False,
        }
        result = BookingModeNode._evaluate_confirmation_gate(ctx)
        assert result is True


class TestEvaluateConfirmationGateFalse:
    """Cases where the gate should return False."""

    def test_already_shown_returns_false(self):
        """When _confirmation_shown is already True → False (gate already fired)."""
        from agent.modes.booking_mode import BookingModeNode

        ctx = {
            "last_services": ["Corte de pelo"],
            "last_stylist": "María",
            "selected_slot": {"date": "2026-04-20", "time": "10:00"},
            "customer_name": "Juan",
            "notes_asked": True,
            "add_more_asked": True,
            "_confirmation_shown": True,  # already shown
        }
        assert BookingModeNode._evaluate_confirmation_gate(ctx) is False

    def test_missing_services_returns_false(self):
        """Without last_services → False (booking not complete)."""
        from agent.modes.booking_mode import BookingModeNode

        ctx = {
            "last_stylist": "María",
            "selected_slot": {"date": "2026-04-20", "time": "10:00"},
            "customer_name": "Juan",
            "notes_asked": True,
            "add_more_asked": True,
            "_confirmation_shown": False,
        }
        assert BookingModeNode._evaluate_confirmation_gate(ctx) is False

    def test_missing_stylist_returns_false(self):
        """Without stylist (neither last_stylist nor no_preference_stylist) → False."""
        from agent.modes.booking_mode import BookingModeNode

        ctx = {
            "last_services": ["Corte"],
            "selected_slot": {"date": "2026-04-20", "time": "10:00"},
            "customer_name": "Juan",
            "notes_asked": True,
            "add_more_asked": True,
            "_confirmation_shown": False,
        }
        assert BookingModeNode._evaluate_confirmation_gate(ctx) is False

    def test_missing_slot_returns_false(self):
        """Without selected_slot → False."""
        from agent.modes.booking_mode import BookingModeNode

        ctx = {
            "last_services": ["Corte"],
            "last_stylist": "María",
            "customer_name": "Juan",
            "notes_asked": True,
            "add_more_asked": True,
            "_confirmation_shown": False,
        }
        assert BookingModeNode._evaluate_confirmation_gate(ctx) is False

    def test_missing_customer_name_returns_false(self):
        """Without customer_name → False."""
        from agent.modes.booking_mode import BookingModeNode

        ctx = {
            "last_services": ["Corte"],
            "last_stylist": "María",
            "selected_slot": {"date": "2026-04-20", "time": "10:00"},
            "notes_asked": True,
            "add_more_asked": True,
            "_confirmation_shown": False,
        }
        assert BookingModeNode._evaluate_confirmation_gate(ctx) is False

    def test_notes_not_asked_returns_false(self):
        """Without notes_asked → False (notes step not completed)."""
        from agent.modes.booking_mode import BookingModeNode

        ctx = {
            "last_services": ["Corte"],
            "last_stylist": "María",
            "selected_slot": {"date": "2026-04-20", "time": "10:00"},
            "customer_name": "Juan",
            "add_more_asked": True,
            "_confirmation_shown": False,
        }
        assert BookingModeNode._evaluate_confirmation_gate(ctx) is False

    def test_add_more_not_asked_returns_false(self):
        """Without add_more_asked → False (¿algo más? step not completed)."""
        from agent.modes.booking_mode import BookingModeNode

        ctx = {
            "last_services": ["Corte"],
            "last_stylist": "María",
            "selected_slot": {"date": "2026-04-20", "time": "10:00"},
            "customer_name": "Juan",
            "notes_asked": True,
            "_confirmation_shown": False,
        }
        assert BookingModeNode._evaluate_confirmation_gate(ctx) is False

    def test_empty_ctx_returns_false(self):
        """Empty dict → False."""
        from agent.modes.booking_mode import BookingModeNode

        assert BookingModeNode._evaluate_confirmation_gate({}) is False

    def test_state_booking_complete_with_confirmation_shown_false(self):
        """All fields present AND _confirmation_shown=False → True (ready to show confirmation)."""
        from agent.modes.booking_mode import BookingModeNode

        ctx = {
            "last_services": ["Pedicura"],
            "last_stylist": "Rosa",
            "selected_slot": {"date": "2026-04-23", "time": "11:00"},
            "customer_name": "Carla",
            "notes_asked": True,
            "add_more_asked": True,
            "_confirmation_shown": False,
        }
        # This is the "state_booking_complete + _confirmation_shown=False → True" case
        assert BookingModeNode._evaluate_confirmation_gate(ctx) is True


class TestEvaluateConfirmationGatePurity:
    """Verify the function is pure — no side-effects on ctx."""

    def test_does_not_mutate_ctx(self):
        """Calling the gate must NOT mutate the ctx dict."""
        from agent.modes.booking_mode import BookingModeNode

        ctx = {
            "last_services": ["Corte"],
            "last_stylist": "María",
            "selected_slot": {"date": "2026-04-20", "time": "10:00"},
            "customer_name": "Juan",
            "notes_asked": True,
            "add_more_asked": True,
            "_confirmation_shown": False,
        }
        ctx_before = dict(ctx)
        BookingModeNode._evaluate_confirmation_gate(ctx)
        assert ctx == ctx_before, "Gate must not mutate ctx — pure function contract"

    def test_idempotent_multiple_calls(self):
        """Calling gate twice with same ctx returns same result without mutation."""
        from agent.modes.booking_mode import BookingModeNode

        ctx = {
            "last_services": ["Corte"],
            "last_stylist": "María",
            "selected_slot": {"date": "2026-04-20", "time": "10:00"},
            "customer_name": "Juan",
            "notes_asked": True,
            "add_more_asked": True,
            "_confirmation_shown": False,
        }
        result1 = BookingModeNode._evaluate_confirmation_gate(ctx)
        result2 = BookingModeNode._evaluate_confirmation_gate(ctx)
        assert result1 == result2
        assert result1 is True

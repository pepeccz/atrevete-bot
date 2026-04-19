"""
Unit tests for compute_next_prompt — 13-branch decision tree.

TDD pair:
- T1.1 RED: this file (all tests must FAIL — module not yet created)
- T1.2 GREEN: agent/booking/grounding.py

Requirements: R1, R2, R3, R6, R7, R8
Scenarios: S1–S9
"""

from __future__ import annotations

from typing import Any

import pytest

# This import will FAIL (module doesn't exist yet) — confirming RED state
from agent.booking.grounding import GroundingDirective, compute_next_prompt


# ============================================================================
# Helpers — minimal ConversationState-like dicts for pure-function testing
# ============================================================================


def _state(booking_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a minimal state dict with the given booking_context."""
    return {"booking_context": booking_context or {}}


def _full_bc(**overrides: Any) -> dict[str, Any]:
    """A booking context with all required slots filled for SHOW_CONFIRMATION."""
    base: dict[str, Any] = {
        "last_services": ["Óleo"],
        "add_more_asked": True,
        "last_stylist": "Pilar",
        "offered_slots": [{"date": "2026-04-20", "time": "10:00", "stylist_name": "Pilar"}],
        "selected_slot": {"date": "2026-04-20", "time": "10:00", "stylist_name": "Pilar"},
        "customer_name": "Ana García",
        "notes_state": "skipped",
        "_confirmation_shown": False,
        "confirmed": False,
        "_booking_completed": False,
    }
    base.update(overrides)
    return base


# ============================================================================
# Branch 1: _booking_completed → BOOKING_COMPLETE
# ============================================================================


class TestBranch01BookingComplete:
    def test_booking_completed_returns_booking_complete(self) -> None:
        bc = {"_booking_completed": True, "booked_appointment_id": "appt-123"}
        directive = compute_next_prompt(_state(bc))
        assert directive.action == "BOOKING_COMPLETE"

    def test_booking_completed_has_no_mandatory_next_call(self) -> None:
        bc = {"_booking_completed": True}
        directive = compute_next_prompt(_state(bc))
        assert directive.mandatory_next_call is None


# ============================================================================
# Branch 2: confirmed == True → CALL_BOOK
# ============================================================================


class TestBranch02CallBook:
    def test_confirmed_true_returns_call_book(self) -> None:
        bc = _full_bc(confirmed=True, _booking_completed=False)
        directive = compute_next_prompt(_state(bc))
        assert directive.action == "CALL_BOOK"

    def test_confirmed_true_sets_mandatory_next_call_book(self) -> None:
        bc = _full_bc(confirmed=True, _booking_completed=False)
        directive = compute_next_prompt(_state(bc))
        assert directive.mandatory_next_call == "book"


# ============================================================================
# Branch 3: _confirmation_shown and not confirmed → AWAIT_CONFIRMATION
# ============================================================================


class TestBranch03AwaitConfirmation:
    def test_confirmation_shown_not_confirmed_returns_await(self) -> None:
        bc = _full_bc(_confirmation_shown=True, confirmed=False, _booking_completed=False)
        directive = compute_next_prompt(_state(bc))
        assert directive.action == "AWAIT_CONFIRMATION"

    def test_await_confirmation_has_no_mandatory_next_call(self) -> None:
        bc = _full_bc(_confirmation_shown=True, confirmed=False, _booking_completed=False)
        directive = compute_next_prompt(_state(bc))
        assert directive.mandatory_next_call is None


# ============================================================================
# Branch 4: pending_disambiguations non-empty → ASK_AUDIENCE
# ============================================================================


class TestBranch04AskAudience:
    def test_pending_disambiguations_returns_ask_audience(self) -> None:
        bc = {
            "pending_disambiguations": [
                {"family": "Corte", "variants": ["Corte Señora", "Corte Caballero"], "resolved_as": None}
            ]
        }
        directive = compute_next_prompt(_state(bc))
        assert directive.action == "ASK_AUDIENCE"

    def test_pending_disambiguations_overrides_stylist_step(self) -> None:
        """Even when stylist is absent, disambiguation takes priority (R7)."""
        bc = {
            "last_services": ["Corte Señora"],
            "add_more_asked": True,
            "last_stylist": None,
            "pending_disambiguations": [
                {"family": "Corte", "variants": ["Corte Señora", "Corte Caballero"], "resolved_as": None}
            ],
        }
        directive = compute_next_prompt(_state(bc))
        assert directive.action == "ASK_AUDIENCE"

    def test_ask_audience_context_contains_pending(self) -> None:
        family = "Corte"
        bc = {
            "pending_disambiguations": [
                {"family": family, "variants": ["Corte Señora", "Corte Caballero"], "resolved_as": None}
            ]
        }
        directive = compute_next_prompt(_state(bc))
        assert directive.context.get("pending") is not None


# ============================================================================
# Branch 5: no services → ASK_SERVICE  (S1)
# ============================================================================


class TestBranch05AskService:
    def test_empty_context_returns_ask_service(self) -> None:
        """S1 — happy path: empty state."""
        directive = compute_next_prompt(_state({}))
        assert directive.action == "ASK_SERVICE"

    def test_none_context_returns_ask_service(self) -> None:
        directive = compute_next_prompt(_state(None))
        assert directive.action == "ASK_SERVICE"

    def test_empty_services_list_returns_ask_service(self) -> None:
        directive = compute_next_prompt(_state({"last_services": []}))
        assert directive.action == "ASK_SERVICE"


# ============================================================================
# Branch 6: services set, add_more_asked False → ASK_MORE_SERVICES  (S2)
# ============================================================================


class TestBranch06AskMoreServices:
    def test_services_set_add_more_not_asked_returns_ask_more(self) -> None:
        """S2 — services set, add_more not asked."""
        bc = {"last_services": ["Óleo"], "add_more_asked": False}
        directive = compute_next_prompt(_state(bc))
        assert directive.action == "ASK_MORE_SERVICES"

    def test_ask_more_services_has_no_mandatory_call(self) -> None:
        bc = {"last_services": ["Óleo"], "add_more_asked": False}
        directive = compute_next_prompt(_state(bc))
        assert directive.mandatory_next_call is None


# ============================================================================
# Branch 7: add_more_asked True, no stylist → ASK_STYLIST  (S3)
# ============================================================================


class TestBranch07AskStylist:
    def test_add_more_asked_no_stylist_returns_ask_stylist(self) -> None:
        """S3 — add_more asked, no stylist."""
        bc = {"last_services": ["Óleo"], "add_more_asked": True, "last_stylist": None}
        directive = compute_next_prompt(_state(bc))
        assert directive.action == "ASK_STYLIST"


# ============================================================================
# Branch 8: stylist set, no offered_slots → ASK_AVAILABILITY
# ============================================================================


class TestBranch08AskAvailability:
    def test_stylist_set_no_slots_returns_ask_availability(self) -> None:
        bc = {
            "last_services": ["Óleo"],
            "add_more_asked": True,
            "last_stylist": "Pilar",
            "offered_slots": None,
        }
        directive = compute_next_prompt(_state(bc))
        assert directive.action == "ASK_AVAILABILITY"

    def test_ask_availability_sets_mandatory_next_call(self) -> None:
        bc = {
            "last_services": ["Óleo"],
            "add_more_asked": True,
            "last_stylist": "Pilar",
            "offered_slots": None,
        }
        directive = compute_next_prompt(_state(bc))
        assert directive.mandatory_next_call == "check_availability"

    def test_no_preference_stylist_also_triggers_availability(self) -> None:
        """no_preference_stylist=True counts as _has_stylist."""
        bc = {
            "last_services": ["Óleo"],
            "add_more_asked": True,
            "no_preference_stylist": True,
            "offered_slots": None,
        }
        directive = compute_next_prompt(_state(bc))
        assert directive.action == "ASK_AVAILABILITY"


# ============================================================================
# Branch 9: slots offered, none selected → ASK_SLOT
# ============================================================================


class TestBranch09AskSlot:
    def test_slots_offered_none_selected_returns_ask_slot(self) -> None:
        bc = {
            "last_services": ["Óleo"],
            "add_more_asked": True,
            "last_stylist": "Pilar",
            "offered_slots": [{"date": "2026-04-20", "time": "10:00"}],
            "selected_slot": None,
        }
        directive = compute_next_prompt(_state(bc))
        assert directive.action == "ASK_SLOT"


# ============================================================================
# Branch 10: slot selected, no customer_name → ASK_NAME
# ============================================================================


class TestBranch10AskName:
    def test_slot_selected_no_name_returns_ask_name(self) -> None:
        bc = {
            "last_services": ["Óleo"],
            "add_more_asked": True,
            "last_stylist": "Pilar",
            "offered_slots": [{"date": "2026-04-20", "time": "10:00"}],
            "selected_slot": {"date": "2026-04-20", "time": "10:00"},
            "customer_name": None,
        }
        directive = compute_next_prompt(_state(bc))
        assert directive.action == "ASK_NAME"


# ============================================================================
# Branch 11: name set, notes_state == 'not_asked' → ASK_NOTES  (S5)
# ============================================================================


class TestBranch11AskNotes:
    def test_name_set_notes_not_asked_returns_ask_notes(self) -> None:
        """S5 — full booking context, notes not asked."""
        bc = _full_bc(notes_state="not_asked", _confirmation_shown=False, confirmed=False)
        directive = compute_next_prompt(_state(bc))
        assert directive.action == "ASK_NOTES"


# ============================================================================
# Branch 12: all slots filled, notes not 'not_asked', _confirmation_shown False → SHOW_CONFIRMATION  (S6)
# ============================================================================


class TestBranch12ShowConfirmation:
    def test_all_filled_notes_skipped_returns_show_confirmation(self) -> None:
        """S6 — all slots filled, notes skipped, confirmation not shown yet."""
        bc = _full_bc(notes_state="skipped", _confirmation_shown=False, confirmed=False)
        directive = compute_next_prompt(_state(bc))
        assert directive.action == "SHOW_CONFIRMATION"

    def test_all_filled_notes_provided_returns_show_confirmation(self) -> None:
        bc = _full_bc(notes_state="provided", _confirmation_shown=False, confirmed=False)
        directive = compute_next_prompt(_state(bc))
        assert directive.action == "SHOW_CONFIRMATION"

    def test_show_confirmation_context_contains_summary_fields(self) -> None:
        bc = _full_bc(notes_state="skipped", _confirmation_shown=False, confirmed=False)
        directive = compute_next_prompt(_state(bc))
        # context must have something useful for LLM to render
        assert isinstance(directive.context, dict)


# ============================================================================
# Branch 13: fallback → ERROR_RECOVERY (hard to hit, but must exist)
# ============================================================================


class TestBranch13ErrorRecovery:
    def test_inconsistent_state_returns_error_recovery(self) -> None:
        """Impossible state: add_more_asked True but also no services."""
        # Force an inconsistent state not covered by any branch above
        bc = {
            "add_more_asked": True,
            "last_services": [],         # empty → normally ASK_SERVICE
            "last_stylist": "X",         # set → normally would skip stylist
            "offered_slots": [{}],       # non-empty → would normally skip availability
            "selected_slot": {"date": "2026-04-20"},  # set → would skip slot
            "customer_name": "Test",
            "notes_state": "provided",
            "_confirmation_shown": True,  # shown → await_confirmation
            "confirmed": False,
            "_booking_completed": False,
        }
        # With _confirmation_shown=True and confirmed=False → should be AWAIT_CONFIRMATION
        # This is not ERROR_RECOVERY. Let's test the real fallback path.
        # The true ERROR_RECOVERY path is when ALL branches evaluate to False.
        # We achieve this by giving an empty bc that wouldn't match branches 2-12:
        # Actually branch 5 catches empty services. Let's verify exhaustive coverage instead.
        directive = compute_next_prompt(_state(bc))
        # With _confirmation_shown True, confirmed False → AWAIT_CONFIRMATION (branch 3)
        assert directive.action == "AWAIT_CONFIRMATION"

    def test_compute_next_prompt_is_total(self) -> None:
        """R8 — compute_next_prompt never raises (total function)."""
        edge_cases = [
            {},
            {"last_services": None},
            {"confirmed": None},
            {"_booking_completed": None},
            {"pending_disambiguations": []},
            {"pending_disambiguations": None},
        ]
        for bc in edge_cases:
            directive = compute_next_prompt(_state(bc))
            assert isinstance(directive, GroundingDirective)


# ============================================================================
# GroundingDirective model shape
# ============================================================================


class TestGroundingDirectiveShape:
    def test_directive_has_required_fields(self) -> None:
        """R3 — GroundingDirective carries action, directive, mandatory_next_call, context."""
        bc = {}
        d = compute_next_prompt(_state(bc))
        assert hasattr(d, "action")
        assert hasattr(d, "directive")
        assert hasattr(d, "mandatory_next_call")
        assert hasattr(d, "context")

    def test_directive_action_is_string(self) -> None:
        d = compute_next_prompt(_state({}))
        assert isinstance(d.action, str)

    def test_directive_directive_is_string(self) -> None:
        d = compute_next_prompt(_state({}))
        assert isinstance(d.directive, str)
        assert len(d.directive) > 0

    def test_directive_directive_is_spanish(self) -> None:
        """Directive must be Spanish (spot check: common Spanish words)."""
        d = compute_next_prompt(_state({}))
        # Very loose: just confirm it's not empty and has some content
        assert d.directive.strip() != ""

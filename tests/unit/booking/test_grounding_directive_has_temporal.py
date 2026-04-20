"""
B.1.2 [RED] — Verify that compute_next_prompt directive.data contains temporal keys.

After Phase B.1, every GroundingInstruction returned by compute_next_prompt() must
contain temporal/environmental keys in directive.data, populated by _common_data(state).

Expected failure on master: KeyError: 'current_datetime' or assertion that value is empty,
because _common_data() has not been added yet.
"""

from __future__ import annotations

import pytest

from agent.booking.grounding import compute_next_prompt

# ---------------------------------------------------------------------------
# Fixtures — one per branch, minimal BookingContext to trigger that branch
# ---------------------------------------------------------------------------


def _state(bc: dict) -> dict:
    """Wrap a BookingContext dict in a minimal ConversationState."""
    return {
        "conversation_id": "test-temporal",
        "booking_context": bc,
        "messages": [],
        "mode_context": {},
        "customer_phone": "+34611223344",
        "conversation_summary": "Resumen de prueba",
        "customer_memories": None,
        "total_message_count": 2,
    }


# One representative state per branch (13 branches in priority order).
BRANCH_STATES = [
    # Branch 1: _booking_completed
    _state({"_booking_completed": True, "booked_appointment_id": "appt-1"}),
    # Branch 2: confirmed = True
    _state({
        "last_services": ["Corte"],
        "last_stylist": "Ana",
        "selected_slot": {"date": "2026-04-25", "time": "10:00"},
        "customer_name": "María",
        "confirmed": True,
    }),
    # Branch 3: _confirmation_shown, not confirmed
    _state({
        "last_services": ["Corte"],
        "last_stylist": "Ana",
        "selected_slot": {"date": "2026-04-25", "time": "10:00"},
        "customer_name": "María",
        "_confirmation_shown": True,
        "confirmed": None,
    }),
    # Branch 4: pending_disambiguations
    _state({
        "pending_disambiguations": [{"family": "Corte", "variants": ["Corte señora", "Corte caballero"]}],
    }),
    # Branch 5: no services, add_more not asked
    _state({}),
    # Branch 6: services set, add_more not asked
    _state({"last_services": ["Corte largo"]}),
    # Branch 7: add_more asked, no stylist
    _state({"last_services": ["Corte largo"], "add_more_asked": True}),
    # Branch 8: stylist set, no offered_slots
    _state({"last_services": ["Corte largo"], "add_more_asked": True, "last_stylist": "Ana"}),
    # Branch 9: slots offered, none selected
    _state({
        "last_services": ["Corte largo"],
        "add_more_asked": True,
        "last_stylist": "Ana",
        "offered_slots": [{"date": "2026-04-25", "time": "10:00", "stylist_name": "Ana"}],
    }),
    # Branch 10: slot selected, no customer name
    _state({
        "last_services": ["Corte largo"],
        "add_more_asked": True,
        "last_stylist": "Ana",
        "offered_slots": [{"date": "2026-04-25", "time": "10:00"}],
        "selected_slot": {"date": "2026-04-25", "time": "10:00"},
    }),
    # Branch 11: name set, notes not asked
    _state({
        "last_services": ["Corte largo"],
        "add_more_asked": True,
        "last_stylist": "Ana",
        "offered_slots": [{"date": "2026-04-25", "time": "10:00"}],
        "selected_slot": {"date": "2026-04-25", "time": "10:00"},
        "customer_name": "María García",
        "notes_state": "not_asked",
    }),
    # Branch 12: all filled, notes done, confirmation not shown
    _state({
        "last_services": ["Corte largo"],
        "add_more_asked": True,
        "last_stylist": "Ana",
        "offered_slots": [{"date": "2026-04-25", "time": "10:00"}],
        "selected_slot": {"date": "2026-04-25", "time": "10:00"},
        "customer_name": "María García",
        "notes_state": "skipped",
        "_confirmation_shown": False,
    }),
    # Branch 13: fallback / ERROR_RECOVERY
    # add_more_asked=True but no services → inconsistent state → ERROR_RECOVERY
    _state({
        "add_more_asked": True,
        "last_services": [],  # empty after being set → inconsistent
    }),
]

EXPECTED_ACTIONS = [
    "BOOKING_COMPLETE",
    "CALL_BOOK",
    "AWAIT_CONFIRMATION",
    "ASK_AUDIENCE",
    "ASK_SERVICE",
    "ASK_MORE_SERVICES",
    "ASK_STYLIST",
    "ASK_AVAILABILITY",
    "ASK_SLOT",
    "ASK_NAME",
    "ASK_NOTES",
    "SHOW_CONFIRMATION",
    "ERROR_RECOVERY",
]


class TestGroundingDirectiveHasTemporalData:
    """For every compute_next_prompt branch, directive.data must contain temporal keys."""

    @pytest.mark.parametrize(
        "state,expected_action",
        list(zip(BRANCH_STATES, EXPECTED_ACTIONS)),
        ids=EXPECTED_ACTIONS,
    )
    def test_directive_data_has_temporal_keys(self, state: dict, expected_action: str):
        """directive.data must contain current_datetime, min_valid_date, tz for all branches.

        RED on master: directive.data does NOT contain these keys because _common_data()
        has not been implemented yet.

        GREEN after B.1.5: _common_data(state) merges temporal keys into every branch.
        """
        directive = compute_next_prompt(state)

        # Verify correct branch was hit
        assert directive.action == expected_action, (
            f"Expected action {expected_action!r} but got {directive.action!r}. "
            f"Check that the branch fixture is correct."
        )

        # The keys that MUST be present after B.1.5
        required_temporal_keys = [
            "current_datetime",
            "min_valid_date",
            "min_valid_date_iso",
            "tz",
        ]

        for key in required_temporal_keys:
            assert key in directive.data, (
                f"Branch {expected_action}: directive.data missing key {key!r}. "
                f"_common_data(state) must be merged into every branch's data dict."
            )
            assert directive.data[key], (
                f"Branch {expected_action}: directive.data[{key!r}] is empty or falsy. "
                f"_common_data(state) must produce a non-empty value."
            )

        # tz must be the canonical Madrid timezone
        assert directive.data["tz"] == "Europe/Madrid", (
            f"Branch {expected_action}: directive.data['tz'] must be 'Europe/Madrid', "
            f"got {directive.data.get('tz')!r}"
        )

"""
Fixtures for agent/booking/ unit tests — Phase 1, task 1.6.

Provides:
- bc_factory: a callable fixture to build arbitrary BookingContext dicts
- 13 per-branch fixtures (bc_branch_1_completed … bc_branch_13_error_recovery)
  that satisfy exactly one branch of compute_next_prompt's decision tree.

REQs covered: REQ-21, REQ-22
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# bc_factory — generic builder fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def bc_factory():
    """
    Build a BookingContext dict with only the keys the test cares about.

    Usage:
        def test_something(bc_factory):
            bc = bc_factory(confirmed=True, last_services=["Corte"])
            ...
    """

    def _build(**overrides) -> dict:
        return {**overrides}

    return _build


# ---------------------------------------------------------------------------
# Per-branch fixtures — one per branch of compute_next_prompt (§3 design doc)
# Priority: first match wins, top-to-bottom (13 branches).
# ---------------------------------------------------------------------------


@pytest.fixture
def bc_branch_1_completed() -> dict:
    """
    Branch 1: _booking_completed=True → BOOKING_COMPLETE
    Condition: booking was already finalized.
    """
    return {
        "_booking_completed": True,
        "booked_appointment_id": "apt-123",
        "confirmed": True,
        "last_services": ["Corte Largo"],
        "last_stylist": "Ana",
        "selected_slot": {"start": "2026-04-21T10:00:00", "end": "2026-04-21T11:00:00"},
        "customer_name": "María García",
        "notes_state": "provided",
        "_confirmation_shown": True,
    }


@pytest.fixture
def bc_branch_2_confirmed() -> dict:
    """
    Branch 2: confirmed=True (and !_booking_completed) → CALL_BOOK
    Condition: user confirmed, all data present, booking not yet created.
    """
    return {
        "_booking_completed": False,
        "confirmed": True,
        "_confirmation_shown": True,
        "last_services": ["Corte Largo"],
        "last_stylist": "Ana",
        "last_stylist_id": "stylist-uuid-001",
        "stylist_id": "stylist-uuid-001",
        "no_preference_stylist": False,
        "selected_slot": {"start": "2026-04-21T10:00:00", "end": "2026-04-21T11:00:00"},
        "customer_name": "María García",
        "customer_first_name": "María",
        "customer_last_name": "García",
        "notes_state": "skipped",
        "add_more_asked": True,
        "offered_slots": [{"start": "2026-04-21T10:00:00"}],
        "pending_disambiguations": [],
    }


@pytest.fixture
def bc_branch_3_await_confirmation() -> dict:
    """
    Branch 3: _confirmation_shown=True and confirmed=False → AWAIT_CONFIRMATION
    Condition: summary was shown, waiting for user's yes/no.
    """
    return {
        "_booking_completed": False,
        "confirmed": False,
        "_confirmation_shown": True,
        "last_services": ["Corte Largo"],
        "last_stylist": "Ana",
        "selected_slot": {"start": "2026-04-21T10:00:00"},
        "customer_name": "María García",
        "notes_state": "skipped",
        "add_more_asked": True,
        "pending_disambiguations": [],
    }


@pytest.fixture
def bc_branch_4_disambig() -> dict:
    """
    Branch 4: pending_disambiguations non-empty → ASK_AUDIENCE
    Condition: service has variants that need audience clarification.
    """
    return {
        "_booking_completed": False,
        "confirmed": False,
        "_confirmation_shown": False,
        "pending_disambiguations": [
            {"family": "Corte", "variants": ["niña", "señora"]}
        ],
        "last_services": ["Corte"],
    }


@pytest.fixture
def bc_branch_5_no_services() -> dict:
    """
    Branch 5: not last_services → ASK_SERVICE
    Condition: no services selected yet.
    """
    return {
        "_booking_completed": False,
        "confirmed": False,
        "_confirmation_shown": False,
        "pending_disambiguations": [],
        "last_services": [],
        "add_more_asked": False,
    }


@pytest.fixture
def bc_branch_6_ask_more() -> dict:
    """
    Branch 6: services present AND not add_more_asked → ASK_MORE_SERVICES
    Condition: services registered but add-more question not yet asked.
    """
    return {
        "_booking_completed": False,
        "confirmed": False,
        "_confirmation_shown": False,
        "pending_disambiguations": [],
        "last_services": ["Corte Largo"],
        "add_more_asked": False,
    }


@pytest.fixture
def bc_branch_7_ask_stylist() -> dict:
    """
    Branch 7: add_more_asked=True AND no stylist → ASK_STYLIST
    Condition: services closed, stylist not yet chosen.
    """
    return {
        "_booking_completed": False,
        "confirmed": False,
        "_confirmation_shown": False,
        "pending_disambiguations": [],
        "last_services": ["Corte Largo"],
        "add_more_asked": True,
        "last_stylist": None,
        "no_preference_stylist": False,
        "stylist_id": None,
    }


@pytest.fixture
def bc_branch_8_ask_availability() -> dict:
    """
    Branch 8: stylist present AND not offered_slots → ASK_AVAILABILITY
    Condition: stylist selected, availability not yet checked.
    """
    return {
        "_booking_completed": False,
        "confirmed": False,
        "_confirmation_shown": False,
        "pending_disambiguations": [],
        "last_services": ["Corte Largo"],
        "add_more_asked": True,
        "last_stylist": "Ana",
        "no_preference_stylist": False,
        "stylist_id": "stylist-uuid-001",
        "offered_slots": None,
        "available_slots": [],
    }


@pytest.fixture
def bc_branch_9_ask_slot() -> dict:
    """
    Branch 9: offered_slots present AND not selected_slot → ASK_SLOT
    Condition: slots shown, user hasn't picked one.
    """
    return {
        "_booking_completed": False,
        "confirmed": False,
        "_confirmation_shown": False,
        "pending_disambiguations": [],
        "last_services": ["Corte Largo"],
        "add_more_asked": True,
        "last_stylist": "Ana",
        "stylist_id": "stylist-uuid-001",
        "offered_slots": [
            {"start": "2026-04-21T10:00:00"},
            {"start": "2026-04-21T11:00:00"},
        ],
        "selected_slot": None,
    }


@pytest.fixture
def bc_branch_10_ask_name() -> dict:
    """
    Branch 10: selected_slot present AND not customer_name → ASK_NAME
    Condition: slot chosen, name not yet collected.
    """
    return {
        "_booking_completed": False,
        "confirmed": False,
        "_confirmation_shown": False,
        "pending_disambiguations": [],
        "last_services": ["Corte Largo"],
        "add_more_asked": True,
        "last_stylist": "Ana",
        "stylist_id": "stylist-uuid-001",
        "offered_slots": [{"start": "2026-04-21T10:00:00"}],
        "selected_slot": {"start": "2026-04-21T10:00:00"},
        "customer_name": None,
    }


@pytest.fixture
def bc_branch_11_ask_notes() -> dict:
    """
    Branch 11: name present AND notes_state == 'not_asked' → ASK_NOTES
    Condition: name collected, notes question not yet offered.
    """
    return {
        "_booking_completed": False,
        "confirmed": False,
        "_confirmation_shown": False,
        "pending_disambiguations": [],
        "last_services": ["Corte Largo"],
        "add_more_asked": True,
        "last_stylist": "Ana",
        "stylist_id": "stylist-uuid-001",
        "offered_slots": [{"start": "2026-04-21T10:00:00"}],
        "selected_slot": {"start": "2026-04-21T10:00:00"},
        "customer_name": "María García",
        "notes_state": "not_asked",
    }


@pytest.fixture
def bc_branch_12_show_confirmation() -> dict:
    """
    Branch 12: all data present AND notes_state != 'not_asked' AND not _confirmation_shown → SHOW_CONFIRMATION
    Condition: booking complete data, notes resolved, summary not yet shown.
    """
    return {
        "_booking_completed": False,
        "confirmed": False,
        "_confirmation_shown": False,
        "pending_disambiguations": [],
        "last_services": ["Corte Largo"],
        "add_more_asked": True,
        "last_stylist": "Ana",
        "stylist_id": "stylist-uuid-001",
        "offered_slots": [{"start": "2026-04-21T10:00:00"}],
        "selected_slot": {"start": "2026-04-21T10:00:00"},
        "customer_name": "María García",
        "notes_state": "skipped",
    }


@pytest.fixture
def bc_branch_13_error_recovery() -> dict:
    """
    Branch 13: fallback — no branch matched → ERROR_RECOVERY
    Condition: inconsistent state that matches none of the other branches.
    This fixture intentionally represents an edge-case/inconsistent state.
    """
    return {
        "_booking_completed": False,
        "confirmed": False,
        "_confirmation_shown": False,
        "pending_disambiguations": [],
        # Inconsistent: add_more_asked=True but also selected_slot=None with no stylist and no services
        # This forces the fallback ERROR_RECOVERY branch.
        "last_services": [],
        "add_more_asked": True,
        "last_stylist": None,
        "stylist_id": None,
        "no_preference_stylist": False,
        "offered_slots": None,
        "selected_slot": None,
        "customer_name": None,
        "notes_state": "not_asked",
    }

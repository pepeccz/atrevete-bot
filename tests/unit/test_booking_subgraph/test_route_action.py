"""
test_route_action.py — Truth-table tests for route_action (Phase 3 RED).

13 branches, each verified with a minimal booking_context fixture.
route_action is a pure sync function; no I/O, no mocking needed.

Branch priority order (matches compute_next_prompt):
 1. _booking_completed=True            → booking_complete
 2. confirmed=True                     → execute_book
 3. _confirmation_shown & !confirmed   → await_confirmation
 4. pending_disambiguations            → ask_audience
 5. no services & !add_more_asked      → ask_service
 6. services & !add_more_asked         → ask_more_services
 7. add_more_asked & !stylist          → ask_stylist
 8. stylist & !offered_slots           → fetch_availability
 9. offered_slots & !selected_slot     → ask_slot
10. selected_slot & !customer_name     → ask_name
11. customer_name & notes_state=not_asked → ask_notes
12. booking_complete & notes done & !confirmation_shown → show_confirmation
13. fallback / inconsistent state      → error_recovery
"""

from __future__ import annotations

from langgraph.types import Command

from agent.booking.nodes.route_action import route_action

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(bc: dict) -> dict:
    """Wrap booking_context in a minimal ConversationState-like dict."""
    return {"booking_context": bc}


def _goto(state: dict) -> str:
    """Run route_action and return the destination node label."""
    cmd = route_action(state)
    assert isinstance(cmd, Command), f"Expected Command, got {type(cmd)}"
    return cmd.goto


# ---------------------------------------------------------------------------
# Base fixtures — building blocks for truth-table rows
# ---------------------------------------------------------------------------

_SERVICES = ["Cortar Señora"]
_STYLIST = "Ana"
_SLOT = {"date": "miércoles 30", "time": "10:00", "stylist_name": "Ana"}
_SLOTS = [_SLOT]


def _bc_empty() -> dict:
    return {}


def _bc_services_only() -> dict:
    return {"last_services": _SERVICES}


def _bc_add_more_asked() -> dict:
    return {"last_services": _SERVICES, "add_more_asked": True}


def _bc_with_stylist() -> dict:
    return {"last_services": _SERVICES, "add_more_asked": True, "last_stylist": _STYLIST}


def _bc_with_slots() -> dict:
    return {**_bc_with_stylist(), "offered_slots": _SLOTS}


def _bc_slot_selected() -> dict:
    return {**_bc_with_slots(), "selected_slot": _SLOT}


def _bc_with_name() -> dict:
    return {**_bc_slot_selected(), "customer_name": "María García"}


def _bc_notes_done() -> dict:
    return {**_bc_with_name(), "notes_state": "skipped"}


def _bc_all_resolved() -> dict:
    """Full booking_context with all fields set but confirmation not shown yet."""
    return {
        **_bc_notes_done(),
        "_confirmation_shown": False,
    }


def _bc_confirmation_shown() -> dict:
    return {**_bc_all_resolved(), "_confirmation_shown": True}


def _bc_confirmed() -> dict:
    return {**_bc_confirmation_shown(), "confirmed": True}


def _bc_booking_completed() -> dict:
    return {**_bc_confirmed(), "_booking_completed": True}


# ---------------------------------------------------------------------------
# Branch 1: _booking_completed=True → booking_complete
# ---------------------------------------------------------------------------


def test_branch_1_booking_completed():
    assert _goto(_state(_bc_booking_completed())) == "booking_complete"


# ---------------------------------------------------------------------------
# Branch 2: confirmed=True → execute_book
# ---------------------------------------------------------------------------


def test_branch_2_confirmed_true():
    assert _goto(_state(_bc_confirmed())) == "execute_book"


# ---------------------------------------------------------------------------
# Branch 3: _confirmation_shown & confirmed is None → await_confirmation
# ---------------------------------------------------------------------------


def test_branch_3_await_confirmation():
    bc = _bc_confirmation_shown()
    bc.pop("confirmed", None)  # ensure confirmed is absent / None
    assert _goto(_state(bc)) == "await_confirmation"


def test_branch_3_confirmed_none_explicit():
    bc = {**_bc_all_resolved(), "_confirmation_shown": True, "confirmed": None}
    assert _goto(_state(bc)) == "await_confirmation"


# ---------------------------------------------------------------------------
# Branch 4: pending_disambiguations → ask_audience
# ---------------------------------------------------------------------------


def test_branch_4_pending_disambiguations():
    bc = {
        "last_services": _SERVICES,
        "pending_disambiguations": [{"family": "Cortar", "options": ["Señora", "Caballero"]}],
    }
    assert _goto(_state(bc)) == "ask_audience"


def test_branch_4_empty_pending_does_not_trigger():
    """empty list must NOT trigger ask_audience."""
    bc = {**_bc_add_more_asked(), "pending_disambiguations": []}
    # No stylist yet → should go to ask_stylist, not ask_audience
    assert _goto(_state(bc)) == "ask_stylist"


# ---------------------------------------------------------------------------
# Branch 5: no services & !add_more_asked → ask_service
# ---------------------------------------------------------------------------


def test_branch_5_no_services():
    assert _goto(_state(_bc_empty())) == "ask_service"


def test_branch_5_no_services_add_more_not_asked():
    assert _goto(_state({"last_services": [], "add_more_asked": False})) == "ask_service"


# ---------------------------------------------------------------------------
# Branch 6: services & !add_more_asked → ask_more_services
# ---------------------------------------------------------------------------


def test_branch_6_ask_more_services():
    assert _goto(_state(_bc_services_only())) == "ask_more_services"


# ---------------------------------------------------------------------------
# Branch 7: add_more_asked & no stylist → ask_stylist
# ---------------------------------------------------------------------------


def test_branch_7_ask_stylist():
    assert _goto(_state(_bc_add_more_asked())) == "ask_stylist"


def test_branch_7_no_preference_stylist_counts():
    """no_preference_stylist=True satisfies stylist requirement → should NOT goto ask_stylist."""
    bc = {**_bc_add_more_asked(), "no_preference_stylist": True}
    # stylist satisfied → should proceed to fetch_availability (no offered_slots yet)
    assert _goto(_state(bc)) == "fetch_availability"


# ---------------------------------------------------------------------------
# Branch 8: stylist & !offered_slots → fetch_availability
# ---------------------------------------------------------------------------


def test_branch_8_fetch_availability():
    assert _goto(_state(_bc_with_stylist())) == "fetch_availability"


def test_branch_8_last_stylist_empty_string_means_no_stylist():
    """Empty string should not count as a valid stylist."""
    bc = {**_bc_add_more_asked(), "last_stylist": ""}
    assert _goto(_state(bc)) == "ask_stylist"


# ---------------------------------------------------------------------------
# Branch 9: offered_slots & !selected_slot → ask_slot
# ---------------------------------------------------------------------------


def test_branch_9_ask_slot():
    assert _goto(_state(_bc_with_slots())) == "ask_slot"


# ---------------------------------------------------------------------------
# Branch 10: selected_slot & !customer_name → ask_name
# ---------------------------------------------------------------------------


def test_branch_10_ask_name():
    assert _goto(_state(_bc_slot_selected())) == "ask_name"


# ---------------------------------------------------------------------------
# Branch 11: customer_name & notes_state=not_asked → ask_notes
# ---------------------------------------------------------------------------


def test_branch_11_ask_notes():
    bc = _bc_with_name()  # notes_state defaults to "not_asked"
    assert _goto(_state(bc)) == "ask_notes"


def test_branch_11_notes_state_absent_means_not_asked():
    """Absent notes_state is equivalent to 'not_asked'."""
    bc = dict(_bc_with_name())
    bc.pop("notes_state", None)
    assert _goto(_state(bc)) == "ask_notes"


# ---------------------------------------------------------------------------
# Branch 12: all resolved, notes done, !_confirmation_shown → show_confirmation
# ---------------------------------------------------------------------------


def test_branch_12_show_confirmation():
    assert _goto(_state(_bc_all_resolved())) == "show_confirmation"


def test_branch_12_notes_skipped_counts_as_done():
    bc = {**_bc_notes_done()}
    assert _goto(_state(bc)) == "show_confirmation"


def test_branch_12_notes_provided_counts_as_done():
    bc = {**_bc_with_name(), "notes_state": "provided", "notes": "sin gluten"}
    assert _goto(_state(bc)) == "show_confirmation"


# ---------------------------------------------------------------------------
# Branch 13: fallback / error_recovery
# ---------------------------------------------------------------------------


def test_branch_13_empty_state_after_all_guards():
    """add_more_asked=True but no services is inconsistent → error_recovery."""
    bc = {"add_more_asked": True, "last_services": []}
    assert _goto(_state(bc)) == "error_recovery"


def test_branch_13_no_state_key():
    """No booking_context key at all → error_recovery (treat as empty)."""
    assert _goto({}) == "ask_service"  # empty bc → branch 5


def test_branch_13_confirmed_false_after_confirmation_clears_flow():
    """confirmed=False (user rejected) → error_recovery to restart."""
    bc = {**_bc_confirmation_shown(), "confirmed": False}
    assert _goto(_state(bc)) == "error_recovery"


# ---------------------------------------------------------------------------
# Phase 7 — CHANGE_DATE branch (R4.3)
# ---------------------------------------------------------------------------


def test_change_date_forces_fetch_availability_over_ask_slot():
    """user_action=CHANGE_DATE with offered_slots still present → fetch_availability (not ask_slot).

    This tests that route_action explicitly re-routes to fetch_availability when
    CHANGE_DATE is detected, even if offered_slots is non-empty (stale from prior fetch).
    The reconciler normally clears offered_slots on date change, but even before that clears,
    route_action should prefer fetch_availability when CHANGE_DATE signal is present.
    """
    # bc has offered_slots present (stale) — without CHANGE_DATE this would go to ask_slot
    bc = {
        **_bc_with_stylist(),
        "offered_slots": _SLOTS,   # stale offered_slots
        "date_hint": "2026-04-25",
    }
    state = {**_state(bc), "user_action": "CHANGE_DATE"}
    assert _goto(state) == "fetch_availability"


def test_change_date_without_stylist_routes_ask_stylist():
    """user_action=CHANGE_DATE but no stylist yet → ask_stylist (normal flow)."""
    bc = {"last_services": _SERVICES, "add_more_asked": True, "date_hint": "2026-04-25"}
    state = {**_state(bc), "user_action": "CHANGE_DATE"}
    # No stylist → branch 7 (ask_stylist) wins before CHANGE_DATE special casing
    assert _goto(state) == "ask_stylist"

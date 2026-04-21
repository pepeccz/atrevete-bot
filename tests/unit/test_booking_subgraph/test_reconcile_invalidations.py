"""
Phase 4 — reconcile_invalidations tests (R2.1–R2.7).

Each INVALIDATION_TABLE row is tested. Additive cascade (date+stylist same turn).
Name/notes change → no cascade.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reconcile(old_bc: dict, new_bc: dict) -> dict:
    from agent.booking.invalidation import reconcile

    return reconcile(old_bc, new_bc)


# ---------------------------------------------------------------------------
# R2.1 — date_hint changes → clears offered_slots + selected_slot
# ---------------------------------------------------------------------------


def test_date_hint_change_clears_offered_slots():
    old = {"date_hint": "2026-04-20", "offered_slots": [{"time": "10:00"}], "selected_slot": {"time": "10:00"}}
    new = dict(old) | {"date_hint": "2026-04-25"}  # changed
    result = _reconcile(old, new)
    assert result.get("offered_slots") is None or result["offered_slots"] == []


def test_date_hint_change_clears_selected_slot():
    old = {"date_hint": "2026-04-20", "selected_slot": {"time": "10:00"}}
    new = dict(old) | {"date_hint": "2026-04-25"}
    result = _reconcile(old, new)
    assert "selected_slot" not in result or result["selected_slot"] is None


# ---------------------------------------------------------------------------
# R2.2 — last_stylist changes → clears offered_slots + selected_slot
# ---------------------------------------------------------------------------


def test_stylist_change_clears_offered_slots():
    old = {"last_stylist": "Ana", "offered_slots": [{"time": "10:00"}]}
    new = dict(old) | {"last_stylist": "Laura"}
    result = _reconcile(old, new)
    assert "offered_slots" not in result


def test_stylist_change_clears_selected_slot():
    old = {"last_stylist": "Ana", "selected_slot": {"time": "10:00"}}
    new = dict(old) | {"last_stylist": "Laura"}
    result = _reconcile(old, new)
    assert "selected_slot" not in result


# ---------------------------------------------------------------------------
# R2.3 — last_services changes → clears duration_min, offered_stylists, offered_slots, selected_slot
# ---------------------------------------------------------------------------


def test_service_change_clears_downstream():
    old = {
        "last_services": ["Corte Señora"],
        "duration_min": 45,
        "offered_stylists": ["Ana"],
        "offered_slots": [{"time": "10:00"}],
        "selected_slot": {"time": "10:00"},
    }
    new = dict(old) | {"last_services": ["Mechas"]}
    result = _reconcile(old, new)
    for key in ("duration_min", "offered_stylists", "offered_slots", "selected_slot"):
        assert key not in result, f"{key} should be cleared"


# ---------------------------------------------------------------------------
# R2.4 — service_audience_hint changes → clears pending_disambiguations
# ---------------------------------------------------------------------------


def test_audience_change_clears_pending_disambiguations():
    old = {"service_audience_hint": "MALE", "pending_disambiguations": [{"service": "Corte"}]}
    new = dict(old) | {"service_audience_hint": "FEMALE"}
    result = _reconcile(old, new)
    assert "pending_disambiguations" not in result


# ---------------------------------------------------------------------------
# R2.5 — customer_name or notes_state changes → NO cascade
# ---------------------------------------------------------------------------


def test_customer_name_change_no_cascade():
    old = {
        "customer_name": None,
        "offered_slots": [{"time": "10:00"}],
        "selected_slot": {"time": "10:00"},
    }
    new = dict(old) | {"customer_name": "María"}
    result = _reconcile(old, new)
    assert result.get("offered_slots") is not None
    assert result.get("selected_slot") is not None


def test_notes_state_change_no_cascade():
    old = {"notes_state": "not_asked", "offered_slots": [{"time": "10:00"}]}
    new = dict(old) | {"notes_state": "skipped"}
    result = _reconcile(old, new)
    assert result.get("offered_slots") is not None


# ---------------------------------------------------------------------------
# R2.6 — additive cascade: date + stylist change same turn
# ---------------------------------------------------------------------------


def test_additive_cascade_date_and_stylist():
    old = {
        "date_hint": "2026-04-20",
        "last_stylist": "Ana",
        "offered_slots": [{"time": "10:00"}],
        "selected_slot": {"time": "10:00"},
    }
    new = dict(old) | {"date_hint": "2026-04-25", "last_stylist": "Laura"}
    result = _reconcile(old, new)
    # Both cascades must apply
    assert "offered_slots" not in result
    assert "selected_slot" not in result


# ---------------------------------------------------------------------------
# No cascade when value unchanged
# ---------------------------------------------------------------------------


def test_unchanged_date_hint_no_cascade():
    old = {"date_hint": "2026-04-20", "offered_slots": [{"time": "10:00"}]}
    new = dict(old)  # no change
    result = _reconcile(old, new)
    assert result.get("offered_slots") is not None

"""
Booking invalidation table and reconciler.

When an upstream slot changes, dependent downstream slots must be cleared
to prevent stale state from mis-routing (spec R2.1–R2.7).

Design ref: design §Interfaces/Invalidation table.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# INVALIDATION_TABLE
# ---------------------------------------------------------------------------
# Maps each "upstream" field to the list of downstream fields that must be
# cleared when that upstream field changes value.

INVALIDATION_TABLE: dict[str, list[str]] = {
    "date_hint": ["offered_slots", "selected_slot"],
    "last_stylist": ["offered_slots", "selected_slot"],
    "last_services": ["duration_min", "offered_stylists", "offered_slots", "selected_slot"],
    "service_audience_hint": ["pending_disambiguations"],
}


def reconcile(old_bc: dict[str, Any], new_bc: dict[str, Any]) -> dict[str, Any]:
    """Apply invalidation cascades when upstream slots change.

    Computes the diff between old_bc and new_bc, then for each key that
    changed and appears in INVALIDATION_TABLE, clears the dependent slots
    in new_bc. Cascades are additive — if two upstream slots change in the
    same turn, both cascades apply (union of cleared slots).

    Args:
        old_bc: booking_context BEFORE the current resolver patch.
        new_bc: booking_context AFTER the resolver patch is applied.

    Returns:
        new_bc with invalidated downstream fields removed/cleared.
    """
    # P1 stub: no-op — returns new_bc unchanged.
    # P4 will replace this with real invalidation logic.
    return new_bc

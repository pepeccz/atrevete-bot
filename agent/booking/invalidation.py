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
    # Collect all downstream fields to clear (union of all cascades)
    to_clear: set[str] = set()

    for upstream_key, downstream_keys in INVALIDATION_TABLE.items():
        old_val = old_bc.get(upstream_key)
        new_val = new_bc.get(upstream_key)
        # Only cascade when the value actually changed
        if old_val != new_val and new_val is not None:
            to_clear.update(downstream_keys)

    if not to_clear:
        return new_bc

    # Apply cascades — remove cleared keys from result
    result = dict(new_bc)
    for key in to_clear:
        result.pop(key, None)

    return result

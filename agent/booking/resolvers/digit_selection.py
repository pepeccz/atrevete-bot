"""
digit_selection resolver — select offered slot by bare digit.

Guard: selected_slot already set → no-op.
Guard: offered_slots empty → no-op.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.booking.resolvers import ResolverResult

logger = logging.getLogger(__name__)


def resolve(user_text: str, bc: dict[str, Any], state: dict[str, Any]) -> ResolverResult | None:
    """Map bare digit to offered_slots[digit-1].

    Returns ResolverResult with:
        patch: {"selected_slot": slot, "last_stylist": stylist_name (if not already set)}
        user_action: "PROVIDE_FIELD"
    or None if guard conditions fail.
    """
    if bc.get("selected_slot"):
        return None

    offered_slots: list[dict[str, Any]] = bc.get("offered_slots") or []
    if not offered_slots:
        return None

    stripped = user_text.strip()
    try:
        digit = int(stripped)
    except (ValueError, TypeError):
        return None

    if not (1 <= digit <= len(offered_slots)):
        return None

    slot = offered_slots[digit - 1]
    patch: dict[str, Any] = {"selected_slot": slot}

    if not bc.get("last_stylist") and slot.get("stylist_name"):
        patch["last_stylist"] = slot["stylist_name"]

    logger.info(
        "resolver.digit_selection.applied | digit=%s | slot_time=%s",
        digit,
        slot.get("start_time", "?"),
    )

    return {
        "patch": patch,
        "matched": True,
        "user_action": "PROVIDE_FIELD",
    }

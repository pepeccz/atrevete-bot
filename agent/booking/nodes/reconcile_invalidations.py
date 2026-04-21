"""
reconcile_invalidations — Apply resolver patch + invalidation cascade.

Reads booking_context_patch from state (set by interpret_user_update),
applies it to booking_context, then runs the invalidation reconciler to
clear downstream stale slots.

Design ref: design §D1, spec R2.1–R2.7, R4.2.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def reconcile_invalidations(state: dict[str, Any]) -> dict[str, Any]:
    """Apply patch from interpret_user_update + run invalidation cascade.

    Returns:
        {"booking_context": <updated_dict>}
    """
    from agent.booking.invalidation import reconcile

    old_bc: dict[str, Any] = dict(state.get("booking_context") or {})
    patch_envelope: dict[str, Any] = state.get("booking_context_patch") or {}

    patch = patch_envelope.get("patch") or {}
    cleared = patch_envelope.get("cleared") or []

    # Apply patch
    new_bc = dict(old_bc)
    new_bc.update(patch)
    for key in cleared:
        new_bc.pop(key, None)

    # Apply invalidation cascade (P1: no-op stub; P4 activates real logic)
    new_bc = reconcile(old_bc, new_bc)

    logger.info(
        "reconcile_invalidations | patched_keys=%s | cleared=%s",
        sorted(patch.keys()),
        cleared,
    )

    return {"booking_context": new_bc}

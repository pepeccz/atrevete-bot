"""
customer_prefill resolver — read-only pre-fill from state.

Injects _suggested_customer_name and customer_id from state into booking_context.
Does NOT write customer_name — that requires explicit user confirmation.

Guard: both _suggested_customer_name and customer_id already set → no-op.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.booking.resolvers import ResolverResult

logger = logging.getLogger(__name__)


def resolve(user_text: str, bc: dict[str, Any], state: dict[str, Any]) -> ResolverResult | None:
    """Pre-fill _suggested_customer_name and customer_id from state.

    Returns ResolverResult or None if nothing to fill.
    """
    from agent.booking.patch_pipeline import resolve_customer_from_state

    result = resolve_customer_from_state(state, bc)
    if result is None or not result.get("matched"):
        return None

    patch = result.get("patch") or {}
    if not patch:
        return None

    logger.info("resolver.customer_prefill.applied | keys=%s", sorted(patch.keys()))
    return {
        "patch": patch,
        "matched": True,
        "user_action": None,
    }

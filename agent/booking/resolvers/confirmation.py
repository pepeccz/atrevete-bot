"""
confirmation resolver — detect affirmation/negation of booking summary.

Guard: _confirmation_shown must be True.
Guard: confirmed must not already be set (idempotent).
"""

from __future__ import annotations

import logging
from typing import Any

from agent.booking.resolvers import ResolverResult

logger = logging.getLogger(__name__)


def resolve(user_text: str, bc: dict[str, Any], state: dict[str, Any]) -> ResolverResult | None:
    """Resolve confirmation/rejection of the booking summary.

    Returns ResolverResult with:
        patch: {"confirmed": True|False} (and {"_confirmation_shown": False} on negation)
        user_action: "AFFIRM" | "NEGATE"
    or None if guard conditions fail.
    """
    if not bc.get("_confirmation_shown"):
        return None
    if bc.get("confirmed") is not None:
        return None

    # Direct booking negations (bare "no", "cancelar", etc.) that is_negation() may miss
    _DIRECT_NEGATION = frozenset(
        ["no", "nop", "nope", "nel", "na", "nah", "cancelar", "cancel",
         "no quiero", "mejor no", "prefiero no", "no confirmo", "no gracias"]
    )

    from infra.resolvers.affirmation import is_affirmation
    from infra.resolvers.negation import is_negation

    if is_affirmation(user_text):
        logger.info("resolver.confirmation.affirm")
        return {
            "patch": {"confirmed": True},
            "matched": True,
            "user_action": "AFFIRM",
        }

    matched, canonical, distance = is_negation(user_text)
    normalized = user_text.strip().lower()
    if matched or normalized in _DIRECT_NEGATION:
        logger.info(
            "resolver.confirmation.negate | canonical=%s | distance=%s",
            canonical,
            distance,
        )
        return {
            "patch": {"confirmed": False, "_confirmation_shown": False},
            "matched": True,
            "user_action": "NEGATE",
        }

    return None

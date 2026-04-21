"""
add_more resolver — detect negation of "¿algo más?" question.

R1.8: fires only when _last_leaf == "ask_more_services".
Wraps existing infra/resolvers/negation.is_negation.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.booking.resolvers import ResolverResult

logger = logging.getLogger(__name__)


def resolve(user_text: str, bc: dict[str, Any], state: dict[str, Any]) -> ResolverResult | None:
    """Detect negation of 'algo más?' — guard: only at ask_more_services step.

    Returns:
        patch: {"add_more_asked": True}
        user_action: "NEGATE"
    or None if guard fails or not a negation.
    """
    # Context guard
    if bc.get("_last_leaf") != "ask_more_services":
        return None

    # Idempotent
    if bc.get("add_more_asked"):
        return None

    from infra.resolvers.negation import is_negation

    matched, canonical, distance = is_negation(user_text)
    if not matched:
        return None

    logger.info(
        "resolver.add_more.negation | canonical=%s | distance=%s",
        canonical,
        distance,
    )
    return {
        "patch": {"add_more_asked": True},
        "matched": True,
        "user_action": "NEGATE",
    }

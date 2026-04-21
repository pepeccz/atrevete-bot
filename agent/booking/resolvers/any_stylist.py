"""
any_stylist resolver — detect "no-preference" sentiment → ANY_AVAILABLE sentinel.

Guard: last_stylist or no_preference_stylist already set → no-op.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from agent.booking.resolvers import ResolverResult

logger = logging.getLogger(__name__)

_ANY_STYLIST_PATTERNS = re.compile(
    r"cualquier(?:[ae]|\b)|"
    r"la\s+primera?\s+(?:con\s+)?disponibilidad|"
    r"quien\s+(?:sea|tenga\s+disponibilidad)|"
    r"la\s+que\s+(?:pueda|est[eé]\s+libre)|"
    r"no\s+(?:me\s+)?importa|"
    r"me\s+da\s+igual|"
    r"da\s+lo\s+mismo",
    re.IGNORECASE,
)


def resolve(user_text: str, bc: dict[str, Any], state: dict[str, Any]) -> ResolverResult | None:
    """Detect "cualquiera/me da igual" patterns → ANY_AVAILABLE sentinel.

    Returns:
        patch: {"last_stylist": ANY_AVAILABLE, "no_preference_stylist": True}
        user_action: "PROVIDE_FIELD"
    or None if guard conditions fail.
    """
    if bc.get("last_stylist") or bc.get("no_preference_stylist"):
        return None

    if not _ANY_STYLIST_PATTERNS.search(user_text):
        return None

    from agent.booking.nodes.resolve_pre_turn import ANY_AVAILABLE

    logger.info("resolver.any_stylist.applied")
    return {
        "patch": {"last_stylist": ANY_AVAILABLE, "no_preference_stylist": True},
        "matched": True,
        "user_action": "PROVIDE_FIELD",
    }

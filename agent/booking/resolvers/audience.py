"""
audience resolver — map señora/caballero/niño → service_audience_hint.

R1.2: maps señora/dama/mujer → FEMALE, caballero/hombre/varón → MALE,
niño/nena/bebé → CHILD; clears pending_disambiguations on match.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from agent.booking.resolvers import ResolverResult

logger = logging.getLogger(__name__)

_FEMALE_PATTERN = re.compile(
    r"\b(?:señora|dama|mujer|femenin[ao]|para\s+(?:una?\s+)?(?:mujer|dama|señora))\b",
    re.IGNORECASE,
)
_MALE_PATTERN = re.compile(
    r"\b(?:caballero|hombre|var[oó]n|masculin[ao]|para\s+(?:un?\s+)?(?:hombre|caballero))\b",
    re.IGNORECASE,
)
_CHILD_PATTERN = re.compile(
    r"\b(?:ni[ñn][oa]|nena?|beb[eé]|infantil|para\s+(?:un?\s+)?(?:ni[ñn][oa]|nena?|beb[eé]))\b",
    re.IGNORECASE,
)


def resolve(user_text: str, bc: dict[str, Any], state: dict[str, Any]) -> ResolverResult | None:
    """Map audience keyword to FEMALE/MALE/CHILD hint.

    Returns:
        patch: {"service_audience_hint": "FEMALE"|"MALE"|"CHILD"}
        cleared: ["pending_disambiguations"]
        user_action: "PROVIDE_FIELD"
    or None if no keyword matched.
    """
    if _FEMALE_PATTERN.search(user_text):
        audience = "FEMALE"
    elif _MALE_PATTERN.search(user_text):
        audience = "MALE"
    elif _CHILD_PATTERN.search(user_text):
        audience = "CHILD"
    else:
        return None

    logger.info("resolver.audience.applied | audience=%s", audience)

    cleared: list[str] = []
    if bc.get("pending_disambiguations"):
        cleared.append("pending_disambiguations")

    return {
        "patch": {"service_audience_hint": audience},
        "cleared": cleared,
        "matched": True,
        "user_action": "PROVIDE_FIELD",
    }

"""Negation resolver — Task 4.4.

Wraps the existing infra.resolvers.negation library with booking-specific
extensions for phrases that aren't in the base canonical set.
Returns {"negation": True} routing signal on match, None on miss.
"""

from __future__ import annotations

from typing import Any

from infra.resolvers._shared import normalize_text
from infra.resolvers.negation import is_negation

# Additional negation phrases specific to the booking flow context.
# These extend (not replace) the infra library's canonical set.
_BOOKING_NEGATIONS: frozenset[str] = frozenset(
    [
        "no",  # bare "no" — excluded from base library to avoid false positives
        # in other contexts, but valid as a booking-flow negation
        "solo eso",  # "solo eso" — not in base library
        "ninguno",  # masculine form — base library has "ninguna" only
        "ninguno mas",
        "ninguna mas",
    ]
)


async def resolve_negation(text: str, state: Any) -> dict[str, Any] | None:
    """Return {"negation": True} if text is a negation of '¿algo más?', else None."""
    # First: try the infra library
    matched, _canonical, _dist = is_negation(text)
    if matched:
        return {"negation": True}

    # Second: check booking-specific extensions
    normalized = normalize_text(text)
    if normalized in _BOOKING_NEGATIONS:
        return {"negation": True}

    return None

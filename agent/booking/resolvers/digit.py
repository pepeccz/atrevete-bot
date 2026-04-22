"""Digit resolver — Task 4.3.

Maps ordinal / numeric / pronoun phrases to a slot index in offered_slots.
"""

from __future__ import annotations

import unicodedata
from typing import Any


def _normalize(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    stripped = "".join(
        ch for ch in nfkd if not unicodedata.combining(ch) and (ch.isascii() or ch == " ")
    )
    return stripped.lower().strip()


# Patterns that map to a specific 0-based index
_INDEX_PATTERNS: list[tuple[list[str], int]] = [
    (["la 1", "el 1", "1", "uno", "una", "primera", "primero", "el primero", "la primera"], 0),
    (["la 2", "el 2", "2", "dos", "segunda", "segundo", "el segundo", "la segunda"], 1),
    (["la 3", "el 3", "3", "tres", "tercera", "tercero", "el tercero", "la tercera"], 2),
    (["la 4", "el 4", "4", "cuatro", "cuarta", "cuarto"], 3),
    (["la 5", "el 5", "5", "cinco", "quinta", "quinto"], 4),
]

# Pronouns meaning "the last offered one"
_LAST_PATTERNS = ["esa", "esta", "esta misma", "ese", "ese mismo"]


async def resolve_digit(text: str, state: Any) -> dict[str, Any] | None:
    """Return patch with selected_slot from offered_slots index, or None."""
    booking = state.get("booking") or {}
    slots = booking.get("offered_slots")
    if not slots:
        return None

    normalized = _normalize(text)

    # Check "last slot" pronouns
    if normalized in _LAST_PATTERNS:
        return {"booking": {"selected_slot": slots[-1]}}

    # Check index patterns
    for patterns, index in _INDEX_PATTERNS:
        if normalized in patterns:
            if index < len(slots):
                return {"booking": {"selected_slot": slots[index]}}
            return None  # Index out of range

    return None

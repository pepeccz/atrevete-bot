"""Escape resolver — Task 4.5.

Recognizes escape-intent phrases and returns a routing signal for the
escape_gate node (Phase 5).
"""

from __future__ import annotations

import difflib
import unicodedata
from typing import Any


def _normalize(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    stripped = "".join(
        ch for ch in nfkd if not unicodedata.combining(ch) and (ch.isascii() or ch == " ")
    )
    return stripped.lower().strip().rstrip(".,!?")


# (canonical_phrase, escape_kind)
_ESCAPE_PHRASES: list[tuple[str, str]] = [
    # cancel
    ("cancelar", "cancel"),
    ("no quiero", "cancel"),
    ("dejalo", "cancel"),
    ("anular", "cancel"),
    # start_over
    ("empezar de cero", "start_over"),
    ("borrar todo", "start_over"),
    ("reiniciar", "start_over"),
    # change_date
    ("cambiar fecha", "change_date"),
    ("otro dia", "change_date"),
    ("otra fecha", "change_date"),
    # change_service
    ("mejor otra cosa", "change_service"),
    ("cambiar servicio", "change_service"),
    ("otro servicio", "change_service"),
    # change_stylist
    ("con otra", "change_stylist"),
    ("otro estilista", "change_stylist"),
    ("cambiar estilista", "change_stylist"),
]

_CANONICAL_TO_KIND = dict(_ESCAPE_PHRASES)
_ALL_CANONICALS = list(_CANONICAL_TO_KIND.keys())


async def resolve_escape(text: str, state: Any) -> dict[str, Any] | None:
    """Return escape intent patch or None if no escape phrase is matched."""
    normalized = _normalize(text)

    # Exact match first
    if normalized in _CANONICAL_TO_KIND:
        return {"booking": {"_escape_intent": _CANONICAL_TO_KIND[normalized]}}

    # Fuzzy match (threshold 0.82 — slightly lower than negation to handle
    # phrase-level similarity across 2-3 word phrases)
    matches = difflib.get_close_matches(normalized, _ALL_CANONICALS, n=1, cutoff=0.82)
    if matches:
        return {"booking": {"_escape_intent": _CANONICAL_TO_KIND[matches[0]]}}

    return None

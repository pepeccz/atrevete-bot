"""Router node — Task 6.1.

Pure keyword-based intent classifier. Stateless (classifies current message only).
Sticky-mode exception: if booking dict has an active (non-done) step, keeps routing
to booking regardless of keywords.

Returns Command(goto="general"|"booking", update={"current_mode": "GENERAL"|"BOOKING"}).
"""

from __future__ import annotations

import unicodedata
from typing import Any

from langgraph.types import Command


def _normalize(s: str) -> str:
    """Lowercase, strip accents, strip punctuation edges."""
    nfkd = unicodedata.normalize("NFKD", s)
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return stripped.lower()


_BOOKING_KEYWORDS: tuple[str, ...] = (
    "reservar",
    "reserva",
    "cita",
    "turno",
    "agendar",
    "cortarme",
    "cortar",
    "tintarme",
    "mechas",
    "manicura",
    "pedicura",
    "masaje",
    "maquillaje",
    "peinado",
)

# Steps that keep the router in sticky-booking mode
_ACTIVE_BOOKING_STEPS = frozenset(
    {"service", "audience", "stylist", "date", "slot", "name", "notes", "confirm"}
)


def _has_booking_keyword(text: str) -> bool:
    normalized = _normalize(text)
    return any(kw in normalized for kw in _BOOKING_KEYWORDS)


def router_node(state: dict[str, Any]) -> Command:
    """Classify intent and return routing Command."""
    booking = state.get("booking")
    user_message = state.get("user_message", "") or ""

    # Preprocess clears user_message; fall back to last HumanMessage in messages list.
    if not user_message:
        msgs = state.get("messages") or []
        for m in reversed(msgs):
            if hasattr(m, "type") and m.type == "human":
                user_message = m.content or ""
                break
            elif isinstance(m, dict) and m.get("role") == "human":
                user_message = m.get("content", "")
                break

    # --- Sticky mode: active booking step (not done) keeps routing to booking ---
    if booking is not None:
        step = booking.get("step")
        if step in _ACTIVE_BOOKING_STEPS:
            return Command(goto="booking", update={"current_mode": "BOOKING"})

    # --- Keyword classification ---
    if _has_booking_keyword(user_message):
        return Command(goto="booking", update={"current_mode": "BOOKING"})

    return Command(goto="general", update={"current_mode": "GENERAL"})

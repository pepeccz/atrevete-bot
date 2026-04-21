"""
resolve_pre_turn — Deterministic entity extraction node (Phase 2).

Runs all patch_pipeline resolvers in a single ordered pass before routing.
Writes extracted entities directly into booking_context.
Guards: any field already resolved is NOT overwritten.

Design ref: design §D6, spec REQ-resolve_pre_turn.
"""

from __future__ import annotations

import logging
import re
from typing import Any

# Simple negation phrases for booking confirmation context.
# is_negation() is scoped to "¿algo más?" and misses bare "no" — we need
# a broader set for the confirmation case.
_BOOKING_NEGATION = frozenset(
    [
        "no",
        "nop",
        "nope",
        "nel",
        "na",
        "nah",
        "cancelar",
        "cancel",
        "no quiero",
        "mejor no",
        "prefiero no",
        "no confirmo",
        "no, cancelar",
        "no gracias",
    ]
)

logger = logging.getLogger(__name__)

# Sentinel value for "any available stylist" resolution.
ANY_AVAILABLE = "__ANY_AVAILABLE__"

# ---------------------------------------------------------------------------
# Regex patterns for "no-preference stylist" detection
# ---------------------------------------------------------------------------

_ANY_STYLIST_PATTERNS = re.compile(
    r"cualquier(?:[ae]|\b)|"
    r"la\s+primera?\s+(?:con\s+)?disponibilidad|"
    r"quien\s+(?:sea|tenga\s+disponibilidad)|"
    r"la\s+que\s+(?:pueda|est[eé]\s+libre)|"
    r"no\s+(?:me\s+)?importa",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Main node
# ---------------------------------------------------------------------------


async def resolve_pre_turn(state: dict[str, Any]) -> dict[str, Any]:
    """
    Runs all resolvers in fixed order on the incoming user message.
    Returns {'booking_context': <updated_dict>} with only resolved patches applied.

    Resolver order (matches original patch_pipeline apply order):
    1. digit-selection          (offered slot by number)
    2. confirmation/negation    (confirmed=True|False after summary shown)
    3. any-stylist sentinel     (cualquiera / la primera con disponibilidad)
    4. customer-fill            (pre-fill _suggested_customer_name + customer_id)

    Note: opening-request-prefill and offered-stylists-prefill from the original
    BookingModeNode are handled at mode transition time (GREETING→BOOKING handoff),
    not here.
    """
    user_text: str = state.get("user_message") or ""
    bc: dict[str, Any] = dict(state.get("booking_context") or {})

    # --- 1. Digit selection ---
    bc = _apply_digit_selection(user_text, bc)

    # --- 2. Confirmation / negation ---
    bc = _apply_confirmation(user_text, bc)

    # --- 3. Any-stylist sentinel ---
    bc = _apply_any_stylist(user_text, bc)

    # --- 4. Customer pre-fill from state ---
    bc = _apply_customer_prefill(state, bc)

    return {"booking_context": bc}


# ---------------------------------------------------------------------------
# Resolver helpers (pure — no I/O)
# ---------------------------------------------------------------------------


def _apply_digit_selection(user_text: str, bc: dict[str, Any]) -> dict[str, Any]:
    """Select offered slot by bare digit. Guard: selected_slot already set."""
    if bc.get("selected_slot"):
        return bc

    offered_slots: list[dict[str, Any]] = bc.get("offered_slots") or []
    if not offered_slots:
        return bc

    stripped = user_text.strip()
    try:
        digit = int(stripped)
    except (ValueError, TypeError):
        return bc

    if not (1 <= digit <= len(offered_slots)):
        return bc

    slot = offered_slots[digit - 1]
    bc = dict(bc)
    bc["selected_slot"] = slot

    if not bc.get("last_stylist") and slot.get("stylist_name"):
        bc["last_stylist"] = slot["stylist_name"]

    logger.info(
        "resolver.digit_selection.applied | digit=%s | slot_time=%s",
        digit,
        slot.get("start_time", "?"),
    )
    return bc


def _apply_confirmation(user_text: str, bc: dict[str, Any]) -> dict[str, Any]:
    """Resolve affirmation/negation of booking summary. Guard: _confirmation_shown."""
    if not bc.get("_confirmation_shown"):
        return bc
    if bc.get("confirmed") is not None:
        return bc

    from infra.resolvers.affirmation import is_affirmation
    from infra.resolvers.negation import is_negation

    if is_affirmation(user_text):
        bc = dict(bc)
        bc["confirmed"] = True
        logger.info("resolver.affirmation.applied")
        return bc

    # is_negation() covers "¿algo más?" scope; also check direct booking negations
    matched, canonical, distance = is_negation(user_text)
    normalized = user_text.strip().lower()
    if matched or normalized in _BOOKING_NEGATION:
        bc = dict(bc)
        bc["confirmed"] = False
        bc["_confirmation_shown"] = False
        logger.info(
            "resolver.negation.applied | canonical=%s | distance=%s | direct=%s",
            canonical,
            distance,
            normalized in _BOOKING_NEGATION,
        )
        return bc

    return bc


def _apply_any_stylist(user_text: str, bc: dict[str, Any]) -> dict[str, Any]:
    """Detect 'cualquiera' patterns → set ANY_AVAILABLE sentinel. Guard: stylist already set."""
    if bc.get("last_stylist") or bc.get("no_preference_stylist"):
        return bc

    if _ANY_STYLIST_PATTERNS.search(user_text):
        bc = dict(bc)
        bc["last_stylist"] = ANY_AVAILABLE
        bc["no_preference_stylist"] = True
        logger.info("resolver.any_stylist.applied")

    return bc


def _apply_customer_prefill(state: dict[str, Any], bc: dict[str, Any]) -> dict[str, Any]:
    """Pre-fill _suggested_customer_name and customer_id from state. Guard: already set."""
    # Re-use patch_pipeline logic directly
    from agent.booking.patch_pipeline import resolve_customer_from_state

    result = resolve_customer_from_state(state, bc)
    if result and result.get("matched") and result.get("patch"):
        bc = dict(bc)
        bc.update(result["patch"])
        logger.info("resolver.customer_prefill.applied | keys=%s", list(result["patch"].keys()))
    return bc

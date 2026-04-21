"""
route_action — Pure deterministic FSM router (Phase 3).

Promoted from compute_next_prompt in agent/booking/grounding.py.
Returns Command(goto=LABEL) — no I/O, no LLM, no side effects.

Branch priority (first match wins):
 1. _booking_completed=True            → booking_complete
 2. confirmed=True                     → execute_book
 3. _confirmation_shown & !confirmed   → await_confirmation
 4. pending_disambiguations            → ask_audience
 5. no services & !add_more_asked      → ask_service
 6. services & !add_more_asked         → ask_more_services
 7. add_more_asked & !stylist          → ask_stylist
 8. stylist & !offered_slots           → fetch_availability
 9. offered_slots & !selected_slot     → ask_slot
10. selected_slot & !customer_name     → ask_name
11. customer_name & notes_state=not_asked → ask_notes
12. booking_complete & notes done & !_confirmation_shown → show_confirmation
13. fallback                           → error_recovery

Design ref: design §D3, spec REQ-route_action.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import Command

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Node labels — match the node names registered in subgraph.py
# ---------------------------------------------------------------------------

_BOOKING_COMPLETE = "booking_complete"
_EXECUTE_BOOK = "execute_book"
_AWAIT_CONFIRMATION = "await_confirmation"
_ASK_AUDIENCE = "ask_audience"
_ASK_SERVICE = "ask_service"
_ASK_MORE_SERVICES = "ask_more_services"
_ASK_STYLIST = "ask_stylist"
_FETCH_AVAILABILITY = "fetch_availability"
_ASK_SLOT = "ask_slot"
_ASK_NAME = "ask_name"
_ASK_NOTES = "ask_notes"
_SHOW_CONFIRMATION = "show_confirmation"
_ERROR_RECOVERY = "error_recovery"


# ---------------------------------------------------------------------------
# Private helpers (same logic as grounding.py — kept local to avoid coupling)
# ---------------------------------------------------------------------------


def _bc(state: dict[str, Any]) -> dict[str, Any]:
    ctx = state.get("booking_context") or {}
    return ctx if isinstance(ctx, dict) else {}


def _has_stylist(bc: dict[str, Any]) -> bool:
    return bool(bc.get("last_stylist") or bc.get("no_preference_stylist"))


def _has_services(bc: dict[str, Any]) -> bool:
    return bool(bc.get("last_services"))


def _booking_complete(bc: dict[str, Any]) -> bool:
    return bool(
        _has_services(bc)
        and _has_stylist(bc)
        and bc.get("offered_slots")
        and bc.get("selected_slot")
        and bc.get("customer_name")
    )


# ---------------------------------------------------------------------------
# route_action — pure sync FSM
# ---------------------------------------------------------------------------


def route_action(state: dict[str, Any]) -> Command:
    """Pure deterministic router. Maps booking_context → next subgraph node.

    Args:
        state: ConversationState dict (only booking_context is read).

    Returns:
        Command(goto=LABEL) where LABEL is one of the 13 node names.
    """
    bc = _bc(state)

    # ── Branch 1: booking already completed ────────────────────────────────
    if bc.get("_booking_completed"):
        label = _BOOKING_COMPLETE

    # ── Branch 2: user confirmed → execute booking ──────────────────────────
    elif bc.get("confirmed") is True:
        label = _EXECUTE_BOOK

    # ── Branch 3: confirmation shown, awaiting user answer ──────────────────
    elif bc.get("_confirmation_shown") and bc.get("confirmed") is not False:
        label = _AWAIT_CONFIRMATION

    # ── Branch 4: disambiguation pending (audience variants) ────────────────
    elif bc.get("pending_disambiguations"):
        label = _ASK_AUDIENCE

    # ── Branch 5: no services recorded yet ─────────────────────────────────
    elif not _has_services(bc) and not bc.get("add_more_asked"):
        label = _ASK_SERVICE

    # ── Branch 6: services set, haven't asked "¿algo más?" ──────────────────
    elif _has_services(bc) and not bc.get("add_more_asked"):
        label = _ASK_MORE_SERVICES

    # ── Branch 7: add_more asked, no stylist yet ────────────────────────────
    elif bc.get("add_more_asked") and not _has_stylist(bc) and _has_services(bc):
        label = _ASK_STYLIST

    # ── Branch 8: stylist set, no offered slots yet ─────────────────────────
    elif _has_stylist(bc) and not bc.get("offered_slots"):
        label = _FETCH_AVAILABILITY

    # ── Branch 9: slots offered, none selected ──────────────────────────────
    elif bc.get("offered_slots") and not bc.get("selected_slot"):
        label = _ASK_SLOT

    # ── Branch 10: slot selected, no customer name ──────────────────────────
    elif bc.get("selected_slot") and not bc.get("customer_name"):
        label = _ASK_NAME

    # ── Branch 11: name set, notes not asked ────────────────────────────────
    elif bc.get("customer_name") and bc.get("notes_state", "not_asked") == "not_asked":
        label = _ASK_NOTES

    # ── Branch 12: all filled, notes done, confirmation not shown ────────────
    elif (
        _booking_complete(bc)
        and bc.get("notes_state", "not_asked") != "not_asked"
        and not bc.get("_confirmation_shown")
    ):
        label = _SHOW_CONFIRMATION

    # ── Branch 13: confirmed=False (user rejected) or inconsistent state ─────
    else:
        label = _ERROR_RECOVERY

    logger.info(
        "route_action | goto=%s | bc_keys=%s",
        label,
        sorted(bc.keys()),
    )
    return Command(goto=label)

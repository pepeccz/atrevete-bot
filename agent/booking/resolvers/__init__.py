"""
Booking resolver registry.

RESOLVER_REGISTRY is the ordered list of resolver callables run by interpret_user_update.
Each resolver has signature: resolve(user_text, bc, state) -> ResolverResult | None

Precedence order (design D4):
 1. digit_selection       — if offered_slots present
 2. confirmation          — if _confirmation_shown
 3. any_stylist           — ANY_AVAILABLE sentinel
 4. date_hint             — dateparser-based
 5. stylist               — explicit name (not ANY_AVAILABLE)
 6. audience              — señora/caballero/niño → clears pending_disambiguations
 7. service               — catalog fuzzy match
 8. add_more              — context-gated: _last_leaf == "ask_more_services"
 9. customer_name         — context-gated: _last_leaf == "ask_name"
10. notes                 — context-gated: _last_leaf == "ask_notes"
11. customer_prefill      — read-only suggestion from state
"""

from __future__ import annotations

from typing import Any, TypedDict


class ResolverResult(TypedDict, total=False):
    """Metadata-rich result from a booking resolver."""

    patch: dict[str, Any]       # fields to merge into booking_context
    cleared: list[str]          # fields to delete (e.g. pending_disambiguations)
    matched: bool
    user_action: str | None     # PROVIDE_FIELD | CHANGE_DATE | AFFIRM | NEGATE | UNKNOWN


# Registry is defined here in fixed precedence order (design D4).
# Populated at the bottom of this file after all resolver modules are imported.
RESOLVER_REGISTRY: list = []


def _build_registry() -> None:
    """Import resolver modules and populate RESOLVER_REGISTRY in precedence order (design D4)."""
    from agent.booking.resolvers import (
        add_more,
        any_stylist,
        audience,
        confirmation,
        customer_name,
        customer_prefill,
        date_hint,
        digit_selection,
        notes,
        service,
        stylist,
    )

    RESOLVER_REGISTRY.extend(
        [
            digit_selection.resolve,   # 1. digit selection (if offered_slots present)
            confirmation.resolve,      # 2. confirmation/negation (if _confirmation_shown)
            any_stylist.resolve,       # 3. ANY_AVAILABLE sentinel
            date_hint.resolve,         # 4. dateparser-based date extraction
            stylist.resolve,           # 5. explicit stylist name (not ANY_AVAILABLE)
            audience.resolve,          # 6. señora/caballero/niño → clears pending_disambiguations
            service.resolve,           # 7. catalog fuzzy match
            add_more.resolve,          # 8. context-gated: _last_leaf == "ask_more_services"
            customer_name.resolve,     # 9. context-gated: _last_leaf == "ask_name"
            notes.resolve,             # 10. context-gated: _last_leaf == "ask_notes"
            customer_prefill.resolve,  # 11. read-only suggestion from state
        ]
    )


_build_registry()

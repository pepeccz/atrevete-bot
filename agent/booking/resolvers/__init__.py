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


# Registry is populated by each resolver module at import time.
# Modules append themselves on load so order is controlled by import order in subgraph.py.
# For now, empty until P2/P3 populate it.
RESOLVER_REGISTRY: list = []

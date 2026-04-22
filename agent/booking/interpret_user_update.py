"""interpret_user_update node — Phase 5.5.

Entry node for the booking subgraph. Runs Phase 4 resolvers in order,
shallow-merges returned patches into the booking sub-dict, and returns
Command(goto="escape_gate", update={merged_booking_update}).

NEVER invokes an LLM. Idempotent — all resolvers return None if no match.

Resolver execution order:
  1. escape     — check for cancel/start_over/change_* intent first
  2. audience   — audience tag detection
  3. digit      — slot selection by ordinal/numeral
  4. negation   — bare "no" or similar
  5. date       — date parsing
  6. stylist    — stylist name matching
  7. name       — customer name extraction
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import Command

from agent.booking.resolvers.audience import resolve_audience  # noqa: F401
from agent.booking.resolvers.date import resolve_date  # noqa: F401
from agent.booking.resolvers.digit import resolve_digit  # noqa: F401
from agent.booking.resolvers.escape import resolve_escape  # noqa: F401
from agent.booking.resolvers.name import resolve_name  # noqa: F401
from agent.booking.resolvers.negation import resolve_negation  # noqa: F401
from agent.booking.resolvers.stylist import resolve_stylist  # noqa: F401

logger = logging.getLogger(__name__)


async def interpret_user_update(state: dict[str, Any]) -> Command:
    """Run all resolvers; merge patches; return Command(goto='escape_gate')."""
    import agent.booking.interpret_user_update as _self

    # Build resolver list at call time so patches applied to this module's names work.
    resolver_fns = [
        _self.resolve_escape,
        _self.resolve_audience,
        _self.resolve_digit,
        _self.resolve_negation,
        _self.resolve_date,
        _self.resolve_stylist,
        _self.resolve_name,
    ]

    text = state.get("user_message", "") or ""

    # Preprocess clears user_message before subgraph runs; fall back to last HumanMessage.
    if not text:
        msgs = state.get("messages") or []
        for m in reversed(msgs):
            if hasattr(m, "type") and m.type == "human":
                text = m.content or ""
                break
            elif isinstance(m, dict) and m.get("role") == "human":
                text = m.get("content", "")
                break

    booking = dict(state.get("booking") or {})

    # Run resolvers and collect booking sub-dict patches
    booking_patch: dict[str, Any] = {}
    for resolver in resolver_fns:
        try:
            result = await resolver(text, state)
        except Exception:
            logger.warning("Resolver %s raised", resolver.__name__, exc_info=True)
            continue

        if result is None:
            continue

        # Each resolver returns {"booking": {...}} — extract the booking sub-dict
        if "booking" in result:
            booking_patch.update(result["booking"])

    # Merge patch into current booking (shallow merge, patch wins)
    merged_booking = {**booking, **booking_patch}

    return Command(goto="escape_gate", update={"booking": merged_booking})

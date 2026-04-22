"""escape_gate node — Phase 5.6.

Reads booking._escape_intent and dispatches accordingly:

  cancel         → Command(goto=END, update={messages:[cancellation], booking:None, current_mode:"GENERAL"})
  start_over     → Command(goto="route_next", update={booking:{step:"service"}})
  change_date    → Command(goto="route_next", update={booking:{...keep, date:None, offered_slots:None, selected_slot:None, step:"date"}})
  change_service → Command(goto="route_next", update={booking:{step:"service"}})
  change_stylist → Command(goto="route_next", update={booking:{...keep, stylist_id:None, step:"stylist"}})
  None           → Command(goto="route_next", update={})
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.constants import END
from langgraph.types import Command

logger = logging.getLogger(__name__)


async def escape_gate(state: dict[str, Any]) -> Command:
    """Dispatch based on escape intent in booking context."""
    booking = state.get("booking") or {}
    intent = booking.get("_escape_intent")

    if intent is None:
        return Command(goto="route_next", update={})

    if intent == "cancel":
        return Command(
            goto=END,
            update={
                "messages": [
                    AIMessage(content="Entendido, la cita ha sido cancelada. ¡Hasta pronto!")
                ],
                "booking": None,
                "current_mode": "GENERAL",
            },
        )

    if intent == "start_over":
        return Command(
            goto="route_next",
            update={"booking": {"step": "service"}},
        )

    if intent == "change_date":
        updated = {
            **booking,
            "date": None,
            "offered_slots": None,
            "selected_slot": None,
            "step": "date",
            "_escape_intent": None,
        }
        return Command(goto="route_next", update={"booking": updated})

    if intent == "change_service":
        return Command(
            goto="route_next",
            update={"booking": {"step": "service"}},
        )

    if intent == "change_stylist":
        updated = {
            **booking,
            "stylist_id": None,
            "step": "stylist",
            "_escape_intent": None,
        }
        return Command(goto="route_next", update={"booking": updated})

    # Unknown intent — pass through
    logger.warning("Unknown escape intent: %s", intent)
    return Command(goto="route_next", update={})

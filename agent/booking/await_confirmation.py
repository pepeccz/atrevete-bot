"""await_confirmation node — Phase 5.9.

1. Renders a booking summary AIMessage.
2. Calls interrupt(<payload>) — pauses execution, surfaces summary to client.
3. On resume: parses user's response (keyword-first, no LLM needed for simple cases).
   - Affirmative → Command(goto="execute_book")
   - Negative    → Command(goto="route_next", update={booking:{step:"slot", offered_slots:None}})

Import: from langgraph.types import interrupt, Command
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.types import Command, interrupt

logger = logging.getLogger(__name__)

_AFFIRMATIVE = frozenset(["sí", "si", "yes", "dale", "confirmo", "ok", "claro", "por supuesto"])
_NEGATIVE = frozenset(["no", "cancel", "cancelar", "no quiero", "mejor no"])


def _render_summary(booking: dict[str, Any]) -> str:
    parts = ["*Resumen de tu reserva:*"]

    date = booking.get("date")
    if date:
        parts.append(f"📅 Fecha: {date}")

    slot = booking.get("selected_slot") or {}
    start = slot.get("start")
    end = slot.get("end")
    if start:
        time_str = f"{start}" + (f" - {end}" if end else "")
        parts.append(f"⏰ Horario: {time_str}")
        stylist = slot.get("stylist") or slot.get("stylist_name")
        if stylist:
            parts.append(f"✂️ Con: {stylist}")

    name = booking.get("customer_full_name")
    if name:
        parts.append(f"👤 Nombre: {name}")

    notes = booking.get("notes")
    if notes:
        parts.append(f"📝 Notas: {notes}")

    parts.append("\n¿Confirmás la reserva? (sí/no)")
    return "\n".join(parts)


def _parse_confirmation(text: str) -> bool | None:
    """Keyword-based confirmation parser. Returns True, False, or None (ambiguous)."""
    normalized = text.strip().lower().rstrip(".,!?")
    if normalized in _AFFIRMATIVE:
        return True
    # Partial match for affirmatives
    for word in _AFFIRMATIVE:
        if normalized.startswith(word):
            return True
    if normalized in _NEGATIVE:
        return False
    for word in _NEGATIVE:
        if normalized.startswith(word):
            return False
    return None


async def await_confirmation(state: dict[str, Any]) -> Command:
    """Emit booking summary, interrupt for user confirmation, route on resume."""
    booking = dict(state.get("booking") or {})
    summary = _render_summary(booking)

    # Interrupt: sends payload to client and waits for resume value
    user_response = interrupt({"summary": summary, "step": "confirm"})

    # On resume: user_response is the string the client provided via Command(resume=...)
    text = str(user_response) if user_response else ""
    confirmed = _parse_confirmation(text)

    summary_message = AIMessage(content=summary)

    if confirmed is True:
        return Command(
            goto="execute_book",
            update={"messages": [summary_message]},
        )
    else:
        # Not confirmed or ambiguous → reopen slot selection
        updated_booking = {**booking, "step": "slot", "offered_slots": None, "selected_slot": None}
        return Command(
            goto="route_next",
            update={
                "messages": [summary_message],
                "booking": updated_booking,
            },
        )

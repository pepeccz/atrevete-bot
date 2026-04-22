"""Deterministic action nodes — Phase 5.7.

fetch_availability_node: calls check_availability tool, parses ToolResponse,
  on ok/partial → Command(goto="route_next", update={booking:{offered_slots, step:"slot"}})
  on rejected   → Command(goto="route_next", update={messages:[fallback], booking:{step:"date"}})

execute_book_node: calls book tool, parses ToolResponse,
  on ok      → Command(goto="route_next", update={booking:{step:"done", appointment_id:...}})
  on rejected → Command(goto="route_next", update={messages:[error], booking:{step:"slot", offered_slots:None}})
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.constants import END
from langgraph.types import Command

from agent.tools.schemas import ToolResponse

logger = logging.getLogger(__name__)


# Module-level references so tests can patch them
async def check_availability_tool(args: dict) -> str:
    from agent.tools.check_availability import check_availability as _check

    return await _check.ainvoke(args)


async def book_tool(args: dict) -> str:
    from agent.tools.book import book as _book

    return await _book.ainvoke(args)


def _parse_response(raw: str | dict) -> ToolResponse:
    if isinstance(raw, str):
        return ToolResponse(**json.loads(raw))
    return ToolResponse(**raw)


async def fetch_availability_node(state: dict[str, Any]) -> Command:
    """Call check_availability and route based on result."""
    import agent.booking.actions as _self

    booking = state.get("booking") or {}
    args = {
        "service_ids": [str(s) for s in (booking.get("service_ids") or [])],
        "date_iso": str(booking.get("date") or ""),
        "stylist_id": str(booking.get("stylist_id") or "") if booking.get("stylist_id") else None,
        "audience": booking.get("audience"),
    }

    try:
        raw = await _self.check_availability_tool(args)
        response = _parse_response(raw)
    except Exception:
        logger.exception("check_availability_tool failed")
        updated_booking = {**booking, "step": "date"}
        return Command(
            goto="route_next",
            update={
                "messages": [
                    AIMessage(
                        content="Lo siento, no pude consultar disponibilidad. Por favor indícame otra fecha."
                    )
                ],
                "booking": updated_booking,
            },
        )

    if response.status in ("ok", "partial"):
        slots = response.payload.get("slots", [])
        updated_booking = {**booking, "offered_slots": slots, "step": "slot"}
        return Command(goto="ask_slot", update={"booking": updated_booking})
    else:
        # rejected
        error_text = "; ".join(response.errors) if response.errors else "Sin disponibilidad."
        updated_booking = {**booking, "step": "date", "offered_slots": None}
        return Command(
            goto=END,
            update={
                "messages": [
                    AIMessage(
                        content=f"No encontré turnos disponibles: {error_text}. ¿Quieres probar otra fecha?"
                    )
                ],
                "booking": updated_booking,
            },
        )


async def execute_book_node(state: dict[str, Any]) -> Command:
    """Call book tool and route based on result."""
    import agent.booking.actions as _self

    booking = state.get("booking") or {}
    raw_stylist_id = booking.get("stylist_id")

    # Precondition guard: stylist_id must be set before invoking book
    if not raw_stylist_id:
        logger.error("execute_book_node: stylist_id missing from booking state")
        return Command(
            goto="route_next",
            update={
                "messages": [
                    AIMessage(
                        content="Necesito saber con qué estilista quieres reservar. ¿Puedes indicarme cuál prefieres?"
                    )
                ],
                "booking": {**booking, "step": "stylist"},
            },
        )

    selected_slot = booking.get("selected_slot") or {}
    args = {
        "service_ids": [str(s) for s in (booking.get("service_ids") or [])],
        "stylist_id": str(raw_stylist_id),
        "start_iso": selected_slot.get("start_iso") or selected_slot.get("start") or "",
        "customer_full_name": booking.get("customer_full_name"),
        "customer_phone": state.get("customer_phone"),
        "notes": booking.get("notes") or "",
    }

    try:
        raw = await _self.book_tool(args)
        response = _parse_response(raw)
    except Exception:
        logger.exception("book_tool failed")
        updated_booking = {**booking, "step": "slot", "offered_slots": None}
        return Command(
            goto="route_next",
            update={
                "messages": [
                    AIMessage(
                        content="Hubo un error al confirmar la reserva. Por favor elige un turno nuevamente."
                    )
                ],
                "booking": updated_booking,
            },
        )

    if response.status == "ok":
        appointment_id = response.payload.get("appointment_id")
        updated_booking = {**booking, "step": "done", "appointment_id": appointment_id}
        return Command(goto=END, update={"booking": updated_booking})
    else:
        error_text = "; ".join(response.errors) if response.errors else "Error al reservar."
        updated_booking = {**booking, "step": "slot", "offered_slots": None}
        return Command(
            goto=END,
            update={
                "messages": [
                    AIMessage(
                        content=f"No pude confirmar la cita: {error_text}. Por favor elige otro turno."
                    )
                ],
                "booking": updated_booking,
            },
        )

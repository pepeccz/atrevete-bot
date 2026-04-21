"""
Deterministic leaf nodes — Phase 4 implementation.

fetch_availability and execute_book assemble ALL tool arguments exclusively
from booking_context. The LLM NEVER influences these arguments.

Design ref: design §D5, spec REQ-fetch_availability, REQ-execute_book.
Invariant #1: LLM MUST NOT control tool arguments.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import Command

from agent.tools.availability_tools import check_availability_impl
from agent.tools.booking_tools import book_impl
from agent.booking.nodes.resolve_pre_turn import ANY_AVAILABLE

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# fetch_availability
# ---------------------------------------------------------------------------


async def fetch_availability(state: dict[str, Any]) -> Command:
    """
    Deterministic node: calls check_availability_impl with args from booking_context.

    Args are assembled from:
        - service_names  ← booking_context["last_services"]  (fully-qualified, e.g. "Cortar Señora")
        - date           ← booking_context.get("date_hint")
        - stylist_name   ← booking_context.get("stylist") if NOT ANY_AVAILABLE sentinel
        - time_range     ← booking_context.get("time_range")

    On success: patches offered_slots into booking_context, routes to route_action.
    On failure: patches last_error + clears offered_slots, routes to route_action.
    route_action then decides the appropriate next step (ask_slot, error_recovery, etc.)
    """
    bc: dict[str, Any] = state.get("booking_context", {})

    service_names: list[str] = bc.get("last_services", [])
    date_hint: str | None = bc.get("date_hint")
    stylist: str | None = bc.get("stylist")
    time_range: str | None = bc.get("time_range")

    # ANY_AVAILABLE sentinel → pass no stylist_name (all stylists queried)
    stylist_name: str | None = None if (not stylist or stylist == ANY_AVAILABLE) else stylist

    logger.info(
        "fetch_availability | service_names=%r | date=%r | stylist=%r",
        service_names,
        date_hint,
        stylist_name,
    )

    result = await check_availability_impl(
        service_names=service_names,
        date=date_hint,
        stylist_name=stylist_name,
        time_range=time_range,
    )

    if result.get("success") and result.get("available_slots"):
        updated_bc = {
            **bc,
            "offered_slots": result["available_slots"],
            "last_error": None,
        }
        logger.info("fetch_availability | success | %d slots", len(result["available_slots"]))
    else:
        updated_bc = {
            **bc,
            "offered_slots": [],
            "last_error": {
                "error_code": result.get("error_code"),
                "error_message": result.get("error_message"),
                "date_too_soon": result.get("date_too_soon", False),
                "min_valid_date": result.get("min_valid_date"),
            },
        }
        logger.warning(
            "fetch_availability | failure | error_code=%r",
            result.get("error_code"),
        )

    return Command(goto="route_action", update={"booking_context": updated_bc})


# ---------------------------------------------------------------------------
# execute_book
# ---------------------------------------------------------------------------


async def execute_book(state: dict[str, Any]) -> Command:
    """
    Deterministic node: calls book_impl with args from booking_context.

    Args are assembled from:
        - services       ← booking_context["last_services"]
        - stylist_id     ← booking_context["selected_slot"]["stylist_id"]
        - start_time     ← booking_context["selected_slot"]["full_datetime"]
        - customer_name  ← booking_context["customer_name"]
        - customer_phone ← booking_context.get("customer_phone")
        - notes          ← booking_context.get("notes")
        - conversation_id ← booking_context.get("conversation_id")

    On success: patches _booking_completed=True + appointment_id into booking_context.
    On failure: patches last_error, _booking_completed stays falsy.
    Always routes to route_action.
    """
    bc: dict[str, Any] = state.get("booking_context", {})

    selected_slot: dict[str, Any] = bc.get("selected_slot", {})
    services: list[str] = bc.get("last_services", [])
    stylist_id: str = selected_slot.get("stylist_id", "")
    start_time: str = selected_slot.get("full_datetime", "")
    customer_name: str = bc.get("customer_name", "")
    customer_phone: str = bc.get("customer_phone", "")
    notes: str | None = bc.get("notes")
    conversation_id: str | None = bc.get("conversation_id")

    logger.info(
        "execute_book | services=%r | stylist_id=%r | start_time=%r | customer=%r",
        services,
        stylist_id,
        start_time,
        customer_name,
    )

    result = await book_impl(
        customer_phone=customer_phone,
        customer_name=customer_name,
        services=services,
        stylist_id=stylist_id,
        start_time=start_time,
        notes=notes,
        conversation_id=conversation_id,
    )

    if result.get("success"):
        updated_bc = {
            **bc,
            "_booking_completed": True,
            "appointment_id": result.get("appointment_id"),
            "last_error": None,
        }
        logger.info("execute_book | success | appointment_id=%r", result.get("appointment_id"))
    else:
        updated_bc = {
            **bc,
            # Do NOT set _booking_completed — absence is falsy; route_action routes to error_recovery
            "last_error": {
                "error_code": result.get("error_code"),
                "error_message": result.get("error_message"),
            },
        }
        logger.warning(
            "execute_book | failure | error_code=%r",
            result.get("error_code"),
        )

    return Command(goto="route_action", update={"booking_context": updated_bc})

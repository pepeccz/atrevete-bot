"""
Availability checking tools for conversational agent.

Converts availability_nodes.py logic to LangChain @tool for use in
conversational agent architecture.
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import select

from agent.tools.calendar_tools import (
    check_holiday_closure,
    fetch_calendar_events,
    generate_time_slots,
    get_stylists_by_category,
    is_slot_available,
)
from database.connection import get_async_session
from database.models import Service, ServiceCategory

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Europe/Madrid")
SAME_DAY_BUFFER_HOURS = 1
MAX_SLOTS_TO_PRESENT = 3


class CheckAvailabilitySchema(BaseModel):
    """Schema for check_availability_tool parameters."""

    service_category: str = Field(
        description="Service category: 'Hairdressing' or 'Aesthetics'"
    )
    date: str = Field(
        description="Date in YYYY-MM-DD format"
    )
    time_range: str | None = Field(
        default=None,
        description="Optional time range: 'morning', 'afternoon', or specific like '14:00-18:00'"
    )
    stylist_id: str | None = Field(
        default=None,
        description="Optional preferred stylist UUID as string"
    )


@tool(args_schema=CheckAvailabilitySchema)
async def check_availability_tool(
    service_category: str,
    date: str,
    time_range: str | None = None,
    stylist_id: str | None = None
) -> dict[str, Any]:
    """
    Check availability across multiple stylist calendars.

    Queries Google Calendar API for all stylists in the specified category
    and returns available time slots prioritized by business rules.

    Args:
        service_category: "Hairdressing" or "Aesthetics"
        date: Date in YYYY-MM-DD format
        time_range: Optional time filter ("morning", "afternoon", or "14:00-18:00")
        stylist_id: Optional preferred stylist UUID

    Returns:
        Dict with:
        - available_slots: List of available slots [{"time": "10:00", "stylist": "Marta", ...}]
        - is_same_day: Boolean indicating same-day booking
        - holiday_detected: Boolean if day is closed
        - error: Error message if failed (None if success)

    Example:
        >>> result = await check_availability_tool("Hairdressing", "2025-11-01", "afternoon")
        >>> result["available_slots"]
        [{"time": "15:00", "stylist": "Marta", "stylist_id": "..."}, ...]
    """
    try:
        # Parse date
        try:
            requested_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=TIMEZONE)
        except ValueError:
            logger.error(f"Invalid date format: {date}")
            return {
                "error": "Formato de fecha inválido",
                "available_slots": [],
                "is_same_day": False,
                "holiday_detected": False,
            }

        # Convert service_category string to enum
        try:
            category_enum = ServiceCategory[service_category.upper()]
        except KeyError:
            logger.error(f"Invalid service category: {service_category}")
            return {
                "error": f"Categoría inválida: {service_category}",
                "available_slots": [],
                "is_same_day": False,
                "holiday_detected": False,
            }

        # Check for holidays
        is_holiday = await check_holiday_closure(requested_date)
        if is_holiday:
            logger.info(f"Holiday detected on {date}")
            return {
                "error": None,
                "available_slots": [],
                "is_same_day": False,
                "holiday_detected": True,
            }

        # Get stylists for category
        stylists = await get_stylists_by_category(category_enum)

        if not stylists:
            logger.warning(f"No stylists found for category {service_category}")
            return {
                "error": f"No hay estilistas disponibles para {service_category}",
                "available_slots": [],
                "is_same_day": False,
                "holiday_detected": False,
            }

        # Filter by preferred stylist if specified
        if stylist_id:
            try:
                stylist_uuid = UUID(stylist_id)
                stylists = [s for s in stylists if s.id == stylist_uuid]
                if not stylists:
                    logger.warning(f"Preferred stylist {stylist_id} not found or wrong category")
            except ValueError:
                logger.error(f"Invalid stylist_id format: {stylist_id}")

        # Check if same-day booking
        current_date = datetime.now(TIMEZONE).date()
        is_same_day = requested_date.date() == current_date

        # Query availability for each stylist
        all_slots = []

        for stylist in stylists:
            # Generate candidate slots for the day
            slots = generate_time_slots(requested_date, time_range)

            # Fetch busy events from Google Calendar
            busy_events = await fetch_calendar_events(
                stylist.google_calendar_id,
                requested_date,
                requested_date + timedelta(days=1)
            )

            # Filter available slots
            for slot_time in slots:
                if is_slot_available(slot_time, busy_events):
                    all_slots.append({
                        "time": slot_time.strftime("%H:%M"),
                        "stylist": stylist.first_name,
                        "stylist_id": str(stylist.id),
                        "datetime_iso": slot_time.isoformat(),
                    })

        # Apply same-day filtering if needed
        if is_same_day:
            current_time = datetime.now(TIMEZONE)
            earliest_time = current_time + timedelta(hours=SAME_DAY_BUFFER_HOURS)
            all_slots = [
                slot for slot in all_slots
                if datetime.fromisoformat(slot["datetime_iso"]) >= earliest_time
            ]

        # Sort by time
        all_slots.sort(key=lambda s: s["time"])

        # Prioritize top slots (simple: take first MAX_SLOTS_TO_PRESENT)
        prioritized_slots = all_slots[:MAX_SLOTS_TO_PRESENT]

        logger.info(
            f"Availability check complete: {len(all_slots)} slots found, "
            f"presenting {len(prioritized_slots)}"
        )

        return {
            "error": None,
            "available_slots": prioritized_slots,
            "is_same_day": is_same_day,
            "holiday_detected": False,
        }

    except Exception as e:
        logger.error(f"Error in check_availability_tool: {e}", exc_info=True)
        return {
            "error": "Error consultando disponibilidad",
            "available_slots": [],
            "is_same_day": False,
            "holiday_detected": False,
        }

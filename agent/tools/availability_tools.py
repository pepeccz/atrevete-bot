"""
Availability Checking Tool for v3.0 Architecture.

Rewritten to integrate natural date parsing from agent/utils/date_parser.py.
Now accepts Spanish natural language dates like "mañana", "viernes", "8 de noviembre".

Key changes from v2:
- Accepts natural language dates in Spanish
- Uses parse_natural_date() from utils
- Validates 3-day rule before checking calendar
- Maintains all existing calendar integration logic
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent.tools.calendar_tools import (
    check_holiday_closure,
    fetch_calendar_events,
    generate_time_slots_async,
    get_calendar_client,
    get_stylists_by_category,
    is_slot_available,
)
from agent.utils import parse_natural_date, MADRID_TZ
from agent.validators import validate_3_day_rule
from database.models import ServiceCategory

logger = logging.getLogger(__name__)

SAME_DAY_BUFFER_HOURS = 1
MAX_SLOTS_TO_PRESENT = 3

# Conservative service duration for informational availability checks
# Used when exact service duration is unknown (conversational queries)
# Set to 90 minutes to cover most common service combinations
CONSERVATIVE_SERVICE_DURATION_MINUTES = 90


class CheckAvailabilitySchema(BaseModel):
    """Schema for check_availability tool parameters."""

    service_category: str = Field(
        description="Service category: 'Peluquería' or 'Estética' (or English: 'Hairdressing', 'Aesthetics')"
    )
    date: str = Field(
        description=(
            "Date in natural language or ISO format. Accepts:\n"
            "- Natural Spanish: 'mañana', 'viernes', '8 de noviembre'\n"
            "- ISO 8601: '2025-11-08'\n"
            "- Day/month: '08/11', '8-11'"
        )
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
async def check_availability(
    service_category: str,
    date: str,
    time_range: str | None = None,
    stylist_id: str | None = None
) -> dict[str, Any]:
    """
    Check availability across stylist calendars with natural date parsing.

    This tool checks calendar availability for the requested date and returns available slots.
    Accepts natural language Spanish dates like "mañana", "viernes", "8 de noviembre".

    Automatically validates:
    - 3-day minimum notice requirement
    - Holiday closures
    - Business hours constraints

    Queries Google Calendar API for all stylists in the specified category
    and returns available time slots prioritized by business rules.

    Args:
        service_category: "Peluquería"/"Hairdressing" or "Estética"/"Aesthetics"
        date: Date in natural Spanish or ISO format:
            - Natural: "mañana", "viernes", "lunes", "8 de noviembre"
            - ISO: "2025-11-08"
            - Day/month: "08/11"
        time_range: Optional time filter ("morning", "afternoon", or "14:00-18:00")
        stylist_id: Optional preferred stylist UUID

    Returns:
        Dict with:
            {
                "available_slots": [
                    {
                        "time": "10:00",
                        "end_time": "11:30",
                        "stylist": "Marta",
                        "stylist_id": "uuid",
                        "date": "2025-11-08"
                    }
                ],
                "is_same_day": bool,
                "holiday_detected": bool,
                "date_too_soon": bool,
                "error": str | None
            }

    Examples:
        Natural Spanish dates:
        >>> await check_availability("Peluquería", "mañana")
        {"available_slots": [...], "is_same_day": False, ...}

        >>> await check_availability("Estética", "viernes", "afternoon")
        {"available_slots": [...], ...}

        >>> await check_availability("Hairdressing", "8 de noviembre")
        {"available_slots": [...], ...}

        ISO format:
        >>> await check_availability("Aesthetics", "2025-11-15")
        {"available_slots": [...], ...}

    Note:
        - Uses CONSERVATIVE_SERVICE_DURATION_MINUTES (90 min) for slot validation
        - Validates 3-day rule before checking calendar (returns error if < 3 days)
        - Checks holiday calendar before querying availability
    """
    try:
        # Parse natural language date
        try:
            requested_date = parse_natural_date(date, timezone=MADRID_TZ)
            logger.info(f"Parsed date '{date}' → {requested_date.date()}")
        except ValueError as e:
            logger.error(f"Failed to parse date '{date}': {e}")
            return {
                "error": str(e),
                "available_slots": [],
                "is_same_day": False,
                "holiday_detected": False,
                "date_too_soon": False,
            }

        # Validate 3-day rule
        validation = await validate_3_day_rule(requested_date)
        if not validation["valid"]:
            logger.warning(f"3-day rule violation for date {requested_date.date()}")
            return {
                "error": validation["error_message"],
                "available_slots": [],
                "is_same_day": False,
                "holiday_detected": False,
                "date_too_soon": True,
                "days_until_appointment": validation["days_until_appointment"],
            }

        # Convert service_category string to enum
        category_normalized = service_category.upper()
        if category_normalized in ["PELUQUERÍA", "PELUQUERIA", "HAIRDRESSING"]:
            category_enum = ServiceCategory.PELUQUERIA
        elif category_normalized in ["ESTÉTICA", "ESTETICA", "AESTHETICS"]:
            category_enum = ServiceCategory.ESTETICA
        else:
            logger.error(f"Invalid service category: {service_category}")
            return {
                "error": f"Categoría inválida: {service_category}. Usa 'Peluquería' o 'Estética'.",
                "available_slots": [],
                "is_same_day": False,
                "holiday_detected": False,
                "date_too_soon": False,
            }

        # Check for holidays
        calendar_client = get_calendar_client()
        is_holiday = await check_holiday_closure(
            calendar_client.service,
            requested_date,
            conversation_id=""  # Tool doesn't have access to state
        )
        if is_holiday:
            logger.info(f"Holiday detected on {requested_date.date()}")
            return {
                "error": None,
                "available_slots": [],
                "is_same_day": False,
                "holiday_detected": True,
                "date_too_soon": False,
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
                "date_too_soon": False,
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
        current_date = datetime.now(MADRID_TZ).date()
        is_same_day = requested_date.date() == current_date

        # Query availability for each stylist
        all_slots = []

        for stylist in stylists:
            # Generate candidate slots for the day
            # Use conservative duration to ensure services fit within business hours
            day_of_week = requested_date.weekday()
            slots = await generate_time_slots_async(
                requested_date,
                day_of_week,
                service_duration_minutes=CONSERVATIVE_SERVICE_DURATION_MINUTES
            )

            # Fetch busy events from Google Calendar
            calendar_client = get_calendar_client()
            service = calendar_client.get_service()

            time_min = requested_date.replace(hour=0, minute=0, second=0, microsecond=0)
            time_max = requested_date.replace(hour=23, minute=59, second=59, microsecond=999999)

            busy_events = fetch_calendar_events(
                service,
                stylist.google_calendar_id,
                time_min.isoformat(),
                time_max.isoformat()
            )

            # Filter available slots
            for slot_time in slots:
                if is_slot_available(
                    slot_time,
                    busy_events,
                    CONSERVATIVE_SERVICE_DURATION_MINUTES
                ):
                    # Calculate end time
                    end_time = slot_time + timedelta(minutes=CONSERVATIVE_SERVICE_DURATION_MINUTES)

                    all_slots.append({
                        "time": slot_time.strftime("%H:%M"),
                        "end_time": end_time.strftime("%H:%M"),
                        "stylist": f"{stylist.first_name} {stylist.last_name}".strip(),
                        "stylist_id": str(stylist.id),
                        "date": requested_date.strftime("%Y-%m-%d"),
                        "full_datetime": slot_time.isoformat(),
                    })

        # Filter by time_range if specified
        if time_range:
            all_slots = _filter_slots_by_time_range(all_slots, time_range)

        # Sort and limit slots
        all_slots = _prioritize_and_limit_slots(all_slots, MAX_SLOTS_TO_PRESENT)

        logger.info(
            f"Found {len(all_slots)} available slots for {service_category} on {requested_date.date()}"
        )

        return {
            "error": None,
            "available_slots": all_slots,
            "is_same_day": is_same_day,
            "holiday_detected": False,
            "date_too_soon": False,
        }

    except Exception as e:
        logger.error(f"Error in check_availability: {e}", exc_info=True)
        return {
            "error": f"Error checking availability: {str(e)}",
            "available_slots": [],
            "is_same_day": False,
            "holiday_detected": False,
            "date_too_soon": False,
        }


def _filter_slots_by_time_range(slots: list[dict], time_range: str) -> list[dict]:
    """
    Filter slots by time range (morning, afternoon, or specific range).

    Args:
        slots: List of slot dicts with "time" field
        time_range: "morning", "afternoon", or "HH:MM-HH:MM"

    Returns:
        Filtered list of slots
    """
    if time_range.lower() == "morning":
        # Morning: before 14:00
        return [s for s in slots if s["time"] < "14:00"]
    elif time_range.lower() == "afternoon":
        # Afternoon: 14:00 or later
        return [s for s in slots if s["time"] >= "14:00"]
    elif "-" in time_range:
        # Specific range like "14:00-18:00"
        try:
            start, end = time_range.split("-")
            return [s for s in slots if start <= s["time"] < end]
        except ValueError:
            logger.warning(f"Invalid time range format: {time_range}")
            return slots
    else:
        logger.warning(f"Unknown time range: {time_range}")
        return slots


def _prioritize_and_limit_slots(slots: list[dict], limit: int) -> list[dict]:
    """
    Prioritize slots by time (earliest first) and limit results.

    Args:
        slots: List of slot dicts
        limit: Maximum number of slots to return

    Returns:
        Prioritized and limited list of slots
    """
    # Sort by time (earliest first)
    sorted_slots = sorted(slots, key=lambda s: s["time"])

    # Limit results
    return sorted_slots[:limit]

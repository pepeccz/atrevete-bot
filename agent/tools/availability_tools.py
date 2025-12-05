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
from shared.business_hours_validator import get_next_open_date, is_date_closed

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
            category_enum = ServiceCategory.HAIRDRESSING
        elif category_normalized in ["ESTÉTICA", "ESTETICA", "AESTHETICS"]:
            category_enum = ServiceCategory.AESTHETICS
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
                        "stylist": stylist.name,
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


class FindNextAvailableSchema(BaseModel):
    """Schema for find_next_available tool parameters."""

    service_category: str = Field(
        description="Service category: 'Peluquería' or 'Estética' (or English: 'Hairdressing', 'Aesthetics')"
    )
    time_range: str | None = Field(
        default=None,
        description="Optional time range: 'morning', 'afternoon', or specific like '14:00-18:00'"
    )
    stylist_id: str | None = Field(
        default=None,
        description="Optional preferred stylist UUID as string"
    )
    max_days_to_search: int = Field(
        default=10,
        description="Maximum number of days to search ahead (default: 10)"
    )
    start_date: str | None = Field(
        default=None,
        description=(
            "Optional preferred start date in natural language or ISO format. "
            "If specified, search starts from this date (respecting 3-day rule). "
            "Accepts: 'mañana', 'viernes', '15 de diciembre', '2025-12-15'"
        )
    )


@tool(args_schema=FindNextAvailableSchema)
async def find_next_available(
    service_category: str,
    time_range: str | None = None,
    stylist_id: str | None = None,
    max_days_to_search: int = 10,
    start_date: str | None = None,
) -> dict[str, Any]:
    """
    Automatically search for next available slots across multiple dates.

    This tool searches the next N days (default: 10) to find available appointment slots.
    Unlike check_availability which checks a single date, this tool iterates through
    multiple dates automatically and returns slots from the first 2-3 dates that have
    availability.

    **v3.2 Optimization**: Returns maximum 5 slots per stylist to reduce token usage.

    WHEN TO USE:
    - Customer asks for "próxima disponibilidad" / "next available"
    - check_availability returned empty for a specific date
    - Customer is flexible with dates
    - You want to present multiple date options automatically

    WHEN NOT TO USE:
    - Customer has a specific date in mind (use check_availability instead)
    - Customer is asking about availability on a particular day

    Args:
        service_category: "Peluquería"/"Hairdressing" or "Estética"/"Aesthetics"
        time_range: Optional time filter ("morning", "afternoon", or "14:00-18:00")
        stylist_id: Optional preferred stylist UUID
        max_days_to_search: Maximum days to search ahead (default: 10)

    Returns:
        Dict with:
            {
                "available_stylists": [
                    {
                        "stylist_name": "Ana",
                        "stylist_id": "uuid",
                        "slots": [
                            {
                                "time": "10:00",
                                "end_time": "11:30",
                                "date": "2025-11-08",
                                "day_name": "viernes",
                                "stylist": "Ana",
                                "stylist_id": "uuid",
                                "full_datetime": "2025-11-08T10:00:00+01:00"
                            }
                        ]
                    }
                ],
                "total_slots_found": int,
                "dates_searched": int,
                "error": str | None
            }

    Example:
        >>> await find_next_available("Peluquería", time_range="afternoon")
        {
            "available_stylists": [
                {"stylist_name": "Ana", "stylist_id": "...", "slots": [...]},
                {"stylist_name": "Pilar", "stylist_id": "...", "slots": [...]},
                {"stylist_name": "Rosa", "stylist_id": "...", "slots": [...]}
            ],
            "total_slots_found": 6,
            "dates_searched": 10
        }
    """
    try:
        # Convert service_category string to enum
        category_normalized = service_category.upper()
        if category_normalized in ["PELUQUERÍA", "PELUQUERIA", "HAIRDRESSING"]:
            category_enum = ServiceCategory.HAIRDRESSING
        elif category_normalized in ["ESTÉTICA", "ESTETICA", "AESTHETICS"]:
            category_enum = ServiceCategory.AESTHETICS
        else:
            logger.error(f"Invalid service category: {service_category}")
            return {
                "error": f"Categoría inválida: {service_category}. Usa 'Peluquería' o 'Estética'.",
                "available_dates": [],
                "total_slots_found": 0,
                "dates_searched": 0,
            }

        # Get stylists for category
        stylists = await get_stylists_by_category(category_enum)

        if not stylists:
            logger.warning(f"No stylists found for category {service_category}")
            return {
                "error": f"No hay estilistas disponibles para {service_category}",
                "available_dates": [],
                "total_slots_found": 0,
                "dates_searched": 0,
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

        # Spanish day names for formatting
        day_names_es = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

        # Start searching from the earliest valid date
        now = datetime.now(MADRID_TZ)
        min_valid_date = now + timedelta(days=3)  # 3-day rule minimum

        # If start_date is provided, parse and use it (respecting 3-day rule)
        if start_date:
            try:
                preferred_date = parse_natural_date(start_date, timezone=MADRID_TZ)
                logger.info(f"Parsed preferred start_date '{start_date}' → {preferred_date.date()}")
                # Use preferred date if it's after the 3-day minimum
                if preferred_date >= min_valid_date:
                    earliest_valid = preferred_date
                else:
                    # Preferred date is too soon, use minimum valid date
                    logger.info(
                        f"Preferred date {preferred_date.date()} is before 3-day minimum "
                        f"{min_valid_date.date()}, using minimum"
                    )
                    earliest_valid = min_valid_date
            except ValueError as e:
                logger.warning(f"Could not parse start_date '{start_date}': {e}, using default")
                earliest_valid = min_valid_date
        else:
            earliest_valid = min_valid_date

        # Skip closed days using database-driven validation
        # If earliest_valid falls on closed day, find next open date
        next_open = await get_next_open_date(earliest_valid, max_search_days=14)
        if next_open is None:
            logger.warning(
                f"No open dates found within 14 days from {earliest_valid.date()}. "
                f"Returning empty result."
            )
            return {
                "available_stylists": [],
                "dates_searched": 0,
                "total_slots_found": 0,
                "error": "No hay fechas disponibles en las próximas 2 semanas",
            }
        earliest_valid = next_open

        search_start = earliest_valid.replace(hour=0, minute=0, second=0, microsecond=0)

        calendar_client = get_calendar_client()
        service = calendar_client.get_service()

        # Collect ALL slots from ALL stylists across multiple dates
        all_slots_by_stylist = {stylist.id: [] for stylist in stylists}
        # Track calendar health: total events seen per stylist to detect broken calendars
        calendar_events_seen = {stylist.id: 0 for stylist in stylists}
        # Track days searched per stylist to detect suspicious empty calendars
        days_searched_per_stylist = {stylist.id: 0 for stylist in stylists}
        # Track which stylists to skip due to calendar issues
        skipped_stylists = set()
        dates_searched = 0
        MAX_SLOTS_PER_STYLIST = 2  # Return 2 slots per stylist

        # Iterate through days
        for day_offset in range(max_days_to_search):
            current_date = search_start + timedelta(days=day_offset)
            dates_searched += 1

            # Check if we have enough slots for all stylists (2 per stylist)
            if all(len(slots) >= MAX_SLOTS_PER_STYLIST for slots in all_slots_by_stylist.values()):
                logger.info(f"Found {MAX_SLOTS_PER_STYLIST} slots for all stylists, stopping search")

            # Skip closed days using database-driven validation
            if await is_date_closed(current_date):
                logger.info(
                    f"Skipping closed day: {current_date.date()} "
                    f"({day_names_es[current_date.weekday()]})"
                )
                continue

            # Check for holidays
            is_holiday = await check_holiday_closure(
                service,
                current_date,
                conversation_id=""
            )
            if is_holiday:
                logger.info(f"Skipping holiday: {current_date.date()}")
                continue

            # Query availability for each stylist on this date
            for stylist in stylists:
                # Skip if we already have enough slots for this stylist
                if len(all_slots_by_stylist[stylist.id]) >= MAX_SLOTS_PER_STYLIST:
                    continue

                # Skip if this stylist has been marked as having calendar issues
                if stylist.id in skipped_stylists:
                    continue

                # Generate candidate slots for the day
                day_of_week = current_date.weekday()
                slots = await generate_time_slots_async(
                    current_date,
                    day_of_week,
                    service_duration_minutes=CONSERVATIVE_SERVICE_DURATION_MINUTES
                )

                # Fetch busy events from Google Calendar
                time_min = current_date.replace(hour=0, minute=0, second=0, microsecond=0)
                time_max = current_date.replace(hour=23, minute=59, second=59, microsecond=999999)

                busy_events = fetch_calendar_events(
                    service,
                    stylist.google_calendar_id,
                    time_min.isoformat(),
                    time_max.isoformat()
                )

                # Track calendar health: count events seen and days searched
                days_searched_per_stylist[stylist.id] += 1
                calendar_events_seen[stylist.id] += len(busy_events)

                # DEFENSIVE VALIDATION: Detect suspiciously empty calendars
                # If we've searched 3+ days for this stylist and seen 0 total events,
                # this likely indicates a calendar setup issue (empty calendar, wrong ID, API failure)
                # Rather than showing "100% available", skip this stylist and log warning
                if (days_searched_per_stylist[stylist.id] >= 3 and
                    calendar_events_seen[stylist.id] == 0):
                    logger.warning(
                        f"CALENDAR HEALTH CHECK FAILED for {stylist.name} (ID: {stylist.id}, "
                        f"Calendar ID: {stylist.google_calendar_id}): "
                        f"Returned 0 events across {days_searched_per_stylist[stylist.id]} days. "
                        f"Possible causes: empty calendar, wrong calendar ID, or API failure. "
                        f"Skipping this stylist from availability results to prevent false availability."
                    )
                    skipped_stylists.add(stylist.id)
                    continue

                # Filter available slots for this stylist on this date
                for slot_time in slots:
                    # Stop if we already have enough slots for this stylist
                    if len(all_slots_by_stylist[stylist.id]) >= MAX_SLOTS_PER_STYLIST:
                        break

                    if is_slot_available(
                        slot_time,
                        busy_events,
                        CONSERVATIVE_SERVICE_DURATION_MINUTES
                    ):
                        # Calculate end time
                        end_time = slot_time + timedelta(minutes=CONSERVATIVE_SERVICE_DURATION_MINUTES)

                        # Apply time_range filter if specified
                        slot_data = {
                            "time": slot_time.strftime("%H:%M"),
                            "end_time": end_time.strftime("%H:%M"),
                            "date": current_date.strftime("%Y-%m-%d"),
                            "day_name": day_names_es[current_date.weekday()],
                            "stylist": stylist.name,
                            "stylist_id": str(stylist.id),
                            "full_datetime": slot_time.isoformat(),
                        }

                        # Filter by time_range if specified
                        if time_range:
                            if not _slot_matches_time_range(slot_data, time_range):
                                continue

                        all_slots_by_stylist[stylist.id].append(slot_data)

        # Format results by stylist (group slots by stylist, v3.2: truncate to 5 per stylist)
        available_stylists = []
        total_slots_found = 0
        max_slots_per_stylist = 5  # Limit slots to reduce token usage

        for stylist in stylists:
            stylist_slots = all_slots_by_stylist[stylist.id]
            if stylist_slots:
                # Truncate to first 5 slots per stylist
                truncated_slots = stylist_slots[:max_slots_per_stylist]

                # Simplify slot output: keep essential fields for display and booking
                simplified_slots = [
                    {
                        "time": slot["time"],
                        "date": slot["date"],
                        "day_name": slot["day_name"],
                        "full_datetime": slot["full_datetime"],  # Keep for booking
                        "stylist": slot["stylist"],  # Keep for display "(con Pilar)"
                        "stylist_id": slot["stylist_id"],  # Keep for booking
                    }
                    for slot in truncated_slots
                ]

                available_stylists.append({
                    "stylist_name": stylist.name,
                    "stylist_id": str(stylist.id),
                    "slots": simplified_slots,
                    "slots_shown": len(simplified_slots),
                    "slots_total": len(stylist_slots)
                })
                total_slots_found += len(stylist_slots)

                logger.info(
                    f"Found {len(simplified_slots)}/{len(stylist_slots)} slots for {stylist.name} "
                    f"(truncated to {max_slots_per_stylist})"
                )

        logger.info(
            f"find_next_available completed: {total_slots_found} total slots across "
            f"{len(available_stylists)} stylists (searched {dates_searched} days)"
        )

        return {
            "error": None,
            "available_stylists": available_stylists,  # Changed from available_dates to available_stylists
            "total_slots_found": total_slots_found,
            "dates_searched": dates_searched,
        }

    except Exception as e:
        logger.error(f"Error in find_next_available: {e}", exc_info=True)
        return {
            "error": f"Error searching availability: {str(e)}",
            "available_dates": [],
            "total_slots_found": 0,
            "dates_searched": 0,
        }


def _slot_matches_time_range(slot_data: dict, time_range: str) -> bool:
    """
    Check if a single slot matches the specified time range.

    Args:
        slot_data: Slot dict with "time" field (format: "HH:MM")
        time_range: "morning", "afternoon", or "HH:MM-HH:MM"

    Returns:
        True if slot matches time range, False otherwise
    """
    slot_time = slot_data["time"]

    if time_range.lower() == "morning":
        # Morning: before 14:00
        return slot_time < "14:00"
    elif time_range.lower() == "afternoon":
        # Afternoon: 14:00 or later
        return slot_time >= "14:00"
    elif "-" in time_range:
        # Specific range like "14:00-18:00"
        try:
            start, end = time_range.split("-")
            return start <= slot_time < end
        except ValueError:
            logger.warning(f"Invalid time range format: {time_range}")
            return True  # Include slot if format is invalid
    else:
        logger.warning(f"Unknown time range: {time_range}")
        return True  # Include slot if format is unknown


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

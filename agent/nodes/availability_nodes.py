"""
Multi-calendar availability checking nodes for booking flow.

This module implements the availability checking and slot selection logic
that queries multiple stylist calendars and presents prioritized options
to customers.

Key Features:
- Check availability across all stylists for a service category
- Support for preferred stylist filtering
- Slot prioritization (preferred stylist, earlier times, load balancing)
- Same-day booking time filtering (1-hour buffer)
- Alternative date suggestions when fully booked
- Spanish day name formatting for responses
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from agent.state.schemas import ConversationState
from agent.tools.booking_tools import calculate_total
from agent.tools.calendar_tools import (
    check_holiday_closure,
    fetch_calendar_events,
    generate_time_slots,
    get_calendar_client,
    get_stylist_by_id,
    get_stylists_by_category,
    is_slot_available,
)
from database.connection import get_async_session
from database.models import Service, ServiceCategory, Stylist

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

TIMEZONE = ZoneInfo("Europe/Madrid")

# Spanish day names mapping
DAY_NAMES_ES = {
    "Monday": "lunes",
    "Tuesday": "martes",
    "Wednesday": "miércoles",
    "Thursday": "jueves",
    "Friday": "viernes",
    "Saturday": "sábado",
    "Sunday": "domingo"
}

# Spanish month names mapping
MONTH_NAMES_ES = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre"
}

# Same-day booking buffer
SAME_DAY_BUFFER_HOURS = 1

# Number of slots to present to customer
MAX_SLOTS_TO_PRESENT = 3

# Maximum days ahead to search for alternatives
MAX_ALTERNATIVE_SEARCH_DAYS = 7

# Number of alternative dates to suggest
NUM_ALTERNATIVE_DATES = 2


# ============================================================================
# Helper Functions
# ============================================================================


def get_spanish_day_name(date: datetime) -> str:
    """
    Get Spanish name for day of week.

    Args:
        date: Date to get day name for

    Returns:
        Spanish day name (e.g., "viernes")
    """
    english_day = date.strftime("%A")
    return DAY_NAMES_ES.get(english_day, english_day.lower())


def format_spanish_date(date: datetime) -> str:
    """
    Format date in Spanish format: "viernes 15 de marzo".

    Args:
        date: Date to format

    Returns:
        Formatted date string in Spanish
    """
    day_name = get_spanish_day_name(date)
    day_num = date.day
    month_name = MONTH_NAMES_ES.get(date.month, "")

    return f"{day_name} {day_num} de {month_name}"


def filter_same_day_slots(slots: list[dict], requested_date: datetime) -> list[dict]:
    """
    Filter out slots that are too soon for same-day bookings.

    Same-day bookings require at least 1 hour notice to allow stylists
    time to prepare and customers time to travel.

    Args:
        slots: List of available slot dictionaries
        requested_date: The requested appointment date

    Returns:
        Filtered list of slots (>= 1 hour from now)
    """
    current_time = datetime.now(TIMEZONE)
    current_date = current_time.date()

    # If not same-day, return all slots
    if requested_date.date() != current_date:
        return slots

    # Calculate earliest allowed time (now + buffer)
    earliest_time = current_time + timedelta(hours=SAME_DAY_BUFFER_HOURS)

    # Filter slots
    filtered_slots = []
    for slot in slots:
        # Parse slot time and combine with requested date
        slot_time_str = slot["time"]
        hour, minute = map(int, slot_time_str.split(":"))
        slot_datetime = requested_date.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )

        if slot_datetime >= earliest_time:
            filtered_slots.append(slot)

    logger.info(
        f"Same-day filtering: {len(slots)} slots -> {len(filtered_slots)} slots "
        f"(earliest allowed: {earliest_time.strftime('%H:%M')})"
    )

    return filtered_slots


def prioritize_slots(
    slots: list[dict],
    preferred_stylist_id: UUID | None = None,
    load_balancing: bool = True
) -> list[dict]:
    """
    Prioritize and select top 2-3 slots based on business rules.

    Prioritization Rules (in order):
    1. Preferred Stylist: If set, prioritize that stylist's slots first
    2. Earlier Times: Within same stylist, sort by earliest start time
    3. Load Balancing: Distribute selections across different stylists when possible

    Args:
        slots: List of available slot dictionaries
        preferred_stylist_id: UUID of preferred stylist (if any)
        load_balancing: Whether to distribute across different stylists

    Returns:
        List of top 2-3 prioritized slots
    """
    if not slots:
        return []

    # Sort slots by time first
    sorted_slots = sorted(slots, key=lambda s: s["time"])

    # If preferred stylist is set, separate their slots
    if preferred_stylist_id:
        preferred_slots = [
            s for s in sorted_slots
            if s["stylist_id"] == str(preferred_stylist_id)
        ]
        other_slots = [
            s for s in sorted_slots
            if s["stylist_id"] != str(preferred_stylist_id)
        ]

        # If preferred stylist has slots, prioritize those
        if preferred_slots:
            # Select up to MAX_SLOTS_TO_PRESENT from preferred stylist
            selected = preferred_slots[:MAX_SLOTS_TO_PRESENT]

            logger.info(
                f"Selected {len(selected)} slots from preferred stylist "
                f"{preferred_slots[0]['stylist_name']}"
            )
            return selected

        # Preferred stylist has no availability, use others
        sorted_slots = other_slots

    # No preferred stylist or preferred stylist not available
    # Apply load balancing if enabled
    if load_balancing and len(sorted_slots) > MAX_SLOTS_TO_PRESENT:
        selected = []
        seen_stylists = set()

        # First pass: select one slot from each stylist (diversity)
        for slot in sorted_slots:
            stylist_id = slot["stylist_id"]
            if stylist_id not in seen_stylists:
                selected.append(slot)
                seen_stylists.add(stylist_id)

            if len(selected) >= MAX_SLOTS_TO_PRESENT:
                break

        # If we still need more slots, add earliest available
        if len(selected) < MAX_SLOTS_TO_PRESENT:
            for slot in sorted_slots:
                if slot not in selected:
                    selected.append(slot)
                if len(selected) >= MAX_SLOTS_TO_PRESENT:
                    break

        logger.info(
            f"Load-balanced selection: {len(selected)} slots across "
            f"{len(seen_stylists)} stylists"
        )
        return selected

    # No load balancing or not enough slots - just take first MAX_SLOTS_TO_PRESENT
    selected = sorted_slots[:MAX_SLOTS_TO_PRESENT]

    logger.info(f"Selected {len(selected)} slots (earliest times)")
    return selected


def format_availability_response(slots: list[dict], date: datetime) -> str:
    """
    Format availability response with Maite's warm Spanish tone.

    Args:
        slots: List of 1-3 prioritized slot dictionaries
        date: Date of availability

    Returns:
        Formatted Spanish response string
    """
    day_name = get_spanish_day_name(date)
    num_slots = len(slots)

    if num_slots == 0:
        # This shouldn't happen (handled by alternative dates flow)
        return f"No tenemos disponibilidad ese {day_name} 😔"

    elif num_slots == 1:
        slot = slots[0]
        return (
            f"Este {day_name} tenemos libre a las {slot['time']} con "
            f"{slot['stylist_name']}. ¿Te viene bien? 🌸"
        )

    elif num_slots == 2:
        s1, s2 = slots[0], slots[1]
        return (
            f"Este {day_name} tenemos libre a las {s1['time']} con {s1['stylist_name']} "
            f"y a las {s2['time']} con {s2['stylist_name']}. ¿Cuál prefieres? 😊"
        )

    else:  # 3 slots
        s1, s2, s3 = slots[0], slots[1], slots[2]
        return (
            f"Este {day_name} tenemos libre a las {s1['time']} con {s1['stylist_name']}, "
            f"a las {s2['time']} con {s2['stylist_name']} y a las {s3['time']} con "
            f"{s3['stylist_name']}. ¿Cuál te viene mejor? 💕"
        )


async def query_all_stylists_parallel(
    stylists: list[Stylist],
    date: datetime,
    time_slots: list[datetime],
    conversation_id: str = ""
) -> list[dict]:
    """
    Query all stylist calendars in parallel for maximum performance.

    Uses asyncio.gather() to query calendars concurrently, with graceful
    degradation if some calendars fail.

    Args:
        stylists: List of Stylist model instances to check
        date: Date to check availability for
        time_slots: List of potential time slots to check
        conversation_id: For logging traceability

    Returns:
        List of available slot dictionaries
    """
    start_time = datetime.now()

    # Prepare time range
    time_min = date.replace(hour=0, minute=0, second=0, microsecond=0)
    time_max = date.replace(hour=23, minute=59, second=59, microsecond=999999)
    time_min_str = time_min.isoformat()
    time_max_str = time_max.isoformat()

    # Get calendar service
    calendar_client = get_calendar_client()
    service = calendar_client.get_service()

    # Define async task for fetching one stylist's calendar
    async def fetch_stylist_availability(stylist: Stylist) -> list[dict]:
        """Fetch availability for a single stylist."""
        try:
            # Fetch busy events (using synchronous API in thread pool)
            loop = asyncio.get_event_loop()
            busy_events = await loop.run_in_executor(
                None,
                fetch_calendar_events,
                service,
                stylist.google_calendar_id,
                time_min_str,
                time_max_str
            )

            # Check each time slot
            available_slots = []
            for slot_time in time_slots:
                if is_slot_available(slot_time, busy_events):
                    available_slots.append({
                        "time": slot_time.strftime("%H:%M"),
                        "stylist_id": str(stylist.id),
                        "stylist_name": stylist.name
                    })

            logger.debug(
                f"Stylist {stylist.name}: {len(available_slots)} slots available"
            )
            return available_slots

        except Exception as e:
            logger.error(
                f"Error fetching calendar for {stylist.name} | "
                f"conversation_id={conversation_id}: {e}"
            )
            # Return empty list on error (graceful degradation)
            return []

    # Query all stylists in parallel
    tasks = [fetch_stylist_availability(s) for s in stylists]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect all successful results
    all_slots = []
    successful_count = 0

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(
                f"Exception querying stylist {stylists[i].name}: {result} | "
                f"conversation_id={conversation_id}"
            )
        elif isinstance(result, list):
            all_slots.extend(result)
            successful_count += 1

    # Log performance
    elapsed_time = (datetime.now() - start_time).total_seconds()

    logger.info(
        f"Multi-calendar query completed in {elapsed_time:.2f}s | "
        f"stylists_queried={len(stylists)} | successful={successful_count} | "
        f"total_slots={len(all_slots)} | conversation_id={conversation_id}"
    )

    # Warn if performance is slow
    if elapsed_time > 8:
        logger.warning(
            f"Slow availability check: {elapsed_time:.2f}s (target: <8s) | "
            f"conversation_id={conversation_id}"
        )

    return all_slots


async def suggest_alternative_dates(
    requested_date: datetime,
    category: str,
    preferred_stylist_id: UUID | None = None,
    conversation_id: str = ""
) -> list[dict]:
    """
    Suggest alternative dates when requested date is fully booked.

    Searches forward from requested date, skipping Sundays and holidays,
    until it finds NUM_ALTERNATIVE_DATES with availability.

    Args:
        requested_date: Originally requested date
        category: Service category to check
        preferred_stylist_id: Optional preferred stylist filter
        conversation_id: For logging traceability

    Returns:
        List of alternative date dictionaries with format:
        [{"date": datetime, "day_name": str, "formatted": str}]
    """
    alternatives = []
    current_date = requested_date + timedelta(days=1)
    days_searched = 0

    calendar_client = get_calendar_client()
    service = calendar_client.get_service()

    while len(alternatives) < NUM_ALTERNATIVE_DATES and days_searched < MAX_ALTERNATIVE_SEARCH_DAYS:
        # Skip Sundays (salon closed)
        if current_date.weekday() == 6:
            current_date += timedelta(days=1)
            days_searched += 1
            continue

        # Check for holidays
        holiday_info = await check_holiday_closure(
            service,
            current_date,
            conversation_id
        )

        if holiday_info:
            logger.debug(
                f"Skipping {current_date.date()} (holiday: {holiday_info.get('reason')})"
            )
            current_date += timedelta(days=1)
            days_searched += 1
            continue

        # Query stylists for this date
        if preferred_stylist_id:
            stylist = await get_stylist_by_id(preferred_stylist_id)
            stylists = [stylist] if stylist else []
        else:
            stylists = await get_stylists_by_category(category)

        if not stylists:
            logger.warning(
                f"No stylists found for category {category} | "
                f"conversation_id={conversation_id}"
            )
            break

        # Generate time slots
        day_of_week = current_date.weekday()
        time_slots = generate_time_slots(current_date, day_of_week)

        if not time_slots:
            # This date is closed (shouldn't happen after Sunday check)
            current_date += timedelta(days=1)
            days_searched += 1
            continue

        # Query availability in parallel
        available_slots = await query_all_stylists_parallel(
            stylists,
            current_date,
            time_slots,
            conversation_id
        )

        # If we found availability, add this date as alternative
        if available_slots:
            alternatives.append({
                "date": current_date,
                "day_name": get_spanish_day_name(current_date),
                "formatted": format_spanish_date(current_date),
                "available_count": len(available_slots)
            })

            logger.debug(
                f"Alternative date found: {current_date.date()} "
                f"({len(available_slots)} slots)"
            )

        current_date += timedelta(days=1)
        days_searched += 1

    logger.info(
        f"Found {len(alternatives)} alternative dates after searching {days_searched} days | "
        f"conversation_id={conversation_id}"
    )

    return alternatives


# ============================================================================
# LangGraph Node Functions
# ============================================================================


async def check_availability(state: ConversationState) -> dict[str, Any]:
    """
    Check availability across multiple stylist calendars.

    Main entry point node for availability checking. Queries all relevant
    stylists (filtered by category and optional preferred stylist),
    prioritizes slots, and prepares response.

    Args:
        state: Current conversation state with requested_services and requested_date

    Returns:
        Updated state with:
        - available_slots: All available slots found
        - prioritized_slots: Top 2-3 slots to present
        - is_same_day: Boolean flag for same-day booking
        - bot_response: Formatted Spanish response (if slots found)
    """
    conversation_id = state.get("conversation_id", "")

    try:
        # Extract required fields from state
        requested_services = state.get("requested_services", [])
        requested_date_str = state.get("requested_date")
        preferred_stylist_id = state.get("preferred_stylist_id")

        # Validate inputs
        if not requested_services:
            logger.error(f"check_availability: No services requested | conversation_id={conversation_id}")
            return {
                "error": "No se especificaron servicios 😔",
                "available_slots": [],
                "prioritized_slots": []
            }

        if not requested_date_str:
            logger.error(f"check_availability: No date requested | conversation_id={conversation_id}")
            return {
                "error": "No se especificó fecha 😔",
                "available_slots": [],
                "prioritized_slots": []
            }

        # Parse date
        try:
            requested_date = datetime.strptime(requested_date_str, "%Y-%m-%d").replace(
                tzinfo=TIMEZONE
            )
        except ValueError:
            logger.error(
                f"Invalid date format: {requested_date_str} | conversation_id={conversation_id}"
            )
            return {
                "error": "Formato de fecha inválido 😔",
                "available_slots": [],
                "prioritized_slots": []
            }

        # Query services to determine category
        async with get_async_session() as session:
            query = select(Service).where(Service.id.in_(requested_services))
            result = await session.execute(query)
            services = list(result.scalars().all())

        if not services:
            logger.error(
                f"Services not found: {requested_services} | conversation_id={conversation_id}"
            )
            return {
                "error": "Servicios no encontrados 😔",
                "available_slots": [],
                "prioritized_slots": []
            }

        # Determine category from services
        categories = set(s.category for s in services)

        if len(categories) > 1:
            # Services span multiple categories - not supported in this story
            logger.warning(
                f"Services span multiple categories: {categories} | "
                f"conversation_id={conversation_id}"
            )
            return {
                "error": "Los servicios requieren diferentes especialidades. Por favor, contacta con nosotros. 🙏",
                "available_slots": [],
                "prioritized_slots": []
            }

        category = categories.pop().value  # Get ServiceCategory enum value

        logger.info(
            f"Checking availability: category={category}, date={requested_date_str}, "
            f"services={len(services)}, preferred_stylist={preferred_stylist_id} | "
            f"conversation_id={conversation_id}"
        )

        # Check for holidays
        calendar_client = get_calendar_client()
        service_client = calendar_client.get_service()

        holiday_info = await check_holiday_closure(
            service_client,
            requested_date,
            conversation_id
        )

        if holiday_info:
            # Holiday detected - suggest alternatives
            logger.info(
                f"Holiday detected: {holiday_info.get('reason')} | "
                f"conversation_id={conversation_id}"
            )

            alternatives = await suggest_alternative_dates(
                requested_date,
                category,
                preferred_stylist_id,
                conversation_id
            )

            if alternatives:
                alt1, alt2 = alternatives[0], alternatives[1] if len(alternatives) > 1 else alternatives[0]
                response = (
                    f"Ese día estamos cerrados por festivo 🎉. "
                    f"¿Qué tal el {alt1['formatted']} o el {alt2['formatted']}?"
                )
            else:
                response = "Ese día estamos cerrados y no tenemos disponibilidad próxima. Por favor, contacta con nosotros. 🙏"

            return {
                "available_slots": [],
                "prioritized_slots": [],
                "suggested_dates": alternatives,
                "bot_response": response,
                "holiday_detected": True
            }

        # Query stylists
        if preferred_stylist_id:
            stylist = await get_stylist_by_id(preferred_stylist_id)
            stylists = [stylist] if stylist else []

            logger.info(
                f"Checking only preferred stylist: {stylist.name if stylist else 'NOT FOUND'} | "
                f"conversation_id={conversation_id}"
            )
        else:
            stylists = await get_stylists_by_category(category)

            logger.info(
                f"Checking all stylists for category {category}: {len(stylists)} found | "
                f"conversation_id={conversation_id}"
            )

        if not stylists:
            logger.error(
                f"No active stylists found for category {category} | "
                f"conversation_id={conversation_id}"
            )
            return {
                "error": "No hay estilistas disponibles 😔",
                "available_slots": [],
                "prioritized_slots": []
            }

        # Generate time slots
        day_of_week = requested_date.weekday()
        time_slots = generate_time_slots(requested_date, day_of_week)

        if not time_slots:
            # Salon closed on this day (likely Sunday)
            logger.info(
                f"Salon closed on {requested_date.date()} (day_of_week={day_of_week}) | "
                f"conversation_id={conversation_id}"
            )

            alternatives = await suggest_alternative_dates(
                requested_date,
                category,
                preferred_stylist_id,
                conversation_id
            )

            if alternatives:
                alt1 = alternatives[0]
                alt2 = alternatives[1] if len(alternatives) > 1 else alternatives[0]
                response = (
                    f"Los domingos estamos cerrados 😔. "
                    f"¿Qué tal el {alt1['formatted']} o el {alt2['formatted']}?"
                )
            else:
                response = "Los domingos estamos cerrados y no tenemos disponibilidad próxima. Por favor, contacta con nosotros. 🙏"

            return {
                "available_slots": [],
                "prioritized_slots": [],
                "suggested_dates": alternatives,
                "bot_response": response
            }

        # Query all stylists in parallel
        available_slots = await query_all_stylists_parallel(
            stylists,
            requested_date,
            time_slots,
            conversation_id
        )

        # Check if same-day and filter slots if needed
        current_date = datetime.now(TIMEZONE).date()
        is_same_day = requested_date.date() == current_date

        if is_same_day:
            available_slots = filter_same_day_slots(available_slots, requested_date)
            logger.info(
                f"Same-day booking: {len(available_slots)} slots after filtering | "
                f"conversation_id={conversation_id}"
            )

        # If no availability, suggest alternatives
        if not available_slots:
            logger.info(
                f"No availability on {requested_date_str}, suggesting alternatives | "
                f"conversation_id={conversation_id}"
            )

            alternatives = await suggest_alternative_dates(
                requested_date,
                category,
                preferred_stylist_id,
                conversation_id
            )

            if alternatives:
                alt1 = alternatives[0]
                alt2 = alternatives[1] if len(alternatives) > 1 else alternatives[0]
                response = (
                    f"Ese día no tenemos disponibilidad 😔. "
                    f"¿Qué tal el {alt1['formatted']} o el {alt2['formatted']}?"
                )
            else:
                response = "No tenemos disponibilidad próxima. Por favor, contacta con nosotros. 🙏"

            return {
                "available_slots": [],
                "prioritized_slots": [],
                "suggested_dates": alternatives,
                "bot_response": response,
                "is_same_day": is_same_day
            }

        # Prioritize slots
        prioritized = prioritize_slots(
            available_slots,
            preferred_stylist_id,
            load_balancing=True
        )

        # Format response
        response = format_availability_response(prioritized, requested_date)

        logger.info(
            f"Availability check complete: {len(available_slots)} total slots, "
            f"{len(prioritized)} prioritized | conversation_id={conversation_id}"
        )

        return {
            "available_slots": available_slots,
            "prioritized_slots": prioritized,
            "bot_response": response,
            "is_same_day": is_same_day
        }

    except Exception as e:
        logger.exception(
            f"Unexpected error in check_availability | conversation_id={conversation_id}: {e}"
        )
        return {
            "error": "No pudimos consultar la disponibilidad. Por favor, inténtalo de nuevo. 🙏",
            "available_slots": [],
            "prioritized_slots": []
        }

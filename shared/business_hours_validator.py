"""
Centralized Business Hours Validation - Single Source of Truth.

This module provides database-driven validation for business hours and closed days.
ALL code checking if a day/date is closed MUST use these functions to ensure consistency.

Design Principles:
- Database is the single source of truth (no hardcoded logic)
- Async-first for integration with availability tools and FSM
- Fails closed on errors (safer than false availability)
- Returns Spanish error messages for user-facing contexts

Usage:
    from shared.business_hours_validator import is_day_closed, is_date_closed

    # Check if Monday is closed
    if await is_day_closed(0):  # 0 = Monday
        print("Monday is closed")

    # Check if specific date is closed
    from datetime import datetime
    if await is_date_closed(datetime(2025, 12, 7)):  # Sunday
        print("Sunday is closed")
"""

import logging
from datetime import datetime, date, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select

from database.connection import get_async_session
from database.models import BusinessHours

logger = logging.getLogger(__name__)

# Spanish day names for error messages
DAY_NAMES_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

MADRID_TZ = ZoneInfo("Europe/Madrid")


async def is_day_closed(day_of_week: int) -> bool:
    """
    Check if a specific day of the week is closed.

    This is the SINGLE SOURCE OF TRUTH for closed day checks.
    Queries the database business_hours table.

    Args:
        day_of_week: Day of week (0=Monday, 1=Tuesday, ..., 6=Sunday)

    Returns:
        True if day is closed, False if open.
        Returns True (fail closed) on database errors for safety.

    Example:
        >>> await is_day_closed(0)  # Monday
        True
        >>> await is_day_closed(2)  # Wednesday
        False
        >>> await is_day_closed(6)  # Sunday
        True
    """
    if not (0 <= day_of_week <= 6):
        logger.error(f"Invalid day_of_week: {day_of_week}. Must be 0-6.")
        return True  # Fail closed for invalid input

    try:
        async with get_async_session() as session:
            result = await session.execute(
                select(BusinessHours.is_closed).where(
                    BusinessHours.day_of_week == day_of_week
                )
            )
            row = result.first()

            if row is None:
                logger.warning(
                    f"No business hours found for day_of_week={day_of_week} ({DAY_NAMES_ES[day_of_week]}). "
                    f"Defaulting to CLOSED for safety."
                )
                return True  # Fail closed if no config found

            is_closed = row[0]
            logger.debug(
                f"Day {day_of_week} ({DAY_NAMES_ES[day_of_week]}): "
                f"{'CLOSED' if is_closed else 'OPEN'}"
            )
            return is_closed

    except Exception as e:
        logger.error(
            f"Error checking if day_of_week={day_of_week} is closed: {e}",
            exc_info=True
        )
        return True  # Fail closed on database errors


async def is_date_closed(target_date: datetime | date) -> bool:
    """
    Check if a specific date is closed.

    Convenience wrapper around is_day_closed() for date objects.

    Args:
        target_date: datetime or date object to check

    Returns:
        True if date falls on a closed day, False if open.

    Example:
        >>> from datetime import datetime
        >>> await is_date_closed(datetime(2025, 12, 7))  # Sunday
        True
        >>> await is_date_closed(datetime(2025, 12, 9))  # Tuesday
        False
    """
    day_of_week = target_date.weekday()
    return await is_day_closed(day_of_week)


async def get_next_open_date(
    start_date: datetime,
    max_search_days: int = 14
) -> Optional[datetime]:
    """
    Find the next open date starting from start_date.

    Searches forward up to max_search_days to find a date that is not closed.
    Returns None if no open date found within search window.

    Args:
        start_date: Date to start searching from (timezone-aware datetime)
        max_search_days: Maximum days to search forward (default: 14)

    Returns:
        Next open date as timezone-aware datetime, or None if not found.

    Example:
        >>> from datetime import datetime
        >>> from zoneinfo import ZoneInfo
        >>> start = datetime(2025, 12, 7, tzinfo=ZoneInfo("Europe/Madrid"))  # Sunday
        >>> next_open = await get_next_open_date(start)
        >>> # Returns Tuesday Dec 9 (skips Sunday + Monday)
    """
    current_date = start_date
    days_searched = 0

    while days_searched < max_search_days:
        if not await is_date_closed(current_date):
            logger.info(
                f"Found next open date: {current_date.date()} ({DAY_NAMES_ES[current_date.weekday()]})"
            )
            return current_date

        # Move to next day
        current_date += timedelta(days=1)
        days_searched += 1

    logger.warning(
        f"No open date found within {max_search_days} days from {start_date.date()}"
    )
    return None


async def validate_slot_on_open_day(slot: dict) -> tuple[bool, Optional[str]]:
    """
    Validate that a slot falls on an open day (not closed).

    This is used by the FSM to reject slots that fall on closed days before
    advancing to CUSTOMER_DATA state.

    Args:
        slot: Slot dictionary with 'start_time' key (ISO 8601 string)
              Example: {"start_time": "2025-12-07T10:00:00+01:00", "duration_minutes": 60}

    Returns:
        Tuple of (is_valid, error_message):
        - (True, None) if slot is on open day
        - (False, "error message in Spanish") if slot is on closed day

    Example:
        >>> slot = {"start_time": "2025-12-07T10:00:00+01:00", "duration_minutes": 60}
        >>> is_valid, error = await validate_slot_on_open_day(slot)
        >>> # Returns: (False, "El salón está cerrado los domingos")
    """
    try:
        start_time_str = slot.get("start_time")
        if not start_time_str:
            return False, "El slot no tiene fecha/hora de inicio (start_time)"

        # Parse ISO 8601 datetime
        start_time = datetime.fromisoformat(start_time_str)

        # Check if day is closed
        if await is_date_closed(start_time):
            day_name = DAY_NAMES_ES[start_time.weekday()]
            error_msg = f"El salón está cerrado los {day_name}s"
            logger.warning(
                f"Slot validation failed: {start_time.date()} ({day_name}) is closed"
            )
            return False, error_msg

        # Day is open
        return True, None

    except (ValueError, AttributeError) as e:
        error_msg = f"Formato de fecha inválido en el slot: {e}"
        logger.error(f"Slot validation error: {error_msg}", exc_info=True)
        return False, error_msg


async def get_business_hours_for_day(day_of_week: int) -> Optional[dict[str, int]]:
    """
    Get business hours (start/end hours) for a specific day.

    Args:
        day_of_week: Day of week (0=Monday, 1=Tuesday, ..., 6=Sunday)

    Returns:
        Dictionary with 'start' and 'end' hours if day is open, None if closed.
        Example: {"start": 10, "end": 20} for Tuesday-Friday
        Example: {"start": 9, "end": 14} for Saturday
        Example: None for Monday/Sunday (closed)

    Example:
        >>> await get_business_hours_for_day(2)  # Wednesday
        {"start": 10, "end": 20}
        >>> await get_business_hours_for_day(6)  # Sunday
        None
    """
    if not (0 <= day_of_week <= 6):
        logger.error(f"Invalid day_of_week: {day_of_week}. Must be 0-6.")
        return None

    try:
        async with get_async_session() as session:
            result = await session.execute(
                select(BusinessHours).where(
                    BusinessHours.day_of_week == day_of_week
                )
            )
            business_hours = result.scalar_one_or_none()

            if business_hours is None:
                logger.warning(
                    f"No business hours found for day_of_week={day_of_week} ({DAY_NAMES_ES[day_of_week]})"
                )
                return None

            if business_hours.is_closed:
                logger.debug(f"Day {day_of_week} ({DAY_NAMES_ES[day_of_week]}) is closed")
                return None

            if business_hours.start_hour is None or business_hours.end_hour is None:
                logger.warning(
                    f"Business hours for day_of_week={day_of_week} has NULL hours but is_closed=False"
                )
                return None

            return {
                "start": business_hours.start_hour,
                "end": business_hours.end_hour,
            }

    except Exception as e:
        logger.error(
            f"Error fetching business hours for day_of_week={day_of_week}: {e}",
            exc_info=True
        )
        return None

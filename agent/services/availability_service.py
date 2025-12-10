"""
DB-First Availability Service.

This module provides availability checking using PostgreSQL as the single source of truth.
All availability queries hit the database instead of Google Calendar API, providing:
- Sub-100ms response times (vs 2-5 seconds with Google Calendar)
- Consistent data (no sync issues between DB and external calendar)
- Support for blocking events and holidays stored in DB

Architecture:
- PostgreSQL = source of truth for all availability
- Google Calendar = push-only mirror (fire-and-forget sync for stylist mobile viewing)

Usage:
    from agent.services.availability_service import (
        check_slot_availability,
        get_available_slots,
        is_holiday,
    )

    # Check if a specific slot is available
    result = await check_slot_availability(
        stylist_id=uuid,
        start_time=datetime,
        duration_minutes=90
    )

    # Get all available slots for a date
    slots = await get_available_slots(
        stylist_id=uuid,
        date=target_date,
        service_duration_minutes=90
    )
"""

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_async_session
from database.models import Appointment, AppointmentStatus, BlockingEvent, Holiday, Stylist
from shared.business_hours_validator import get_business_hours_for_day, is_date_closed

logger = logging.getLogger(__name__)

MADRID_TZ = ZoneInfo("Europe/Madrid")


async def is_holiday(target_date: date | datetime) -> Optional[str]:
    """
    Check if a date is a salon holiday.

    Queries the holidays table for salon-wide closures.

    Args:
        target_date: Date or datetime to check

    Returns:
        Holiday name if it's a holiday, None otherwise

    Example:
        >>> await is_holiday(date(2025, 12, 25))
        "Navidad"
        >>> await is_holiday(date(2025, 11, 15))
        None
    """
    # Normalize to date
    if isinstance(target_date, datetime):
        check_date = target_date.date()
    else:
        check_date = target_date

    try:
        async with get_async_session() as session:
            result = await session.execute(
                select(Holiday.name).where(Holiday.date == check_date)
            )
            row = result.first()

            if row:
                holiday_name = row[0]
                logger.info(f"Holiday found on {check_date}: {holiday_name}")
                return holiday_name

            return None

    except Exception as e:
        logger.error(f"Error checking holiday for {check_date}: {e}", exc_info=True)
        return None  # Fail open for holidays (don't block if DB error)


async def get_busy_periods(
    stylist_id: UUID,
    start_time: datetime,
    end_time: datetime,
    session: Optional[AsyncSession] = None,
) -> list[dict[str, Any]]:
    """
    Get all busy periods for a stylist within a time range.

    Queries both appointments and blocking_events tables.

    Args:
        stylist_id: UUID of the stylist
        start_time: Start of time range (timezone-aware)
        end_time: End of time range (timezone-aware)
        session: Optional existing database session

    Returns:
        List of busy periods with start, end, type, and title:
        [
            {
                "start": datetime,
                "end": datetime,
                "type": "appointment" | "blocking_event",
                "title": str,
                "status": str | None  # Only for appointments
            }
        ]
    """
    busy_periods = []

    async def _fetch(sess: AsyncSession) -> list[dict[str, Any]]:
        periods = []

        # Query appointments (PENDING or CONFIRMED only)
        appt_result = await sess.execute(
            select(Appointment).where(
                and_(
                    Appointment.stylist_id == stylist_id,
                    Appointment.status.in_([AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED]),
                    # Overlap check: appointment overlaps with the time range
                    Appointment.start_time < end_time,
                    Appointment.start_time + Appointment.duration_minutes * timedelta(minutes=1) > start_time,
                )
            )
        )
        appointments = appt_result.scalars().all()

        for appt in appointments:
            appt_end = appt.start_time + timedelta(minutes=appt.duration_minutes)
            periods.append({
                "start": appt.start_time,
                "end": appt_end,
                "type": "appointment",
                "title": f"Cita: {appt.first_name}",
                "status": appt.status.value,
            })

        # Query blocking events
        block_result = await sess.execute(
            select(BlockingEvent).where(
                and_(
                    BlockingEvent.stylist_id == stylist_id,
                    # Overlap check
                    BlockingEvent.start_time < end_time,
                    BlockingEvent.end_time > start_time,
                )
            )
        )
        blocking_events = block_result.scalars().all()

        for block in blocking_events:
            periods.append({
                "start": block.start_time,
                "end": block.end_time,
                "type": "blocking_event",
                "title": block.title,
                "event_type": block.event_type.value,
            })

        # Sort by start time
        periods.sort(key=lambda p: p["start"])
        return periods

    try:
        if session:
            busy_periods = await _fetch(session)
        else:
            async with get_async_session() as sess:
                busy_periods = await _fetch(sess)

        logger.debug(
            f"Found {len(busy_periods)} busy periods for stylist {stylist_id} "
            f"between {start_time} and {end_time}"
        )
        return busy_periods

    except Exception as e:
        logger.error(f"Error fetching busy periods: {e}", exc_info=True)
        return []


async def check_slot_availability(
    stylist_id: UUID,
    start_time: datetime,
    duration_minutes: int,
) -> dict[str, Any]:
    """
    Check if a specific time slot is available for a stylist.

    Performs comprehensive conflict check against:
    1. Holidays (salon-wide closures)
    2. Business hours (salon opening times)
    3. Blocking events (vacations, meetings, breaks)
    4. Existing appointments (PENDING, CONFIRMED)

    Args:
        stylist_id: UUID of the stylist
        start_time: Proposed start time (timezone-aware)
        duration_minutes: Duration of the service in minutes

    Returns:
        {
            "available": bool,
            "conflict_type": str | None,  # "holiday", "closed", "blocking_event", "appointment"
            "conflict_details": str | None,  # Human-readable description
        }

    Example:
        >>> result = await check_slot_availability(
        ...     stylist_id=uuid,
        ...     start_time=datetime(2025, 12, 15, 10, 0, tzinfo=MADRID_TZ),
        ...     duration_minutes=90
        ... )
        >>> result
        {"available": True, "conflict_type": None, "conflict_details": None}
    """
    end_time = start_time + timedelta(minutes=duration_minutes)

    try:
        # 1. Check if it's a holiday
        holiday_name = await is_holiday(start_time.date())
        if holiday_name:
            return {
                "available": False,
                "conflict_type": "holiday",
                "conflict_details": f"El salón está cerrado por {holiday_name}",
            }

        # 2. Check if day is closed (business hours)
        if await is_date_closed(start_time):
            day_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
            day_name = day_names[start_time.weekday()]
            return {
                "available": False,
                "conflict_type": "closed",
                "conflict_details": f"El salón está cerrado los {day_name}s",
            }

        # 3. Check business hours for the slot
        business_hours = await get_business_hours_for_day(start_time.weekday())
        if business_hours:
            slot_start_hour = start_time.hour + start_time.minute / 60
            slot_end_hour = end_time.hour + end_time.minute / 60

            if slot_start_hour < business_hours["start"]:
                return {
                    "available": False,
                    "conflict_type": "closed",
                    "conflict_details": f"El salón abre a las {business_hours['start']:02d}:00",
                }

            if slot_end_hour > business_hours["end"]:
                return {
                    "available": False,
                    "conflict_type": "closed",
                    "conflict_details": f"El salón cierra a las {business_hours['end']:02d}:00",
                }

        # 4. Check for conflicts with appointments and blocking events
        busy_periods = await get_busy_periods(stylist_id, start_time, end_time)

        for period in busy_periods:
            # Check if there's any overlap
            if period["start"] < end_time and period["end"] > start_time:
                if period["type"] == "appointment":
                    return {
                        "available": False,
                        "conflict_type": "appointment",
                        "conflict_details": f"El estilista tiene otra cita a esa hora",
                    }
                else:
                    return {
                        "available": False,
                        "conflict_type": "blocking_event",
                        "conflict_details": f"El estilista no está disponible: {period['title']}",
                    }

        # No conflicts found
        return {
            "available": True,
            "conflict_type": None,
            "conflict_details": None,
        }

    except Exception as e:
        logger.error(f"Error checking slot availability: {e}", exc_info=True)
        # Fail closed on errors (return unavailable)
        return {
            "available": False,
            "conflict_type": "error",
            "conflict_details": f"Error verificando disponibilidad: {str(e)}",
        }


async def get_available_slots(
    stylist_id: UUID,
    target_date: date | datetime,
    service_duration_minutes: int,
    slot_interval_minutes: int = 15,
) -> list[dict[str, Any]]:
    """
    Get all available time slots for a stylist on a specific date.

    Generates candidate slots based on business hours, then filters out
    slots that conflict with appointments or blocking events.

    Args:
        stylist_id: UUID of the stylist
        target_date: Date to check availability
        service_duration_minutes: Duration of the service in minutes
        slot_interval_minutes: Interval between slot start times (default: 15 min)

    Returns:
        List of available slots:
        [
            {
                "time": "10:00",
                "end_time": "11:30",
                "full_datetime": "2025-12-15T10:00:00+01:00",
                "stylist_id": str,
            }
        ]

    Example:
        >>> slots = await get_available_slots(
        ...     stylist_id=uuid,
        ...     target_date=date(2025, 12, 15),
        ...     service_duration_minutes=90
        ... )
        >>> len(slots)
        8  # Depends on busy periods
    """
    available_slots = []

    # Normalize to date
    if isinstance(target_date, datetime):
        check_date = target_date.date()
    else:
        check_date = target_date

    try:
        # Check if it's a holiday
        holiday_name = await is_holiday(check_date)
        if holiday_name:
            logger.info(f"No slots available on {check_date}: holiday ({holiday_name})")
            return []

        # Check if day is closed
        if await is_date_closed(check_date):
            logger.info(f"No slots available on {check_date}: salon closed")
            return []

        # Get business hours
        day_of_week = check_date.weekday()
        business_hours = await get_business_hours_for_day(day_of_week)

        if not business_hours:
            logger.info(f"No business hours found for {check_date}")
            return []

        # Generate candidate slots
        start_hour = business_hours["start"]
        end_hour = business_hours["end"]

        # Create timezone-aware datetimes for the day boundaries
        day_start = datetime(
            check_date.year, check_date.month, check_date.day,
            start_hour, 0, 0, tzinfo=MADRID_TZ
        )
        day_end = datetime(
            check_date.year, check_date.month, check_date.day,
            end_hour, 0, 0, tzinfo=MADRID_TZ
        )

        # Get all busy periods for the day
        busy_periods = await get_busy_periods(stylist_id, day_start, day_end)

        # Generate slots
        current_slot = day_start
        while current_slot + timedelta(minutes=service_duration_minutes) <= day_end:
            slot_end = current_slot + timedelta(minutes=service_duration_minutes)

            # Check if slot conflicts with any busy period
            is_available = True
            for period in busy_periods:
                if period["start"] < slot_end and period["end"] > current_slot:
                    is_available = False
                    break

            if is_available:
                available_slots.append({
                    "time": current_slot.strftime("%H:%M"),
                    "end_time": slot_end.strftime("%H:%M"),
                    "full_datetime": current_slot.isoformat(),
                    "stylist_id": str(stylist_id),
                })

            # Move to next slot
            current_slot += timedelta(minutes=slot_interval_minutes)

        logger.info(
            f"Found {len(available_slots)} available slots for stylist {stylist_id} "
            f"on {check_date}"
        )
        return available_slots

    except Exception as e:
        logger.error(f"Error getting available slots: {e}", exc_info=True)
        return []


async def get_stylist_by_id(stylist_id: UUID) -> Optional[Stylist]:
    """
    Fetch a stylist by ID.

    Args:
        stylist_id: UUID of the stylist

    Returns:
        Stylist object or None if not found
    """
    try:
        async with get_async_session() as session:
            result = await session.execute(
                select(Stylist).where(
                    and_(
                        Stylist.id == stylist_id,
                        Stylist.is_active == True,
                    )
                )
            )
            return result.scalar_one_or_none()

    except Exception as e:
        logger.error(f"Error fetching stylist {stylist_id}: {e}", exc_info=True)
        return None


async def get_calendar_events_for_range(
    stylist_ids: list[UUID],
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    """
    Get all calendar events (appointments + blocking events) for multiple stylists.

    Used by the admin calendar view to display events.

    Args:
        stylist_ids: List of stylist UUIDs to query
        start_time: Start of time range
        end_time: End of time range

    Returns:
        List of calendar events formatted for FullCalendar:
        [
            {
                "id": str,
                "title": str,
                "start": str (ISO 8601),
                "end": str (ISO 8601),
                "backgroundColor": str,
                "borderColor": str,
                "extendedProps": {...}
            }
        ]
    """
    events = []

    try:
        async with get_async_session() as session:
            # Fetch appointments - simplified query to avoid timezone issues
            # The datetime arithmetic in SQL causes "can't subtract offset-naive and offset-aware datetimes"
            # So we fetch a broader range and filter in Python
            appt_result = await session.execute(
                select(Appointment).where(
                    and_(
                        Appointment.stylist_id.in_(stylist_ids),
                        Appointment.status.in_([
                            AppointmentStatus.PENDING,
                            AppointmentStatus.CONFIRMED,
                        ]),
                        Appointment.start_time < end_time,
                        Appointment.start_time >= start_time - timedelta(hours=24),  # Buffer for duration
                    )
                )
            )
            all_appointments = appt_result.scalars().all()

            # Filter in Python for exact overlap check (appointment ends after our start time)
            appointments = [
                appt for appt in all_appointments
                if appt.start_time + timedelta(minutes=appt.duration_minutes) > start_time
            ]

            for appt in appointments:
                appt_end = appt.start_time + timedelta(minutes=appt.duration_minutes)

                # Convert to Madrid timezone before serialization
                start_madrid = appt.start_time.astimezone(MADRID_TZ)
                end_madrid = appt_end.astimezone(MADRID_TZ)

                events.append({
                    "id": f"appt-{appt.id}",
                    "title": f"{appt.first_name} {appt.last_name or ''}".strip(),
                    "start": start_madrid.isoformat(),
                    "end": end_madrid.isoformat(),
                    "backgroundColor": "#7C3AED",  # Default violet
                    "borderColor": "#7C3AED",
                    "extendedProps": {
                        "appointment_id": str(appt.id),
                        "customer_id": str(appt.customer_id),
                        "stylist_id": str(appt.stylist_id),
                        "status": appt.status.value,
                        "duration_minutes": appt.duration_minutes,
                        "notes": appt.notes,
                        "type": "appointment",
                    },
                })

            # Fetch blocking events
            block_result = await session.execute(
                select(BlockingEvent).where(
                    and_(
                        BlockingEvent.stylist_id.in_(stylist_ids),
                        BlockingEvent.start_time < end_time,
                        BlockingEvent.end_time > start_time,
                    )
                )
            )
            blocking_events = block_result.scalars().all()

            # Color map for blocking event types
            block_colors = {
                "vacation": "#DC2626",   # Red
                "meeting": "#D97706",    # Amber
                "break": "#059669",      # Emerald
                "general": "#6B7280",    # Gray
                "personal": "#EC4899",   # Pink
            }

            for block in blocking_events:
                color = block_colors.get(block.event_type.value, "#6B7280")

                # Convert to Madrid timezone before serialization
                start_madrid = block.start_time.astimezone(MADRID_TZ)
                end_madrid = block.end_time.astimezone(MADRID_TZ)

                events.append({
                    "id": f"block-{block.id}",
                    "title": block.title,
                    "start": start_madrid.isoformat(),
                    "end": end_madrid.isoformat(),
                    "backgroundColor": color,
                    "borderColor": color,
                    "extendedProps": {
                        "blocking_event_id": str(block.id),
                        "stylist_id": str(block.stylist_id),
                        "description": block.description,
                        "event_type": block.event_type.value,
                        "type": "blocking_event",
                    },
                })

            # Fetch holidays (salon-wide closures)
            start_date = start_time.date()
            end_date = end_time.date()

            holiday_result = await session.execute(
                select(Holiday).where(
                    and_(
                        Holiday.date >= start_date,
                        Holiday.date <= end_date,
                    )
                )
            )
            holidays = holiday_result.scalars().all()

            for holiday in holidays:
                events.append({
                    "id": f"holiday-{holiday.id}",
                    "title": f"FESTIVO: {holiday.name}",
                    "start": holiday.date.isoformat(),
                    "end": holiday.date.isoformat(),
                    "allDay": True,
                    "backgroundColor": "#991B1B",  # Dark red
                    "borderColor": "#7F1D1D",
                    "extendedProps": {
                        "holiday_id": str(holiday.id),
                        "type": "holiday",
                    },
                })

        logger.info(
            f"Found {len(events)} calendar events for {len(stylist_ids)} stylists "
            f"between {start_time} and {end_time}"
        )
        return events

    except Exception as e:
        logger.error(f"Error fetching calendar events: {e}", exc_info=True)
        return []

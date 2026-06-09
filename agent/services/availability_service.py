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
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_async_session
from database.models import (
    Appointment,
    AppointmentStatus,
    BlockingEvent,
    Holiday,
    Service,
    ServiceCategory,
    Stylist,
)
from shared.business_hours_validator import get_business_hours_for_day, is_date_closed
from shared.locale import SPANISH_WEEKDAYS

logger = logging.getLogger(__name__)

MADRID_TZ = ZoneInfo("Europe/Madrid")
MAX_FALLBACK_SEARCH_DAYS = 7
MAX_FALLBACK_OPTIONS = 3

FallbackStrategy = Literal["same_stylist_then_any", "any_stylist"]


async def is_holiday(target_date: date | datetime) -> str | None:
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
            result = await session.execute(select(Holiday.name).where(Holiday.date == check_date))
            row = result.first()

            if row:
                holiday_name = row[0]
                logger.info(f"Holiday found on {check_date}: {holiday_name}")
                return holiday_name

            return None

    except Exception as e:
        logger.error(f"Error checking holiday for {check_date}: {e}", exc_info=True)
        return "DB_UNAVAILABLE"  # Fail closed: block slot when DB is unavailable


async def get_busy_periods(
    stylist_id: UUID,
    start_time: datetime,
    end_time: datetime,
    session: AsyncSession | None = None,
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

        # Query appointments (PENDING, CONFIRMED, or non-expired HOLD)
        # Broad range fetch — exact overlap filtered in Python to avoid tz-naive vs
        # tz-aware DataError in SQL datetime arithmetic (same pattern as
        # get_calendar_events_for_range, line 628). The SQL interval arithmetic
        # `start_time + duration * timedelta(minutes=1)` produces TIMESTAMP WITHOUT
        # TIME ZONE which asyncpg refuses to compare against a tz-aware param.
        appt_result = await sess.execute(
            select(Appointment).where(
                and_(
                    Appointment.stylist_id == stylist_id,
                    Appointment.status.in_(
                        [
                            AppointmentStatus.PENDING,
                            AppointmentStatus.CONFIRMED,
                            AppointmentStatus.HOLD,
                        ]
                    ),
                    Appointment.start_time < end_time,
                    Appointment.start_time >= start_time - timedelta(hours=12),
                )
            )
        )
        all_appointments = appt_result.scalars().all()

        # Python-side exact overlap filter: appointment ends after range start.
        # Also exclude expired HOLDs (lazy-expiry pattern) — they are treated as
        # free slots once hold_expires_at <= now().
        now_utc = datetime.now(UTC)
        appointments = [
            appt
            for appt in all_appointments
            if appt.start_time + timedelta(minutes=appt.duration_minutes) > start_time
            and (
                appt.status != AppointmentStatus.HOLD
                or (appt.hold_expires_at is not None and appt.hold_expires_at > now_utc)
            )
        ]

        for appt in appointments:
            appt_end = appt.start_time + timedelta(minutes=appt.duration_minutes)
            periods.append(
                {
                    "start": appt.start_time,
                    "end": appt_end,
                    "type": "appointment",
                    "title": f"Cita: {appt.first_name}",
                    "status": appt.status.value,
                }
            )

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
            periods.append(
                {
                    "start": block.start_time,
                    "end": block.end_time,
                    "type": "blocking_event",
                    "title": block.title,
                    "event_type": block.event_type.value,
                }
            )

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
                        "conflict_details": "El estilista tiene otra cita a esa hora",
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
    slot_interval_minutes: int | None = None,
    pack_slots: bool = True,
) -> list[dict[str, Any]]:
    """
    Get all available time slots for a stylist on a specific date.

    Generates candidate slots based on business hours, then filters out
    slots that conflict with appointments or blocking events.

    **v4.2 Enhancement:** Slots are now packed adjacent to existing appointments
    to minimize dead time and use service duration as minimum interval.

    Args:
        stylist_id: UUID of the stylist
        target_date: Date to check availability
        service_duration_minutes: Duration of the service in minutes
        slot_interval_minutes: Interval between slot start times.
            If None, uses service_duration_minutes to avoid overlapping options.
        pack_slots: If True (default), prioritize slots adjacent to existing appointments.

    Returns:
        List of available slots:
        [
            {
                "time": "10:00",
                "end_time": "11:30",
                "full_datetime": "2025-12-15T10:00:00+01:00",
                "stylist_id": str,
                "adjacent_priority": int,  # Lower = higher priority (0 = adjacent to appointment)
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

    # Use service duration as interval to avoid showing overlapping slots
    # e.g., for 70-min service, don't show 10:00 AND 10:30
    if slot_interval_minutes is None:
        slot_interval_minutes = service_duration_minutes

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
            check_date.year, check_date.month, check_date.day, start_hour, 0, 0, tzinfo=MADRID_TZ
        )
        day_end = datetime(
            check_date.year, check_date.month, check_date.day, end_hour, 0, 0, tzinfo=MADRID_TZ
        )

        # Get all busy periods for the day
        busy_periods = await get_busy_periods(stylist_id, day_start, day_end)

        # Calculate adjacent times (slots that start right after existing appointments)
        adjacent_times = set()
        if pack_slots and busy_periods:
            for period in busy_periods:
                # Add end time of each busy period as a preferred slot start
                adjacent_times.add(period["end"])

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
                # Calculate adjacent priority (0 = adjacent to appointment, higher = less priority)
                adjacent_priority = 1  # Default: not adjacent
                if current_slot in adjacent_times:
                    adjacent_priority = 0  # Highest priority: starts right after appointment

                available_slots.append(
                    {
                        "time": current_slot.strftime("%H:%M"),
                        "end_time": slot_end.strftime("%H:%M"),
                        "full_datetime": current_slot.isoformat(),
                        "stylist_id": str(stylist_id),
                        "adjacent_priority": adjacent_priority,
                    }
                )

            # Move to next slot
            current_slot += timedelta(minutes=slot_interval_minutes)

        # Sort by adjacent priority (adjacent slots first) then by time
        if pack_slots:
            available_slots.sort(key=lambda s: (s["adjacent_priority"], s["time"]))

        logger.info(
            f"Found {len(available_slots)} available slots for stylist {stylist_id} "
            f"on {check_date} (interval={slot_interval_minutes}min, pack={pack_slots})"
        )
        return available_slots

    except Exception as e:
        logger.error(f"Error getting available slots: {e}", exc_info=True)
        return []


def _normalize_fallback_search_days(search_days: int) -> int:
    """Clamp fallback search to the product-defined 7-day maximum."""
    return max(1, min(search_days, MAX_FALLBACK_SEARCH_DAYS))


def _normalize_fallback_max_options(max_options: int) -> int:
    """Clamp returned fallback options to the product-defined maximum."""
    return max(1, min(max_options, MAX_FALLBACK_OPTIONS))


def _build_ranked_fallback_stylists(
    preferred_stylist_id: UUID | None,
    candidate_stylist_ids: list[UUID],
    strategy: FallbackStrategy,
) -> list[tuple[int, UUID, str]]:
    """Build stylist search order while preserving same-stylist-first ranking."""
    unique_candidates: list[UUID] = []
    for stylist_id in candidate_stylist_ids:
        if stylist_id not in unique_candidates:
            unique_candidates.append(stylist_id)

    ranked: list[tuple[int, UUID, str]] = []

    if strategy == "same_stylist_then_any" and preferred_stylist_id is not None:
        ranked.append((0, preferred_stylist_id, "same_stylist"))
        for stylist_id in unique_candidates:
            if stylist_id != preferred_stylist_id:
                ranked.append((1, stylist_id, "alternate_stylist"))
        return ranked

    for stylist_id in unique_candidates:
        ranked.append((0, stylist_id, "any_stylist"))

    return ranked


def _compute_slot_end_iso(start_iso: str, duration_minutes: int) -> str:
    """Compute the slot end timestamp from the slot start ISO string."""
    try:
        start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    except ValueError:
        return start_iso

    return (start_dt + timedelta(minutes=duration_minutes)).isoformat()


def _build_rank_reason(base_reason: str, day_offset: int) -> str:
    """Return a compact rank reason for tool/prompt consumers."""
    if base_reason == "same_stylist":
        return "same_stylist_next_day" if day_offset == 1 else "same_stylist_later_week"
    if base_reason == "alternate_stylist":
        return "alternate_stylist_next_day" if day_offset == 1 else "alternate_stylist_later_week"
    return "earliest_any_stylist"


async def get_next_available_options(
    requested_date: date | datetime,
    service_duration_minutes: int,
    preferred_stylist_id: UUID | None = None,
    candidate_stylist_ids: list[UUID] | None = None,
    strategy: FallbackStrategy = "same_stylist_then_any",
    max_options: int = MAX_FALLBACK_OPTIONS,
    search_days: int = MAX_FALLBACK_SEARCH_DAYS,
) -> dict[str, Any]:
    """Return bounded fallback options beyond the requested exact day.

    This helper NEVER changes exact-day lookup semantics. It only searches the
    next bounded window after the requested day and ranks results according to
    the requested fallback strategy.
    """
    if isinstance(requested_date, datetime):
        base_date = requested_date.date()
    else:
        base_date = requested_date

    bounded_search_days = _normalize_fallback_search_days(search_days)
    bounded_max_options = _normalize_fallback_max_options(max_options)

    ranked_stylists = _build_ranked_fallback_stylists(
        preferred_stylist_id=preferred_stylist_id,
        candidate_stylist_ids=candidate_stylist_ids
        or ([] if preferred_stylist_id is None else [preferred_stylist_id]),
        strategy=strategy,
    )

    ranked_options: list[dict[str, Any]] = []
    for phase_priority, stylist_id, base_reason in ranked_stylists:
        for day_offset in range(1, bounded_search_days + 1):
            search_date = base_date + timedelta(days=day_offset)
            slots = await get_available_slots(
                stylist_id=stylist_id,
                target_date=search_date,
                service_duration_minutes=service_duration_minutes,
            )

            for slot in slots:
                start_iso = slot["full_datetime"]
                ranked_options.append(
                    {
                        "start_iso": start_iso,
                        "end_iso": _compute_slot_end_iso(start_iso, service_duration_minutes),
                        "date_iso": search_date.isoformat(),
                        "stylist_id": str(stylist_id),
                        "adjacent_priority": slot.get("adjacent_priority", 1),
                        "rank_reason": _build_rank_reason(base_reason, day_offset),
                        "_priority": (
                            phase_priority,
                            day_offset,
                            slot.get("adjacent_priority", 1),
                            start_iso,
                        ),
                    }
                )

    ranked_options.sort(key=lambda option: option["_priority"])

    # Dedup by start_iso — keep first (best priority) entry per start_iso.
    # Because ranked_options is sorted by _priority ascending (best first), the
    # first occurrence of each start_iso is always the highest-priority stylist.
    # Design §2 Slice 2, spec R2.5/R2.6, Task 2.7.
    seen_start: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for opt in ranked_options:
        if opt["start_iso"] in seen_start:
            continue
        seen_start.add(opt["start_iso"])
        deduped.append(opt)

    clean_options = [
        {
            key: value
            for key, value in option.items()
            if key not in {"_priority", "adjacent_priority"}
        }
        for option in deduped[:bounded_max_options]
    ]

    result: dict[str, Any] = {
        "options": clean_options,
        "searched_until": (base_date + timedelta(days=bounded_search_days)).isoformat(),
        "search_days": bounded_search_days,
        "max_options": bounded_max_options,
    }

    # Compute gap_explanation_hint when nearest slot is > 2 calendar days away.
    # Design §2 Slice 2 OQ2, spec R3.5, Task 2.9.
    if deduped:
        first_date = date.fromisoformat(deduped[0]["date_iso"])
        gap_days = (first_date - base_date).days
        if gap_days > 2:
            skipped: list[dict[str, str]] = []
            for offset in range(1, gap_days):  # exclude the first_date itself
                if len(skipped) >= 7:  # cap at 7 entries
                    break
                d = base_date + timedelta(days=offset)
                reason = "closed_day" if await is_date_closed(d) else "fully_booked"
                skipped.append(
                    {
                        "date_iso": d.isoformat(),
                        "weekday": SPANISH_WEEKDAYS[d.weekday()],
                        "reason": reason,
                    }
                )
            result["gap_explanation_hint"] = {
                "gap_days_count": gap_days,
                "skipped_dates": skipped,
            }

    return result


async def get_soonest_slot_any_stylist(
    category: ServiceCategory,
    service_duration_minutes: int,
    search_days: int = 7,
    excluded_stylist_id: UUID | None = None,
) -> dict[str, Any] | None:
    """
    Find the soonest available slot across ALL stylists in a category.

    This is used for the "PRÓXIMO DISPONIBLE" option that shows the earliest
    available slot regardless of which stylist has it.

    Args:
        category: Service category (HAIRDRESSING or AESTHETICS)
        service_duration_minutes: Duration of the service in minutes
        search_days: Maximum number of days to search (default: 7, extends to 14 if empty)
        excluded_stylist_id: Optional stylist ID to exclude from search (if we want truly different)

    Returns:
        Soonest available slot dict with stylist info, or None if nothing found:
        {
            "time": "10:00",
            "end_time": "11:30",
            "date": "2025-12-15",
            "day_name": "lunes",
            "full_datetime": "2025-12-15T10:00:00+01:00",
            "stylist_id": str,
            "stylist_name": str,
        }

    Example:
        >>> slot = await get_soonest_slot_any_stylist(
        ...     category=ServiceCategory.HAIRDRESSING,
        ...     service_duration_minutes=90
        ... )
        >>> slot
        {"time": "10:00", "stylist_name": "Ana", ...}
    """
    from agent.transactions.validators.transaction_validators import MINIMUM_DAYS

    # Spanish day names
    day_names_es = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

    try:
        # Get all stylists in category (mirrors pattern in _resolve_active_stylists)
        if category == ServiceCategory.HAIRDRESSING:
            cat_filter = Stylist.category.in_([ServiceCategory.HAIRDRESSING, ServiceCategory.BOTH])
        else:
            cat_filter = Stylist.category.in_([ServiceCategory.AESTHETICS, ServiceCategory.BOTH])

        async with get_async_session() as session:
            _result = await session.execute(
                select(Stylist).where(Stylist.is_active == True, cat_filter)  # noqa: E712
            )
            stylists = list(_result.scalars().all())
        if excluded_stylist_id:
            stylists = [s for s in stylists if s.id != excluded_stylist_id]

        if not stylists:
            logger.warning(f"No stylists found for category {category}")
            return None

        # Start from 3-day minimum
        now = datetime.now(MADRID_TZ)
        search_start = now + timedelta(days=MINIMUM_DAYS)

        # Try first search_days, then extend to 14 if nothing found
        for max_days in [search_days, 14]:
            for day_offset in range(max_days):
                current_date = search_start + timedelta(days=day_offset)

                # Skip holidays
                holiday_name = await is_holiday(current_date)
                if holiday_name:
                    continue

                # Skip closed days
                if await is_date_closed(current_date):
                    continue

                # Check all stylists for this date
                for stylist in stylists:
                    slots = await get_available_slots(
                        stylist_id=stylist.id,
                        target_date=current_date,
                        service_duration_minutes=service_duration_minutes,
                        pack_slots=True,  # Prefer packed slots
                    )

                    if slots:
                        # Return the first available slot (already sorted by priority)
                        first_slot = slots[0]
                        logger.info(
                            f"Soonest slot found: {first_slot['time']} on {current_date.date()} "
                            f"with {stylist.name}"
                        )
                        return {
                            "time": first_slot["time"],
                            "end_time": first_slot["end_time"],
                            "date": current_date.strftime("%Y-%m-%d"),
                            "day_name": day_names_es[current_date.weekday()],
                            "full_datetime": first_slot["full_datetime"],
                            "stylist_id": str(stylist.id),
                            "stylist_name": stylist.name,
                        }

            # If we searched 7 days and found nothing, try 14
            if max_days == search_days:
                logger.info(f"No slots found in {search_days} days, extending search to 14 days")

        logger.warning(f"No slots found within 14 days for category {category}")
        return None

    except Exception as e:
        logger.error(f"Error finding soonest slot: {e}", exc_info=True)
        return None


async def get_stylist_by_id(stylist_id: UUID) -> Stylist | None:
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
                        Stylist.is_active,
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
                        Appointment.status.in_(
                            [
                                AppointmentStatus.PENDING,
                                AppointmentStatus.CONFIRMED,
                            ]
                        ),
                        Appointment.start_time < end_time,
                        Appointment.start_time
                        >= start_time - timedelta(hours=24),  # Buffer for duration
                    )
                )
            )
            all_appointments = appt_result.scalars().all()

            # Filter in Python for exact overlap check (appointment ends after our start time)
            appointments = [
                appt
                for appt in all_appointments
                if appt.start_time + timedelta(minutes=appt.duration_minutes) > start_time
            ]

            for appt in appointments:
                appt_end = appt.start_time + timedelta(minutes=appt.duration_minutes)

                # Convert to Madrid timezone before serialization
                start_madrid = appt.start_time.astimezone(MADRID_TZ)
                end_madrid = appt_end.astimezone(MADRID_TZ)

                # Get service names for this appointment
                if appt.service_ids:
                    service_result = await session.execute(
                        select(Service.name).where(Service.id.in_(appt.service_ids))
                    )
                    service_names_list = [row[0] for row in service_result.fetchall()]
                    service_names_str = ", ".join(service_names_list)
                else:
                    service_names_list = []
                    service_names_str = ""

                # Build title: Name LastName - Services
                full_name = f"{appt.first_name} {appt.last_name or ''}".strip()
                title = f"{full_name} - {service_names_str}" if service_names_str else full_name

                events.append(
                    {
                        "id": f"appt-{appt.id}",
                        "title": title,
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
                            "customer_name": full_name,
                            "service_names": service_names_list,
                        },
                    }
                )

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
                "vacation": "#DC2626",  # Red
                "meeting": "#D97706",  # Amber
                "break": "#059669",  # Emerald
                "general": "#6B7280",  # Gray
                "personal": "#EC4899",  # Pink
            }

            for block in blocking_events:
                color = block_colors.get(block.event_type.value, "#6B7280")

                # Convert to Madrid timezone before serialization
                start_madrid = block.start_time.astimezone(MADRID_TZ)
                end_madrid = block.end_time.astimezone(MADRID_TZ)

                events.append(
                    {
                        "id": f"block-{block.id}",
                        "title": block.title,
                        "start": start_madrid.isoformat(),
                        "end": end_madrid.isoformat(),
                        "backgroundColor": color,
                        "borderColor": color,
                        "extendedProps": {
                            "blocking_event_id": str(block.id),
                            "stylist_id": str(block.stylist_id),
                            "title": block.title,
                            "description": block.description,
                            "event_type": block.event_type.value,
                            "type": "blocking_event",
                            # Include recurring series info if available
                            "recurring_series_id": (
                                str(block.recurring_series_id)
                                if block.recurring_series_id
                                else None
                            ),
                            "occurrence_index": block.occurrence_index,
                        },
                    }
                )

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
                events.append(
                    {
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
                    }
                )

        logger.info(
            f"Found {len(events)} calendar events for {len(stylist_ids)} stylists "
            f"between {start_time} and {end_time}"
        )
        return events

    except Exception as e:
        logger.error(f"Error fetching calendar events: {e}", exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Availability window aggregator — T3 (ADR-2)
# ---------------------------------------------------------------------------

_WEEKDAYS_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


async def _load_lead_time_min_days() -> int:
    """Return minimum_booking_days_advance from settings, defaulting to 3."""
    try:
        from shared.settings_service import get_settings_service

        service = await get_settings_service()
        value = await service.get("minimum_booking_days_advance", default=3)
        return int(value or 3)
    except Exception:
        return 3


async def _get_active_stylists_for_window(
    service_ids: list[UUID],
    audience: str | None,
) -> list[tuple[UUID, str, str]]:
    """Return list of (stylist_id, stylist_name, category) eligible for the given services."""
    async with get_async_session() as session:
        svc_result = await session.execute(
            select(Service.category).where(Service.id.in_(service_ids))
        )
        categories = {row[0] for row in svc_result.fetchall()}

        has_hair = ServiceCategory.HAIRDRESSING in categories
        has_aesth = ServiceCategory.AESTHETICS in categories
        has_both = ServiceCategory.BOTH in categories

        # Mixed HAIRDRESSING+AESTHETICS without BOTH bridge → no eligible stylists
        if has_hair and has_aesth and not has_both:
            return []

        if has_both and not has_hair and not has_aesth:
            stylist_filter = Stylist.is_active.is_(True)
        elif has_hair or (has_both and not has_aesth):
            stylist_filter = Stylist.category.in_(
                [ServiceCategory.HAIRDRESSING, ServiceCategory.BOTH]
            )
        else:
            stylist_filter = Stylist.category.in_(
                [ServiceCategory.AESTHETICS, ServiceCategory.BOTH]
            )

        result = await session.execute(
            select(Stylist.id, Stylist.name, Stylist.category)
            .where(Stylist.is_active.is_(True))
            .where(stylist_filter)
            .order_by(Stylist.name.asc())
        )
        return [(row[0], row[1], str(row[2])) for row in result.fetchall()]


async def _get_total_duration_for_window(service_ids: list[UUID]) -> int:
    """Return total duration in minutes for the given service IDs."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Service.duration_minutes).where(Service.id.in_(service_ids))
        )
        durations = [row[0] for row in result.fetchall()]
        return sum(durations) if durations else 60


async def get_availability_window(
    service_ids: list[UUID],
    audience: str | None,
    days: int = 7,
    max_slots_per_day: int = 4,
) -> dict[str, list[dict]]:
    """Aggregate available slots across all eligible stylists for a rolling date window.

    Reuses get_available_slots to avoid duplicating holiday/hours/blocking logic.
    Applies lead-time floor from settings (default 3 days).

    Args:
        service_ids: List of service UUIDs to check.
        audience: Optional audience filter (passed through to stylist eligibility).
        days: Number of days in the window (default 7).
        max_slots_per_day: Maximum slots to include per day per stylist (default 4).

    Returns:
        Dict keyed by stylist_name. Each value is a list of day entries:
        [{"date_iso": "2026-04-30", "weekday_es": "jueves", "slots": ["10:00", "11:00"]}, ...]
        Days with no slots are excluded. Stylists with no availability are excluded.
    """
    eligible_stylists = await _get_active_stylists_for_window(service_ids, audience)
    if not eligible_stylists:
        return {}

    total_duration = await _get_total_duration_for_window(service_ids)
    min_days = await _load_lead_time_min_days()

    today = date.today()
    start_date = today + timedelta(days=min_days)

    result: dict[str, list[dict]] = {}

    for stylist_id, stylist_name, _category in eligible_stylists:
        day_entries: list[dict] = []

        for offset in range(days):
            target_date = start_date + timedelta(days=offset)
            slots = await get_available_slots(
                stylist_id=stylist_id,
                target_date=target_date,
                service_duration_minutes=total_duration,
            )

            if not slots:
                continue

            # Sort by adjacent_priority then time, cap at max_slots_per_day
            sorted_slots = sorted(
                slots, key=lambda s: (s.get("adjacent_priority", 1), s.get("time", ""))
            )[:max_slots_per_day]

            day_entries.append(
                {
                    "date_iso": target_date.isoformat(),
                    "weekday_es": _WEEKDAYS_ES[target_date.weekday()],
                    "slots": [s["time"] for s in sorted_slots],
                }
            )

        if day_entries:
            result[stylist_name] = day_entries

    return result

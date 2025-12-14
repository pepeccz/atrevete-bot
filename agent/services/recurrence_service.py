"""
Recurrence Expansion Service.

Provides RFC 5545 compliant date expansion for recurring blocking events.
Uses python-dateutil rrule for reliable date calculations including:
- Weekly patterns (specific days of week)
- Monthly patterns (specific days of month)
- Interval support (every N weeks/months)

This service is used by the admin API to:
1. Preview what instances will be created
2. Detect conflicts with existing appointments/blocking events
3. Generate dates for creating BlockingEvent instances
"""

from datetime import date, datetime, time, timedelta
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from dateutil.rrule import rrule, WEEKLY, MONTHLY, MO, TU, WE, TH, FR, SA, SU
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_async_session
from database.models import (
    BlockingEvent,
    Appointment,
    AppointmentStatus,
    BusinessHours,
    Stylist,
)

MADRID_TZ = ZoneInfo("Europe/Madrid")

# Mapping from integer (0=Monday) to dateutil weekday constants
WEEKDAY_MAP = {
    0: MO,  # Monday
    1: TU,  # Tuesday
    2: WE,  # Wednesday
    3: TH,  # Thursday
    4: FR,  # Friday
    5: SA,  # Saturday
    6: SU,  # Sunday
}

# Reverse mapping for parsing BYDAY strings like "MO,WE,FR"
WEEKDAY_ABBREV_TO_INT = {
    "MO": 0,
    "TU": 1,
    "WE": 2,
    "TH": 3,
    "FR": 4,
    "SA": 5,
    "SU": 6,
}


def expand_recurrence(
    start_date: date,
    frequency: str,
    interval: int,
    days_of_week: list[int] | None,
    days_of_month: list[int] | None,
    count: int,
) -> list[date]:
    """
    Expand recurrence rule to concrete dates.

    Args:
        start_date: First occurrence date (or date from which to start generating)
        frequency: "WEEKLY" or "MONTHLY"
        interval: Every N weeks/months (1 = every week, 2 = every other week, etc.)
        days_of_week: List of weekdays (0=Mon, 1=Tue, ..., 6=Sun) for WEEKLY
        days_of_month: List of month days (1-31) for MONTHLY
        count: Total number of occurrences to generate

    Returns:
        List of dates for each occurrence, sorted chronologically

    Examples:
        # Every Monday and Wednesday for 4 weeks
        expand_recurrence(date(2025,1,6), "WEEKLY", 1, [0,2], None, 8)
        # Returns 8 dates: Jan 6, 8, 13, 15, 20, 22, 27, 29

        # Every other Friday for 6 occurrences
        expand_recurrence(date(2025,1,3), "WEEKLY", 2, [4], None, 6)
        # Returns 6 dates: Jan 3, 17, 31, Feb 14, 28, Mar 14

        # 15th of each month for 3 months
        expand_recurrence(date(2025,1,15), "MONTHLY", 1, None, [15], 3)
        # Returns 3 dates: Jan 15, Feb 15, Mar 15
    """
    freq = WEEKLY if frequency == "WEEKLY" else MONTHLY

    # Build rrule kwargs
    kwargs: dict = {
        "dtstart": datetime.combine(start_date, time.min),
        "freq": freq,
        "interval": interval,
        "count": count,
    }

    # Add day constraints based on frequency
    if frequency == "WEEKLY" and days_of_week:
        kwargs["byweekday"] = [WEEKDAY_MAP[d] for d in days_of_week]
    elif frequency == "MONTHLY" and days_of_month:
        kwargs["bymonthday"] = days_of_month

    # Generate dates
    rule = rrule(**kwargs)
    return sorted([dt.date() for dt in rule])


def parse_byday(byday_str: str | None) -> list[int]:
    """
    Parse BYDAY string like "MO,WE,FR" to list of weekday integers.

    Args:
        byday_str: Comma-separated weekday abbreviations (e.g., "MO,WE,FR")

    Returns:
        List of integers where 0=Monday, 6=Sunday
    """
    if not byday_str:
        return []
    return [WEEKDAY_ABBREV_TO_INT[day.strip().upper()] for day in byday_str.split(",")]


def parse_bymonthday(bymonthday_str: str | None) -> list[int]:
    """
    Parse BYMONTHDAY string like "15,30" to list of day integers.

    Args:
        bymonthday_str: Comma-separated day numbers (e.g., "15,30")

    Returns:
        List of integers (1-31)
    """
    if not bymonthday_str:
        return []
    return [int(day.strip()) for day in bymonthday_str.split(",")]


def format_byday(days_of_week: list[int]) -> str:
    """
    Format list of weekday integers to BYDAY string.

    Args:
        days_of_week: List of integers where 0=Monday, 6=Sunday

    Returns:
        Comma-separated weekday abbreviations (e.g., "MO,WE,FR")
    """
    abbrevs = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
    return ",".join(abbrevs[d] for d in sorted(days_of_week))


def format_bymonthday(days_of_month: list[int]) -> str:
    """
    Format list of month day integers to BYMONTHDAY string.

    Args:
        days_of_month: List of integers (1-31)

    Returns:
        Comma-separated day numbers (e.g., "15,30")
    """
    return ",".join(str(d) for d in sorted(days_of_month))


async def get_business_hours_summary() -> dict[int, dict | None]:
    """
    Get business hours for each day of the week.

    Returns:
        Dict mapping day_of_week (0=Monday, 6=Sunday) to:
        - {"open": "HH:MM", "close": "HH:MM"} if open
        - None if closed
    """
    async for session in get_async_session():
        result = await session.execute(
            select(BusinessHours).order_by(BusinessHours.day_of_week)
        )
        hours_list = result.scalars().all()
        break

    # Build summary dict
    summary: dict[int, dict | None] = {}
    for h in hours_list:
        if h.is_closed:
            summary[h.day_of_week] = None
        else:
            summary[h.day_of_week] = {
                "open": f"{h.start_hour:02d}:{h.start_minute:02d}",
                "close": f"{h.end_hour:02d}:{h.end_minute:02d}",
            }

    # Fill in missing days as None (closed)
    for dow in range(7):
        if dow not in summary:
            summary[dow] = None

    return summary


async def get_remaining_week_days(
    from_date: date,
    business_hours: dict[int, dict | None] | None = None,
) -> list[dict]:
    """
    Get the remaining days of the week from a given date.
    Only includes days when the salon is open.

    Args:
        from_date: Start date
        business_hours: Pre-fetched business hours (optional, will fetch if None)

    Returns:
        List of dicts with: {"date": date, "day_of_week": int, "name": str}
        where day_of_week is 0=Monday, 6=Sunday
    """
    if business_hours is None:
        business_hours = await get_business_hours_summary()

    day_names = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

    # Get current day of week (Python: 0=Monday, 6=Sunday)
    current_dow = from_date.weekday()

    remaining_days = []
    # Start from tomorrow, go to end of week (Sunday)
    for offset in range(1, 7 - current_dow + 1):
        check_date = from_date + timedelta(days=offset)
        dow = check_date.weekday()

        # Only include if salon is open
        if business_hours.get(dow) is not None:
            remaining_days.append({
                "date": check_date,
                "day_of_week": dow,
                "name": day_names[dow],
            })

    return remaining_days


async def check_conflicts_for_dates(
    stylist_id: UUID,
    dates: list[date],
    start_time: time,
    end_time: time,
    session: AsyncSession | None = None,
) -> list[dict]:
    """
    Check for conflicts with existing appointments and blocking events.

    Args:
        stylist_id: UUID of the stylist
        dates: List of dates to check
        start_time: Start time of the blocking event
        end_time: End time of the blocking event
        session: Optional database session (will create one if not provided)

    Returns:
        List of conflict dicts with:
        - date: the date
        - stylist_id: UUID
        - conflict_type: "appointment" or "blocking_event"
        - conflict_title: title/description of the conflict
        - start_time: "HH:MM"
        - end_time: "HH:MM"
    """
    conflicts = []

    # Get or create session
    if session is None:
        async for sess in get_async_session():
            conflicts = await _check_conflicts_internal(
                sess, stylist_id, dates, start_time, end_time
            )
            break
    else:
        conflicts = await _check_conflicts_internal(
            session, stylist_id, dates, start_time, end_time
        )

    return conflicts


async def _check_conflicts_internal(
    session: AsyncSession,
    stylist_id: UUID,
    dates: list[date],
    start_time: time,
    end_time: time,
) -> list[dict]:
    """Internal conflict check implementation."""
    conflicts = []

    # Get stylist name for conflict details
    stylist_result = await session.execute(
        select(Stylist.name).where(Stylist.id == stylist_id)
    )
    stylist_name = stylist_result.scalar_one_or_none() or "Unknown"

    for check_date in dates:
        # Build datetime range for this date
        start_dt = datetime.combine(check_date, start_time, tzinfo=MADRID_TZ)
        end_dt = datetime.combine(check_date, end_time, tzinfo=MADRID_TZ)

        # Check appointments (PENDING or CONFIRMED only)
        appt_result = await session.execute(
            select(Appointment).where(
                and_(
                    Appointment.stylist_id == stylist_id,
                    Appointment.status.in_([
                        AppointmentStatus.PENDING,
                        AppointmentStatus.CONFIRMED
                    ]),
                    Appointment.start_time < end_dt,
                    # Calculate end time: start_time + duration_minutes
                    Appointment.start_time + (Appointment.duration_minutes * timedelta(minutes=1)) > start_dt,
                )
            )
        )
        for appt in appt_result.scalars():
            appt_end = appt.start_time + timedelta(minutes=appt.duration_minutes)
            conflicts.append({
                "date": check_date.isoformat(),
                "stylist_id": str(stylist_id),
                "stylist_name": stylist_name,
                "conflict_type": "appointment",
                "conflict_title": f"Cita: {appt.first_name or 'Cliente'}",
                "start_time": appt.start_time.astimezone(MADRID_TZ).strftime("%H:%M"),
                "end_time": appt_end.astimezone(MADRID_TZ).strftime("%H:%M"),
            })

        # Check existing blocking events
        block_result = await session.execute(
            select(BlockingEvent).where(
                and_(
                    BlockingEvent.stylist_id == stylist_id,
                    BlockingEvent.start_time < end_dt,
                    BlockingEvent.end_time > start_dt,
                )
            )
        )
        for block in block_result.scalars():
            conflicts.append({
                "date": check_date.isoformat(),
                "stylist_id": str(stylist_id),
                "stylist_name": stylist_name,
                "conflict_type": "blocking_event",
                "conflict_title": block.title,
                "start_time": block.start_time.astimezone(MADRID_TZ).strftime("%H:%M"),
                "end_time": block.end_time.astimezone(MADRID_TZ).strftime("%H:%M"),
            })

    return conflicts


def get_open_days_of_week(business_hours: dict[int, dict | None]) -> list[int]:
    """
    Get list of weekdays when the salon is open.

    Args:
        business_hours: Dict from get_business_hours_summary()

    Returns:
        List of weekday integers (0=Monday, 6=Sunday) when salon is open
    """
    return [dow for dow, hours in business_hours.items() if hours is not None]


def validate_time_within_business_hours(
    start_time: time,
    end_time: time,
    day_of_week: int,
    business_hours: dict[int, dict | None],
) -> tuple[bool, str | None]:
    """
    Validate that the blocking event times are within business hours.

    Args:
        start_time: Event start time
        end_time: Event end time
        day_of_week: Day of week (0=Monday, 6=Sunday)
        business_hours: Dict from get_business_hours_summary()

    Returns:
        Tuple of (is_valid, error_message)
    """
    hours = business_hours.get(day_of_week)

    if hours is None:
        day_names = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        return False, f"El salón está cerrado los {day_names[day_of_week]}"

    open_time = time.fromisoformat(hours["open"])
    close_time = time.fromisoformat(hours["close"])

    if start_time < open_time:
        return False, f"La hora de inicio ({start_time.strftime('%H:%M')}) es anterior a la apertura ({hours['open']})"

    if end_time > close_time:
        return False, f"La hora de fin ({end_time.strftime('%H:%M')}) es posterior al cierre ({hours['close']})"

    return True, None

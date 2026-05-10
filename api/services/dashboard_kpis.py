"""
Dashboard KPI helper functions — Slice 2a.

Pure async functions that query the DB for each KPI.
Designed to be called in parallel via asyncio.gather().
Each function takes an AsyncSession and returns a scalar result.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Appointment, AppointmentStatus, BusinessHours, Customer, Stylist

MADRID_TZ = ZoneInfo("Europe/Madrid")


async def _confirmation_rate_today(session: AsyncSession, today: date) -> float:
    """
    Return the fraction of today's non-cancelled/no_show appointments that are confirmed.

    Denominator: appointments with status NOT IN (cancelled, no_show)
    Numerator: appointments with status = confirmed

    Returns 0.0 when denominator is 0 (divide-by-zero guard).
    """
    excluded = {AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW, AppointmentStatus.HOLD}
    confirmed_status = AppointmentStatus.CONFIRMED

    query = select(
        func.count(Appointment.id)
        .filter(Appointment.status == confirmed_status)
        .label("confirmed_count"),
        func.count(Appointment.id).label("total_count"),
    ).where(
        func.date(Appointment.start_time) == today,
        Appointment.status.not_in(excluded),
    )

    result = await session.execute(query)
    row = result.one()
    # Access by index for compatibility with both real Row and plain tuple in tests
    confirmed_count: int = int(row[0] or 0)
    total_count: int = int(row[1] or 0)

    if total_count == 0:
        return 0.0
    return confirmed_count / total_count


async def _appointments_count_today(session: AsyncSession, today: date) -> int:
    """
    Return count of today's appointments excluding cancelled and no_show statuses.
    """
    excluded = {AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW, AppointmentStatus.HOLD}

    query = select(func.count(Appointment.id)).where(
        func.date(Appointment.start_time) == today,
        Appointment.status.not_in(excluded),
    )

    result = await session.execute(query)
    count = result.scalar()
    return int(count) if count is not None else 0


async def _occupation_today(session: AsyncSession, today: date) -> float:
    """
    Return today's occupation ratio: booked_minutes / available_minutes.

    booked_minutes: sum of duration_minutes for confirmed/pending appointments today.
    available_minutes: active_stylist_count × business_open_minutes_today.

    Returns 0.0 when available_minutes is 0 (salon closed or no active stylists).
    """
    # 1. Sum booked minutes (confirmed + pending only)
    booked_query = select(func.sum(Appointment.duration_minutes)).where(
        func.date(Appointment.start_time) == today,
        Appointment.status.in_([AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING]),
    )
    booked_result = await session.execute(booked_query)
    booked_minutes: int = int(booked_result.scalar() or 0)

    # 2. Count active stylists
    active_stylist_query = select(func.count(Stylist.id)).where(Stylist.is_active.is_(True))
    stylist_result = await session.execute(active_stylist_query)
    active_count: int = int(stylist_result.scalar() or 0)

    if active_count == 0:
        return 0.0

    # 3. Business hours for today (day_of_week: Monday=0 ... Sunday=6)
    # Python date.weekday() returns 0=Monday ... 6=Sunday — matches BusinessHours.day_of_week
    day_of_week = today.weekday()
    bh_query = select(BusinessHours).where(BusinessHours.day_of_week == day_of_week)
    bh_result = await session.execute(bh_query)
    business_hours = bh_result.scalar_one_or_none()

    if business_hours is None or business_hours.is_closed:
        return 0.0

    # Business open minutes = (end_hour*60 + end_minute) - (start_hour*60 + start_minute)
    open_minutes = (business_hours.end_hour * 60 + business_hours.end_minute) - (
        business_hours.start_hour * 60 + business_hours.start_minute
    )

    if open_minutes <= 0:
        return 0.0

    available_minutes = active_count * open_minutes
    return booked_minutes / available_minutes


async def _new_customers_last_7d(session: AsyncSession, now: datetime) -> int:
    """
    Return count of customers created in the rolling 7-day window [now - 7d, now].

    Uses a rolling window (NOT ISO week Monday boundary) per user decision.
    """
    since = now - timedelta(days=7)

    query = select(func.count(Customer.id)).where(
        Customer.created_at >= since,
        Customer.created_at <= now,
    )

    result = await session.execute(query)
    count = result.scalar()
    return int(count) if count is not None else 0

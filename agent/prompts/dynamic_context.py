"""
Dynamic context loading for prompt injection.

This module provides functions to load dynamic business context from the database
that can be injected into prompts at runtime. Supports caching to reduce DB load.

Variables loaded:
- minimum_booking_days_advance: From system_settings table
- cancellation_window_hours: From system_settings table (default 48)
- salon_address: From config (SALON_ADDRESS)
- business_hours: From business_hours table
- upcoming_holidays: From holidays table (next 30 days)
- current_datetime: Current datetime in Europe/Madrid timezone
"""

import asyncio
import logging
from datetime import datetime, timedelta, date
from typing import Any

import pytz
from sqlalchemy import select

from database.connection import get_async_session
from database.models import BusinessHours, Holiday, SystemSetting
from shared.config import get_settings

logger = logging.getLogger(__name__)

# Cache for dynamic context with TTL (5 minutes)
_DYNAMIC_CONTEXT_CACHE: dict[str, Any] = {
    "data": None,
    "expires_at": None,
    "lock": None,  # Will be initialized on first use
}

# Day names in Spanish
DAY_NAMES_ES = {
    0: "Lunes",
    1: "Martes",
    2: "Miércoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sábado",
    6: "Domingo",
}

# Cache TTL in minutes
CACHE_TTL_MINUTES = 5


def _get_lock() -> asyncio.Lock:
    """Get or create the async lock for cache access."""
    if _DYNAMIC_CONTEXT_CACHE["lock"] is None:
        _DYNAMIC_CONTEXT_CACHE["lock"] = asyncio.Lock()
    return _DYNAMIC_CONTEXT_CACHE["lock"]


async def load_dynamic_context(force_refresh: bool = False) -> dict[str, Any]:
    """
    Load dynamic business context from database with caching.

    This function queries the database for runtime configuration and formats it
    for injection into system prompts. Uses a 5-minute TTL cache.

    Args:
        force_refresh: If True, bypass cache and reload from database

    Returns:
        dict with:
        - minimum_booking_days_advance: int (from system_settings)
        - cancellation_window_hours: int (from system_settings, default 48)
        - salon_address: str (from config)
        - business_hours: list[dict] with day_name, is_closed, start, end
        - upcoming_holidays: list[dict] with date, name (next 30 days)
        - current_datetime: str formatted in Spanish (Europe/Madrid)

    Raises:
        No exceptions raised - returns fallback values on errors.
    """
    now = datetime.now()
    lock = _get_lock()

    async with lock:
        # Check cache validity
        if (
            not force_refresh
            and _DYNAMIC_CONTEXT_CACHE["data"] is not None
            and _DYNAMIC_CONTEXT_CACHE["expires_at"] is not None
            and _DYNAMIC_CONTEXT_CACHE["expires_at"] > now
        ):
            logger.debug("Using cached dynamic context (cache hit)")
            # Update current_datetime even on cache hit
            cached = _DYNAMIC_CONTEXT_CACHE["data"].copy()
            cached["current_datetime"] = _format_current_datetime()
            return cached

        logger.info("Cache miss - loading dynamic context from database")

        try:
            context = await _load_context_from_db()

            # Update cache
            _DYNAMIC_CONTEXT_CACHE["data"] = context
            _DYNAMIC_CONTEXT_CACHE["expires_at"] = now + timedelta(minutes=CACHE_TTL_MINUTES)

            logger.info(
                f"Dynamic context cached (TTL: {CACHE_TTL_MINUTES} min, "
                f"min_days={context['minimum_booking_days_advance']}, "
                f"cancel_window_h={context['cancellation_window_hours']}, "
                f"holidays={len(context['upcoming_holidays'])})"
            )
            return context

        except Exception as e:
            logger.error(f"Error loading dynamic context: {e}", exc_info=True)
            return _get_fallback_context()


async def _load_context_from_db() -> dict[str, Any]:
    """Load all dynamic context values from database."""
    settings = get_settings()

    context = {
        "minimum_booking_days_advance": 3,  # Default
        "cancellation_window_hours": 48,  # Default
        "salon_address": settings.SALON_ADDRESS,
        "business_hours": [],
        "upcoming_holidays": [],
        "current_datetime": _format_current_datetime(),
    }

    async with get_async_session() as session:
        # 1. Load minimum_booking_days_advance from system_settings
        stmt = select(SystemSetting).where(
            SystemSetting.key == "minimum_booking_days_advance"
        )
        result = await session.execute(stmt)
        setting = result.scalar_one_or_none()

        if setting and setting.value is not None:
            # value is stored as JSONB, could be {"value": 3} or just 3
            if isinstance(setting.value, dict):
                context["minimum_booking_days_advance"] = setting.value.get("value", setting.value)
            else:
                context["minimum_booking_days_advance"] = setting.value

        # 2. Load cancellation_window_hours from system_settings
        stmt = select(SystemSetting).where(
            SystemSetting.key == "cancellation_window_hours"
        )
        result = await session.execute(stmt)
        setting = result.scalar_one_or_none()

        if setting and setting.value is not None:
            if isinstance(setting.value, dict):
                context["cancellation_window_hours"] = setting.value.get("value", setting.value)
            else:
                context["cancellation_window_hours"] = setting.value

        # 3. Load business hours
        stmt = select(BusinessHours).order_by(BusinessHours.day_of_week)
        result = await session.execute(stmt)
        hours = result.scalars().all()

        for hour in hours:
            day_info = {
                "day_name": DAY_NAMES_ES.get(hour.day_of_week, f"Día {hour.day_of_week}"),
                "is_closed": hour.is_closed,
            }

            if hour.is_closed:
                day_info["start"] = None
                day_info["end"] = None
            else:
                # Format times as HH:MM
                start_hour = hour.start_hour or 0
                start_minute = hour.start_minute or 0
                end_hour = hour.end_hour or 0
                end_minute = hour.end_minute or 0

                day_info["start"] = f"{start_hour:02d}:{start_minute:02d}"
                day_info["end"] = f"{end_hour:02d}:{end_minute:02d}"

            context["business_hours"].append(day_info)

        # 4. Load upcoming holidays (next 30 days)
        today = date.today()
        thirty_days_later = today + timedelta(days=30)

        stmt = (
            select(Holiday)
            .where(Holiday.date >= today)
            .where(Holiday.date <= thirty_days_later)
            .order_by(Holiday.date)
        )
        result = await session.execute(stmt)
        holidays = result.scalars().all()

        for holiday in holidays:
            context["upcoming_holidays"].append({
                "date": _format_date_spanish(holiday.date),
                "name": holiday.name,
            })

    return context


def _format_current_datetime() -> str:
    """Format current datetime in Spanish for Europe/Madrid timezone."""
    madrid_tz = pytz.timezone("Europe/Madrid")
    now = datetime.now(madrid_tz)

    # Format: "lunes 15 de diciembre de 2025, 10:30"
    day_names = {
        0: "lunes", 1: "martes", 2: "miércoles", 3: "jueves",
        4: "viernes", 5: "sábado", 6: "domingo"
    }
    month_names = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
        5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
        9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
    }

    day_name = day_names[now.weekday()]
    month_name = month_names[now.month]

    return f"{day_name} {now.day} de {month_name} de {now.year}, {now.hour:02d}:{now.minute:02d}"


def _format_date_spanish(d: date) -> str:
    """Format a date in Spanish (e.g., '25 de diciembre')."""
    month_names = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
        5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
        9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
    }
    return f"{d.day} de {month_names[d.month]}"


def _get_fallback_context() -> dict[str, Any]:
    """Return fallback context when database is unavailable."""
    settings = get_settings()

    return {
        "minimum_booking_days_advance": 3,
        "cancellation_window_hours": 48,
        "salon_address": settings.SALON_ADDRESS,
        "business_hours": [],
        "upcoming_holidays": [],
        "current_datetime": _format_current_datetime(),
    }


def clear_dynamic_context_cache() -> None:
    """Clear the dynamic context cache. Useful for testing or after admin updates."""
    _DYNAMIC_CONTEXT_CACHE["data"] = None
    _DYNAMIC_CONTEXT_CACHE["expires_at"] = None
    logger.info("Dynamic context cache cleared")


__all__ = ["load_dynamic_context", "clear_dynamic_context_cache"]

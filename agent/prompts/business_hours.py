"""Business hours snapshot loader — Phase 5.3.

Queries BusinessHours table and returns a dict of day → "HH:MM-HH:MM" (or "cerrado").
Result is cached for 15 minutes; explicitly invalidated via invalidate_business_hours_cache().
"""

from __future__ import annotations

import logging

from agent.prompts.loader import _TtlCache

logger = logging.getLogger(__name__)

_DAY_NAMES = {
    0: "lunes",
    1: "martes",
    2: "miercoles",
    3: "jueves",
    4: "viernes",
    5: "sabado",
    6: "domingo",
}

# 15-min TTL — hours change quarterly; pub/sub covers explicit mutations.
_hours_cache: _TtlCache[dict[str, str]] = _TtlCache(ttl_minutes=15)


async def _load_hours_snapshot() -> dict[str, str]:
    """Query DB and return {day_name: 'HH:MM-HH:MM'} snapshot."""
    try:
        from sqlalchemy import select

        from database.connection import get_async_session
        from database.models import BusinessHours

        async with get_async_session() as session:
            result = await session.execute(select(BusinessHours))
            rows = result.scalars().all()

        snapshot: dict[str, str] = {}
        for row in rows:
            day_name = _DAY_NAMES.get(row.day_of_week, str(row.day_of_week))
            if row.is_closed or row.start_hour is None or row.end_hour is None:
                snapshot[day_name] = "cerrado"
            else:
                open_str = f"{row.start_hour:02d}:{row.start_minute:02d}"
                close_str = f"{row.end_hour:02d}:{row.end_minute:02d}"
                snapshot[day_name] = f"{open_str}-{close_str}"
        return snapshot
    except Exception:
        logger.warning("Could not load business hours snapshot", exc_info=True)
        return {}


async def load_business_hours_snapshot() -> dict[str, str]:
    """Return {day_name: 'HH:MM-HH:MM'} for active days, 'cerrado' for closed days.

    Result is cached for 15 minutes. Call invalidate_business_hours_cache() to force
    an immediate refresh (used by the pub/sub listener when hours are mutated).
    """
    return await _hours_cache.get_or_load(_load_hours_snapshot)


def invalidate_business_hours_cache() -> None:
    """Force cache refresh on next call. Called by cache_signal_listener on entity='business_hours'."""
    _hours_cache.invalidate()

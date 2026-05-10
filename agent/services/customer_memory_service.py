"""Customer memory service — read/write cross-conversation preferences via Store API."""

import logging
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy import update as sa_update

from database.connection import get_async_session
from database.models import Customer

# Import get_store at module level so tests can patch it with
# patch("agent.services.customer_memory_service.get_store")
try:
    from langgraph.config import get_store
except ImportError:  # pragma: no cover
    get_store = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Day names in Spanish (indexed by weekday() 0=Monday)
_DAY_NAMES_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

NAMESPACE_PREFIX = "customers"
PREFERENCES_KEY = "preferences"


def _get_store_safe():
    """Get the Store instance via contextvar. Returns None if unavailable."""
    if get_store is None:
        return None
    try:
        return get_store()
    except Exception:
        return None


async def read_customer_memories(phone: str) -> dict[str, Any] | None:
    """Read customer preferences from Store, falling back to PG metadata_.

    Never raises — returns None on any failure.

    Args:
        phone: Customer phone in E.164 format (e.g. "+34612345678")

    Returns:
        Preferences dict or None if not found / error.
    """
    # 1. Try Redis Store
    store = _get_store_safe()
    if store is not None:
        try:
            item = await store.aget(
                namespace=(NAMESPACE_PREFIX, phone),
                key=PREFERENCES_KEY,
            )
            if item is not None:
                logger.debug("customer_memory: Store HIT for %s", phone)
                return item.value
            logger.debug("customer_memory: Store MISS for %s", phone)
        except Exception as exc:
            logger.warning("customer_memory: Store read failed for %s: %s", phone, exc)

    # 2. Fallback to PG Customer.metadata_["memories"]
    try:
        async with get_async_session() as session:
            stmt = select(Customer.metadata_).where(Customer.phone == phone)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row and isinstance(row, dict):
                memories = row.get("memories")
                if memories:
                    logger.debug("customer_memory: PG fallback HIT for %s", phone)
                    return memories
    except Exception as exc:
        logger.warning("customer_memory: PG fallback failed for %s: %s", phone, exc)

    return None


async def write_customer_memories(
    phone: str,
    booking_data: dict[str, Any],
    existing_prefs: dict[str, Any] | None,
) -> None:
    """Write merged preferences to Store + PG dual-write.

    Never raises — logs WARNING on failures.

    Args:
        phone: Customer phone in E.164 format
        booking_data: Data extracted from the current booking:
            - service_names: list[str]
            - stylist_name: str | None
            - stylist_id: str | None
            - no_preference_stylist: bool
            - start_time: str (ISO datetime)
            - notes: str | None
        existing_prefs: Current preferences (from state.customer_memories), or None
    """
    merged = _merge_preferences(existing_prefs, booking_data)

    # 1. Write to Redis Store
    store = _get_store_safe()
    if store is not None:
        try:
            await store.aput(
                namespace=(NAMESPACE_PREFIX, phone),
                key=PREFERENCES_KEY,
                value=merged,
            )
            logger.info("customer_memory: Store write OK for %s", phone)
        except Exception as exc:
            logger.warning("customer_memory: Store write failed for %s: %s", phone, exc)

    # 2. Dual-write to PG Customer.metadata_["memories"]
    try:
        async with get_async_session() as session:
            stmt = (
                sa_update(Customer)
                .where(Customer.phone == phone)
                .values(metadata_=Customer.metadata_.op("||")({"memories": merged}))
            )
            await session.execute(stmt)
            await session.commit()
            logger.info("customer_memory: PG dual-write OK for %s", phone)
    except Exception as exc:
        logger.warning("customer_memory: PG dual-write failed for %s: %s", phone, exc)


def _merge_preferences(
    existing: dict[str, Any] | None,
    booking_data: dict[str, Any],
) -> dict[str, Any]:
    """Merge existing preferences with new booking data.

    Pure function — no I/O. See spec REQ-4 for merge rules.

    Args:
        existing: Current preferences dict (or None for first booking)
        booking_data: Data from the latest booking

    Returns:
        Merged preferences dict conforming to the memory schema (REQ-3)
    """
    existing = existing or {}

    visit_count = existing.get("visit_count", 0) + 1
    no_pref = booking_data.get("no_preference_stylist", False)

    # Stylist preference
    if no_pref:
        preferred_stylist_name = None
        preferred_stylist_id = None
    else:
        preferred_stylist_name = booking_data.get("stylist_name") or existing.get(
            "preferred_stylist_name"
        )
        preferred_stylist_id = booking_data.get("stylist_id") or existing.get(
            "preferred_stylist_id"
        )

    # last_stylist: always reflects the most recent booking
    last_stylist_name = booking_data.get("stylist_name") or existing.get("last_stylist_name")

    # Rolling typical_services — last 3 distinct, most-recent first
    new_services = booking_data.get("service_names") or []
    old_services = list(existing.get("typical_services") or [])
    combined: list[str] = []
    seen: set[str] = set()
    for svc in new_services + old_services:
        if svc not in seen:
            combined.append(svc)
            seen.add(svc)
        if len(combined) >= 3:
            break
    typical_services = combined

    # Date/time from booking start_time
    start_time_str = booking_data.get("start_time")
    typical_day = existing.get("typical_day_of_week")
    typical_time = existing.get("typical_time_of_day")
    last_visit_date = existing.get("last_visit_date")

    if start_time_str:
        try:
            dt = datetime.fromisoformat(start_time_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("Europe/Madrid"))
            typical_day = _DAY_NAMES_ES[dt.weekday()]
            typical_time = "morning" if dt.hour < 13 else "afternoon"
            last_visit_date = dt.date().isoformat()
        except (ValueError, IndexError):
            last_visit_date = date.today().isoformat()

    if not last_visit_date:
        last_visit_date = date.today().isoformat()

    # Agent notes — new overwrites existing if non-empty
    new_notes = booking_data.get("notes")
    agent_notes = new_notes if new_notes else existing.get("agent_notes")

    return {
        "preferred_stylist_name": preferred_stylist_name,
        "preferred_stylist_id": preferred_stylist_id,
        "no_preference_stylist": no_pref,
        "typical_services": typical_services,
        "typical_day_of_week": typical_day,
        "typical_time_of_day": typical_time,
        "agent_notes": agent_notes,
        "visit_count": visit_count,
        "last_visit_date": last_visit_date,
        "last_stylist_name": last_stylist_name,
    }

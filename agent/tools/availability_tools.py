"""
Availability Checking Tool for v4.0 Architecture (DB-First).

Rewritten to use DB-first availability checking via availability_service.
Now queries PostgreSQL for availability instead of Google Calendar API.

Key changes from v3:
- Uses DB-first availability_service for all availability checks
- Queries blocking_events and appointments tables instead of Google Calendar
- Uses holidays table instead of Google Calendar keyword detection
- Google Calendar is now push-only (fire-and-forget after DB commit)

v5.0 changes:
- check_availability now accepts service_name (exact catalog name) instead of service_category
- Resolves Service from name → extracts duration_minutes and category automatically
- Accepts stylist_name instead of stylist_id — resolves Stylist from name
- Validates category compatibility between service and stylist
- AUTO-SEARCH: if no slots on requested date, searches next 3 open business days
- find_next_available removed — merged into check_availability AUTO-SEARCH logic

Performance improvement:
- Before (Google Calendar): 2-5 seconds per availability check
- After (PostgreSQL): <100ms per availability check
"""

import logging
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from agent.config import get_booking_config
from agent.services.availability_service import (
    get_available_slots,
    is_holiday,
)
from agent.utils import parse_natural_date, MADRID_TZ
from agent.utils.date_parser import DateParseError
from agent.validators import validate_3_day_rule
from agent.validators.transaction_validators import MINIMUM_DAYS
from database.connection import get_async_session
from database.models import Service, ServiceCategory, Stylist
from shared.business_hours_validator import is_date_closed

logger = logging.getLogger(__name__)


class InterpretationReason(StrEnum):
    """Canonical semantic reasons produced while interpreting availability results.

    The values are shared by booking mode and availability tools so semantic
    payloads stay stable across prompt rendering, transition decisions, and tests.
    """

    MINIMUM_DAYS_RULE = "minimum_days_rule"
    NO_AVAILABILITY = "no_availability"
    STYLIST_UNAVAILABLE = "stylist_unavailable"
    SUCCESS = "success"


SAME_DAY_BUFFER_HOURS = 1
MAX_SLOTS_TO_PRESENT = 5

# Spanish day names indexed by weekday() (Monday=0 … Sunday=6)
_DAY_NAMES_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# How many additional business days to auto-search when the requested date has no slots
_AUTO_SEARCH_EXTRA_DAYS = 3


async def _resolve_service_by_name(name: str) -> Service | None:
    """Case-insensitive exact match on services WHERE is_active=true."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Service).where(
                func.lower(Service.name) == func.lower(name),
                Service.is_active == True,
            )
        )
        return result.scalar_one_or_none()


async def _resolve_stylist_by_name(name: str) -> Stylist | None:
    """Case-insensitive match on stylists WHERE is_active=true."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Stylist).where(
                func.lower(Stylist.name) == func.lower(name),
                Stylist.is_active == True,
            )
        )
        return result.scalar_one_or_none()


async def _get_active_stylists_for_category(category: ServiceCategory) -> list[Stylist]:
    """Return all active stylists that can handle the given service category."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Stylist).where(
                Stylist.is_active == True,
                Stylist.category.in_([category, ServiceCategory.BOTH]),
            )
        )
        return list(result.scalars().all())


class CheckAvailabilitySchema(BaseModel):
    """Schema for check_availability tool parameters."""

    service_names: list[str] = Field(
        description="Lista de nombres exactos de servicios del catálogo (uno o varios)"
    )
    date: str = Field(
        description="Fecha en español natural ('mañana', 'viernes') o ISO ('2026-04-10')"
    )
    stylist_name: str | None = Field(
        default=None, description="Nombre de la estilista preferida del catálogo"
    )
    time_range: str | None = Field(
        default=None,
        description="Filtro de horario: 'morning', 'afternoon', o rango como '14:00-18:00'",
    )


@tool(args_schema=CheckAvailabilitySchema)
async def check_availability(
    service_names: list[str],
    date: str,
    stylist_name: str | None = None,
    time_range: str | None = None,
) -> dict[str, Any]:
    """
    Check availability for one or more services on a date.

    Resolves each service from the catalog, sums durations, validates all share
    the same category, then queries the DB-first availability service.

    For multi-service bookings (e.g., "corte y color"), pass ALL service names
    as a list. The tool sums durations and searches for slots that fit the total.

    AUTO-SEARCH: If no slots exist on the requested date, automatically searches
    the next open business days.

    Args:
        service_names: List of exact service names from the catalog
        date: Date in natural Spanish ('mañana', 'viernes') or ISO ('2026-04-10')
        stylist_name: Optional preferred stylist name from the catalog
        time_range: Optional time filter ('morning', 'afternoon', or '14:00-18:00')

    Returns:
        {
            "success": bool,
            "service": {"name": str, "duration_minutes": int, "category": str},
            "services": [{"name": str, "duration_minutes": int, "category": str}, ...],
            "total_duration_minutes": int,
            "requested_date": str,
            "available_slots": [...],
            "alternative_dates": bool,
            "date_too_soon": bool,
            "min_valid_date": str | None,
            "holiday_detected": bool,
            "error_code": str | None,
            "error_message": str | None
        }
    """
    base_response: dict[str, Any] = {
        "success": False,
        "service": None,
        "services": [],
        "total_duration_minutes": 0,
        "requested_date": None,
        "available_slots": [],
        "alternative_dates": False,
        "date_too_soon": False,
        "min_valid_date": None,
        "holiday_detected": False,
        "error_code": None,
        "error_message": None,
    }

    try:
        # ── 1. Resolve all services ───────────────────────────────────────────
        resolved_services: list[Service] = []
        for svc_name in service_names:
            service = await _resolve_service_by_name(svc_name)
            if service is None:
                logger.warning(f"Service not found: '{svc_name}'")
                return {
                    **base_response,
                    "error_code": "SERVICE_NOT_FOUND",
                    "error_message": (
                        f"No encontré el servicio '{svc_name}' en el catálogo. "
                        "Verifica que el nombre sea exacto."
                    ),
                }
            resolved_services.append(service)

        # Validate all services share the same category
        categories = {svc.category for svc in resolved_services}
        if len(categories) > 1:
            cat_labels = ", ".join(c.value for c in categories)
            logger.warning(f"Category mismatch in multi-service: {cat_labels}")
            return {
                **base_response,
                "error_code": "CATEGORY_MISMATCH",
                "error_message": (
                    f"No se pueden combinar servicios de categorías distintas ({cat_labels}) "
                    "en la misma cita. Ofrece dos citas separadas."
                ),
            }

        # Sum durations and build service info
        duration_minutes = sum(svc.duration_minutes for svc in resolved_services)
        service_category = resolved_services[0].category
        services_info = [
            {"name": svc.name, "duration_minutes": svc.duration_minutes, "category": svc.category.value}
            for svc in resolved_services
        ]
        # Backwards compat: "service" points to first
        base_response["service"] = services_info[0]
        base_response["services"] = services_info
        base_response["total_duration_minutes"] = duration_minutes

        # ── 2. Resolve stylist (optional) ──────────────────────────────────────
        resolved_stylist: Stylist | None = None
        if stylist_name:
            resolved_stylist = await _resolve_stylist_by_name(stylist_name)
            if resolved_stylist is None:
                logger.warning(f"Stylist not found: '{stylist_name}'")
                return {
                    **base_response,
                    "error_code": "STYLIST_NOT_FOUND",
                    "error_message": (
                        f"No encontré la estilista '{stylist_name}'. "
                        "Verifica que el nombre sea exacto."
                    ),
                }

            # Validate category compatibility
            stylist_ok = (
                resolved_stylist.category == service_category
                or resolved_stylist.category == ServiceCategory.BOTH
            )
            if not stylist_ok:
                logger.warning(
                    f"Category mismatch: stylist '{resolved_stylist.name}' "
                    f"({resolved_stylist.category.value}) cannot do "
                    f"'{service.name}' ({service_category.value})"
                )
                return {
                    **base_response,
                    "error_code": "CATEGORY_MISMATCH",
                    "error_message": (
                        f"{resolved_stylist.name} no realiza servicios de "
                        f"{service_category.value}. "
                        "Elige una estilista compatible o deja el campo vacío."
                    ),
                }

        # ── 3. Build stylist list ──────────────────────────────────────────────
        if resolved_stylist:
            stylists = [resolved_stylist]
        else:
            stylists = await _get_active_stylists_for_category(service_category)
            if not stylists:
                logger.warning(f"No active stylists for category {service_category.value}")
                return {
                    **base_response,
                    "error_code": "NO_SLOTS",
                    "error_message": (
                        f"No hay estilistas activas para {service_category.value} en este momento."
                    ),
                }

        # ── 4. Parse date ──────────────────────────────────────────────────────
        try:
            requested_date = parse_natural_date(date, timezone=MADRID_TZ)
            logger.info(f"Parsed date '{date}' → {requested_date.date()}")
        except DateParseError as e:
            logger.error(f"Failed to parse date '{date}': {e}")
            return {
                **base_response,
                "error_code": "DATE_CLOSED",
                "error_message": (
                    f"No pude interpretar la fecha '{date}'. "
                    "Usa formato YYYY-MM-DD o una frase como 'próximo jueves'."
                ),
            }

        base_response["requested_date"] = requested_date.date().isoformat()

        # ── 5. Validate 3-day rule ─────────────────────────────────────────────
        validation = await validate_3_day_rule(requested_date)
        if not validation["valid"]:
            logger.warning(f"3-day rule violation for date {requested_date.date()}")
            min_valid = (
                datetime.now(MADRID_TZ) + timedelta(days=MINIMUM_DAYS)
            ).date().isoformat()
            return {
                **base_response,
                "date_too_soon": True,
                "min_valid_date": min_valid,
                "error_code": "DATE_CLOSED",
                "error_message": validation["error_message"],
            }

        # ── 6. Check holiday on requested date ─────────────────────────────────
        holiday_name = await is_holiday(requested_date)
        if holiday_name:
            logger.info(f"Holiday detected on {requested_date.date()}: {holiday_name}")
            return {
                **base_response,
                "holiday_detected": True,
                "error_code": "DATE_CLOSED",
                "error_message": (
                    f"El salón está cerrado el {requested_date.date().isoformat()} "
                    f"por {holiday_name}."
                ),
            }

        # ── 7. Check if date is a closed business day ──────────────────────────
        if await is_date_closed(requested_date):
            logger.info(f"Business closed on {requested_date.date()}")
            day_label = _DAY_NAMES_ES[requested_date.weekday()]
            return {
                **base_response,
                "error_code": "DATE_CLOSED",
                "error_message": (
                    f"El salón no abre los {day_label}s. "
                    "Elige otro día."
                ),
            }

        # ── 8. Query availability ──────────────────────────────────────────────
        def _build_day_label(dt: datetime) -> str:
            day_name = _DAY_NAMES_ES[dt.weekday()]
            return f"{day_name} {dt.day} de {_MONTH_NAMES_ES[dt.month - 1]}"

        all_slots = await _collect_slots_for_date(
            requested_date, stylists, duration_minutes, time_range
        )

        # ── 9. AUTO-SEARCH: next 3 open days if empty ──────────────────────────
        config = await get_booking_config()
        alternative_dates = False
        if not all_slots:
            logger.info(
                f"No slots on {requested_date.date()}, auto-searching next "
                f"{config.auto_search_extra_days} open business days"
            )
            search_from = requested_date + timedelta(days=1)
            days_found = 0

            for _ in range(30):  # safety upper-bound
                if days_found >= config.auto_search_extra_days:
                    break

                # Skip closed days
                if await is_date_closed(search_from):
                    search_from += timedelta(days=1)
                    continue

                # Skip holidays
                if await is_holiday(search_from):
                    search_from += timedelta(days=1)
                    continue

                day_slots = await _collect_slots_for_date(
                    search_from, stylists, duration_minutes, time_range
                )
                if day_slots:
                    all_slots.extend(day_slots)
                    days_found += 1
                    alternative_dates = True

                search_from += timedelta(days=1)

        # ── 10. Return result ──────────────────────────────────────────────────
        if not all_slots:
            logger.info("No slots found even after auto-search")
            return {
                **base_response,
                "error_code": "NO_SLOTS",
                "error_message": (
                    "No encontré disponibilidad en los próximos días. "
                    "Intenta con otra fecha o estilista."
                ),
            }

        # Diversify and limit slots using config
        all_slots = diversify_slots(
            all_slots,
            strategy=config.slot_diversification_strategy.value,
            max_slots=config.max_slots_to_present,
        )

        # Add 1-based index
        for idx, slot in enumerate(all_slots, start=1):
            slot["index"] = idx

        logger.info(
            f"Found {len(all_slots)} slots for {service_names} ({duration_minutes}min) "
            f"({'alternative dates' if alternative_dates else 'requested date'})"
        )

        return {
            **base_response,
            "success": True,
            "available_slots": all_slots,
            "alternative_dates": alternative_dates,
        }

    except Exception as e:
        logger.error(f"Error in check_availability: {e}", exc_info=True)
        return {
            **base_response,
            "error_code": "NO_SLOTS",
            "error_message": f"Error verificando disponibilidad: {str(e)}",
        }


# Spanish month names (1-indexed via month - 1)
_MONTH_NAMES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


async def _collect_slots_for_date(
    target_date: datetime,
    stylists: list[Stylist],
    duration_minutes: int,
    time_range: str | None,
) -> list[dict[str, Any]]:
    """Query all stylists for available slots on target_date, apply time_range filter."""
    day_label = (
        f"{_DAY_NAMES_ES[target_date.weekday()]} "
        f"{target_date.day} de "
        f"{_MONTH_NAMES_ES[target_date.month - 1]}"
    )
    date_iso = target_date.strftime("%Y-%m-%d")

    slots: list[dict[str, Any]] = []
    for stylist in stylists:
        raw_slots = await get_available_slots(
            stylist_id=stylist.id,
            target_date=target_date,
            service_duration_minutes=duration_minutes,
            pack_slots=True,
        )
        for slot in raw_slots:
            slot_data = {
                "time": slot["time"],
                "end_time": slot["end_time"],
                "stylist_name": stylist.name,
                "stylist_id": str(stylist.id),
                "date": date_iso,
                "day_label": day_label,
                "full_datetime": slot["full_datetime"],
            }
            if time_range and not _slot_matches_time_range(slot_data, time_range):
                continue
            slots.append(slot_data)

    return slots


def diversify_slots(
    slots: list[dict[str, Any]],
    strategy: str = "one_per_stylist",
    max_slots: int = 5,
) -> list[dict[str, Any]]:
    """
    Select and diversify slots for presentation using the given strategy.

    This is a PURE function — no I/O, no async, no side effects.

    Each slot dict must contain at minimum: date (str), time (str),
    stylist_name (str), stylist_id (str).

    Strategies:
        "one_per_stylist" (default):
            Pick the earliest slot per stylist, then round-robin fill remaining
            capacity from leftover slots ordered by stylist earliest time.

        "time_spread":
            Pick one slot per 1-hour time bucket (earliest in bucket, prefer
            stylist diversity). Fill remaining from largest buckets first.

        "none":
            Sort by (date, time), return [:max_slots].

        Unknown strategy:
            Logs a WARNING and falls back to "none" behaviour. Never raises.

    Args:
        slots: List of slot dicts.
        strategy: Diversification strategy name.
        max_slots: Maximum number of slots to return.

    Returns:
        Sorted (date, time) list of at most max_slots slots.
    """
    if not slots:
        return []

    if strategy == "one_per_stylist":
        return _diversify_one_per_stylist(slots, max_slots)
    elif strategy == "time_spread":
        return _diversify_time_spread(slots, max_slots)
    elif strategy == "none":
        return _diversify_none(slots, max_slots)
    else:
        logger.warning(
            f"diversify_slots: unknown strategy '{strategy}', falling back to 'none'"
        )
        return _diversify_none(slots, max_slots)


def _sort_key(slot: dict[str, Any]) -> tuple[str, str]:
    """Sort key: (date, time) ascending."""
    return (slot["date"], slot["time"])


def _diversify_none(slots: list[dict[str, Any]], max_slots: int) -> list[dict[str, Any]]:
    """Sort by (date, time) and cap at max_slots."""
    return sorted(slots, key=_sort_key)[:max_slots]


def _diversify_one_per_stylist(
    slots: list[dict[str, Any]], max_slots: int
) -> list[dict[str, Any]]:
    """
    Round-robin strategy: one earliest slot per stylist, then fill from leftovers.

    Algorithm:
    1. Group all slots by stylist_name.
    2. Sort each group by (date, time) ascending.
    3. Pick the first (earliest) slot from each group → result.
    4. While len(result) < max_slots and there are remaining slots:
       - Cycle through stylists ordered by their earliest remaining time.
       - Take the next earliest slot per stylist in round-robin order.
    5. Sort result by (date, time) and return [:max_slots].
    """
    # Group by stylist
    groups: dict[str, list[dict[str, Any]]] = {}
    for slot in slots:
        name = slot["stylist_name"]
        groups.setdefault(name, []).append(slot)

    # Sort each group by (date, time)
    for name in groups:
        groups[name].sort(key=_sort_key)

    # Pointers into each group (index of next slot to consume)
    pointers: dict[str, int] = {name: 0 for name in groups}

    result: list[dict[str, Any]] = []

    # Pick first slot per stylist
    for name in groups:
        if len(result) >= max_slots:
            break
        result.append(groups[name][0])
        pointers[name] = 1

    # Round-robin fill from remaining slots
    while len(result) < max_slots:
        # Build list of stylists that still have slots, ordered by their next earliest slot
        available = [
            name
            for name in groups
            if pointers[name] < len(groups[name])
        ]
        if not available:
            break
        # Sort by next earliest slot for consistent ordering
        available.sort(key=lambda n: _sort_key(groups[n][pointers[n]]))

        added_this_round = False
        for name in available:
            if len(result) >= max_slots:
                break
            idx = pointers[name]
            if idx < len(groups[name]):
                result.append(groups[name][idx])
                pointers[name] += 1
                added_this_round = True

        if not added_this_round:
            break

    return sorted(result, key=_sort_key)[:max_slots]


def _diversify_time_spread(
    slots: list[dict[str, Any]], max_slots: int
) -> list[dict[str, Any]]:
    """
    Time-spread strategy: one slot per 1-hour bucket, then fill from largest buckets.

    Algorithm:
    1. Bucket slots by hour (slot["time"][:2], e.g. "10", "11").
    2. Within each bucket sort by (date, time); prefer different stylists when picking.
    3. Pick one slot per bucket → result.
    4. While len(result) < max_slots:
       - Fill from remaining slots in buckets, largest bucket first (most remaining).
    5. Sort result by (date, time) and return [:max_slots].
    """
    # Group slots into 1-hour buckets
    buckets: dict[str, list[dict[str, Any]]] = {}
    for slot in slots:
        hour = slot["time"][:2]
        buckets.setdefault(hour, []).append(slot)

    # Sort each bucket by (date, time)
    for hour in buckets:
        buckets[hour].sort(key=_sort_key)

    # Pointers into each bucket
    pointers: dict[str, int] = {hour: 0 for hour in buckets}

    result: list[dict[str, Any]] = []
    seen_stylists: set[str] = set()

    # Pick one slot per bucket (prefer diversity of stylists)
    for hour in sorted(buckets.keys()):
        if len(result) >= max_slots:
            break
        bucket = buckets[hour]
        # Try to pick a stylist not yet represented
        picked = None
        for slot in bucket:
            if slot["stylist_name"] not in seen_stylists:
                picked = slot
                pointers[hour] = bucket.index(slot) + 1
                break
        if picked is None:
            # All stylists already seen — just pick earliest
            picked = bucket[0]
            pointers[hour] = 1
        result.append(picked)
        seen_stylists.add(picked["stylist_name"])

    # Fill remaining from buckets with most leftover slots first
    while len(result) < max_slots:
        # Find buckets that still have slots
        available_buckets = [
            hour for hour in buckets if pointers[hour] < len(buckets[hour])
        ]
        if not available_buckets:
            break
        # Sort by remaining count descending, then hour ascending for stability
        available_buckets.sort(
            key=lambda h: (-len(buckets[h]) + pointers[h], h)
        )
        added_this_round = False
        for hour in available_buckets:
            if len(result) >= max_slots:
                break
            idx = pointers[hour]
            if idx < len(buckets[hour]):
                result.append(buckets[hour][idx])
                pointers[hour] += 1
                added_this_round = True
        if not added_this_round:
            break

    return sorted(result, key=_sort_key)[:max_slots]


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

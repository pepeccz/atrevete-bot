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

    service_name: str = Field(description="Nombre exacto del servicio del catálogo")
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
    service_name: str,
    date: str,
    stylist_name: str | None = None,
    time_range: str | None = None,
) -> dict[str, Any]:
    """
    Check availability for a service on a date, resolved from the service catalog.

    ONLY valid source for available appointment slots. You MUST NOT guess availability
    or invent time slots. ALWAYS call this tool when checking if a customer can book
    on a specific date.

    Resolves service_name to a catalog Service (duration + category), optionally
    resolves stylist_name to a Stylist, validates category compatibility, then
    queries the DB-first availability service.

    AUTO-SEARCH: If no slots exist on the requested date, automatically searches
    the next 3 open business days and returns those results with alternative_dates=True.

    Automatically validates:
    - Service exists in catalog (SERVICE_NOT_FOUND)
    - Stylist exists (STYLIST_NOT_FOUND) and matches service category (CATEGORY_MISMATCH)
    - 3-day minimum notice requirement (date_too_soon=True)
    - Holiday closures (holiday_detected=True)
    - Business hours constraints

    Args:
        service_name: Exact service name from the catalog
        date: Date in natural Spanish ('mañana', 'viernes') or ISO ('2026-04-10')
        stylist_name: Optional preferred stylist name from the catalog
        time_range: Optional time filter ('morning', 'afternoon', or '14:00-18:00')

    Returns:
        {
            "success": bool,
            "service": {"name": str, "duration_minutes": int, "category": str},
            "requested_date": str,          # ISO format
            "available_slots": [
                {
                    "index": int,           # 1-based
                    "time": "10:00",
                    "end_time": "10:45",
                    "stylist_name": "Marta",
                    "stylist_id": "uuid",
                    "date": "2026-04-10",
                    "day_label": "jueves 10 de abril",
                    "full_datetime": "2026-04-10T10:00:00+02:00"
                }
            ],
            "alternative_dates": bool,      # True if slots are from later dates (auto-search)
            "date_too_soon": bool,
            "min_valid_date": str | None,   # ISO date if date_too_soon
            "holiday_detected": bool,
            "error_code": str | None,       # SERVICE_NOT_FOUND, STYLIST_NOT_FOUND,
                                            # CATEGORY_MISMATCH, NO_SLOTS, DATE_CLOSED
            "error_message": str | None
        }
    """
    base_response: dict[str, Any] = {
        "success": False,
        "service": None,
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
        # ── 1. Resolve service ─────────────────────────────────────────────────
        service = await _resolve_service_by_name(service_name)
        if service is None:
            logger.warning(f"Service not found: '{service_name}'")
            return {
                **base_response,
                "error_code": "SERVICE_NOT_FOUND",
                "error_message": (
                    f"No encontré el servicio '{service_name}' en el catálogo. "
                    "Verificá que el nombre sea exacto."
                ),
            }

        duration_minutes = service.duration_minutes
        service_category = service.category
        service_info = {
            "name": service.name,
            "duration_minutes": duration_minutes,
            "category": service_category.value,
        }
        base_response["service"] = service_info

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
                        "Verificá que el nombre sea exacto."
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
                        "Elegí una estilista compatible o dejá el campo vacío."
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
                    "Usá formato YYYY-MM-DD o una frase como 'próximo jueves'."
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
                    "Elegí otro día."
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
        alternative_dates = False
        if not all_slots:
            logger.info(
                f"No slots on {requested_date.date()}, auto-searching next "
                f"{_AUTO_SEARCH_EXTRA_DAYS} open business days"
            )
            search_from = requested_date + timedelta(days=1)
            days_found = 0

            for _ in range(30):  # safety upper-bound
                if days_found >= _AUTO_SEARCH_EXTRA_DAYS:
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
                    "Intentá con otra fecha o estilista."
                ),
            }

        # Sort by date then time, limit to MAX_SLOTS_TO_PRESENT
        all_slots.sort(key=lambda s: (s["date"], s["time"]))
        all_slots = all_slots[:MAX_SLOTS_TO_PRESENT]

        # Add 1-based index
        for idx, slot in enumerate(all_slots, start=1):
            slot["index"] = idx

        logger.info(
            f"Found {len(all_slots)} slots for '{service_name}' "
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

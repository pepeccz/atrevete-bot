"""
check_availability — slot query tool for BOOKING mode.

Thin wrapper over agent/services/availability_service.get_available_slots.
Does NOT re-implement availability logic.
Returns JSON-serialized ToolResponse.
"""

import logging
from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from langchain_core.tools import tool

from agent.services.availability_service import get_available_slots
from agent.tools.schemas import ToolResponse
from shared.date_format import format_date_spanish

logger = logging.getLogger(__name__)


async def _load_lead_time_settings() -> tuple[int, int]:
    """Return (minimum_booking_days_advance, same_day_buffer_hours).

    Raises any exception on DB/settings failure (caller handles fail-closed).
    Imported lazily inside function so tests can patch get_settings_service.
    """
    from shared.settings_service import get_settings_service

    service = await get_settings_service()
    min_days = await service.get("minimum_booking_days_advance", default=0)
    buffer_hours = await service.get("same_day_buffer_hours", default=0)
    return int(min_days or 0), int(buffer_hours or 0)


async def _get_service_durations(service_ids: list[UUID]) -> dict[UUID, int]:
    """Fetch duration_minutes for each service_id. Returns {id: duration}."""
    from sqlalchemy import select

    from database.connection import get_async_session
    from database.models import Service

    async with get_async_session() as session:
        result = await session.execute(
            select(Service.id, Service.duration_minutes).where(Service.id.in_(service_ids))
        )
        return {row[0]: row[1] for row in result.fetchall()}


async def _get_active_stylists_for_services(
    service_ids: list[UUID],
    audience: str | None,
) -> list[UUID]:
    """
    Return IDs of active stylists who can serve the given services.

    Matching logic: use the service.category to determine which stylist category
    can serve it. If all services are HAIRDRESSING → hairdressing stylists.
    If any service is AESTHETICS → aesthetics stylists.
    Mixed → all active stylists.
    """
    from sqlalchemy import select

    from database.connection import get_async_session
    from database.models import Service, ServiceCategory, Stylist

    async with get_async_session() as session:
        svc_result = await session.execute(
            select(Service.category).where(Service.id.in_(service_ids))
        )
        categories = {row[0] for row in svc_result.fetchall()}

        has_hair = ServiceCategory.HAIRDRESSING in categories
        has_aesthetics = ServiceCategory.AESTHETICS in categories

        if has_hair and not has_aesthetics:
            stylist_filter = Stylist.category == ServiceCategory.HAIRDRESSING
        elif has_aesthetics and not has_hair:
            stylist_filter = Stylist.category == ServiceCategory.AESTHETICS
        else:
            # Mixed or empty — return all active
            stylist_filter = Stylist.is_active.is_(True)

        result = await session.execute(
            select(Stylist.id).where(Stylist.is_active.is_(True)).where(stylist_filter)
        )
        return [row[0] for row in result.fetchall()]


async def _get_stylist_name(stylist_id: UUID) -> str:
    """Fetch stylist name by ID."""
    from sqlalchemy import select

    from database.connection import get_async_session
    from database.models import Stylist

    async with get_async_session() as session:
        result = await session.execute(select(Stylist.name).where(Stylist.id == stylist_id))
        row = result.first()
        return row[0] if row else str(stylist_id)


async def _get_stylist_names_map(stylist_ids: list[UUID]) -> dict[UUID, str]:
    """Fetch names for a list of stylist UUIDs. Returns {id: name}."""
    from sqlalchemy import select

    from database.connection import get_async_session
    from database.models import Stylist

    if not stylist_ids:
        return {}

    async with get_async_session() as session:
        result = await session.execute(
            select(Stylist.id, Stylist.name).where(Stylist.id.in_(stylist_ids))
        )
        return {row[0]: row[1] for row in result.fetchall()}


def _build_available_stylists(stylist_ids: list[UUID], names_map: dict[UUID, str]) -> list[dict]:
    """Build sorted available_stylists list from IDs + names map."""
    entries = [{"id": str(sid), "name": names_map.get(sid, str(sid))} for sid in stylist_ids]
    return sorted(entries, key=lambda e: e["name"])


@tool
async def check_availability(
    service_ids: list[str],
    stylist_id: str | None,
    date_iso: str | None = None,
    audience: (
        Literal["adult_female", "adult_male", "child_female", "child_male", "baby", "unisex"] | None
    ) = None,
    no_preference: bool = True,
) -> str:
    """
    Check available time slots for the given services on a specific date.

    Args:
        service_ids: List of service UUIDs (as strings).
        stylist_id: Stylist UUID string, or None for "no preference" (aggregates all).
        date_iso: Target date in ISO format (YYYY-MM-DD).
        audience: Customer audience filter (optional).
        no_preference: True if the customer has no stylist preference (skips stylist guard).

    Returns:
        JSON-serialized ToolResponse with payload.slots list and
        payload.total_duration_minutes.
    """
    from agent.tools._booking_helpers import _compute_first_valid_date

    # --- Precondition: date required ---
    if not date_iso:
        logger.info(
            "tool.response.rejected",
            extra={"tool_name": "check_availability", "next_step": "date_required"},
        )
        return ToolResponse(
            status="rejected",
            next_step="date_required",
            errors=["Se necesita una fecha para consultar disponibilidad."],
        ).model_dump_json()

    # --- Precondition: stylist required (unless no_preference) ---
    if stylist_id is None and not no_preference:
        logger.info(
            "tool.response.rejected",
            extra={"tool_name": "check_availability", "next_step": "stylist_required"},
        )
        return ToolResponse(
            status="rejected",
            next_step="stylist_required",
            errors=["Se necesita un estilista o indicar 'sin preferencia' para consultar."],
        ).model_dump_json()

    # --- Parse + validate date ---
    try:
        target_date = date.fromisoformat(date_iso)
    except ValueError:
        return ToolResponse(
            status="rejected",
            errors=[f"El formato de fecha '{date_iso}' no es válido (se esperaba YYYY-MM-DD)."],
        ).model_dump_json()

    # --- Lead-time guard (fail-closed on SettingsService error) ---
    try:
        min_days, _buffer_hours = await _load_lead_time_settings()
    except Exception as exc:
        logger.warning("check_availability: SettingsService unavailable: %s", exc)
        return ToolResponse(
            status="rejected",
            errors=[
                "No pudimos validar el tiempo mínimo de reserva. "
                "Intenta de nuevo en unos minutos."
            ],
        ).model_dump_json()

    today = date.today()
    if target_date < today:
        return ToolResponse(
            status="rejected",
            errors=[
                f"La fecha solicitada ({date_iso}) ya ha pasado. "
                "La disponibilidad solo puede consultarse para fechas futuras."
            ],
        ).model_dump_json()

    if min_days > 0 and target_date < today + timedelta(days=min_days):
        first_valid = _compute_first_valid_date(today, min_days)
        days_word = "día" if min_days == 1 else "días"
        logger.info(
            "tool.response.rejected",
            extra={
                "tool_name": "check_availability",
                "next_step": "advance_policy_violated",
                "first_valid_date": first_valid.isoformat(),
                "policy_min_days": min_days,
            },
        )
        return ToolResponse(
            status="rejected",
            next_step="advance_policy_violated",
            payload={
                "first_valid_date": first_valid.isoformat(),
                "policy_min_days": min_days,
            },
            errors=[
                f"Solo podemos reservar con al menos {min_days} {days_word} de antelación. "
                f"La fecha más próxima disponible es {first_valid.isoformat()}."
            ],
        ).model_dump_json()

    # --- Parse service IDs ---
    try:
        parsed_service_ids = [UUID(sid) for sid in service_ids]
    except (ValueError, AttributeError):
        return ToolResponse(
            status="rejected",
            errors=["Uno o más service_ids no tienen formato UUID válido."],
        ).model_dump_json()

    # --- Fetch service durations ---
    durations = await _get_service_durations(parsed_service_ids)
    if not durations:
        return ToolResponse(
            status="rejected",
            errors=["No se encontraron los servicios solicitados en el catálogo activo."],
        ).model_dump_json()

    total_duration = sum(durations.values())

    # --- Determine stylists to query ---
    if stylist_id:
        try:
            parsed_stylist_id = UUID(stylist_id)
        except ValueError:
            return ToolResponse(
                status="rejected",
                errors=[f"El stylist_id '{stylist_id}' no tiene formato UUID válido."],
            ).model_dump_json()
        stylist_ids = [parsed_stylist_id]
    else:
        stylist_ids = await _get_active_stylists_for_services(parsed_service_ids, audience)
        if not stylist_ids:
            return ToolResponse(
                status="rejected",
                errors=["No hay estilistas activos disponibles para los servicios solicitados."],
            ).model_dump_json()

    # --- Fetch stylist names for available_stylists payload field ---
    names_map = await _get_stylist_names_map(stylist_ids)

    # --- Aggregate slots across stylists ---
    all_slots = []
    for sid in stylist_ids:
        slots = await get_available_slots(
            stylist_id=sid,
            target_date=target_date,
            service_duration_minutes=total_duration,
        )
        for slot in slots:
            full_dt = slot["full_datetime"]
            all_slots.append(
                {
                    "start_iso": full_dt,
                    "end_iso": _compute_end_iso(full_dt, total_duration),
                    "stylist_id": str(sid),
                    "stylist_name": slot.get("stylist_name", names_map.get(sid, "")),
                    "label": _slot_label(full_dt),
                    "adjacent_priority": slot.get("adjacent_priority", 1),
                }
            )

    # Sort by adjacent_priority then start_iso
    all_slots.sort(key=lambda s: (s["adjacent_priority"], s["start_iso"]))
    # Strip internal priority field before returning
    clean_slots = [{k: v for k, v in s.items() if k != "adjacent_priority"} for s in all_slots]

    return ToolResponse(
        status="ok",
        payload={
            "slots": clean_slots,
            "total_duration_minutes": total_duration,
            "requested_date_iso": target_date.isoformat(),
            "requested_date_label": format_date_spanish(target_date),
            "is_exact_day": True,
            "has_availability": bool(clean_slots),
            "available_stylists": _build_available_stylists(stylist_ids, names_map),
        },
    ).model_dump_json()


def _slot_label(full_datetime: str) -> str:
    """Return Spanish date label for a slot's full_datetime ISO string."""
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(full_datetime.replace("Z", "+00:00"))
    except ValueError:
        return full_datetime[:10]  # fallback to ISO date prefix
    return format_date_spanish(dt)


def _compute_end_iso(start_iso: str, duration_minutes: int) -> str:
    """Compute end ISO from start ISO + duration."""
    from datetime import datetime

    # Parse ISO with offset
    try:
        if "+" in start_iso[10:] or start_iso.endswith("Z"):
            dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(start_iso)
    except ValueError:
        return start_iso  # fallback
    end = dt + timedelta(minutes=duration_minutes)
    return end.isoformat()

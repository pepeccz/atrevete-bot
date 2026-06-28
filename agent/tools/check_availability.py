"""
check_availability — slot query tool for BOOKING mode.

Thin wrapper over agent/services/availability_service.get_available_slots.
Does NOT re-implement availability logic.
Returns JSON-serialized ToolResponse.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.services.availability_service import get_available_slots
from agent.tools.schemas import ToolResponse
from shared.date_format import format_date_spanish

logger = logging.getLogger(__name__)

_MADRID_TZ = ZoneInfo("Europe/Madrid")


async def _load_lead_time_settings() -> tuple[int, int]:
    """Return (minimum_booking_days_advance, same_day_buffer_hours).

    Raises any exception on DB/settings failure (caller handles fail-closed).
    Imported lazily inside function so tests can patch get_settings_service.
    """
    from shared.settings_service import get_settings_service

    service = await get_settings_service()
    min_days = await service.get("minimum_booking_days_advance", default=3)
    buffer_hours = await service.get("same_day_buffer_hours", default=0)
    return int(min_days or 3), int(buffer_hours or 0)


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
            # Mixed or empty — fail-closed (defense in depth; update_booking blocks upstream)
            return []

        result = await session.execute(
            select(Stylist.id).where(Stylist.is_active.is_(True)).where(stylist_filter)
        )
        return [row[0] for row in result.fetchall()]


async def _requires_audience_disambiguation(
    service_ids: list[UUID],
    customer_memories: dict | None = None,
    customer_id: str | None = None,
) -> bool:
    """True when the services need an audience resolved before offering slots.

    Source-aware (guard C): a pinned gendered service with a legitimate audience
    source (memory backing or a prior appointment) is ALLOWED so a known customer
    is not re-asked; a gendered service with NO source still BLOCKS (cold
    direct-to-availability bypass); a genuinely ambiguous neutral principal always
    BLOCKS. Thin DB wrapper over `availability_requires_audience`. Fail-open
    (returns False) on any error: an availability check must never be killed by
    this guard. Module-level so unit tests can patch it without a live catalog.
    """
    try:
        from agent.tools._booking_helpers import availability_requires_audience
        from database.connection import get_async_session

        async with get_async_session() as session:
            return await availability_requires_audience(
                session, service_ids, customer_memories, customer_id
            )
    except Exception as exc:
        logger.error(
            "check_availability: audience-family guard failed (fail-open): %s", exc, exc_info=True
        )
        return False


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


def _madrid_hour(start_iso: str) -> int:
    """Return the hour (0-23) of a slot's start_iso string in Madrid time (Europe/Madrid)."""
    _MADRID_TZ = ZoneInfo("Europe/Madrid")
    dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    return dt.astimezone(_MADRID_TZ).hour


@tool
async def check_availability(
    service_ids: list[str],
    stylist_id: str | None,
    date_iso: str | None = None,
    audience: (
        Literal["adult_female", "adult_male", "child_female", "child_male", "baby", "unisex"] | None
    ) = None,
    no_preference: bool = True,
    slot_time: str | None = None,
    preferred_window: Literal["morning", "afternoon"] | None = None,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Check available time slots for the given services on a specific date.

    Args:
        service_ids: List of service UUIDs (as strings).
        stylist_id: Stylist UUID string, or None for "no preference" (aggregates all).
        date_iso: Target date in ISO format (YYYY-MM-DD).
        audience: Customer audience filter (optional).
        no_preference: True if the customer has no stylist preference (skips stylist guard).
        slot_time: Optional HH:MM time string for pre-book exact-match validation.
            When set, filters slots to an exact time match:
            - If found → returns status="ok" with payload.exact_match=True and a single slot.
            - If not found → returns status="rejected", next_step="slot_no_longer_available",
              and payload.alternatives with up to 3 available slots.
        preferred_window: Optional time-of-day filter for returned slots.
            - "morning": only slots 09:00–13:59 Madrid time.
            - "afternoon": only slots 14:00–19:59 Madrid time.
            - None: no filter applied (default).

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
        logger.error("check_availability: SettingsService unavailable: %s", exc, exc_info=True)
        return ToolResponse(
            status="rejected",
            errors=[
                "No pudimos validar el tiempo mínimo de reserva. "
                "Intenta de nuevo en unos minutos."
            ],
        ).model_dump_json()

    today = datetime.now(_MADRID_TZ).date()
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

    # --- Audience-disambiguation guard (source-aware, deterministic) ---
    # If the services belong to an audience-ambiguous family (e.g. the "cut"
    # dimension: Corte de Mujer / Corte de Hombre / Corte de Niña …) and the
    # caller has not resolved the audience, refuse to offer slots and ask first —
    # UNLESS the service pins a single gendered audience AND the customer has a
    # legitimate source (memory backing or a prior appointment), in which case a
    # known customer is not re-asked. A gendered service with NO source still
    # blocks (cold direct-to-availability bypass). See R32 / R9b.
    _state = state or {}
    if audience is None and await _requires_audience_disambiguation(
        parsed_service_ids,
        customer_memories=_state.get("customer_memories"),
        customer_id=_state.get("customer_id"),
    ):
        logger.info(
            "tool.response.rejected",
            extra={"tool_name": "check_availability", "next_step": "audience_required"},
        )
        return ToolResponse(
            status="rejected",
            next_step="audience_required",
            errors=["Necesito saber para quién es el servicio antes de mirar los horarios."],
        ).model_dump_json()

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

    # --- preferred_window filter (time-of-day, Madrid time) ---
    if preferred_window == "morning":
        clean_slots = [s for s in clean_slots if 9 <= _madrid_hour(s["start_iso"]) < 14]
    elif preferred_window == "afternoon":
        clean_slots = [s for s in clean_slots if 14 <= _madrid_hour(s["start_iso"]) < 20]

    # --- Closed-day detection (REQ-P2A-2) ---
    # When no slots were returned, check if the absence is due to closure rather than
    # genuine unavailability. This allows the prompt to give the correct apology message.
    if not clean_slots:
        from shared.business_hours_validator import is_date_closed

        if await is_date_closed(target_date):
            logger.info(
                "tool.response.rejected",
                extra={
                    "tool_name": "check_availability",
                    "next_step": "closed_day",
                    "date_iso": date_iso,
                },
            )
            return ToolResponse(
                status="rejected",
                next_step="closed_day",
                payload={
                    "closed_date": date_iso,
                    "weekday": target_date.strftime("%A").lower(),
                    "stylist_id": stylist_id,
                    "service_ids": service_ids,
                },
                errors=[f"El salón está cerrado el {format_date_spanish(target_date)}."],
            ).model_dump_json()

    # --- slot_time exact-match filter (pre-book re-validation, ADR-7) ---
    if slot_time is not None:
        matched = [s for s in clean_slots if s.get("start_iso", "").find(f"T{slot_time}:00") != -1]
        if matched:
            return ToolResponse(
                status="ok",
                payload={
                    "slots": matched[:1],
                    "exact_match": True,
                    "total_duration_minutes": total_duration,
                    "requested_date_iso": target_date.isoformat(),
                    "requested_date_label": format_date_spanish(target_date),
                    "available_stylists": _build_available_stylists(stylist_ids, names_map),
                },
            ).model_dump_json()
        else:
            alternatives = clean_slots[:3]
            return ToolResponse(
                status="rejected",
                next_step="slot_no_longer_available",
                payload={
                    "requested_slot_time": slot_time,
                    "alternatives": alternatives,
                    "total_duration_minutes": total_duration,
                    "requested_date_iso": target_date.isoformat(),
                },
                errors=[
                    f"El hueco de las {slot_time} ya no está disponible. "
                    "Aquí tienes alternativas para el mismo día."
                ],
            ).model_dump_json()

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

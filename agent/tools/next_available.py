"""Bounded next-available fallback tool for BOOKING mode."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from langchain_core.tools import tool

from agent.prompts.catalog_builder import get_service_display_label_by_ids
from agent.services.availability_service import (
    get_next_available_options as get_next_available_options_service,
)
from agent.tools.check_availability import (
    _get_active_stylists_for_services,
    _load_lead_time_settings,
    _get_service_durations,
    _get_stylist_name,
)
from agent.tools.schemas import ToolResponse


@tool
async def get_next_available_options(
    service_ids: list[str],
    requested_date_iso: str,
    stylist_id: str | None,
    audience: (
        Literal["adult_female", "adult_male", "child_female", "child_male", "baby", "unisex"] | None
    ) = None,
    strategy: Literal["same_stylist_then_any", "any_stylist"] = "same_stylist_then_any",
    max_options: int = 3,
    search_days: int = 7,
) -> str:
    """Return bounded next-available alternatives after an empty exact-day lookup."""
    try:
        requested_date = date.fromisoformat(requested_date_iso)
    except ValueError:
        return ToolResponse(
            status="rejected",
            errors=[
                f"El formato de fecha '{requested_date_iso}' no es válido (se esperaba YYYY-MM-DD)."
            ],
        ).model_dump_json()

    if requested_date < date.today():
        return ToolResponse(
            status="rejected",
            errors=[
                f"La fecha solicitada ({requested_date_iso}) ya ha pasado. "
                "La disponibilidad solo puede consultarse para fechas futuras."
            ],
        ).model_dump_json()

    # Apply minimum lead-time floor (sourced from settings, fallback = 3 days).
    try:
        min_days, _ = await _load_lead_time_settings()
    except Exception:
        min_days = 3

    floor_date = date.today() + timedelta(days=min_days)
    effective_from = max(requested_date, floor_date)
    floor_was_applied = effective_from != requested_date

    try:
        parsed_service_ids = [UUID(service_id) for service_id in service_ids]
    except (ValueError, AttributeError):
        return ToolResponse(
            status="rejected",
            errors=["Uno o más service_ids no tienen formato UUID válido."],
        ).model_dump_json()

    durations = await _get_service_durations(parsed_service_ids)
    if not durations:
        return ToolResponse(
            status="rejected",
            errors=["No se encontraron los servicios solicitados en el catálogo activo."],
        ).model_dump_json()

    total_duration = sum(durations.values())

    preferred_stylist_id: UUID | None = None
    if stylist_id:
        try:
            preferred_stylist_id = UUID(stylist_id)
        except ValueError:
            return ToolResponse(
                status="rejected",
                errors=[f"El stylist_id '{stylist_id}' no tiene formato UUID válido."],
            ).model_dump_json()

    compatible_stylist_ids = await _get_active_stylists_for_services(parsed_service_ids, audience)
    if preferred_stylist_id and preferred_stylist_id not in compatible_stylist_ids:
        compatible_stylist_ids = [preferred_stylist_id, *compatible_stylist_ids]

    if not compatible_stylist_ids and preferred_stylist_id is None:
        return ToolResponse(
            status="rejected",
            errors=["No hay estilistas activos disponibles para los servicios solicitados."],
        ).model_dump_json()

    fallback_result = await get_next_available_options_service(
        requested_date=effective_from,
        service_duration_minutes=total_duration,
        preferred_stylist_id=preferred_stylist_id,
        candidate_stylist_ids=compatible_stylist_ids,
        strategy=strategy,
        max_options=max_options,
        search_days=search_days,
    )

    service_label = await get_service_display_label_by_ids(parsed_service_ids)
    enriched_options = []
    for option in fallback_result["options"]:
        enriched_options.append(
            {
                **option,
                "stylist_name": await _get_stylist_name(UUID(option["stylist_id"])),
                "service_label": service_label,
            }
        )

    payload: dict = {
        "options": enriched_options,
        "searched_until": fallback_result["searched_until"],
        "requested_date_iso": requested_date_iso,
        "total_duration_minutes": total_duration,
        "strategy": strategy,
    }
    if floor_was_applied:
        payload["effective_from_iso"] = effective_from.isoformat()

    return ToolResponse(
        status="ok",
        payload=payload,
    ).model_dump_json()

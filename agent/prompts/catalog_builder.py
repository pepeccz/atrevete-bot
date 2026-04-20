"""Builds the service catalog markdown from DB for LLM prompt injection."""
import logging

from sqlalchemy import select

from database.connection import get_async_session
from database.models import BusinessHours, Service, ServiceCategory, Stylist

logger = logging.getLogger(__name__)

_AUDIENCE_LABELS = {
    "adult_female": "Señora",
    "adult_male": "Caballero",
    "child_female": "Niña",
    "child_male": "Niño",
    "unisex": "Unisex",
    None: "General",
}

# Stable audience token used inside the [PRINCIPAL · dim · audience] tag.
# Kept machine-readable (matches the values the LLM sees in tool schemas).
_AUDIENCE_TOKENS = {
    "adult_female": "adult_female",
    "adult_male": "adult_male",
    "child_female": "child_female",
    "child_male": "child_male",
    "unisex": "unisex",
    None: "any",
}


def _build_service_type_tag(svc: Service) -> str:
    """Return the ``[PRINCIPAL · … ]`` / ``[VARIANTE de X]`` / ``[ADDON · …]``
    tag for a service, or an empty string when metadata is missing.

    Backward-compatible: if ``metadata_`` is absent / empty / lacks
    ``service_type``, no tag is emitted and the catalog line keeps the previous
    shape (``- {name} [INTERNO: …min] — {description}``).
    """
    metadata = svc.metadata_ or {}
    service_type = metadata.get("service_type")
    if not service_type:
        return ""

    dimension = metadata.get("dimension") or "unknown"

    if service_type == "principal":
        audience_token = _AUDIENCE_TOKENS.get(svc.audience, "any")
        return f" [PRINCIPAL · {dimension} · {audience_token}]"

    if service_type == "variant":
        parent = metadata.get("parent_service_name") or "?"
        return f" [VARIANTE de {parent}]"

    if service_type == "addon":
        return f" [ADDON · {dimension}]"

    # Unknown service_type — skip tag rather than emitting garbage.
    return ""

_CATEGORY_LABELS = {
    ServiceCategory.HAIRDRESSING: "Peluquería",
    ServiceCategory.AESTHETICS: "Estética",
    ServiceCategory.BOTH: "Peluquería y Estética",
}

_DAY_NAMES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


# Re-use the same _TtlCache pattern from agent/prompts/loader.py
# (datetime-based, asyncio.Lock for thundering-herd protection)
from agent.prompts.loader import _TtlCache

_catalog_cache = _TtlCache(ttl_minutes=5)  # 5-minute cache


async def build_catalog_markdown() -> str:
    """Build the full catalog markdown from DB. Cached for 5 minutes."""
    return await _catalog_cache.get_or_load(_build_catalog_from_db)


def invalidate_catalog_cache() -> None:
    """Force cache refresh on next call. Called by admin panel after service/stylist changes."""
    _catalog_cache.invalidate()
    logger.info("catalog_cache invalidated")


async def _build_catalog_from_db() -> str:
    """Query DB and render markdown."""
    async with get_async_session() as session:
        # Fetch active services ordered by category, name
        services_result = await session.execute(
            select(Service)
            .where(Service.is_active == True)  # noqa: E712
            .order_by(Service.category, Service.name)
        )
        services = services_result.scalars().all()

        # Fetch active stylists ordered by name
        stylists_result = await session.execute(
            select(Stylist)
            .where(Stylist.is_active == True)  # noqa: E712
            .order_by(Stylist.name)
        )
        stylists = stylists_result.scalars().all()

        # Fetch business hours ordered by day
        hours_result = await session.execute(
            select(BusinessHours).order_by(BusinessHours.day_of_week)
        )
        hours = hours_result.scalars().all()

    sections: list[str] = []

    # --- Services Section ---
    sections.append("## Catálogo de Servicios\n")

    # Group by category (ServiceCategory is str-enum so direct comparison works)
    categories: dict[str, list[Service]] = {}
    for svc in services:
        cat_label = _CATEGORY_LABELS.get(svc.category, str(svc.category))
        categories.setdefault(cat_label, []).append(svc)

    for cat_label, cat_services in categories.items():
        sections.append(f"### {cat_label}\n")

        for svc in cat_services:
            type_tag = _build_service_type_tag(svc)
            line = f"- {svc.name} [INTERNO: {svc.duration_minutes}min]{type_tag}"
            if svc.description:
                line += f" — {svc.description}"
            sections.append(line)
        sections.append("")

    # --- Stylists Section ---
    sections.append("## Estilistas\n")
    for sty in stylists:
        cat_label = _CATEGORY_LABELS.get(sty.category, str(sty.category))
        sections.append(f"- {sty.name} — {cat_label}")
    sections.append("")

    # --- Business Hours Section ---
    sections.append("## Horario del Salón\n")
    for h in hours:
        day_name = _DAY_NAMES[h.day_of_week] if h.day_of_week < len(_DAY_NAMES) else f"Día {h.day_of_week}"
        if h.is_closed:
            sections.append(f"- {day_name}: Cerrado")
        else:
            start = f"{h.start_hour:02d}:{h.start_minute:02d}"
            end = f"{h.end_hour:02d}:{h.end_minute:02d}"
            sections.append(f"- {day_name}: {start} - {end}")
    sections.append("")

    # --- Policies Section ---
    sections.append("## Políticas de Reserva\n")
    sections.append("- Anticipación mínima: 3 días (validado por herramientas — no rechaces fechas)")
    sections.append("- Cancelación o cambio: hasta 48 horas antes de la cita")
    sections.append("- La compatibilidad de categorías se valida automáticamente al buscar disponibilidad")
    sections.append("")

    catalog = "\n".join(sections)

    # Token estimate and logging
    estimated_tokens = len(catalog) // 4
    logger.info(
        "catalog_builder: generated %d services, %d stylists, ~%d tokens",
        len(services),
        len(stylists),
        estimated_tokens,
    )
    if estimated_tokens > 5000:
        logger.warning(
            "catalog_builder: token estimate %d exceeds 5000 budget", estimated_tokens
        )

    return catalog


__all__ = [
    "build_catalog_markdown",
    "invalidate_catalog_cache",
]

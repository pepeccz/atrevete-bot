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

        # Group by audience within category
        audience_groups: dict[str, list[Service]] = {}
        for svc in cat_services:
            aud_label = _AUDIENCE_LABELS.get(svc.audience, svc.audience or "General")
            audience_groups.setdefault(aud_label, []).append(svc)

        for aud_label, aud_services in audience_groups.items():
            if aud_label != "General":
                sections.append(f"**{aud_label}:**")
            for svc in aud_services:
                line = f"- {svc.name} [INTERNO: {svc.duration_minutes}min]"
                if svc.description:
                    line += f" — {svc.description}"
                sections.append(line)
            sections.append("")  # blank line between audience groups

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

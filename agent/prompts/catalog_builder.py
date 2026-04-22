"""Builds the service catalog for LLM prompt injection.

Public API
----------
ServiceRow: frozen dataclass — typed service row (name, audience, metadata).
build_catalog_for_prompt(services) -> str
    Pure function. Accepts list of Service-like objects. Returns tagged catalog string.
    Appends ``id={svc.id}`` to each line so the LLM can copy UUIDs verbatim.
build_catalog_markdown() -> Awaitable[str]
    Async. Full catalog markdown (services + stylists + hours + policies). Cached.
get_active_services() -> Awaitable[list[ServiceRow]]
    Async. Returns typed ServiceRow list. Shares cache with build_catalog_markdown.
build_catalog_prompt_section() -> Awaitable[str]
    Async. Alias that returns the catalog string (for DynamicPromptMiddleware).
invalidate_catalog_cache() -> None
    Force cache refresh. Called by admin panel after catalog changes.

Internal helpers
----------------
_build_service_type_tag(svc) -> str
    Renders the [PRINCIPAL · dim · audience] / [VARIANTE de X] / [ADDON · dim] tag.
_AUDIENCE_LABELS: dict[str | None, str] — human labels for audience values.
_CATEGORY_LABELS: dict[ServiceCategory, str] — human labels for service categories.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Typed row (immutable — safe to cache and pass across async boundaries)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ServiceRow:
    """Immutable typed row copied from the ORM session.

    Used by catalog consumers that need the active service list without
    a live DB session (e.g. tests, resolvers).
    """

    name: str
    audience: str | None
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Audience labels and tokens
# ---------------------------------------------------------------------------

_AUDIENCE_LABELS: dict[str | None, str] = {
    "adult_female": "Señora",
    "adult_male": "Caballero",
    "child_female": "Niña",
    "child_male": "Niño",
    "unisex": "Unisex",
    None: "General",
}

_AUDIENCE_TOKENS: dict[str | None, str] = {
    "adult_female": "adult_female",
    "adult_male": "adult_male",
    "child_female": "child_female",
    "child_male": "child_male",
    "unisex": "unisex",
    None: "any",
}

# ---------------------------------------------------------------------------
# Category labels
# ---------------------------------------------------------------------------


def _get_category_labels() -> dict:
    """Lazy-load category labels to avoid import-time circular imports."""
    from database.models import ServiceCategory

    return {
        ServiceCategory.HAIRDRESSING: "Peluquería",
        ServiceCategory.AESTHETICS: "Estética",
        ServiceCategory.BOTH: "Peluquería y Estética",
    }


try:
    from database.models import ServiceCategory

    _CATEGORY_LABELS: dict = {
        ServiceCategory.HAIRDRESSING: "Peluquería",
        ServiceCategory.AESTHETICS: "Estética",
        ServiceCategory.BOTH: "Peluquería y Estética",
    }
except Exception:  # pragma: no cover
    _CATEGORY_LABELS = {}

# ---------------------------------------------------------------------------
# Service type order
# ---------------------------------------------------------------------------

_SERVICE_TYPE_ORDER = {"principal": 0, "variant": 1, "addon": 2}

# ---------------------------------------------------------------------------
# Tag builder (pure function — easy to test)
# ---------------------------------------------------------------------------


def _build_service_type_tag(svc: Any) -> str:
    """Return the [PRINCIPAL · dim · audience] / [VARIANTE de X] / [ADDON · dim] tag.

    Returns an empty string when metadata is absent or incomplete (backward-compatible).
    """
    metadata = getattr(svc, "metadata_", None) or {}
    service_type = metadata.get("service_type")
    if not service_type:
        return ""

    dimension = metadata.get("dimension") or "unknown"

    if service_type == "principal":
        audience = getattr(svc, "audience", None)
        audience_token = _AUDIENCE_TOKENS.get(audience, "any")
        return f" [PRINCIPAL · {dimension} · {audience_token}]"

    if service_type == "variant":
        parent = metadata.get("parent_service_name") or "?"
        return f" [VARIANTE de {parent}]"

    if service_type == "addon":
        return f" [ADDON · {dimension}]"

    return ""


# ---------------------------------------------------------------------------
# Sort key for catalog ordering
# ---------------------------------------------------------------------------


def _sort_key(svc: Any) -> tuple[int, str, str]:
    meta = getattr(svc, "metadata_", None) or {}
    service_type = meta.get("service_type", "")
    order = _SERVICE_TYPE_ORDER.get(service_type, 99)
    cat = str(getattr(svc, "category", ""))
    return (order, cat, svc.name)


# ---------------------------------------------------------------------------
# Pure catalog builder (no DB, no cache — unit-testable)
# ---------------------------------------------------------------------------


def build_catalog_for_prompt(services: list[Any]) -> str:
    """Build a tagged catalog string from a list of Service-like objects.

    Format per line:
        [PRINCIPAL · {dim} · {audience}] {name} — {dur}min — {description} — id={uuid}

    UUID is appended so the LLM can copy it verbatim into tool call arguments
    (avoids hallucinated service IDs).

    Ordering: principals first (by category, name), then variants, then addons.
    """
    if not services:
        return ""

    sorted_services = sorted(services, key=_sort_key)
    lines: list[str] = []
    for svc in sorted_services:
        tag = _build_service_type_tag(svc)
        desc = getattr(svc, "description", None)
        dur = getattr(svc, "duration_minutes", 0)
        name = svc.name

        if tag:
            line = f"{tag} {name} — {dur}min"
        else:
            line = f"{name} — {dur}min"

        if desc:
            line += f" — {desc}"

        # Append machine-readable UUID so the LLM can copy it verbatim
        svc_id = getattr(svc, "id", None)
        if svc_id is not None:
            line += f" — id={svc_id}"

        lines.append(line)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Async DB helpers + TTL cache
# ---------------------------------------------------------------------------

from agent.prompts.loader import _TtlCache

_catalog_cache: _TtlCache[tuple[list[ServiceRow], str]] = _TtlCache(ttl_minutes=5)

_DAY_NAMES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


async def _build_catalog_from_db() -> tuple[list[ServiceRow], str]:
    """Query DB; return (list[ServiceRow], markdown_string) for cache storage."""
    from sqlalchemy import select

    from database.connection import get_async_session
    from database.models import BusinessHours, Service, Stylist

    async with get_async_session() as session:
        services_result = await session.execute(
            select(Service)
            .where(Service.is_active == True)  # noqa: E712
            .order_by(Service.category, Service.name)
        )
        services = services_result.scalars().all()

        stylists_result = await session.execute(
            select(Stylist).where(Stylist.is_active == True).order_by(Stylist.name)  # noqa: E712
        )
        stylists = stylists_result.scalars().all()

        hours_result = await session.execute(
            select(BusinessHours).order_by(BusinessHours.day_of_week)
        )
        hours = hours_result.scalars().all()

        rows: list[ServiceRow] = [
            ServiceRow(
                name=svc.name,
                audience=svc.audience,
                metadata=dict(svc.metadata_ or {}),
            )
            for svc in services
        ]

    # Build markdown
    cat_labels = _get_category_labels()
    sections: list[str] = []

    sections.append("## Catálogo de Servicios\n")
    categories: dict[str, list[Any]] = {}
    for svc in services:
        cat_label = cat_labels.get(svc.category, str(svc.category))
        categories.setdefault(cat_label, []).append(svc)

    for cat_label, cat_services in categories.items():
        sections.append(f"### {cat_label}\n")
        for svc in cat_services:
            type_tag = _build_service_type_tag(svc)
            line = f"- {svc.name} [INTERNO: {svc.duration_minutes}min]{type_tag}"
            if svc.description:
                line += f" — {svc.description}"
            svc_id = getattr(svc, "id", None)
            if svc_id is not None:
                line += f" — id={svc_id}"
            sections.append(line)
        sections.append("")

    sections.append("## Estilistas\n")
    for sty in stylists:
        cat_label = cat_labels.get(sty.category, str(sty.category))
        sections.append(f"- {sty.name} — {cat_label}")
    sections.append("")

    sections.append("## Horario del Salón\n")
    for h in hours:
        day_name = (
            _DAY_NAMES[h.day_of_week] if h.day_of_week < len(_DAY_NAMES) else f"Día {h.day_of_week}"
        )
        if h.is_closed:
            sections.append(f"- {day_name}: Cerrado")
        else:
            start = f"{h.start_hour:02d}:{h.start_minute:02d}"
            end = f"{h.end_hour:02d}:{h.end_minute:02d}"
            sections.append(f"- {day_name}: {start} - {end}")
    sections.append("")

    sections.append("## Políticas de Reserva\n")
    sections.append("- Anticipación mínima: 3 días")
    sections.append("- Cancelación: hasta 48 horas antes")
    sections.append("")

    return rows, "\n".join(sections)


async def build_catalog_markdown() -> str:
    """Build the full catalog markdown. Cached for 5 minutes."""
    _rows, markdown = await _catalog_cache.get_or_load(_build_catalog_from_db)
    return markdown


async def get_active_services() -> list[ServiceRow]:
    """Return active services as typed rows. Shares cache with build_catalog_markdown."""
    rows, _md = await _catalog_cache.get_or_load(_build_catalog_from_db)
    return rows


async def load_active_catalog() -> list[Any]:
    """Return active services from DB. Backward-compat alias."""
    return await get_active_services()


async def build_catalog_prompt_section() -> str:
    """Load active catalog from DB and return a tagged prompt string.

    Used by DynamicPromptMiddleware to inject catalog per-turn.
    Falls back to the simpler build_catalog_for_prompt format (with UUIDs).
    """
    try:
        services = await get_active_services()
        # For prompt injection we use the simple tagged format (not full markdown)
        # We need Service ORM-compatible objects; ServiceRow lacks `id` and other fields.
        # Query directly for the prompt format.
        from sqlalchemy import select

        from database.connection import get_async_session
        from database.models import Service

        async with get_async_session() as session:
            result = await session.execute(
                select(Service)
                .where(Service.is_active == True)  # noqa: E712
                .order_by(Service.category, Service.name)
            )
            orm_services = list(result.scalars().all())

        return build_catalog_for_prompt(orm_services)
    except Exception:
        logger.warning("Could not build catalog prompt section", exc_info=True)
        return ""


def invalidate_catalog_cache() -> None:
    """Force cache refresh on next call. Called by admin panel after service changes."""
    _catalog_cache.invalidate()
    logger.info("catalog_cache invalidated")


__all__ = [
    "ServiceRow",
    "build_catalog_for_prompt",
    "build_catalog_markdown",
    "build_catalog_prompt_section",
    "get_active_services",
    "load_active_catalog",
    "invalidate_catalog_cache",
    # internal helpers (exported for tests)
    "_build_service_type_tag",
    "_AUDIENCE_LABELS",
    "_CATEGORY_LABELS",
    "_catalog_cache",
]

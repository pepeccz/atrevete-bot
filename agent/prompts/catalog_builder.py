"""Builds the service catalog string for LLM prompt injection.

Public API
----------
build_catalog_for_prompt(services) -> str
    Pure function. Accepts any list of objects with the Service ORM attributes
    (.name, .duration_minutes, .description, .audience, .metadata_). Returns a
    formatted string with one tagged line per service. Ordering: principals
    first (sorted by category, name), then variants grouped under their parent,
    then addons.

load_active_catalog() -> list[Service]
    Async. Queries DB: WHERE is_active=true ORDER BY category, name.

build_catalog_prompt_section() -> str
    Async. Composes load_active_catalog + build_catalog_for_prompt.

No caching layer in Phase 4 MVP — each call queries DB. Caching deferred to
Phase 7 via shared.cache_signals.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tag renderers
# ---------------------------------------------------------------------------

_SERVICE_TYPE_ORDER = {"principal": 0, "variant": 1, "addon": 2}


def _audience_token(audience: str | None) -> str:
    """Return the audience token as-is (already DB-aligned strings)."""
    if audience is None:
        return "any"
    return audience


def _render_tag(svc: Any) -> str:
    """Render the [TYPE · dim · ...] tag from metadata_."""
    meta = svc.metadata_ or {}
    service_type = meta.get("service_type")
    dimension = meta.get("dimension") or "unknown"

    if service_type == "principal":
        aud = _audience_token(getattr(svc, "audience", None))
        return f"[PRINCIPAL · {dimension} · {aud}]"
    if service_type == "variant":
        parent = meta.get("parent_service_name") or "?"
        return f"[VARIANTE de {parent} · {dimension}]"
    if service_type == "addon":
        return f"[ADDON · {dimension}]"
    return ""


def _sort_key(svc: Any) -> tuple[int, str, str]:
    """Sort key: (type_order, category_str, name)."""
    meta = svc.metadata_ or {}
    service_type = meta.get("service_type", "")
    order = _SERVICE_TYPE_ORDER.get(service_type, 99)
    cat = str(getattr(svc, "category", ""))
    return (order, cat, svc.name)


def build_catalog_for_prompt(services: list[Any]) -> str:
    """Build a tagged catalog string from a list of Service-like objects.

    Format per line:
        [PRINCIPAL · {dim} · {audience}] {name} — {duration_minutes}min — {description}
        [VARIANTE de {parent} · {dim}] {name} — {duration_minutes}min — {description}
        [ADDON · {dim}] {name} — {duration_minutes}min — {description}

    Ordering: principals first (by category then name), then variants, then addons.
    Description is omitted (not ' — None') when absent.
    """
    if not services:
        return ""

    sorted_services = sorted(services, key=_sort_key)
    lines: list[str] = []
    for svc in sorted_services:
        tag = _render_tag(svc)
        desc = getattr(svc, "description", None)
        dur = getattr(svc, "duration_minutes", 0)
        name = svc.name

        if tag:
            line = f"{tag} {name} — {dur}min"
        else:
            line = f"{name} — {dur}min"

        if desc:
            line += f" — {desc}"

        lines.append(line)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Async DB helpers
# ---------------------------------------------------------------------------


async def _query_active_services() -> list[Any]:
    """Query DB for active services ordered by category, name."""
    from sqlalchemy import select

    from database.connection import get_async_session
    from database.models import Service

    async with get_async_session() as session:
        result = await session.execute(
            select(Service)
            .where(Service.is_active == True)  # noqa: E712
            .order_by(Service.category, Service.name)
        )
        return list(result.scalars().all())


async def load_active_catalog() -> list[Any]:
    """Return active services from DB. No caching (Phase 4 MVP)."""
    return await _query_active_services()


async def build_catalog_prompt_section() -> str:
    """Load active catalog from DB and return the tagged prompt string."""
    services = await load_active_catalog()
    return build_catalog_for_prompt(services)


def invalidate_catalog_cache() -> None:
    """No-op cache invalidation hook.

    Phase 4 MVP has no in-process cache. This function exists so that
    api/routes/admin.py lazy-import blocks can call it without breaking.
    A real implementation (e.g., clearing an in-memory LRU cache) can be
    added here when caching is introduced post-MVP.
    """


__all__ = [
    "build_catalog_for_prompt",
    "load_active_catalog",
    "build_catalog_prompt_section",
    "invalidate_catalog_cache",
]

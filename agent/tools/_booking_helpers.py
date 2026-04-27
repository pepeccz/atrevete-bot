"""Internal helpers for booking-flow tools.

DB-bound helpers live here (not in infra/resolvers/ which is DB-free).
All functions are private (underscore prefix) — consumed by update_booking,
check_availability, and book. Do NOT import directly from outside agent/tools/.

Refs: R2, R3, design §8
"""

from __future__ import annotations

import unicodedata
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _validate_full_name(name: str | None) -> tuple[str, str] | None:
    """Return (first_name, last_name) if name has >= 2 non-empty tokens after strip; else None.

    Semantics: first token = first_name, remaining tokens joined = last_name.
    Used by update_booking gate (presence check) and book.py (rejection path).
    Spec refs: SPEC-6.1 → 6.4, ADR-4.
    """
    if name is None:
        return None
    stripped = name.strip()
    if not stripped:
        return None
    parts = stripped.split(None, 1)  # split on first whitespace — same as _split_full_name
    if len(parts) < 2:
        return None
    first_name = parts[0]
    last_name = parts[1].strip()
    if not last_name:
        return None
    return first_name, last_name


def _normalize_name(text: str) -> str:
    """Lowercase + strip accents for fuzzy name matching."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _compute_first_valid_date(today: date, min_days: int) -> date:
    """Return today + min_days (pure — no DB)."""
    return today + timedelta(days=min_days)


async def _resolve_stylist(session: AsyncSession, name: str) -> UUID | None:
    """Resolve stylist name to UUID via unaccented lowercase match.

    Returns None if no active stylist matches.
    """
    from database.models import Stylist

    normalized_input = _normalize_name(name)

    result = await session.execute(
        select(Stylist.id, Stylist.name).where(Stylist.is_active.is_(True))
    )
    rows = result.fetchall()

    for stylist_id, stylist_name in rows:
        if _normalize_name(stylist_name) == normalized_input:
            return stylist_id

    return None


async def _resolve_audience_variants(
    session: AsyncSession, service_name: str
) -> tuple[str, str, list[str]]:
    """Detect whether a service belongs to an ambiguous family.

    Returns a 3-tuple (kind, family_label, candidates):
      - kind ∈ {"none", "audience", "variant"}
      - family_label: the dimension (audience axis) or parent_service_name (variant axis)
      - candidates: sorted list of sibling service names

    Axis (a) — audience: PRINCIPAL services sharing the same `dimension` metadata key
    but differing by `audience` column value.

    Axis (b) — variant: services sharing `parent_service_name` in metadata (pre-existing
    behaviour, preserved).

    Returns ("none", "", []) when the service is unambiguous.

    Used by update_booking Rule 1 to trigger audience_required / variant_required.
    """
    from database.models import Service

    # Fetch the service row (metadata + audience)
    result = await session.execute(
        select(Service.metadata_, Service.audience).where(
            Service.name == service_name,
            Service.is_active.is_(True),
        )
    )
    row = result.first()
    if row is None:
        return ("none", "", [])

    metadata = row[0] or {}
    audience = row[1]

    # ── Case (b): variant axis — has parent_service_name ─────────────────────
    parent_name = metadata.get("parent_service_name")
    if parent_name:
        siblings_result = await session.execute(
            select(Service.name).where(
                Service.metadata_["parent_service_name"].as_string() == parent_name,
                Service.is_active.is_(True),
            )
        )
        sibling_names = sorted(r[0] for r in siblings_result.fetchall())
        if len(sibling_names) > 1:
            return ("variant", parent_name, sibling_names)

    # ── Case (a): audience axis — PRINCIPAL peers sharing dimension ───────────
    service_type = metadata.get("service_type", "")
    dimension = metadata.get("dimension")
    if service_type == "principal" and dimension:
        peers_result = await session.execute(
            select(Service.name, Service.audience).where(
                Service.metadata_["service_type"].as_string() == "principal",
                Service.metadata_["dimension"].as_string() == dimension,
                Service.is_active.is_(True),
            )
        )
        peers = peers_result.fetchall()
        distinct_audiences = {p[1] for p in peers if p[1] is not None}
        if len(peers) > 1 and len(distinct_audiences) > 1:
            return ("audience", dimension, sorted(p[0] for p in peers))

    return ("none", "", [])


async def _resolve_service_ids(
    session: AsyncSession, service_names: list[str]
) -> tuple[list[str], list[str]]:
    """Resolve service names to UUIDs via normalized name match.

    Matches against BOTH the internal Service.name (e.g. "Corte Dama") AND the
    customer-safe display name (e.g. "corte de mujer") computed by
    `_derive_customer_safe_service_name`. The LLM uses display names from the
    catalog block, while the DB stores internal names.

    Returns (resolved_ids, unknown_names).
    """
    from agent.prompts.catalog_builder import _derive_customer_safe_service_name
    from database.models import Service

    result = await session.execute(
        select(Service.id, Service.name).where(Service.is_active.is_(True))
    )

    by_internal: dict[str, str] = {}
    by_display: dict[str, str] = {}
    for service_id, service_name in result.fetchall():
        sid = str(service_id)
        by_internal[_normalize_name(service_name)] = sid
        display = _derive_customer_safe_service_name(service_name)
        by_display[_normalize_name(display)] = sid

    resolved_ids: list[str] = []
    unknown: list[str] = []

    for name in service_names:
        normalized = _normalize_name(name)
        if normalized in by_internal:
            resolved_ids.append(by_internal[normalized])
        elif normalized in by_display:
            resolved_ids.append(by_display[normalized])
        else:
            unknown.append(name)

    return resolved_ids, unknown

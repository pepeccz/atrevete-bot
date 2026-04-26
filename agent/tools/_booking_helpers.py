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
) -> tuple[str, list[str]]:
    """Check if service has siblings (shared parent_service_name in metadata).

    Returns (family_name, [variant_names]) where variant_names is the list of
    sibling service names (includes the passed service itself).
    Returns ("", []) if the service is unambiguous (no parent metadata).

    Used to detect when LLM should ask for audience clarification.
    """
    from database.models import Service

    # Look up the service to get its metadata
    result = await session.execute(
        select(Service.metadata_).where(
            Service.name == service_name,
            Service.is_active.is_(True),
        )
    )
    row = result.first()
    if row is None:
        return ("", [])

    metadata = row[0] or {}
    parent_name = metadata.get("parent_service_name")
    if not parent_name:
        return ("", [])

    # Find all services with the same parent
    siblings_result = await session.execute(
        select(Service.name).where(
            Service.metadata_["parent_service_name"].as_string() == parent_name,
            Service.is_active.is_(True),
        )
    )
    sibling_names = [r[0] for r in siblings_result.fetchall()]
    return (parent_name, sibling_names)


async def _resolve_service_ids(
    session: AsyncSession, service_names: list[str]
) -> tuple[list[str], list[str]]:
    """Resolve service names to UUIDs via exact (normalized) name match.

    Returns (resolved_ids, unknown_names).
    resolved_ids: list of str UUIDs for found services.
    unknown_names: list of names that could not be matched.
    """
    from database.models import Service

    result = await session.execute(
        select(Service.id, Service.name).where(Service.is_active.is_(True))
    )
    all_services = {_normalize_name(row[1]): str(row[0]) for row in result.fetchall()}

    resolved_ids: list[str] = []
    unknown: list[str] = []

    for name in service_names:
        normalized = _normalize_name(name)
        if normalized in all_services:
            resolved_ids.append(all_services[normalized])
        else:
            unknown.append(name)

    return resolved_ids, unknown

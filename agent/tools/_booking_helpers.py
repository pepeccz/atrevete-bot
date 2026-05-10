"""Internal helpers for booking-flow tools.

DB-bound helpers live here (not in infra/resolvers/ which is DB-free).
All functions are private (underscore prefix) — consumed by update_booking,
check_availability, and book. Do NOT import directly from outside agent/tools/.

Refs: R2, R3, design §8
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ServiceCategory imported lazily inside functions to avoid circular imports at module load.

# ---------------------------------------------------------------------------
# Diminutive normalization helpers (ADR-10)
# ---------------------------------------------------------------------------

_DIMINUTIVE_RE = re.compile(r"(c?it[oa]s?)$")
"""Matches Spanish diminutive suffixes: -ito, -ita, -itos, -itas, -cito, -cita, -citos, -citas."""


def _strip_diminutive(normalized: str) -> str | None:
    """Return the stem if the word ends in a Spanish diminutive suffix, else None.

    Only strips if the resulting stem is >= 4 characters to avoid over-stripping
    short words (e.g. 'café' → 'ca' would be wrong).

    Args:
        normalized: Accent-stripped lowercase string.

    Returns:
        Stem string (without suffix) if diminutive detected, or None.
    """
    m = _DIMINUTIVE_RE.search(normalized)
    if not m:
        return None
    stem = normalized[: m.start()]
    if len(stem) < 4:
        return None
    return stem


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
      - candidates: list of candidate service names (principal included)

    Axis (a) — audience: PRINCIPAL services sharing the same `dimension` metadata key
    but differing by `audience` column value.

    Axis (b) — variant (child): input service has `parent_service_name` → look up siblings.
    Axis (b') — variant (principal): input service has no `parent_service_name` → look up
      active children where their `parent_service_name == this.name`. If ≥1 child exists,
      return variant gate with [principal] + sorted children.

    Returns ("none", "", []) when the service is unambiguous.

    Used by update_booking Rule 1 to trigger audience_required / variant_required.
    Design: ADR-2 (booking-disambiguation-hardening).
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

    parent_name = metadata.get("parent_service_name")

    if parent_name:
        # ── Case (b): variant axis — input IS a child ─────────────────────────
        siblings_result = await session.execute(
            select(Service.name).where(
                Service.metadata_["parent_service_name"].as_string() == parent_name,
                Service.name != service_name,
                Service.is_active.is_(True),
            )
        )
        siblings = sorted(r[0] for r in siblings_result.fetchall())
        if len(siblings) >= 1:
            # Include parent name + siblings + self; de-duplicate preserving order
            candidates_raw = [parent_name] + siblings + [service_name]
            seen: set[str] = set()
            candidates: list[str] = []
            for c in candidates_raw:
                if c not in seen:
                    seen.add(c)
                    candidates.append(c)
            return ("variant", parent_name, candidates)
    else:
        # ── Case (b'): variant axis — input IS a principal ────────────────────
        children_result = await session.execute(
            select(Service.name).where(
                Service.metadata_["parent_service_name"].as_string() == service_name,
                Service.is_active.is_(True),
            )
        )
        children = sorted(r[0] for r in children_result.fetchall())
        if len(children) >= 1:
            return ("variant", service_name, [service_name] + children)

        # ── Case (a): audience axis — PRINCIPAL peers sharing dimension ───────
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
            # Include None as a distinct sentinel so null-audience principals
            # sharing a dimension with audience-tagged peers correctly trigger
            # the audience-required gate (design §2 Slice 2, Task 2.3).
            audience_values = {p[1] for p in peers}  # include None
            input_audience = row[1]
            if len(peers) > 1 and len(audience_values) > 1 and input_audience is None:
                logger.info(
                    "_resolve_audience_variants: audience_required axis=%s options_count=%d",
                    dimension,
                    len(peers),
                )
                return ("audience", dimension, sorted(p[0] for p in peers))

    return ("none", "", [])


async def _resolve_service_id_to_category_map(
    session: AsyncSession, service_ids: list[str]
) -> dict[str, object]:
    """Return {service_id_str: ServiceCategory} for the given IDs.

    Used by the category_mix_required gate to build the payload.
    """
    from database.models import Service

    if not service_ids:
        return {}

    result = await session.execute(
        select(Service.id, Service.category).where(Service.id.in_(service_ids))
    )
    return {str(row[0]): row[1] for row in result.fetchall()}


async def _resolve_service_categories(session: AsyncSession, service_ids: list[str]) -> set:
    """Return the distinct ServiceCategory values for the given service IDs.

    Empty set if no rows match or service_ids is empty.
    UUID strings or UUID objects accepted (SQLAlchemy coerces both).

    Used by _resolve_active_stylists and the category_mix_required gate in update_booking.
    """
    from database.models import Service

    if not service_ids:
        return set()

    result = await session.execute(select(Service.category).where(Service.id.in_(service_ids)))
    return {row[0] for row in result.fetchall()}


async def _resolve_active_stylists(
    session: AsyncSession, service_ids: list[str] | None = None
) -> list[str]:
    """Return first names of active stylists, ordered alphabetically by full name.

    First name = token before the first whitespace in Stylist.name.
    Filters: is_active=True only.

    When service_ids is None (DEPRECATED — legacy path), all active stylists are returned.
    When service_ids is provided, applies the category filter matrix:
      - {HAIRDRESSING} → stylists with category IN (HAIRDRESSING, BOTH)
      - {AESTHETICS}   → stylists with category IN (AESTHETICS, BOTH)
      - {BOTH}         → all active stylists
      - {HAIR, AESTH}  → [] (mixed, fail-closed)
      - empty set      → [] (fail-closed — unresolved IDs)

    Design: ADR-2, ADR-3 (stylist-category-filtering-fix-v2).
    """
    from database.models import ServiceCategory, Stylist

    if service_ids is None:
        # Legacy path — unchanged behavior
        result = await session.execute(
            select(Stylist.name).where(Stylist.is_active.is_(True)).order_by(Stylist.name.asc())
        )
        return [row[0].split(None, 1)[0] for row in result.fetchall()]

    # Resolve category set for the given service IDs
    categories = await _resolve_service_categories(session, service_ids)

    if not categories:
        # Empty service_ids or no DB rows — fail-closed
        return []

    has_hair = ServiceCategory.HAIRDRESSING in categories
    has_aesth = ServiceCategory.AESTHETICS in categories
    has_both = ServiceCategory.BOTH in categories

    # Mixed non-BOTH categories → fail-closed
    if has_hair and has_aesth:
        return []

    # Build the WHERE clause
    if has_both and not has_hair and not has_aesth:
        # All-BOTH → any active stylist can serve
        category_filter = Stylist.is_active.is_(True)
    elif has_hair or (has_both and not has_aesth):
        # HAIRDRESSING (possibly with BOTH) → hair + BOTH stylists
        category_filter = Stylist.category.in_([ServiceCategory.HAIRDRESSING, ServiceCategory.BOTH])
    else:
        # AESTHETICS (possibly with BOTH) → aesth + BOTH stylists
        category_filter = Stylist.category.in_([ServiceCategory.AESTHETICS, ServiceCategory.BOTH])

    result = await session.execute(
        select(Stylist.name)
        .where(Stylist.is_active.is_(True))
        .where(category_filter)
        .order_by(Stylist.name.asc())
    )
    return [row[0].split(None, 1)[0] for row in result.fetchall()]


async def _resolve_service_ids_strict(
    session: AsyncSession, service_names: list[str]
) -> tuple[list[str], list[str], list[dict]]:
    """Resolve service names to UUIDs with ambiguity detection.

    Like _resolve_service_ids but returns a 3-tuple:
      (resolved_ids, unknown_names, ambiguous_descriptors)

    When a service term maps to an ambiguous principal (audience axis or variant axis),
    its UUID is NOT appended to resolved_ids — instead, a descriptor dict is added to
    the third element.

    Ambiguous descriptor shape (design §2 Slice 2):
    {
        "status": "ambiguous",
        "axis": "audience" | "variant",
        "service_term": str,
        "family_label": str,
        "candidates": list[str],
        "question_hint": "audience_required" | "variant_required",
    }

    _resolve_service_ids stays as a thin 2-tuple wrapper for backward compatibility.

    Refs: design §2 Slice 2, spec R2.1-R2.3, NFR-2
    """
    from agent.prompts.catalog_builder import _derive_customer_safe_service_name
    from database.models import Service

    result = await session.execute(
        select(Service.id, Service.name).where(Service.is_active.is_(True))
    )

    by_internal: dict[str, str] = {}
    by_display: dict[str, str] = {}
    internal_name_by_norm: dict[str, str] = {}  # normalized → internal Service.name
    for service_id, service_name in result.fetchall():
        sid = str(service_id)
        norm_internal = _normalize_name(service_name)
        by_internal[norm_internal] = sid
        internal_name_by_norm[norm_internal] = service_name
        display = _derive_customer_safe_service_name(service_name)
        norm_display = _normalize_name(display)
        by_display[norm_display] = sid
        if norm_display not in internal_name_by_norm:
            internal_name_by_norm[norm_display] = service_name

    resolved_ids: list[str] = []
    unknown: list[str] = []
    ambiguous: list[dict] = []

    for name in service_names:
        normalized = _normalize_name(name)

        # Resolve to internal service name first
        matched_internal: str | None = None
        if normalized in by_internal:
            matched_internal = internal_name_by_norm.get(normalized)
        elif normalized in by_display:
            matched_internal = internal_name_by_norm.get(normalized)
        else:
            # Try diminutive stripping
            stem = _strip_diminutive(normalized)
            if stem is not None:
                for candidate in [stem, stem + "o", stem + "a", stem + "e"]:
                    if candidate in by_internal:
                        matched_internal = internal_name_by_norm.get(candidate)
                        break
                    if candidate in by_display:
                        matched_internal = internal_name_by_norm.get(candidate)
                        break

        if matched_internal is None:
            unknown.append(name)
            continue

        # Check for ambiguity before committing UUID
        kind, family_label, candidates = await _resolve_audience_variants(session, matched_internal)
        if kind == "audience":
            logger.info(
                "_resolve_service_ids_strict: ambiguous axis=%s term=%s options=%d",
                "audience",
                name,
                len(candidates),
            )
            ambiguous.append(
                {
                    "status": "ambiguous",
                    "axis": "audience",
                    "service_term": name,
                    "family_label": family_label,
                    "candidates": candidates,
                    "question_hint": "audience_required",
                }
            )
        elif kind == "variant":
            logger.info(
                "_resolve_service_ids_strict: ambiguous axis=%s term=%s options=%d",
                "variant",
                name,
                len(candidates),
            )
            ambiguous.append(
                {
                    "status": "ambiguous",
                    "axis": "variant",
                    "service_term": name,
                    "family_label": family_label,
                    "candidates": candidates,
                    "question_hint": "variant_required",
                }
            )
        else:
            # Unambiguous — commit UUID
            norm = _normalize_name(matched_internal)
            if norm in by_internal:
                resolved_ids.append(by_internal[norm])
            elif norm in by_display:
                resolved_ids.append(by_display[norm])

    return resolved_ids, unknown, ambiguous


async def _resolve_service_ids(
    session: AsyncSession, service_names: list[str]
) -> tuple[list[str], list[str]]:
    """Resolve service names to UUIDs via normalized name match.

    Matches against BOTH the internal Service.name (e.g. "Corte de Mujer") AND the
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
        # Step 1: exact internal or display match (existing behavior)
        if normalized in by_internal:
            resolved_ids.append(by_internal[normalized])
        elif normalized in by_display:
            resolved_ids.append(by_display[normalized])
        else:
            # Step 2: try diminutive stripping (ADR-10)
            stem = _strip_diminutive(normalized)
            found = False
            if stem is not None:
                # Try stem + common vowel endings that Spanish services use
                for candidate in [stem, stem + "o", stem + "a", stem + "e"]:
                    if candidate in by_internal:
                        resolved_ids.append(by_internal[candidate])
                        found = True
                        break
                    if candidate in by_display:
                        resolved_ids.append(by_display[candidate])
                        found = True
                        break
            if not found:
                unknown.append(name)

    return resolved_ids, unknown

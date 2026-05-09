"""Booking query service — promoted from agent/tools/_booking_helpers.py.

All DB-bound booking resolution functions live here. Pure utility functions
(_validate_full_name, _normalize_name, _compute_first_valid_date, _strip_diminutive)
remain in agent/tools/booking_helpers.py (tool-layer concerns).

Session ownership: this service opens and closes its own sessions.
Callers NEVER pass sessions in.

Design: SDD service-boundary-extraction PR#2, design D2.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select

from database.connection import get_async_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass for resolve_all facade (Design D2)
# ---------------------------------------------------------------------------


@dataclass
class ResolveAllResult:
    """Result of BookingQueryService.resolve_all().

    success=True means service IDs resolved without unknown names.
    All other fields are populated regardless of success for the caller
    to use in building responses (e.g. active_stylists for payload).

    category_mix fields avoid the need for tools to import database.models:
    - has_category_mix: True when services span HAIRDRESSING + AESTHETICS
    - hair_services: input names that map to HAIRDRESSING
    - aesth_services: input names that map to AESTHETICS
    - both_services: input names that map to BOTH
    """

    success: bool
    service_ids: list[str] = field(default_factory=list)
    unknown_names: list[str] = field(default_factory=list)
    stylist_id: UUID | None = None
    audience_variants: tuple[str, str, list[str]] | None = None
    categories: set = field(default_factory=set)
    id_to_category: dict = field(default_factory=dict)
    active_stylists: list[str] = field(default_factory=list)
    has_category_mix: bool = False
    hair_services: list[str] = field(default_factory=list)
    aesth_services: list[str] = field(default_factory=list)
    both_services: list[str] = field(default_factory=list)
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Pure utility helpers (local copies — keep in sync with booking_helpers.py)
# ---------------------------------------------------------------------------


def _normalize_name(text: str) -> str:
    """Lowercase + strip accents for fuzzy name matching."""
    import unicodedata

    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


_DIMINUTIVE_RE = None


def _strip_diminutive(normalized: str) -> str | None:
    """Return the stem if the word ends in a Spanish diminutive suffix, else None."""
    import re

    global _DIMINUTIVE_RE
    if _DIMINUTIVE_RE is None:
        _DIMINUTIVE_RE = re.compile(r"(c?it[oa]s?)$")

    m = _DIMINUTIVE_RE.search(normalized)
    if not m:
        return None
    stem = normalized[: m.start()]
    if len(stem) < 4:
        return None
    return stem


# ---------------------------------------------------------------------------
# BookingQueryService
# ---------------------------------------------------------------------------


class BookingQueryService:
    """Service for all DB-bound booking resolution queries.

    All methods are static/class — no instance state needed.
    Each single-step method opens its OWN session.
    For multi-step resolution use resolve_all() which owns ONE session.
    """

    @staticmethod
    async def resolve_stylist(name: str) -> UUID | None:
        """Resolve stylist name to UUID via unaccented lowercase match.

        Returns None if no active stylist matches.
        """
        from database.models import Stylist

        normalized_input = _normalize_name(name)

        async with get_async_session() as session:
            result = await session.execute(
                select(Stylist.id, Stylist.name).where(Stylist.is_active.is_(True))
            )
            rows = result.fetchall()

        for stylist_id, stylist_name in rows:
            if _normalize_name(stylist_name) == normalized_input:
                return stylist_id

        return None

    @staticmethod
    async def resolve_service_ids(
        service_names: list[str],
    ) -> tuple[list[str], list[str]]:
        """Resolve service names to UUIDs via normalized name match.

        Matches against both internal Service.name and customer-safe display name.
        Returns (resolved_ids, unknown_names).
        """
        from agent.prompts.catalog_builder import _derive_customer_safe_service_name
        from database.models import Service

        async with get_async_session() as session:
            result = await session.execute(
                select(Service.id, Service.name).where(Service.is_active.is_(True))
            )
            rows = result.fetchall()

        by_internal: dict[str, str] = {}
        by_display: dict[str, str] = {}
        for service_id, service_name in rows:
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
                stem = _strip_diminutive(normalized)
                found = False
                if stem is not None:
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

    @staticmethod
    async def resolve_audience_variants(
        service_name: str,
    ) -> tuple[str, str, list[str]]:
        """Detect whether a service belongs to an ambiguous family.

        Returns (kind, family_label, candidates):
          - kind in {"none", "audience", "variant"}
          - family_label: dimension or parent_service_name
          - candidates: list of candidate service names

        Returns ("none", "", []) when service is unambiguous.
        """
        from database.models import Service

        async with get_async_session() as session:
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
                siblings_result = await session.execute(
                    select(Service.name).where(
                        Service.metadata_["parent_service_name"].as_string() == parent_name,
                        Service.name != service_name,
                        Service.is_active.is_(True),
                    )
                )
                siblings = sorted(r[0] for r in siblings_result.fetchall())
                if len(siblings) >= 1:
                    candidates_raw = [parent_name] + siblings + [service_name]
                    seen: set[str] = set()
                    candidates: list[str] = []
                    for c in candidates_raw:
                        if c not in seen:
                            seen.add(c)
                            candidates.append(c)
                    return ("variant", parent_name, candidates)
            else:
                children_result = await session.execute(
                    select(Service.name).where(
                        Service.metadata_["parent_service_name"].as_string() == service_name,
                        Service.is_active.is_(True),
                    )
                )
                children = sorted(r[0] for r in children_result.fetchall())
                if len(children) >= 1:
                    return ("variant", service_name, [service_name] + children)

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

    @staticmethod
    async def resolve_service_categories(service_ids: list[str]) -> set:
        """Return the distinct ServiceCategory values for the given service IDs.

        Empty set if no rows match or service_ids is empty.
        """
        from database.models import Service

        if not service_ids:
            return set()

        async with get_async_session() as session:
            result = await session.execute(
                select(Service.category).where(Service.id.in_(service_ids))
            )
            return {row[0] for row in result.fetchall()}

    @staticmethod
    async def resolve_service_id_to_category_map(service_ids: list[str]) -> dict:
        """Return {service_id_str: ServiceCategory} for the given IDs."""
        from database.models import Service

        if not service_ids:
            return {}

        async with get_async_session() as session:
            result = await session.execute(
                select(Service.id, Service.category).where(Service.id.in_(service_ids))
            )
            return {str(row[0]): row[1] for row in result.fetchall()}

    @staticmethod
    async def resolve_active_stylists(service_ids: list[str] | None = None) -> list[str]:
        """Return first names of active stylists, ordered alphabetically.

        When service_ids is None: all active stylists (legacy path).
        When service_ids is provided: applies category filter matrix per ADR-2/ADR-3.
        """
        from database.models import Service, ServiceCategory, Stylist

        async with get_async_session() as session:
            if service_ids is None:
                result = await session.execute(
                    select(Stylist.name)
                    .where(Stylist.is_active.is_(True))
                    .order_by(Stylist.name.asc())
                )
                return [row[0].split(None, 1)[0] for row in result.fetchall()]

            # Resolve categories for the given service IDs
            cat_result = await session.execute(
                select(Service.category).where(Service.id.in_(service_ids))
            )
            categories = {row[0] for row in cat_result.fetchall()}

            if not categories:
                return []

            has_hair = ServiceCategory.HAIRDRESSING in categories
            has_aesth = ServiceCategory.AESTHETICS in categories
            has_both = ServiceCategory.BOTH in categories

            if has_hair and has_aesth:
                return []

            if has_both and not has_hair and not has_aesth:
                category_filter = Stylist.is_active.is_(True)
            elif has_hair or (has_both and not has_aesth):
                category_filter = Stylist.category.in_(
                    [ServiceCategory.HAIRDRESSING, ServiceCategory.BOTH]
                )
            else:
                category_filter = Stylist.category.in_(
                    [ServiceCategory.AESTHETICS, ServiceCategory.BOTH]
                )

            result = await session.execute(
                select(Stylist.name)
                .where(Stylist.is_active.is_(True))
                .where(category_filter)
                .order_by(Stylist.name.asc())
            )
            return [row[0].split(None, 1)[0] for row in result.fetchall()]

    @staticmethod
    async def resolve_all(
        services: list[str] | None,
        stylist_name: str | None,
        audience: str | None,
    ) -> ResolveAllResult:
        """Single-session facade for the full booking slot resolution.

        Opens EXACTLY ONE session for the entire resolution chain.
        This preserves transactional locality — update_booking used to hold one
        session for all helper calls; this service now owns that session boundary.

        Steps (in order, same session):
        1. Resolve service names → IDs
        2. Resolve audience/variant disambiguation per service
        3. Resolve service categories (for category-mix gate)
        4. Resolve service_id → category map (for mix payload)
        5. Resolve stylist name → UUID (if provided)
        6. Resolve active stylists (for stylist_required payload)
        """
        from agent.prompts.catalog_builder import _derive_customer_safe_service_name
        from database.models import Service, ServiceCategory, Stylist

        async with get_async_session() as session:
            # ── Step 1: Resolve service IDs ───────────────────────────────────
            service_ids: list[str] = []
            unknown_names: list[str] = []

            if services:
                svc_result = await session.execute(
                    select(Service.id, Service.name).where(Service.is_active.is_(True))
                )
                rows = svc_result.fetchall()

                by_internal: dict[str, str] = {}
                by_display: dict[str, str] = {}
                for service_id, service_name in rows:
                    sid = str(service_id)
                    by_internal[_normalize_name(service_name)] = sid
                    display = _derive_customer_safe_service_name(service_name)
                    by_display[_normalize_name(display)] = sid

                for name in services:
                    normalized = _normalize_name(name)
                    if normalized in by_internal:
                        service_ids.append(by_internal[normalized])
                    elif normalized in by_display:
                        service_ids.append(by_display[normalized])
                    else:
                        stem = _strip_diminutive(normalized)
                        found = False
                        if stem is not None:
                            for candidate in [stem, stem + "o", stem + "a", stem + "e"]:
                                if candidate in by_internal:
                                    service_ids.append(by_internal[candidate])
                                    found = True
                                    break
                                if candidate in by_display:
                                    service_ids.append(by_display[candidate])
                                    found = True
                                    break
                        if not found:
                            unknown_names.append(name)

            success = len(unknown_names) == 0

            # ── Step 2: Audience/variant resolution (all services, same session) ──
            audience_variants_per_service: list[tuple[str, str, list[str]]] = []
            if services and service_ids:
                for service_name in (services or []):
                    avar_result = await session.execute(
                        select(Service.metadata_, Service.audience).where(
                            Service.name == service_name,
                            Service.is_active.is_(True),
                        )
                    )
                    row = avar_result.first()
                    if row is None:
                        audience_variants_per_service.append(("none", "", []))
                        continue

                    metadata = row[0] or {}
                    parent_name = metadata.get("parent_service_name")
                    avar_tuple = await _resolve_audience_variants_in_session(
                        session, service_name, metadata, parent_name
                    )
                    audience_variants_per_service.append(avar_tuple)

            # ── Step 3: Service categories ────────────────────────────────────
            categories: set = set()
            if service_ids:
                cat_result = await session.execute(
                    select(Service.category).where(Service.id.in_(service_ids))
                )
                categories = {row[0] for row in cat_result.fetchall()}

            # ── Step 4: Service ID → category map ────────────────────────────
            id_to_category: dict = {}
            if service_ids:
                map_result = await session.execute(
                    select(Service.id, Service.category).where(Service.id.in_(service_ids))
                )
                id_to_category = {str(row[0]): row[1] for row in map_result.fetchall()}

            # ── Step 5: Stylist resolution ────────────────────────────────────
            stylist_id: UUID | None = None
            if stylist_name:
                stylist_result = await session.execute(
                    select(Stylist.id, Stylist.name).where(Stylist.is_active.is_(True))
                )
                stylist_rows = stylist_result.fetchall()
                normalized_input = _normalize_name(stylist_name)
                for sid, sname in stylist_rows:
                    if _normalize_name(sname) == normalized_input:
                        stylist_id = sid
                        break

            # ── Step 6: Active stylists (for payload) ─────────────────────────
            active_stylists: list[str] = []
            has_hair = ServiceCategory.HAIRDRESSING in categories
            has_aesth = ServiceCategory.AESTHETICS in categories
            has_both = ServiceCategory.BOTH in categories

            if not categories or (has_hair and has_aesth):
                active_stylists = []
            else:
                if has_both and not has_hair and not has_aesth:
                    category_filter = Stylist.is_active.is_(True)
                elif has_hair or (has_both and not has_aesth):
                    category_filter = Stylist.category.in_(
                        [ServiceCategory.HAIRDRESSING, ServiceCategory.BOTH]
                    )
                else:
                    category_filter = Stylist.category.in_(
                        [ServiceCategory.AESTHETICS, ServiceCategory.BOTH]
                    )

                active_result = await session.execute(
                    select(Stylist.name)
                    .where(Stylist.is_active.is_(True))
                    .where(category_filter)
                    .order_by(Stylist.name.asc())
                )
                active_stylists = [row[0].split(None, 1)[0] for row in active_result.fetchall()]

        # ── Step 7: Compute category mix breakdown (avoids tool importing ServiceCategory) ──
        _has_hair = ServiceCategory.HAIRDRESSING in categories
        _has_aesth = ServiceCategory.AESTHETICS in categories
        has_category_mix = _has_hair and _has_aesth

        hair_services: list[str] = []
        aesth_services: list[str] = []
        both_services: list[str] = []

        if has_category_mix and services:
            for _svc_name, _svc_id in zip(services, service_ids):
                _cat = id_to_category.get(_svc_id)
                if _cat == ServiceCategory.HAIRDRESSING:
                    hair_services.append(_svc_name)
                elif _cat == ServiceCategory.AESTHETICS:
                    aesth_services.append(_svc_name)
                else:
                    both_services.append(_svc_name)

        # Expose first audience_variants tuple (caller iterates services separately)
        first_avar = audience_variants_per_service[0] if audience_variants_per_service else None

        return ResolveAllResult(
            success=success,
            service_ids=service_ids,
            unknown_names=unknown_names,
            stylist_id=stylist_id,
            audience_variants=first_avar,
            categories=categories,
            id_to_category=id_to_category,
            active_stylists=active_stylists,
            has_category_mix=has_category_mix,
            hair_services=hair_services,
            aesth_services=aesth_services,
            both_services=both_services,
            error_message=None,
        )


# ---------------------------------------------------------------------------
# Internal session-bound helper (not exported)
# ---------------------------------------------------------------------------


async def _resolve_audience_variants_in_session(
    session,
    service_name: str,
    metadata: dict,
    parent_name: str | None,
) -> tuple[str, str, list[str]]:
    """Resolve audience/variant disambiguation using an already-open session.

    This is an internal helper used by resolve_all to avoid opening extra sessions.
    NOT part of the public API.
    """
    from database.models import Service

    if parent_name:
        siblings_result = await session.execute(
            select(Service.name).where(
                Service.metadata_["parent_service_name"].as_string() == parent_name,
                Service.name != service_name,
                Service.is_active.is_(True),
            )
        )
        siblings = sorted(r[0] for r in siblings_result.fetchall())
        if len(siblings) >= 1:
            candidates_raw = [parent_name] + siblings + [service_name]
            seen: set[str] = set()
            candidates: list[str] = []
            for c in candidates_raw:
                if c not in seen:
                    seen.add(c)
                    candidates.append(c)
            return ("variant", parent_name, candidates)
    else:
        children_result = await session.execute(
            select(Service.name).where(
                Service.metadata_["parent_service_name"].as_string() == service_name,
                Service.is_active.is_(True),
            )
        )
        children = sorted(r[0] for r in children_result.fetchall())
        if len(children) >= 1:
            return ("variant", service_name, [service_name] + children)

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

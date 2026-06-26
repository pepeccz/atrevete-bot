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
# Audience-from-name inference (Q1 — memory-service audience pinning)
# ---------------------------------------------------------------------------

# Mapping of normalized name tokens → audience value.
# Mirrors the qualifier table in booking_flow.md Paso 2, applied to service NAMES
# stored in customer memories (e.g. "Corte de Mujer" → adult_female).
# Keys are lowercase, accent-stripped substrings. First match wins.
_AUDIENCE_TOKEN_MAP: list[tuple[tuple[str, ...], str]] = [
    # adult_female qualifiers
    (("mujer", "dama", "senora", "señora", "chica", "femenino", "femenina"), "adult_female"),
    # adult_male qualifiers
    (("caballero", "hombre", "senor", "señor", "chico", "masculino"), "adult_male"),
    # child qualifiers — order matters: check 'nina'/'nino' before 'bebe'
    (("nina", "niña"), "child_female"),
    (("nino", "niño"), "child_male"),
    (("bebe", "bebé"), "baby"),
]


def _infer_audience_from_service_name(service_name: str) -> str | None:
    """Infer audience from qualifier tokens embedded in a service name.

    Used on the memory-resolution path (Q1) so that a service name like
    "Corte de Mujer" stored in customer memories is resolved to the correct
    adult_female audience variant without re-triggering the audience_required gate.

    Returns the audience string ("adult_female" | "adult_male" | "child_female" |
    "child_male" | "baby") when a qualifier token is found, or None when the name
    contains no recognisable qualifier.

    Pure function — no DB I/O.
    """
    normalized = _normalize_name(service_name)
    tokens = normalized.split()
    for qualifiers, audience_value in _AUDIENCE_TOKEN_MAP:
        for token in tokens:
            if token in qualifiers:
                return audience_value
    return None


# ---------------------------------------------------------------------------
# Audience-ambiguous FAMILY recognition (neutral family token → audience gate)
# ---------------------------------------------------------------------------
# Some audience families have NO neutral parent principal in the catalog. The
# "cut" dimension, for example, is six gendered principals (Corte de Mujer,
# Corte de Hombre, Corte de Niña, …) with no bare "Corte" row. A neutral
# customer term ("corte", "corte de pelo") therefore resolves to nothing and is
# rejected as unknown ("No reconozco el servicio: corte"), which forces the
# model to GUESS a gendered variant. These helpers let the resolver map a
# neutral family token to the audience-ambiguous family and raise
# audience_required instead of rejecting — WITHOUT hard-coding any family name:
# the index is derived from the live catalog (families where a single dimension
# carries >1 distinct audience and the principal names share a leading token).
# Families that already expose a resolvable neutral principal (e.g. "Tinte" in
# the color dimension, "Manicura" in the manicure dimension) are handled by the
# existing resolution + audience gate and do not need this fallback.

_MIN_FAMILY_STEM_LEN = 4


def _derive_family_stem(names: list[str]) -> str | None:
    """Return the shared leading word across `names`, or None if not shared.

    "Corte de Mujer"/"Corte de Hombre"/… → "corte". Names that do not share a
    common first token (e.g. "Tinte"/"Color para Hombre") → None. The stem must
    be at least `_MIN_FAMILY_STEM_LEN` chars to avoid matching tiny tokens.
    Pure function — no I/O.

    CAVEAT: the neutral family fallback only works while every principal in an
    audience-ambiguous dimension shares this leading token. Adding a `cut`
    principal that does NOT start with "Corte" (e.g. "Pelado"/"Rapado") makes the
    whole family stem resolve to None → the family silently drops from the index
    and neutral "corte" reverts to "No reconozco el servicio". If such names are
    introduced, give them the shared stem or add an explicit family-key mapping.
    """
    first_tokens: set[str] = set()
    for n in names:
        tokens = _normalize_name(n).split()
        if not tokens:
            return None
        first_tokens.add(tokens[0])
    if len(first_tokens) != 1:
        return None
    stem = next(iter(first_tokens))
    if len(stem) < _MIN_FAMILY_STEM_LEN:
        return None
    return stem


def build_audience_family_index(principal_rows: list[dict]) -> dict[str, dict]:
    """Build {family_stem: {dimension, candidates, by_audience}} from PRINCIPAL rows.

    A family qualifies when its dimension carries >1 distinct `audience` value
    across its principals (genuinely audience-ambiguous) AND the principal names
    share a common leading token (the neutral family stem). Catalog-derived: no
    family name is hard-coded, so new audience families inherit the behavior.
    Pure function — no I/O.

    Each input row is a dict: {"name": str, "audience": str | None,
    "dimension": str | None}. `by_audience` maps each non-null audience to its
    principal name, so a neutral family token plus an explicit audience can be
    resolved to the specific gendered principal (e.g. "corte" + adult_male →
    "Corte de Hombre") instead of re-asking.
    """
    by_dim: dict[str, list[dict]] = {}
    for row in principal_rows:
        dimension = row.get("dimension")
        if not dimension:
            continue
        by_dim.setdefault(dimension, []).append(row)

    index: dict[str, dict] = {}
    for dimension, rows in by_dim.items():
        if len(rows) < 2:
            continue
        audiences = {r.get("audience") for r in rows}
        if len(audiences) < 2:
            continue  # single audience → not ambiguous
        names = sorted(r["name"] for r in rows)
        stem = _derive_family_stem(names)
        if stem is None or stem in index:
            continue  # no shared stem, or cross-dimension stem collision → skip
        by_audience = {r["audience"]: r["name"] for r in rows if r.get("audience") is not None}
        index[stem] = {
            "dimension": dimension,
            "candidates": names,
            "by_audience": by_audience,
        }
    return index


def match_audience_family(term: str, index: dict[str, dict]) -> dict | None:
    """Return the family entry whose stem appears as a whole token in `term`.

    Whole-token match guards against substring false positives — "cortina" must
    NOT match stem "corte". Returns {"stem", "dimension", "candidates"} or None.
    Pure function — no I/O.
    """
    tokens = set(_normalize_name(term).split())
    if not tokens:
        return None
    for stem, entry in index.items():
        if stem in tokens:
            return {"stem": stem, **entry}
    return None


def dimension_audience_is_ambiguous(principal_rows: list[dict]) -> bool:
    """True if any dimension in `principal_rows` carries >1 distinct audience.

    Pure decision helper shared by the availability audience-disambiguation
    guard. Each row dict: {"dimension": str | None, "audience": str | None}.
    Pure function — no I/O.
    """
    by_dim: dict[str, set] = {}
    for row in principal_rows:
        dimension = row.get("dimension")
        if not dimension:
            continue
        by_dim.setdefault(dimension, set()).add(row.get("audience"))
    return any(len(audiences) > 1 for audiences in by_dim.values())


# ---------------------------------------------------------------------------
# Diminutive normalization helpers (ADR-10)
# ---------------------------------------------------------------------------

_DIMINUTIVE_RE = re.compile(r"(c?it[oa]s?)$")
"""Matches Spanish diminutive suffixes: -ito, -ita, -itos, -itas, -cito, -cita, -citos, -citas."""

# ---------------------------------------------------------------------------
# Colloquial synonym map (ADR-2 — multi-service-resolution PR 1)
# ---------------------------------------------------------------------------
# Maps normalized colloquial terms → INTERNAL Service.name strings.
# Applied BEFORE by_internal / by_display / diminutive lookup in
# _resolve_service_ids_strict so _AUDIENCE_SUFFIX_REPLACEMENTS is never
# re-applied (double-transform guard).
#
# Values are internal names (e.g. "Corte de Hombre"), NOT customer-safe
# display names (e.g. "corte de caballero"). Audience inference on the
# internal name (e.g. "hombre" → adult_male) then self-pins the audience
# so the audience_required gate does NOT fire for these synonyms.
#
# Seed: Rioplatense colloquialisms for a male haircut. Extend by adding more
# entries here — no other code change required.
#
# CAUTION: each value MUST stay an exact, currently-active internal Service.name.
# If a mapped name is renamed/deactivated in the catalog, the synonym resolves to
# a name that no longer matches by_internal/by_display → the term is SILENTLY
# DROPPED (not resolved, not in unknown_names, no error to the model). Keep this
# map in sync with database/seeds/services.py when renaming services.
_COLLOQUIAL_SYNONYM_MAP: dict[str, str] = {
    "pelado": "Corte de Hombre",
    "rapado": "Corte de Hombre",
    "pelao": "Corte de Hombre",
    "rapao": "Corte de Hombre",
    "pelaito": "Corte de Hombre",
    "rapadito": "Corte de Hombre",
}


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
    session: AsyncSession, service_name: str, input_audience: str | None = None
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
            # Gate fires only when the CALLER has not yet provided an explicit audience.
            # input_audience is the caller's audience value (parameter), NOT the DB row's
            # audience column — reading the row value was semantically wrong (ADR-2 fix).
            if len(peers) > 1 and len(audience_values) > 1 and input_audience is None:
                logger.info(
                    "_resolve_audience_variants: audience_required axis=%s options_count=%d",
                    dimension,
                    len(peers),
                )
                return ("audience", dimension, sorted(p[0] for p in peers))

    return ("none", "", [])


async def service_ids_require_audience(
    session: AsyncSession, service_ids: list[str] | list[UUID]
) -> bool:
    """True when the given services sit in an audience-ambiguous dimension.

    A dimension is audience-ambiguous when its active PRINCIPAL services carry
    >1 distinct `audience` value (e.g. "cut": Corte de Mujer / Corte de Hombre /
    Corte de Niña …). The availability tools call this to refuse to offer slots
    when the audience has not been resolved (i.e. the `audience` parameter is
    None) — the audience MUST arrive via the parameter, set from the customer's
    explicit words or a remembered preference, never guessed from a service name
    (R32). Returns False on empty input.
    """
    from database.models import Service

    if not service_ids:
        return False

    # Dimensions of the requested services
    dim_result = await session.execute(
        select(Service.metadata_["dimension"].as_string()).where(Service.id.in_(service_ids))
    )
    dimensions = {row[0] for row in dim_result.fetchall() if row[0]}
    if not dimensions:
        return False

    # Audience spread among active principals in those dimensions
    principal_result = await session.execute(
        select(
            Service.metadata_["dimension"].as_string(),
            Service.audience,
        ).where(
            Service.metadata_["service_type"].as_string() == "principal",
            Service.metadata_["dimension"].as_string().in_(dimensions),
            Service.is_active.is_(True),
        )
    )
    rows = [{"dimension": d, "audience": a} for d, a in principal_result.fetchall()]
    return dimension_audience_is_ambiguous(rows)


def _memory_backs_audience(
    audience: str | None,
    service_name: str,
    customer_memories: dict | None,
) -> bool:
    """True when the customer's injected memory backs `audience` (source (a)).

    Legitimate when the resolved gendered service name is echoed in
    `typical_services`, OR any remembered service name / the agent_notes text
    infers the same audience qualifier (e.g. memory "Corte de Mujer" backs
    audience="adult_female"). This is the "lo de siempre" loyal-customer signal
    that must NOT be re-asked. Pure function — no I/O.
    """
    if not customer_memories or not audience:
        return False

    target_norm = _normalize_name(service_name)
    typical_services = customer_memories.get("typical_services") or []
    for remembered in typical_services:
        if _normalize_name(remembered) == target_norm:
            return True
        if _infer_audience_from_service_name(remembered) == audience:
            return True

    # agent_notes is free text — strip punctuation so qualifier tokens like
    # "mujer." are tokenized cleanly before audience inference.
    agent_notes = customer_memories.get("agent_notes") or ""
    if agent_notes:
        cleaned_notes = re.sub(r"[^\w\s]", " ", agent_notes)
        if _infer_audience_from_service_name(cleaned_notes) == audience:
            return True

    return False


async def _customer_has_prior_audience(
    session: AsyncSession, customer_id: str | None, audience: str | None
) -> bool:
    """True when the customer has a prior appointment carrying `audience` (source (b)).

    Appointments store a UUID array of service_ids; a prior appointment backs the
    audience when any of its services' `audience` column equals the target.
    Fail-safe: returns False on missing customer_id/audience or any error.

    CAVEAT: backing is audience-property-wide, not per-person. A customer with
    mixed-audience history (e.g. prior Corte de Mujer for herself + Corte de Niño
    for her child) backs BOTH audiences, so a cold model guess of either gendered
    service would pass the gate without re-asking for a multi-member household.
    Acceptable trade-off here (errs toward not re-asking returning customers);
    revisit if per-person audience tracking is added.
    """
    if not customer_id or not audience:
        return False
    from database.models import Appointment, Service

    try:
        cid: object = UUID(customer_id) if isinstance(customer_id, str) else customer_id
    except (ValueError, AttributeError):
        return False

    appt_result = await session.execute(
        select(Appointment.service_ids).where(Appointment.customer_id == cid)
    )
    service_ids: set = set()
    for row in appt_result.fetchall():
        for sid in row[0] or []:
            service_ids.add(sid)
    if not service_ids:
        return False

    svc_result = await session.execute(
        select(Service.id).where(Service.id.in_(service_ids), Service.audience == audience).limit(1)
    )
    return svc_result.first() is not None


async def gendered_service_without_audience_source(
    session: AsyncSession,
    service_ids: list[str],
    customer_memories: dict | None,
    customer_id: str | None,
) -> tuple[str, list[str]] | None:
    """Return (dimension, candidate_principal_names) for the FIRST resolved service
    that is a gendered audience-variant lacking a legitimate audience source.

    A service is a "gendered audience-variant" when it is a PRINCIPAL whose own
    `audience` column is non-null AND its dimension carries >1 distinct audience
    among active principals (e.g. "Corte de Mujer" in the "cut" dimension). Such a
    service resolved with `audience=None` is only legitimate when the customer has
    a real audience SOURCE — memory backing (source (a)) or a prior appointment
    (source (b)). Without a source it is a cold GUESS by the model and the gate
    returns the family so the caller asks `audience_required`.

    Returns None when every gendered service has a source, or none is gendered.
    """
    from database.models import Service

    if not service_ids:
        return None

    svc_result = await session.execute(
        select(Service.id, Service.name, Service.audience, Service.metadata_).where(
            Service.id.in_(service_ids)
        )
    )
    resolved_rows = svc_result.fetchall()

    dimensions = {
        (row[3] or {}).get("dimension")
        for row in resolved_rows
        if (row[3] or {}).get("service_type") == "principal" and (row[3] or {}).get("dimension")
    }
    if not dimensions:
        return None

    principal_result = await session.execute(
        select(
            Service.metadata_["dimension"].as_string(),
            Service.name,
            Service.audience,
        ).where(
            Service.metadata_["service_type"].as_string() == "principal",
            Service.metadata_["dimension"].as_string().in_(dimensions),
            Service.is_active.is_(True),
        )
    )
    audiences_by_dim: dict[str, set] = {}
    names_by_dim: dict[str, list[str]] = {}
    for dim, name, audience_value in principal_result.fetchall():
        audiences_by_dim.setdefault(dim, set()).add(audience_value)
        names_by_dim.setdefault(dim, []).append(name)

    for _sid, name, audience_value, metadata in resolved_rows:
        meta = metadata or {}
        if meta.get("service_type") != "principal":
            continue
        dimension = meta.get("dimension")
        if not dimension or audience_value is None:
            continue  # only gendered principals (own audience set) qualify
        if len(audiences_by_dim.get(dimension, set())) <= 1:
            continue  # single-audience dimension → not a gendered variant
        if _memory_backs_audience(audience_value, name, customer_memories):
            continue  # source (a)
        if await _customer_has_prior_audience(session, customer_id, audience_value):
            continue  # source (b)
        return dimension, sorted(names_by_dim.get(dimension, []))

    return None


async def availability_requires_audience(
    session: AsyncSession,
    service_ids: list[str],
    customer_memories: dict | None,
    customer_id: str | None,
) -> bool:
    """Source-aware guard C: must the availability tools BLOCK to resolve audience?

    Called only when the `audience` parameter is None. Returns True (BLOCK) when:
      - a resolved PRINCIPAL sits in a multi-audience dimension and its OWN
        `audience` is null (genuinely ambiguous — the audience cannot be derived
        from the service alone, e.g. a neutral "Manicura" / "corte" family), OR
      - a resolved PRINCIPAL is a gendered variant (own audience non-null in a
        multi-audience dimension, e.g. "Corte de Mujer") with NO legitimate
        audience source (the cold direct-to-availability bypass — stays protected).

    Returns False (ALLOW) when every multi-audience principal present is a gendered
    variant that HAS a legitimate audience source (memory backing or a prior
    appointment — the loyal-customer echo) and no null-audience ambiguous principal
    is present. A pinned gendered service is NOT ambiguous: its audience is
    derivable from the service itself, so a backed loyal customer is not re-asked.
    """
    from database.models import Service

    if not service_ids:
        return False

    svc_result = await session.execute(
        select(Service.id, Service.name, Service.audience, Service.metadata_).where(
            Service.id.in_(service_ids)
        )
    )
    resolved_rows = svc_result.fetchall()

    dimensions = {
        (row[3] or {}).get("dimension")
        for row in resolved_rows
        if (row[3] or {}).get("service_type") == "principal" and (row[3] or {}).get("dimension")
    }
    if not dimensions:
        return False

    principal_result = await session.execute(
        select(
            Service.metadata_["dimension"].as_string(),
            Service.audience,
        ).where(
            Service.metadata_["service_type"].as_string() == "principal",
            Service.metadata_["dimension"].as_string().in_(dimensions),
            Service.is_active.is_(True),
        )
    )
    audiences_by_dim: dict[str, set] = {}
    for dim, audience_value in principal_result.fetchall():
        audiences_by_dim.setdefault(dim, set()).add(audience_value)

    for _sid, name, audience_value, metadata in resolved_rows:
        meta = metadata or {}
        if meta.get("service_type") != "principal":
            continue
        dimension = meta.get("dimension")
        if not dimension:
            continue
        if len(audiences_by_dim.get(dimension, set())) <= 1:
            continue  # single-audience dimension → not ambiguous → allow

        if audience_value is None:
            return True  # neutral principal in a multi-audience dim → ambiguous → block

        # Pinned gendered service: audience derivable; block only without a source.
        if _memory_backs_audience(audience_value, name, customer_memories):
            continue  # source (a)
        if await _customer_has_prior_audience(session, customer_id, audience_value):
            continue  # source (b)
        return True  # gendered + no source → cold bypass → block

    return False


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
    session: AsyncSession, service_names: list[str], audience: str | None = None
) -> tuple[list[str], list[str], list[dict], list[str]]:
    """Resolve service names to UUIDs with ambiguity detection.

    Returns a 4-tuple:
      (resolved_ids, unknown_names, ambiguous_descriptors, partial_resolved_ids)

    When a service term maps to an ambiguous principal (audience axis or variant axis),
    its UUID is NOT appended to resolved_ids — instead, a descriptor dict is added to
    the third element.

    When any ambiguity exists in the call, resolved_ids is set to [] and the UUIDs
    that DID resolve cleanly are placed in partial_resolved_ids. When no ambiguity
    exists, partial_resolved_ids is [].

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

    Refs: REQ-TL-3, design ADR-DR-2, spec R2.1-R2.3, NFR-2
    """
    from agent.prompts.catalog_builder import _derive_customer_safe_service_name
    from database.models import Service

    result = await session.execute(
        select(Service.id, Service.name, Service.audience, Service.metadata_).where(
            Service.is_active.is_(True)
        )
    )

    by_internal: dict[str, str] = {}
    by_display: dict[str, str] = {}
    internal_name_by_norm: dict[str, str] = {}  # normalized → internal Service.name
    principal_rows: list[dict] = []  # for the audience-family index (neutral-token fallback)
    for service_id, service_name, audience_value, metadata in result.fetchall():
        sid = str(service_id)
        norm_internal = _normalize_name(service_name)
        by_internal[norm_internal] = sid
        internal_name_by_norm[norm_internal] = service_name
        display = _derive_customer_safe_service_name(service_name)
        norm_display = _normalize_name(display)
        by_display[norm_display] = sid
        if norm_display not in internal_name_by_norm:
            internal_name_by_norm[norm_display] = service_name
        meta = metadata or {}
        if meta.get("service_type") == "principal":
            principal_rows.append(
                {
                    "name": service_name,
                    "audience": audience_value,
                    "dimension": meta.get("dimension"),
                }
            )

    # Catalog-derived index of audience-ambiguous families that have NO neutral
    # parent principal (e.g. "cut"). Lets a neutral term like "corte" raise
    # audience_required instead of being rejected as unknown.
    family_index = build_audience_family_index(principal_rows)

    resolved_ids: list[str] = []
    unknown: list[str] = []
    ambiguous: list[dict] = []
    clean_uuids: list[str] = []  # UUIDs that resolved cleanly this call (ADR-DR-2)

    for name in service_names:
        normalized = _normalize_name(name)

        # Resolve to internal service name first.
        # Step 1 (ADR-2): colloquial synonym map — checked BEFORE by_internal/display/diminutive
        # so _AUDIENCE_SUFFIX_REPLACEMENTS is never re-applied (double-transform guard).
        matched_internal: str | None = _COLLOQUIAL_SYNONYM_MAP.get(normalized)

        if matched_internal is None:
            # Step 2: exact internal / display name lookup
            if normalized in by_internal:
                matched_internal = internal_name_by_norm.get(normalized)
            elif normalized in by_display:
                matched_internal = internal_name_by_norm.get(normalized)
            else:
                # Step 3: diminutive stripping
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
            # Neutral family-token fallback: a bare "corte" has no principal to
            # resolve to, but it clearly names an audience-ambiguous family.
            family = match_audience_family(name, family_index)
            if family is not None:
                # When the audience IS known (explicit param), resolve the neutral
                # token directly to the family principal matching that audience
                # (e.g. "corte" + adult_male → "Corte de Hombre"). Only ask when
                # NO audience is available.
                pinned_name = family.get("by_audience", {}).get(audience) if audience else None
                if pinned_name is not None:
                    pinned_norm = _normalize_name(pinned_name)
                    if pinned_norm in by_internal:
                        clean_uuids.append(by_internal[pinned_norm])
                        continue
                    if pinned_norm in by_display:
                        clean_uuids.append(by_display[pinned_norm])
                        continue
                # No audience (or unresolvable audience) → ask. Emit an
                # audience_required descriptor so the agent ASKS instead of
                # rejecting the term (which would push the model to guess a gender).
                ambiguous.append(
                    {
                        "status": "ambiguous",
                        "axis": "audience",
                        "service_term": name,
                        "family_label": family["dimension"],
                        "candidates": family["candidates"],
                        "question_hint": "audience_required",
                    }
                )
            else:
                unknown.append(name)
            continue

        # Q1 (memory-service audience pinning): when no caller audience is provided,
        # attempt to infer audience from qualifier tokens in the service name itself.
        # This covers memory-stored names like "Corte de Mujer" (adult_female) so that
        # the audience_required gate does not fire for already-specific service names.
        # ADR-2 extension: if `name` yields no audience token (e.g. "pelado"), also try
        # `matched_internal` ("Corte de Hombre" → "hombre" → adult_male) so that
        # synonym-resolved services self-pin without triggering audience_required.
        effective_audience = audience
        if effective_audience is None:
            effective_audience = _infer_audience_from_service_name(name)
            if effective_audience is None and matched_internal is not None:
                effective_audience = _infer_audience_from_service_name(matched_internal)
            if effective_audience is not None:
                logger.debug(
                    "_resolve_service_ids_strict: inferred audience=%s from name=%r (matched=%r)",
                    effective_audience,
                    name,
                    matched_internal,
                )

        # Check for ambiguity before committing UUID.
        # Pass caller's audience so the gate does not fire when audience is already known.
        kind, family_label, candidates = await _resolve_audience_variants(
            session, matched_internal, input_audience=effective_audience
        )
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
                clean_uuids.append(by_internal[norm])
            elif norm in by_display:
                clean_uuids.append(by_display[norm])

    # ADR-DR-2: when any ambiguity exists, nothing is committed this turn.
    # Clean UUIDs are returned in partial_resolved_ids for the LLM to round-trip.
    if ambiguous:
        return [], unknown, ambiguous, clean_uuids
    resolved_ids = clean_uuids
    return resolved_ids, unknown, ambiguous, []


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

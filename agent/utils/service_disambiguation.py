"""
Service Disambiguation Resolver.

Shared module that reads Service.metadata_ from the database, groups services
by their ``family`` code, and either resolves a candidate list to a single
concrete service or returns a structured clarification payload that the agent
can use to ask the customer the right follow-up question.

Architecture
============
This module is the single source of truth for service disambiguation logic.
It is called by:
  - agent/tools/search_services.py   (search-time disambiguation)
  - agent/utils/service_resolver.py  (booking-time disambiguation)

Both callers pass a candidate list of Service ORM objects (already fetched from
the DB) together with any axes the customer has already provided. The resolver
then:

  1. Partitions candidates into families (from metadata_["family"]).
  2. For services WITHOUT metadata (metadata_ == {}): returned unchanged via
     the ``fallback`` path — no disambiguation attempted.
  3. For services WITH metadata in a shared family: applies the provided axes
     (audience / hair_length / hair_density) to narrow down. If a single match
     results → returns ``ResolvedService``. If still ambiguous → returns the
     first outstanding axis as a ``ClarificationPayload``.

Key types
=========
``ResolvedService``
    A lightweight dataclass representing a fully resolved service with all the
    fields the agent needs for booking (id, name, duration_minutes, etc.).

``ClarificationPayload``
    Instructions for the agent: which axis to ask about (e.g. ``hair_density``)
    plus the human-readable question hint and the list of options the customer
    can choose from (each option maps to a concrete service UUID/name/duration).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from database.models import Service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


@dataclass
class ResolvedService:
    """A fully resolved, unambiguous service ready for booking."""

    id: UUID
    name: str
    duration_minutes: int
    category: str
    family: str | None
    ask_if_missing: list[str] = field(default_factory=list)
    combo_recommendations: list[str] = field(default_factory=list)
    description: str | None = None


@dataclass
class ClarificationPayload:
    """
    Payload returned when disambiguation requires a follow-up question.

    Attributes:
        axis: The metadata dimension to clarify (``"audience"``,
            ``"hair_length"``, or ``"hair_density"``).
        question_hint: A pre-translated question string for the agent to relay
            to the customer (in Spanish).
        options: Each option maps to a concrete service. Fields:
            - ``label``: human-readable option label (Spanish)
            - ``value``: the axis value (e.g. ``"long"``)
            - ``service_name``: service name in the catalog
            - ``service_id``: deterministic UUID for that service (as string)
            - ``duration_minutes``: duration of that service
            - ``category``: service category value (e.g. ``"HAIRDRESSING"``)
            - ``family``: service family code from metadata (or None)
            - ``combo_recommendations``: list of combo service names (may be empty)
            - ``description``: human-readable service description (or None)
    """

    axis: str
    question_hint: str
    options: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Human-readable question hints per axis (Spanish)
_AXIS_QUESTION_HINTS: dict[str, str] = {
    "audience": "¿Para quién es el corte?",
    "hair_length": "¿Es para cabello corto/medio o largo?",
    "hair_density": "¿Es cabello normal o muy largo/denso (necesita servicio extra)?",
}

# Human-readable labels per axis value (Spanish)
_AXIS_VALUE_LABELS: dict[str, dict[str, str]] = {
    "audience": {
        "baby": "Bebé",
        "child_male": "Niño",
        "child_female": "Niña",
        "adult_male": "Hombre",
        "adult_female": "Mujer",
    },
    "hair_length": {
        "short_medium": "Corto o medio",
        "long": "Largo",
    },
    "hair_density": {
        "normal": "Normal",
        "extra": "Muy largo o muy denso (extra)",
    },
}


def _meta(service: Service) -> dict[str, Any]:
    """Return metadata_ dict, safely."""
    return service.metadata_ or {}


def _has_family(service: Service) -> bool:
    """Return True if the service has a non-empty family code in metadata_."""
    return bool(_meta(service).get("family"))


def _apply_axis_filter(
    candidates: list[Service],
    axis: str,
    value: str,
) -> list[Service]:
    """Return only services where metadata_[axis] == value."""
    return [s for s in candidates if _meta(s).get(axis) == value]


def _to_resolved(service: Service) -> ResolvedService:
    """Convert a Service ORM object to a ResolvedService dataclass."""
    meta = _meta(service)
    return ResolvedService(
        id=service.id,
        name=service.name,
        duration_minutes=service.duration_minutes,
        category=service.category.value,
        family=meta.get("family"),
        ask_if_missing=meta.get("ask_if_missing", []),
        combo_recommendations=meta.get("combo_recommendations", []),
        description=service.description,
    )


def _build_clarification(
    axis: str,
    candidates: list[Service],
) -> ClarificationPayload:
    """
    Build a ClarificationPayload for the given axis over a candidate list.

    Each unique axis value maps to one option entry. If multiple services share
    the same axis value (shouldn't normally happen for well-seeded data) only
    the first one is used for the option entry.
    """
    seen: set[str] = set()
    options: list[dict[str, Any]] = []
    axis_labels = _AXIS_VALUE_LABELS.get(axis, {})

    for svc in candidates:
        meta = _meta(svc)
        ax_value = meta.get(axis)
        if ax_value is None:
            continue
        if ax_value in seen:
            continue
        seen.add(ax_value)
        options.append(
            {
                "label": axis_labels.get(ax_value, ax_value),
                "value": ax_value,
                "service_name": svc.name,
                "service_id": str(svc.id),
                "duration_minutes": svc.duration_minutes,
                "category": svc.category.value,
                "family": meta.get("family"),
                "combo_recommendations": meta.get("combo_recommendations", []),
                "description": svc.description,
            }
        )

    return ClarificationPayload(
        axis=axis,
        question_hint=_AXIS_QUESTION_HINTS.get(axis, f"¿Qué {axis} prefiere?"),
        options=options,
    )


def _build_variant_clarification(candidates: list[Service]) -> ClarificationPayload:
    """Build a name-based clarification when candidates are indistinguishable on metadata axes.

    Uses axis="service_variant" with each option labeled by service name.
    This is the last-resort disambiguation — the user picks by name.
    """
    options: list[dict[str, Any]] = []
    for svc in candidates:
        meta = _meta(svc)
        options.append(
            {
                "label": svc.name,
                "value": svc.name,
                "service_name": svc.name,
                "service_id": str(svc.id),
                "duration_minutes": svc.duration_minutes,
                "category": svc.category.value,
                "family": meta.get("family"),
                "combo_recommendations": meta.get("combo_recommendations", []),
                "description": svc.description,
            }
        )

    return ClarificationPayload(
        axis="service_variant",
        question_hint="Hay varias opciones. ¿Cuál preferís?",
        options=options,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_candidates(
    candidates: list[Service],
    *,
    audience: str | None = None,
    hair_length: str | None = None,
    hair_density: str | None = None,
) -> ResolvedService | ClarificationPayload | list[Service]:
    """
    Resolve a candidate list of Service objects using metadata-based disambiguation.

    Given a list of candidate services (already fuzzy-matched against the user
    query) and any disambiguation axes the user has already supplied, this
    function either:

    a) Returns a single ``ResolvedService`` when the candidates narrow down to
       exactly one match.
    b) Returns a ``ClarificationPayload`` with the next axis to clarify when
       the candidates are still ambiguous.
    c) Returns the original ``candidates`` list unchanged when no service has
       family metadata (graceful fallback for metadata-free services).

    Args:
        candidates:   List of Service ORM objects to disambiguate.
        audience:     User-provided audience axis, e.g. ``"adult_male"``.
        hair_length:  User-provided hair_length axis, e.g. ``"long"``.
        hair_density: User-provided hair_density axis, e.g. ``"extra"``.

    Returns:
        - ``ResolvedService`` — unambiguous single result
        - ``ClarificationPayload`` — clarification needed
        - ``list[Service]`` — no metadata, fall through to caller's logic

    Examples:
        >>> # Mechas family — hair_density not yet provided
        >>> resolve_candidates(mechas_candidates)
        ClarificationPayload(axis='hair_density', ...)

        >>> # Mechas family — hair_density provided by user
        >>> resolve_candidates(mechas_candidates, hair_density='normal')
        ResolvedService(name='Mechas', ...)

        >>> # Service without metadata (e.g. Bioterapia Facial)
        >>> resolve_candidates(bio_candidates)
        [<Service 'Bioterapia Facial Completa'>, ...]
    """
    if not candidates:
        logger.debug("resolve_candidates called with empty candidate list")
        return candidates

    # -----------------------------------------------------------------------
    # 1. Separate metadata-bearing services from bare services
    # -----------------------------------------------------------------------
    with_meta = [s for s in candidates if _has_family(s)]
    without_meta = [s for s in candidates if not _has_family(s)]

    if not with_meta:
        # All candidates lack family metadata → graceful fallback
        logger.debug(
            "resolve_candidates: no family metadata on any candidate — returning candidates unchanged"
        )
        return candidates

    # -----------------------------------------------------------------------
    # 2. Group by family — take the most represented family if mixed
    # -----------------------------------------------------------------------
    from collections import Counter

    family_counts: Counter[str] = Counter(_meta(s)["family"] for s in with_meta)
    dominant_family = family_counts.most_common(1)[0][0]
    family_candidates = [s for s in with_meta if _meta(s)["family"] == dominant_family]

    logger.debug(
        f"resolve_candidates: family='{dominant_family}', "
        f"candidates={[s.name for s in family_candidates]}"
    )

    # -----------------------------------------------------------------------
    # 3. Apply provided axes in priority order: audience → hair_length → hair_density
    # -----------------------------------------------------------------------
    axes: list[tuple[str, str | None]] = [
        ("audience", audience),
        ("hair_length", hair_length),
        ("hair_density", hair_density),
    ]

    active = list(family_candidates)

    for axis, value in axes:
        if value is None:
            continue  # Axis not provided by user — skip
        narrowed = _apply_axis_filter(active, axis, value)
        if narrowed:
            active = narrowed
            logger.debug(
                f"resolve_candidates: applied axis '{axis}'='{value}' → {len(active)} remaining"
            )
        else:
            logger.debug(
                f"resolve_candidates: axis '{axis}'='{value}' filtered out all — ignoring filter"
            )

    # -----------------------------------------------------------------------
    # 4. Single match → resolve directly
    # -----------------------------------------------------------------------
    if len(active) == 1:
        logger.info(f"resolve_candidates: resolved to single service '{active[0].name}'")
        return _to_resolved(active[0])

    # -----------------------------------------------------------------------
    # 5. Still multiple — find next axis to clarify (from ask_if_missing)
    # -----------------------------------------------------------------------
    # Collect all ask_if_missing axes across remaining candidates
    all_ask_axes: list[str] = []
    for svc in active:
        for ax in _meta(svc).get("ask_if_missing", []):
            if ax not in all_ask_axes:
                all_ask_axes.append(ax)

    # Filter out axes already provided
    provided_axes = {ax for ax, val in axes if val is not None}
    pending_axes = [ax for ax in all_ask_axes if ax not in provided_axes]

    if pending_axes:
        clarification_axis = pending_axes[0]
        logger.info(
            f"resolve_candidates: ambiguous on axis '{clarification_axis}' "
            f"with {len(active)} candidates"
        )
        return _build_clarification(clarification_axis, active)

    # -----------------------------------------------------------------------
    # 6. No more axes to try — if still multiple, build clarification on
    #    any differentiating axis (audience / hair_length / hair_density)
    # -----------------------------------------------------------------------
    for fallback_axis in ("audience", "hair_length", "hair_density"):
        unique_values = {_meta(s).get(fallback_axis) for s in active} - {None}
        if len(unique_values) > 1:
            logger.info(f"resolve_candidates: fallback clarification on axis '{fallback_axis}'")
            return _build_clarification(fallback_axis, active)

    # -----------------------------------------------------------------------
    # 7. All remaining candidates differ only by name — ask user to choose
    # -----------------------------------------------------------------------
    if len(active) > 1:
        logger.info(
            f"resolve_candidates: {len(active)} indistinguishable candidates — "
            "building service_variant clarification"
        )
        return _build_variant_clarification(active)

    return _to_resolved(active[0])

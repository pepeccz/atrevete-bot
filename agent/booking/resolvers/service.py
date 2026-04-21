"""
service resolver — fuzzy catalog match.

R1.3: on single match writes last_services; on multiple matches populates
pending_disambiguations and defers. Uses audience hint when present.

Phase 2 (catalog-loader SDD) — accepts list[ServiceRow] (production shape) or
list[str] (legacy test shape). When rows are present, audience filtering reads
the Service.audience column. When strings are present, the legacy name-keyword
parse is preserved for backward compatibility.
"""

from __future__ import annotations

import difflib
import logging
from typing import Any

from agent.booking.resolvers import ResolverResult
from agent.prompts.catalog_builder import ServiceRow

logger = logging.getLogger(__name__)

_CUTOFF = 0.35  # fuzzy match cutoff for service names (generous; audience-hint refines)


# Audience-column → allowed row-audience mapping (Phase 2, data-driven).
_AUDIENCE_MAP: dict[str, set[str | None]] = {
    "FEMALE": {"adult_female", "unisex", None},
    "MALE": {"adult_male", "unisex", None},
    "CHILD": {"child_female", "child_male", "unisex"},
}


def _normalize(text: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower().strip()


def _audience_matches(item: ServiceRow | str, audience_hint: str | None) -> bool:
    """Return True when *item* is consistent with *audience_hint*.

    When *item* is a ServiceRow, filters by the ``audience`` DB column using
    ``_AUDIENCE_MAP`` (Phase 2 — data-driven). When *item* is a plain string,
    preserves the legacy name-keyword parse for backward compatibility.
    """
    if not audience_hint:
        return True

    if isinstance(item, ServiceRow):
        allowed = _AUDIENCE_MAP.get(audience_hint, set())
        return item.audience in allowed

    # Legacy string path — preserved for existing unit tests.
    name_lower = item.lower()
    if audience_hint == "FEMALE" and any(
        k in name_lower for k in ("señora", "dama", "mujer", "femenin")
    ):
        return True
    if audience_hint == "MALE" and any(
        k in name_lower for k in ("caballero", "hombre", "masculin")
    ):
        return True
    if audience_hint == "CHILD" and any(
        k in name_lower for k in ("niño", "niña", "infantil", "nena")
    ):
        return True
    if not any(
        k in name_lower
        for k in (
            "señora",
            "caballero",
            "niño",
            "niña",
            "dama",
            "hombre",
            "infantil",
            "nena",
            "mujer",
        )
    ):
        return True
    return False


def _score_candidate(normalized_input: str, norm_name: str) -> float:
    """Compute the fuzzy-match score between a normalized user text and
    a normalized catalog entry. Extracted for testability."""
    ratio = difflib.SequenceMatcher(None, normalized_input, norm_name).ratio()
    input_words = set(normalized_input.split())
    name_words = set(norm_name.split())
    fwd_overlap = len(input_words & name_words) / max(len(name_words), 1)
    root_match = any(
        nw in iw or iw in nw
        for nw in name_words
        for iw in input_words
        if len(nw) >= 4 and len(iw) >= 4
    )
    score = max(ratio, fwd_overlap)
    if root_match:
        score = max(score, 0.4)
    return score


def _item_name(item: ServiceRow | str) -> str:
    return item.name if isinstance(item, ServiceRow) else item


def resolve(user_text: str, bc: dict[str, Any], state: dict[str, Any]) -> ResolverResult | None:
    """Fuzzy match user_text against the active service catalog.

    Catalog sourced from ``state["service_catalog"]`` (list of ``ServiceRow`` in
    prod; list of strings in legacy tests). When absent, falls back to the
    module-level loader.
    """
    catalog: list[ServiceRow | str] = state.get("service_catalog") or []
    if not catalog:
        catalog = _load_catalog_from_cache()

    if not catalog:
        return None

    audience_hint: str | None = bc.get("service_audience_hint")
    normalized_input = _normalize(user_text)

    candidates: list[tuple[ServiceRow | str, float]] = []
    for item in catalog:
        norm_name = _normalize(_item_name(item))
        score = _score_candidate(normalized_input, norm_name)
        if score >= _CUTOFF:
            candidates.append((item, score))

    if not candidates:
        return None

    audience_filtered = [
        (item, score) for item, score in candidates if _audience_matches(item, audience_hint)
    ]

    working = audience_filtered if audience_filtered else candidates
    working.sort(key=lambda x: x[1], reverse=True)

    if len(working) == 1 or (audience_hint and len(audience_filtered) == 1):
        chosen = _item_name(working[0][0])
        logger.info("resolver.service.single_match | service=%s", chosen)
        return {
            "patch": {"last_services": [chosen]},
            "matched": True,
            "user_action": "PROVIDE_FIELD",
        }

    disambig = [
        {"service_name": _item_name(item), "score": score} for item, score in working[:5]
    ]
    logger.info("resolver.service.ambiguous | count=%d", len(disambig))
    return {
        "patch": {"pending_disambiguations": disambig},
        "matched": True,
        "user_action": "PROVIDE_FIELD",
    }


def _load_catalog_from_cache() -> list[ServiceRow]:
    """Load active services from the shared catalog cache.

    Wired in Phase 3 of the catalog-loader SDD — kept as a stub here so that
    Phase 2 can land without depending on a synchronous path into the async
    cache. Phase 3 patches this function to call ``get_active_services()``.
    """
    return []

"""
service resolver — fuzzy catalog match.

R1.3: on single match writes last_services; on multiple matches populates
pending_disambiguations and defers. Uses audience hint when present.
"""

from __future__ import annotations

import difflib
import logging
from typing import Any

from agent.booking.resolvers import ResolverResult

logger = logging.getLogger(__name__)

_CUTOFF = 0.35  # fuzzy match cutoff for service names (generous; audience-hint refines)


def _normalize(text: str) -> str:
    import unicodedata
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower().strip()


def _audience_matches(service_name: str, audience_hint: str | None) -> bool:
    """Return True if service_name is consistent with audience_hint."""
    if not audience_hint:
        return True
    name_lower = service_name.lower()
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
    # Neutral services (no audience keyword) match any hint
    if not any(
        k in name_lower
        for k in ("señora", "caballero", "niño", "niña", "dama", "hombre", "infantil", "nena", "mujer")
    ):
        return True
    return False


def resolve(user_text: str, bc: dict[str, Any], state: dict[str, Any]) -> ResolverResult | None:
    """Fuzzy match user_text against service catalog.

    Catalog sourced from state["service_catalog"] (list of service name strings)
    or falls back to empty (no match).

    Returns:
        Single match: patch={"last_services": [name], "add_more_asked": False}
        Ambiguous: patch={"pending_disambiguations": [...]}
        No match: None
    """
    catalog: list[str] = state.get("service_catalog") or []
    if not catalog:
        # Try loading from shared catalog cache
        catalog = _load_catalog_from_cache()

    if not catalog:
        return None

    audience_hint: str | None = bc.get("service_audience_hint")
    normalized_input = _normalize(user_text)

    # Score each catalog item
    candidates: list[tuple[str, float]] = []
    norm_catalog = [_normalize(name) for name in catalog]

    for name, norm_name in zip(catalog, norm_catalog):
        ratio = difflib.SequenceMatcher(None, normalized_input, norm_name).ratio()
        # Keyword overlap: check if any word from input appears in service name OR vice versa
        input_words = set(normalized_input.split())
        name_words = set(norm_name.split())
        # Forward overlap: service name words found in user input
        fwd_overlap = len(input_words & name_words) / max(len(name_words), 1)
        # Root word match: any name word is a substring of any input word or vice versa
        root_match = any(
            nw in iw or iw in nw
            for nw in name_words
            for iw in input_words
            if len(nw) >= 4 and len(iw) >= 4
        )
        score = max(ratio, fwd_overlap)
        if root_match:
            score = max(score, 0.4)
        if score >= _CUTOFF:
            candidates.append((name, score))

    if not candidates:
        return None

    # Filter by audience hint
    audience_filtered = [
        (name, score)
        for name, score in candidates
        if _audience_matches(name, audience_hint)
    ]

    # If audience filter produced results, use them; otherwise use all
    working = audience_filtered if audience_filtered else candidates

    # Sort by score descending
    working.sort(key=lambda x: x[1], reverse=True)

    if len(working) == 1 or (audience_hint and len(audience_filtered) == 1):
        chosen = working[0][0]
        logger.info("resolver.service.single_match | service=%s", chosen)
        return {
            "patch": {"last_services": [chosen]},
            "matched": True,
            "user_action": "PROVIDE_FIELD",
        }

    # Multiple matches → disambiguate
    disambig = [{"service_name": name, "score": score} for name, score in working[:5]]
    logger.info("resolver.service.ambiguous | count=%d", len(disambig))
    return {
        "patch": {"pending_disambiguations": disambig},
        "matched": True,
        "user_action": "PROVIDE_FIELD",
    }


def _load_catalog_from_cache() -> list[str]:
    """Load service names from the shared prompt catalog cache."""
    try:
        # The catalog_builder stores a formatted string; we need names.
        # For now, return empty — tests inject via state["service_catalog"].
        return []
    except Exception:
        return []

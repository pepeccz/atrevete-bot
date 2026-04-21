"""
stylist resolver — explicit name match against known stylists.

R1.5: fires only on explicit name mention, not on ANY_AVAILABLE sentinel.
Guard: last_stylist or no_preference_stylist already set → no-op.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.booking.resolvers import ResolverResult

logger = logging.getLogger(__name__)


def resolve(user_text: str, bc: dict[str, Any], state: dict[str, Any]) -> ResolverResult | None:
    """Match explicit stylist name from known_stylists in state.

    State is expected to have "known_stylists" list, or falls back to
    shared.stylist_cache.get_stylist_names().

    Returns:
        patch: {"last_stylist": canonical_name}
        user_action: "PROVIDE_FIELD"
    or None if no match.
    """
    if bc.get("last_stylist") or bc.get("no_preference_stylist"):
        return None

    known: list[str] = state.get("known_stylists") or _load_known_stylists()
    if not known:
        return None

    from infra.resolvers._shared import normalize_text

    # Skip if text matches any-stylist patterns (ANY_AVAILABLE handled by any_stylist resolver)
    import re
    _ANY_PAT = re.compile(
        r"cualquier(?:[ae]|\b)|la\s+primera|quien\s+sea|me\s+da\s+igual|no\s+(?:me\s+)?importa",
        re.IGNORECASE,
    )
    if _ANY_PAT.search(user_text):
        return None

    normalized_text = normalize_text(user_text)
    tokens = normalized_text.split()
    clean_tokens = [t.strip(".,!?¡¿…") for t in tokens]

    for stylist in known:
        norm_name = normalize_text(stylist)
        # Token-level match (exact normalized token == stylist name)
        for token in clean_tokens:
            if token == norm_name:
                logger.info("resolver.stylist.applied | stylist=%s", stylist)
                return {
                    "patch": {"last_stylist": stylist},
                    "matched": True,
                    "user_action": "PROVIDE_FIELD",
                }
        # Substring match for multi-word names
        if norm_name in normalized_text:
            logger.info("resolver.stylist.applied | stylist=%s (substring)", stylist)
            return {
                "patch": {"last_stylist": stylist},
                "matched": True,
                "user_action": "PROVIDE_FIELD",
            }

    return None


def _load_known_stylists() -> list[str]:
    """Load known stylist names from shared stylist cache."""
    try:
        from shared.stylist_cache import get_stylist_names

        return get_stylist_names() or []
    except Exception:
        return []

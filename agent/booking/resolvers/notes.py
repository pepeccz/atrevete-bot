"""
notes resolver — capture or skip notes at ask_notes step.

R1.7: fires only when _last_leaf == "ask_notes";
maps negation → notes_state=skipped; any text → notes_state=provided + notes=<text>.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.booking.resolvers import ResolverResult

logger = logging.getLogger(__name__)


def resolve(user_text: str, bc: dict[str, Any], state: dict[str, Any]) -> ResolverResult | None:
    """Detect notes response — guard: only at ask_notes step.

    Returns:
        negation: patch={"notes_state": "skipped"}, user_action="NEGATE"
        text: patch={"notes_state": "provided", "notes": text}, user_action="PROVIDE_FIELD"
    or None if guard fails.
    """
    if bc.get("_last_leaf") != "ask_notes":
        return None

    # Already handled
    if bc.get("notes_state") in ("skipped", "provided"):
        return None

    text = user_text.strip()
    if not text:
        return None

    _NOTES_NEGATION = frozenset(
        ["sin notas", "sin nota", "no tengo notas", "no hay notas", "nada", "ninguna",
         "no", "nada mas", "ya esta", "sin comentarios", "sin observaciones", "no gracias"]
    )

    from infra.resolvers.negation import is_negation
    from infra.resolvers._shared import normalize_text

    normalized = normalize_text(user_text)
    matched_direct = normalized in _NOTES_NEGATION
    matched_is_neg, canonical, _ = is_negation(user_text)
    if matched_is_neg or matched_direct:
        logger.info("resolver.notes.skipped")
        return {
            "patch": {"notes_state": "skipped"},
            "matched": True,
            "user_action": "NEGATE",
        }

    logger.info("resolver.notes.provided")
    return {
        "patch": {"notes_state": "provided", "notes": text},
        "matched": True,
        "user_action": "PROVIDE_FIELD",
    }

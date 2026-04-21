"""
date_hint resolver — dateparser-based date extraction.

R1.4: fires only when a date/day expression is detected.
Uses dateparser with locale=es-AR.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from agent.booking.resolvers import ResolverResult

logger = logging.getLogger(__name__)

# Quick pre-filter: only try dateparser if these patterns appear
_DATE_TRIGGER = re.compile(
    r"\b(?:"
    r"lunes|martes|mi[eé]rcoles|jueves|viernes|s[áa]bado|domingo|"
    r"hoy|ma[ñn]ana|pasado\s+ma[ñn]ana|"
    r"la\s+semana|pr[oó]ximo?|siguiente|"
    r"el\s+\d{1,2}|"
    r"\d{1,2}[/-]\d{1,2}"
    r")\b",
    re.IGNORECASE,
)

_DATEPARSER_SETTINGS = {
    "RETURN_AS_TIMEZONE_AWARE": False,
    "PREFER_DATES_FROM": "future",
}


def resolve(user_text: str, bc: dict[str, Any], state: dict[str, Any]) -> ResolverResult | None:
    """Extract date hint from user message using dateparser.

    Returns:
        patch: {"date_hint": "<ISO date string>"}
        user_action: "CHANGE_DATE" if date_hint already set, else "PROVIDE_FIELD"
    or None if no date expression detected.
    """
    if not _DATE_TRIGGER.search(user_text):
        return None

    try:
        import dateparser

        # Try original text first; if None, strip leading article "el/la" and retry
        parsed = dateparser.parse(user_text, languages=["es"], settings=_DATEPARSER_SETTINGS)
        if parsed is None:
            # Strip leading "el/la/los/las" articles before weekday names
            stripped = re.sub(r"^(?:el|la|los|las)\s+", "", user_text.strip(), flags=re.IGNORECASE)
            if stripped != user_text.strip():
                parsed = dateparser.parse(stripped, languages=["es"], settings=_DATEPARSER_SETTINGS)
        if parsed is None:
            # Also try extracting just the date expression
            _WEEKDAY_PAT = re.compile(
                r"\b(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[áa]bado|domingo|"
                r"hoy|ma[ñn]ana|pasado\s+ma[ñn]ana)\b",
                re.IGNORECASE,
            )
            m = _WEEKDAY_PAT.search(user_text)
            if m:
                parsed = dateparser.parse(
                    m.group(0), languages=["es"], settings=_DATEPARSER_SETTINGS
                )
    except Exception:
        logger.exception("dateparser raised; skipping date_hint resolver")
        return None

    if parsed is None:
        return None

    date_str = parsed.date().isoformat()
    existing = bc.get("date_hint")
    action = "CHANGE_DATE" if existing else "PROVIDE_FIELD"

    logger.info(
        "resolver.date_hint.applied | date=%s | action=%s",
        date_str,
        action,
    )

    return {
        "patch": {"date_hint": date_str},
        "matched": True,
        "user_action": action,
    }

"""Date resolver — Task 4.6.

Parses natural language date expressions using dateparser.
Returns {"booking": {"date": "YYYY-MM-DD"}} on success, None on failure
or if the parsed date is in the past.
"""

from __future__ import annotations

import datetime
import re
import unicodedata
from typing import Any

# Prefixes that dateparser can't handle but we can strip
_STRIP_PREFIXES = re.compile(
    r"^(?:el|la|los|las|un|una|para el|para la|proximo|proxima|siguiente)\s+",
    re.IGNORECASE,
)

# "pasado mañana" → "+2 days" dateparser-friendly
_PASADO_MANANA = re.compile(r"pasado\s+ma[ñn]ana", re.IGNORECASE)

# "próximo/a viernes" → "viernes" (dateparser handles bare weekday)
_PROXIMO = re.compile(r"(?:proximo|proxima|siguiente)\s+", re.IGNORECASE)


def _normalize_for_dateparser(text: str) -> str:
    """Strip accent-sensitive prefixes and expand known patterns."""
    # NFKD to handle ñ/accents in pattern matching
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_approx = "".join(ch if not unicodedata.combining(ch) else "" for ch in nfkd)

    # "pasado mañana" → keep as-is for manual handling below
    if _PASADO_MANANA.search(ascii_approx):
        return "__pasado_manana__"

    # "próximo viernes" → "viernes"
    cleaned = _PROXIMO.sub("", ascii_approx).strip()

    # "el/la viernes" → "viernes", "el 25" → "25"
    cleaned = _STRIP_PREFIXES.sub("", cleaned).strip()

    return cleaned


def _now() -> datetime.datetime:
    """Return current datetime in Europe/Madrid timezone."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.datetime.now(ZoneInfo("Europe/Madrid"))
    except Exception:
        return datetime.datetime.now()


async def resolve_date(text: str, state: Any) -> dict[str, Any] | None:
    """Parse a natural language date from text.

    Returns {"booking": {"date": "YYYY-MM-DD"}} on success, None if
    no date is found or the date is in the past.
    """
    try:
        import dateparser
    except ImportError:
        return None

    now = _now()
    cleaned = _normalize_for_dateparser(text)

    # Handle "pasado mañana" manually — dateparser doesn't support it in Spanish
    if cleaned == "__pasado_manana__":
        result_date = now.date() + datetime.timedelta(days=2)
        return {"booking": {"date": result_date.isoformat()}}

    parsed = dateparser.parse(
        cleaned,
        languages=["es"],
        settings={
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": now.replace(tzinfo=None),
            "TIMEZONE": "Europe/Madrid",
            "RETURN_AS_TIMEZONE_AWARE": False,
        },
    )

    if parsed is None:
        return None

    result_date = parsed.date()
    today = now.date()

    if result_date < today:
        return None

    return {"booking": {"date": result_date.isoformat()}}

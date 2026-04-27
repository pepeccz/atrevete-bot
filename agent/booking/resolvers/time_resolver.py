"""Pure relative-date resolver for Spanish booking phrases.

Public API:
    resolve_relative_date(text: str, today: date) -> date | None

Pure function — no I/O, no clock access. Caller injects `today`.
Returns None for ambiguous or unrecognized input. Never raises.

Phrase families (matched in priority order):
  1. hoy
  2. mañana (standalone)
  3. pasado mañana
  4. el N de mes  (e.g. "el 5 de mayo")
  5. próximo / que-viene weekday
  6. bare weekday (el miércoles / miércoles)
  7. el N  (day of month without month name)

Design: ADR-3 (pure, injected today), ADR-4 (None for ambiguous),
        ADR-5 (bare weekday never returns today), ADR-7 (hardcoded weekday names).
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date, timedelta

# Minimum advance booking days — single source of truth.
# Referenced by update_booking (payload label) and next_available_options.
MIN_BOOKING_DAYS: int = 3

# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------

_WEEKDAYS_ES: dict[str, int] = {
    "lunes": 0,
    "martes": 1,
    "miércoles": 2,
    "miercoles": 2,  # unaccented variant
    "jueves": 3,
    "viernes": 4,
    "sábado": 5,
    "sabado": 5,  # unaccented variant
    "domingo": 6,
}

_MONTHS_ES: dict[str, int] = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

# ---------------------------------------------------------------------------
# Pre-compiled regexes
# ---------------------------------------------------------------------------

# el 5 de mayo  /  el 3 de enero
_RE_DAY_OF_MONTH_NAMED = re.compile(
    r"^(?:el\s+)?(\d{1,2})\s+de\s+([a-záéíóúüñ]+)$"
)

# próximo miércoles / el próximo miércoles / próxima lunes
_RE_PROXIMO = re.compile(
    r"^(?:el\s+)?pr[oó]xim[oa]\s+([a-záéíóúüñ]+)$"
)

# el miércoles que viene / miércoles que viene / lunes que viene
_RE_QUE_VIENE = re.compile(
    r"^(?:el\s+)?([a-záéíóúüñ]+)\s+que\s+viene$"
)

# el miércoles / el lunes / bare weekday with or without article
_RE_BARE_WEEKDAY = re.compile(
    r"^(?:el\s+|este\s+)?([a-záéíóúüñ]+)$"
)

# el 5 / el 30 (no month name)
_RE_DAY_OF_MONTH = re.compile(
    r"^el\s+(\d{1,2})$"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Strip, lowercase, NFC-normalize, collapse whitespace, strip punctuation."""
    text = unicodedata.normalize("NFC", text.strip().lower())
    text = re.sub(r"\s+", " ", text)
    text = text.rstrip(".,;!?")
    return text


def _next_weekday(today: date, weekday: int, min_delta: int = 1) -> date:
    """Return the next date >= today + min_delta with the given weekday (0=Monday)."""
    target = today + timedelta(days=min_delta)
    days_ahead = (weekday - target.weekday()) % 7
    return target + timedelta(days=days_ahead)


def _safe_date(year: int, month: int, day: int) -> date | None:
    """Return date(year, month, day) or None if the day doesn't exist in that month."""
    max_day = calendar.monthrange(year, month)[1]
    if day > max_day:
        return None
    return date(year, month, day)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_relative_date(text: str, today: date) -> date | None:
    """Resolve a Spanish relative date phrase to a concrete date.

    Args:
        text:  Raw phrase from the user (e.g. "el miércoles que viene", "mañana").
        today: Reference date — injected by caller, no internal clock access.

    Returns:
        Resolved date, or None for ambiguous / unrecognized input.
        Never raises.
    """
    try:
        return _resolve(text, today)
    except Exception:
        return None


def _resolve(text: str, today: date) -> date | None:  # noqa: C901
    if not text:
        return None

    norm = _normalize(text)

    # 1. hoy
    if norm == "hoy":
        return today

    # 2. mañana (standalone)
    if norm == "mañana":
        return today + timedelta(days=1)

    # 3. pasado mañana
    if norm in ("pasado mañana", "pasado"):
        return today + timedelta(days=2)

    # 4. el N de mes (highest priority day-of-month pattern to avoid collision)
    m = _RE_DAY_OF_MONTH_NAMED.match(norm)
    if m:
        day = int(m.group(1))
        month_name = m.group(2)
        month = _MONTHS_ES.get(month_name)
        if month is None:
            return None
        # Try current year first
        candidate = _safe_date(today.year, month, day)
        if candidate is None:
            return None
        if candidate > today:
            return candidate
        # Already passed → next year
        candidate = _safe_date(today.year + 1, month, day)
        return candidate  # may be None if day invalid next year too

    # 5a. próximo weekday
    m = _RE_PROXIMO.match(norm)
    if m:
        weekday_name = m.group(1)
        weekday = _WEEKDAYS_ES.get(weekday_name)
        if weekday is None:
            return None
        return _next_weekday(today, weekday, min_delta=1)

    # 5b. weekday que viene (strictly next week: min_delta=7)
    m = _RE_QUE_VIENE.match(norm)
    if m:
        weekday_name = m.group(1)
        weekday = _WEEKDAYS_ES.get(weekday_name)
        if weekday is None:
            # e.g. "la semana que viene" — week without day
            return None
        return _next_weekday(today, weekday, min_delta=7)

    # 6. el N (day of month, no month name)
    m = _RE_DAY_OF_MONTH.match(norm)
    if m:
        day = int(m.group(1))
        if day < 1 or day > 31:
            return None
        # Try current month if day is still in the future (> today.day)
        if day > today.day:
            candidate = _safe_date(today.year, today.month, day)
            if candidate is not None:
                return candidate
        # Otherwise next month
        next_month = today.month + 1 if today.month < 12 else 1
        next_year = today.year if today.month < 12 else today.year + 1
        candidate = _safe_date(next_year, next_month, day)
        if candidate is not None:
            return candidate
        # Skip further months (edge case: day 31 in months without 31 days)
        # Try up to 12 months ahead
        for delta in range(2, 13):
            m_idx = ((today.month - 1 + delta) % 12) + 1
            y = today.year + (today.month - 1 + delta) // 12
            candidate = _safe_date(y, m_idx, day)
            if candidate is not None:
                return candidate
        return None

    # 7. bare weekday (el miércoles / miércoles / este lunes)
    m = _RE_BARE_WEEKDAY.match(norm)
    if m:
        weekday_name = m.group(1)
        weekday = _WEEKDAYS_ES.get(weekday_name)
        if weekday is None:
            return None
        return _next_weekday(today, weekday, min_delta=1)

    return None

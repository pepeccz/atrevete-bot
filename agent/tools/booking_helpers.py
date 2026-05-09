"""Pure utility functions for booking-flow tools.

DB-bound helpers were promoted to agent/services/booking_query_service.py (PR#2).
Only pure (no I/O) utility functions remain here — available to any tool.

Refs: R2, R3, design §8, SDD service-boundary-extraction PR#2.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Diminutive normalization helpers (ADR-10)
# ---------------------------------------------------------------------------

_DIMINUTIVE_RE = re.compile(r"(c?it[oa]s?)$")
"""Matches Spanish diminutive suffixes: -ito, -ita, -itos, -itas, -cito, -cita, -citos, -citas."""


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

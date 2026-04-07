"""
FuzzyResolver — Centralized fuzzy name/option resolution utility.

Deterministic strategy chain (first match wins):
  1. exact             — normalized exact match
  2. normalized_contains — option contains the normalized input (strips articles/prepositions)
  3. prefix            — normalized input is a prefix of the option
  4. time_pattern      — parse as time ("las 11", "9:00", "a las 9 y media")
  5. ordinal           — parse as ordinal ("primero", "la primera", "2")
  6. fuzzy_ratio       — Levenshtein-like similarity ≥ threshold (default 0.75)

No external dependencies — uses difflib.SequenceMatcher (stdlib).
All functions are synchronous and side-effect-free.

WS-1 (parallel delegation) will overwrite this file with the full implementation.
This stub provides the minimum surface area needed by WS-5 tools.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable

# ── Spanish articles and prepositions to strip during normalization ────────────
_STRIP_WORDS = frozenset(
    {
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "unos",
        "unas",
        "de",
        "del",
        "con",
        "para",
        "a",
        "al",
        "en",
        "y",
        "o",
        "por",
        "que",
        "se",
        "me",
        "te",
        "le",
    }
)

# ── Time pattern (reused from booking_mode) ────────────────────────────────────
_TIME_PATTERN = re.compile(
    r"(?:a\s+)?las?\s+(\d{1,2})(?::(\d{2})|\s+y\s+media)?|^(\d{1,2}):(\d{2})$",
    re.IGNORECASE,
)

# ── Ordinal pattern ────────────────────────────────────────────────────────────
_ORDINAL_PATTERN = re.compile(
    r"(?:la\s+|el\s+)?(primer[ao]?|segund[ao]|tercer[ao]?|cuart[ao]|quint[ao]|últim[ao])",
    re.IGNORECASE,
)

_ORDINAL_STEM_MAP: dict[str, int] = {
    "prime": 0,
    "segun": 1,
    "terce": 2,
    "cuart": 3,
    "quint": 4,
    "últim": -1,
}


@dataclass(frozen=True, slots=True)
class Match:
    """Result of a fuzzy resolution attempt."""

    value: str  # The matched option (original casing)
    confidence: float  # 0.0–1.0
    strategy: str  # "exact"|"normalized_contains"|"prefix"|"time"|"ordinal"|"fuzzy"


def normalize_spanish(text: str) -> str:
    """Strip articles, prepositions, accents; lowercase.

    Examples:
        "las balayage" → "balayage"
        "con Ana"      → "ana"
        "el primer[o]" → "primer"
    """
    # Remove accents (NFD decomposition + strip combining marks)
    nfd = unicodedata.normalize("NFD", text)
    without_accents = "".join(ch for ch in nfd if not unicodedata.combining(ch))

    # Lowercase and tokenize
    tokens = without_accents.lower().split()

    # Strip known articles/prepositions
    filtered = [t for t in tokens if t not in _STRIP_WORDS]

    return " ".join(filtered).strip()


def resolve_from_options(
    user_input: str,
    options: list[str],
    key_fn: Callable[[str], str] | None = None,
    threshold: float = 0.75,
) -> Match | None:
    """Try strategies in order; return first match above threshold, or None.

    Args:
        user_input:  Raw user text to match.
        options:     List of candidate strings (original casing preserved in Match.value).
        key_fn:      Optional function to extract a comparison key from each option.
                     Defaults to identity (use the option itself).
        threshold:   Minimum confidence for fuzzy_ratio strategy (default 0.75).

    Returns:
        Match(value, confidence, strategy) or None.
    """
    if not user_input or not options:
        return None

    key = key_fn or (lambda x: x)
    normalized_input = normalize_spanish(user_input)

    for option in options:
        normalized_option = normalize_spanish(key(option))

        # Strategy 1: exact (normalized)
        if normalized_input == normalized_option:
            return Match(value=option, confidence=1.0, strategy="exact")

    for option in options:
        normalized_option = normalize_spanish(key(option))

        # Strategy 2: normalized_contains
        if normalized_input and normalized_option and normalized_input in normalized_option:
            return Match(value=option, confidence=0.95, strategy="normalized_contains")
        if normalized_option and normalized_input and normalized_option in normalized_input:
            return Match(value=option, confidence=0.90, strategy="normalized_contains")

    for option in options:
        normalized_option = normalize_spanish(key(option))

        # Strategy 3: prefix
        if (
            normalized_option
            and normalized_input
            and normalized_option.startswith(normalized_input)
        ):
            return Match(value=option, confidence=0.85, strategy="prefix")
        if (
            normalized_input
            and normalized_option
            and normalized_input.startswith(normalized_option)
        ):
            return Match(value=option, confidence=0.80, strategy="prefix")

    # Strategy 6: fuzzy_ratio (last resort — expensive)
    best_option: str | None = None
    best_ratio = 0.0
    for option in options:
        normalized_option = normalize_spanish(key(option))
        ratio = SequenceMatcher(None, normalized_input, normalized_option).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_option = option

    if best_ratio >= threshold and best_option is not None:
        return Match(value=best_option, confidence=best_ratio, strategy="fuzzy_ratio")

    return None


def resolve_time_slot(user_input: str, slots: list[dict]) -> dict | None:
    """Extract time pattern from input, match against slots[].time field.

    Args:
        user_input: Raw user text (e.g. "a las 11", "las 9:00").
        slots:      List of slot dicts, each with a "time" key ("HH:MM").

    Returns:
        The matching slot dict, or None if no unambiguous match found.
    """
    if not user_input or not slots:
        return None

    time_match = _TIME_PATTERN.search(user_input)
    if not time_match:
        return None

    raw_hour = time_match.group(1) or time_match.group(3)
    raw_minute = time_match.group(2) or time_match.group(4)
    if raw_hour is None:
        return None

    hour = int(raw_hour)
    if raw_minute is not None:
        minute = int(raw_minute)
    elif "media" in user_input.lower():
        minute = 30
    else:
        minute = 0

    target_time = f"{hour:02d}:{minute:02d}"
    matches = [s for s in slots if s.get("time", "") == target_time]
    return matches[0] if len(matches) == 1 else None


def resolve_ordinal(user_input: str, count: int) -> int | None:
    """Parse ordinal expression, return 0-based index or None.

    Handles:
      - Bare digits: "1" → 0, "2" → 1 (1-based input, 0-based output)
      - Spanish ordinals: "primero" → 0, "la segunda" → 1, "el último" → count-1
      - Out-of-range → None

    Args:
        user_input: Raw user text.
        count:      Number of available items (upper bound).

    Returns:
        0-based index or None if unresolvable.
    """
    if not user_input or count <= 0:
        return None

    stripped = user_input.strip()

    # Try bare digit first
    try:
        digit = int(stripped)
        if 1 <= digit <= count:
            return digit - 1
        return None
    except (ValueError, TypeError):
        pass

    # Try ordinal word pattern
    ordinal_match = _ORDINAL_PATTERN.search(stripped)
    if ordinal_match:
        stem = ordinal_match.group(1)[:5].lower()
        # Normalize accent on "últim"
        stem = stem.replace("u\u0301lt", "últim")[:5]
        idx = _ORDINAL_STEM_MAP.get(stem)
        if idx is not None:
            resolved = idx if idx >= 0 else count + idx
            if 0 <= resolved < count:
                return resolved

    return None

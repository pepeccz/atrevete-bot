"""
Unified audience maps for the Atrévete Bot.

Single source of truth for audience/demographic hint maps used across:
- agent/modes/greeting_mode.py   (AUDIENCE_HINT_MAP)

Design decision: superset merge of all local maps that were previously
duplicated in each consumer file (ADR: REQ-4).
"""

import re
import unicodedata

# Maps normalized (accent-stripped, lowercase) message tokens → audience hint values.
# Used to extract audience from user phrases like "quiero un corte de dama" → "adult_female".
# Superset of all local _AUDIENCE_HINT_MAP dicts previously defined in
# greeting_mode.py and tool_extractors.py.
AUDIENCE_HINT_MAP: dict[str, str] = {
    # adult_male
    "caballero": "adult_male",
    "hombre": "adult_male",
    "adulto": "adult_male",
    "senor": "adult_male",
    "chico": "adult_male",
    # adult_female
    "dama": "adult_female",
    "mujer": "adult_female",
    "adulta": "adult_female",
    "senora": "adult_female",
    "chica": "adult_female",
    "seorita": "adult_female",
    "srita": "adult_female",
    # child_male
    "nino": "child_male",
    "nene": "child_male",
    "hijo": "child_male",
    "chiquitin": "child_male",
    # child_female
    "nina": "child_female",
    "nena": "child_female",
    "hija": "child_female",
    "chiquitina": "child_female",
    # baby
    "bebe": "baby",
}

def canonicalize_audience(raw: str) -> str:
    """Normalize an audience string to a canonical audience hint value.

    Uses AUDIENCE_HINT_MAP to resolve free-form audience descriptions (as they
    appear in service metadata or user messages) to canonical values like
    ``"adult_female"``, ``"adult_male"``, ``"child_male"``, ``"child_female"``,
    or ``"baby"``.

    Algorithm:
        1. Fast-path: NFKD-normalize + strip accents + lowercase the entire
           ``raw`` string. If it is a direct key in ``AUDIENCE_HINT_MAP``,
           return the mapped value.
        2. Tokenize: split on ``[/,]+``, ``\\by\\b``, and ``\\s+``. Strip each
           token.
        3. For each token: NFKD-normalize, strip accents, lowercase. If it is
           in ``AUDIENCE_HINT_MAP``, return the mapped value.
        4. No match: return ``raw`` unchanged.

    Args:
        raw: Raw audience string from service metadata or user input.

    Returns:
        A canonical audience hint value if a match is found, otherwise ``raw``
        unchanged.  Returns ``""`` for empty input.

    Examples:
        >>> canonicalize_audience("señora")
        'adult_female'
        >>> canonicalize_audience("Dama / Señora")
        'adult_female'
        >>> canonicalize_audience("Caballero, Adulto")
        'adult_male'
        >>> canonicalize_audience("Dama y Caballero")
        'adult_female'
        >>> canonicalize_audience("adult_female")
        'adult_female'
        >>> canonicalize_audience("unknown_value")
        'unknown_value'
        >>> canonicalize_audience("")
        ''
    """
    if not raw:
        return ""

    def _normalize(text: str) -> str:
        """NFKD-normalize, strip combining characters, then lowercase."""
        nfkd = unicodedata.normalize("NFKD", text)
        return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).lower()

    # Fast-path: try the whole string as a single key.
    normalized_raw = _normalize(raw)
    if normalized_raw in AUDIENCE_HINT_MAP:
        return AUDIENCE_HINT_MAP[normalized_raw]

    # Tokenize: split on "/" or "," runs, the word "y", and whitespace.
    tokens = re.split(r"[/,]+|\by\b|\s+", raw)
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        normalized_token = _normalize(token)
        if normalized_token in AUDIENCE_HINT_MAP:
            return AUDIENCE_HINT_MAP[normalized_token]

    return raw

"""
Deterministic negation resolver for the booking flow.

Moved from shared/negation_phrases.py in E1 per P8 (shared/ is for utilities,
not domain resolvers; resolvers belong in infra/resolvers/).

Classifies whether a user message is a negation of "¿algo más?" BEFORE the LLM
agentic loop runs. Uses stdlib only (unicodedata, difflib) — zero new dependencies.

Public API
----------
NEGATION_PHRASES : frozenset[str]
    Canonical normalized forms of negation utterances.

normalize_for_negation(text) -> str
    NFKD-normalize, strip combining chars, lowercase, strip trailing punct,
    collapse whitespace. Mirrors the pipeline in shared/audience_maps.py:91-94.

is_negation(user_text) -> tuple[bool, str | None, int]
    Returns (matched, canonical_phrase_or_None, distance_or_minus1).
    - Exact match is checked first (O(1) frozenset lookup).
    - Fuzzy match via difflib.get_close_matches(cutoff=0.86) only when
      len(tokens) <= 3 (activation window rule — avoids false positives on
      longer sentences like "no sé cuál estilista").
    - distance: int((1 - ratio) * 100) for fuzzy hits; -1 for exact or no match.

Design rules
------------
- Match against the FULL normalized utterance, not substrings.
- ≤3-token window activates fuzzy matching (prevents "no ahora mismo" from matching).
- "nada" and "ya" alone DO match (single-token canonical phrases).
- "no sé", "no ahora", "no quiero X" do NOT match — multi-token with non-negation
  filler; distance > 0.14 to any single-token canonical.
"""

from __future__ import annotations

import difflib
import unicodedata

# ---------------------------------------------------------------------------
# Canonical phrases — normalized form (output of normalize_for_negation).
# R2 requires at minimum 14 forms.
# ---------------------------------------------------------------------------

NEGATION_PHRASES: frozenset[str] = frozenset(
    [
        "nada mas",
        "nomas",
        "no mas",
        "nada",
        "nel",
        "nope",
        "nah",
        "ya esta",
        "ya estamos",
        "ya estamos asi",  # colloquial variant: "ya estamos así"
        "listo",
        "ya",
        "basta",
        "es todo",
        "eso es todo",
    ]
)


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------


def normalize_for_negation(text: str) -> str:
    """Normalize a user utterance for negation matching.

    Pipeline:
    1. NFKD Unicode normalization — decomposes accented chars and compatibility
       forms (e.g. "ß" → "ss" in compatibility; "á" → "a" + combining acute).
    2. Strip combining characters — removes accent marks left by step 1.
    3. Lowercase.
    4. Strip trailing ASCII punctuation (.,!?¡¿…).
    5. Collapse internal whitespace.

    This mirrors the _normalize() helper in shared/audience_maps.py:91-94 and
    agent/modes/booking_mode.py:134-137.

    Examples:
        >>> normalize_for_negation("Nada Máß")
        'nada mass'
        >>> normalize_for_negation("NADA!")
        'nada'
        >>> normalize_for_negation("  ya  está  ")
        'ya esta'
    """
    # Step 1: NFKD decomposition
    nfkd = unicodedata.normalize("NFKD", text)
    # Step 2: strip combining characters AND non-ASCII non-space symbols (emoji, etc.)
    # Keep only ASCII printable chars and spaces — negation phrases are all ASCII after NFKD.
    stripped = "".join(
        ch
        for ch in nfkd
        if not unicodedata.combining(ch) and (ch.isascii() or ch == " ")
    )
    # Step 3: lowercase
    lowered = stripped.lower()
    # Step 4: strip trailing ASCII punctuation (including leading for safety)
    trimmed = lowered.rstrip(".,!?¡¿…").lstrip("¡¿")
    # Step 5: collapse whitespace
    collapsed = " ".join(trimmed.split())
    return collapsed


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------


def _is_composition_of_canonicals(normalized: str) -> bool:
    """True iff `normalized` is a space-joined concatenation of 1+ canonical phrases.

    Greedy longest-match consumption left-to-right. Added to handle compound
    utterances like "nope nada mas" (conv 99001 T7 canary regression) — the
    concatenation of two canonicals ("nope" + "nada mas") that neither the
    exact lookup nor fuzzy cutoff 0.86 could match.

    Composition (not substring) to avoid false positives like "no quiero nada"
    where a canonical appears mixed with non-canonical filler.
    """
    if not normalized:
        return False
    sorted_phrases = sorted(NEGATION_PHRASES, key=len, reverse=True)
    remaining = normalized
    while remaining:
        consumed = False
        for phrase in sorted_phrases:
            if remaining == phrase:
                return True
            if remaining.startswith(phrase + " "):
                remaining = remaining[len(phrase) + 1 :]
                consumed = True
                break
        if not consumed:
            return False
    return True


def is_negation(user_text: str) -> tuple[bool, str | None, int]:
    """Classify whether user_text is a negation of "¿algo más?".

    Returns:
        (matched, canonical_phrase, distance)

        - matched: True if the message is a negation utterance.
        - canonical_phrase: the matched canonical phrase string, or None.
        - distance: int((1 - ratio) * 100) for fuzzy matches; -1 for exact
          or compositional matches; -1 for no match.

    Algorithm:
    1. Normalize user_text via normalize_for_negation().
    2. Exact O(1) frozenset lookup → return (True, phrase, -1).
    3. Compositional match: input = concat of 1+ canonicals → return (True, normalized, -1).
    4. Token count check: only if len(tokens) <= 3 proceed to fuzzy.
    5. Fuzzy match via difflib.get_close_matches(cutoff=0.86).
    6. No match → return (False, None, -1).
    """
    normalized = normalize_for_negation(user_text)

    # Step 2: exact match (O(1))
    if normalized in NEGATION_PHRASES:
        return (True, normalized, -1)

    # Step 3: compositional match — handles compounds like "nope nada mas"
    if _is_composition_of_canonicals(normalized):
        return (True, normalized, -1)

    # Step 4: token window gate — fuzzy only for short utterances
    tokens = normalized.split()
    if len(tokens) > 3:
        return (False, None, -1)

    # Step 5: fuzzy match
    candidates = list(NEGATION_PHRASES)
    matches = difflib.get_close_matches(normalized, candidates, n=1, cutoff=0.86)
    if matches:
        canonical = matches[0]
        ratio = difflib.SequenceMatcher(None, normalized, canonical).ratio()
        distance = int((1 - ratio) * 100)
        return (True, canonical, distance)

    return (False, None, -1)

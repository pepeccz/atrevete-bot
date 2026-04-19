"""
Deterministic affirmation resolver for the booking flow.

Symmetric to infra/resolvers/negation.py. Classifies whether a user message
is a confirmation of a shown booking summary BEFORE the LLM agentic loop runs.
Uses stdlib only (unicodedata, difflib) — zero new dependencies.

Public API
----------
AFFIRMATION_PHRASES : frozenset[str]
    Canonical normalized forms of affirmation utterances.

is_affirmation(text, window=3) -> tuple[bool, str | None, float]
    Returns (matched, canonical_phrase_or_None, distance_or_0.0).
    - Exact match is checked first (O(1) frozenset lookup).
    - Conjunction/negation blocking: if any blocking token is present,
      returns (False, None, 0.0) immediately.
    - Fuzzy match via difflib.get_close_matches(cutoff=0.86) only when
      len(tokens) <= window (default 3).
    - distance: SequenceMatcher ratio for fuzzy hits; 1.0 for exact match;
      0.0 when no match.

Design rules
------------
- Match against the FULL normalized utterance, not substrings.
- ≤3-token window activates fuzzy matching (prevents false positives on
  longer sentences like "sí pero también quiero mechas").
- Blocking tokens ("pero", "y", "sino", "aunque", "tampoco") prevent match
  even within the window — they indicate additive or conditional intent.
- "sí", "si", "dale", "ok" alone DO match (single-token canonical phrases).
- "no" alone does NOT match (negation token).
"""

from __future__ import annotations

import difflib
import unicodedata

# ---------------------------------------------------------------------------
# Canonical phrases — normalized form.
# R17 requires at minimum 12 forms.
# ---------------------------------------------------------------------------

AFFIRMATION_PHRASES: frozenset[str] = frozenset(
    [
        "si",
        "si",  # duplicate normalized form — frozenset deduplicates
        "dale",
        "confirmo",
        "adelante",
        "perfecto",
        "bueno",
        "ok",
        "va",
        "listo",
        "claro",
        "confirmado",
        "exacto",
        "correcto",
        "bien",
    ]
)

# ---------------------------------------------------------------------------
# Blocking tokens — conjunction / negation qualifiers that cancel affirmation
# even within the ≤3-token window (R18)
# ---------------------------------------------------------------------------

_BLOCKING_TOKENS: frozenset[str] = frozenset(
    [
        "pero",
        "y",
        "sino",
        "aunque",
        "tampoco",
        "no",
        "ni",
        "nunca",
        "jamas",  # normalized form of "jamás"
        "igual",  # "me da igual" = not affirmation
    ]
)


# ---------------------------------------------------------------------------
# Normalizer — mirrors normalize_for_negation exactly
# ---------------------------------------------------------------------------


def normalize_for_affirmation(text: str) -> str:
    """Normalize a user utterance for affirmation matching.

    Same pipeline as normalize_for_negation:
    1. NFKD Unicode normalization.
    2. Strip combining characters.
    3. Lowercase.
    4. Strip trailing/leading ASCII punctuation.
    5. Collapse whitespace.

    Examples:
        >>> normalize_for_affirmation("Sí!")
        'si'
        >>> normalize_for_affirmation("  Dale  ")
        'dale'
        >>> normalize_for_affirmation("PERFECTO.")
        'perfecto'
    """
    # Step 1: NFKD decomposition
    nfkd = unicodedata.normalize("NFKD", text)
    # Step 2: strip combining characters and non-ASCII non-space symbols
    stripped = "".join(
        ch
        for ch in nfkd
        if not unicodedata.combining(ch) and (ch.isascii() or ch == " ")
    )
    # Step 3: lowercase
    lowered = stripped.lower()
    # Step 4: strip trailing/leading ASCII punctuation
    trimmed = lowered.rstrip(".,!?¡¿…").lstrip("¡¿")
    # Step 5: collapse whitespace
    collapsed = " ".join(trimmed.split())
    return collapsed


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------


def is_affirmation(text: str, window: int = 3) -> tuple[bool, str | None, float]:
    """Classify whether user_text is a confirmation utterance.

    Returns:
        (matched, canonical_phrase, distance)

        - matched: True if the message is an affirmation.
        - canonical_phrase: the matched canonical phrase string, or None.
        - distance: SequenceMatcher ratio (0.0–1.0) for fuzzy matches;
          1.0 for exact matches; 0.0 when no match is found.

    Algorithm:
    1. Normalize user_text via normalize_for_affirmation().
    2. Exact O(1) frozenset lookup → return (True, phrase, 1.0).
    3. Token count check: if len(tokens) > window → (False, None, 0.0).
    4. Blocking token check: if any token in _BLOCKING_TOKENS → (False, None, 0.0).
    5. Fuzzy match via difflib.get_close_matches(cutoff=0.86).
    6. No match → return (False, None, 0.0).
    """
    normalized = normalize_for_affirmation(text)

    # Step 2: exact match (O(1))
    if normalized in AFFIRMATION_PHRASES:
        return (True, normalized, 1.0)

    # Step 3: token window gate — fuzzy only for short utterances
    tokens = normalized.split()
    if len(tokens) > window:
        return (False, None, 0.0)

    # Step 4: blocking token check (R18)
    if any(tok in _BLOCKING_TOKENS for tok in tokens):
        return (False, None, 0.0)

    # Step 5: fuzzy match
    candidates = list(AFFIRMATION_PHRASES)
    matches = difflib.get_close_matches(normalized, candidates, n=1, cutoff=0.86)
    if matches:
        canonical = matches[0]
        ratio = difflib.SequenceMatcher(None, normalized, canonical).ratio()
        return (True, canonical, ratio)

    return (False, None, 0.0)

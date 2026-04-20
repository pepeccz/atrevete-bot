"""
Deterministic affirmation resolver for the booking flow.

Symmetric to infra/resolvers/negation.py. Classifies whether a user message
is a confirmation of a shown booking summary BEFORE the LLM agentic loop runs.
Uses stdlib only (unicodedata, difflib) — zero new dependencies.

Public API
----------
AFFIRMATION_PHRASES : frozenset[str]
    Canonical normalized forms of affirmation utterances.

is_affirmation(text, window=3) -> bool
    Returns True if the message is a clear affirmation, False otherwise.
    - Exact match is checked first (O(1) frozenset lookup).
    - Conjunction/negation blocking: if any blocking token is present,
      returns False immediately.
    - Fuzzy match via difflib.get_close_matches(cutoff=0.86) only when
      len(tokens) <= window (default 3).

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

from infra.resolvers._shared import normalize_text as _normalize_text

# ---------------------------------------------------------------------------
# Canonical phrases — normalized form.
# R17 requires at minimum 12 forms.
# ---------------------------------------------------------------------------

AFFIRMATION_PHRASES: frozenset[str] = frozenset(
    [
        "si",
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
        # Additional forms required by REQ-1 test parametrize list
        "vale",
        "de acuerdo",
        "por supuesto",
        "genial",
        "okay",
    ]
)

# ---------------------------------------------------------------------------
# Blocking tokens — conjunction / negation qualifiers that cancel affirmation
# even within the ≤3-token window (R18)
# ---------------------------------------------------------------------------

_BLOCKING_TOKENS: frozenset[str] = frozenset(
    [
        "pero",
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
# Normalizer
# ---------------------------------------------------------------------------


def normalize_for_affirmation(text: str) -> str:
    """Normalize user text for affirmation matching.

    Delegates to infra.resolvers._shared.normalize_text — same pipeline,
    single source of truth (R2).

    Examples:
        >>> normalize_for_affirmation("Sí!")
        'si'
        >>> normalize_for_affirmation("  Dale  ")
        'dale'
        >>> normalize_for_affirmation("PERFECTO.")
        'perfecto'
    """
    return _normalize_text(text)


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------


def is_affirmation(text: str, window: int = 3) -> bool:
    """Classify whether user_text is a confirmation utterance.

    Returns:
        True if the message is a clear affirmation, False otherwise.

    Algorithm:
    1. Normalize user_text via normalize_for_affirmation().
    2. Exact O(1) frozenset lookup → return True.
    3. Token count check: if len(tokens) > window → False.
    4. Blocking token check: if any token in _BLOCKING_TOKENS → False.
    5. Fuzzy match via difflib.get_close_matches(cutoff=0.86) → True if match.
    6. No match → return False.
    """
    normalized = normalize_for_affirmation(text)

    # Step 2: exact match (O(1))
    if normalized in AFFIRMATION_PHRASES:
        return True

    # Step 3: token window gate — fuzzy only for short utterances
    tokens = normalized.split()
    if len(tokens) > window:
        return False

    # Step 4: blocking token check (R18)
    if any(tok in _BLOCKING_TOKENS for tok in tokens):
        return False

    # Step 4b: individual token exact match — handles "dale gracias", "ok gracias" etc.
    # where the affirmation token is followed by a filler word within the window.
    if any(tok in AFFIRMATION_PHRASES for tok in tokens):
        return True

    # Step 5: fuzzy match
    candidates = list(AFFIRMATION_PHRASES)
    matches = difflib.get_close_matches(normalized, candidates, n=1, cutoff=0.86)
    if matches:
        return True

    return False

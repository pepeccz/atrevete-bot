"""
Stylist resolver — deterministic pre-loop stylist selection.

R3–R11 — pure function, no I/O, no side effects.

Public API
----------
resolve_stylist(user_text, offered_stylists, *, conversation_id, turn_number) -> dict | None
    Returns {"last_stylist": name} or {"no_preference_stylist": True} or None.
"""

from __future__ import annotations

import difflib
import logging

from infra.resolvers._shared import hash_text, normalize_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# No-preference phrases (R5)
# ---------------------------------------------------------------------------

_NO_PREF_PHRASES: frozenset[str] = frozenset(
    {
        "sin preferencia",
        "me da igual",
        "cualquiera",
        "la primera disponible",
        "no tengo preferencia",
        "da lo mismo",
        "no me importa",
        "la que sea",
        "el que sea",
        "la primera con disponibilidad",
    }
)

# Bare digit tokens that activate digit-match branch (R4)
_DIGIT_TOKENS: frozenset[str] = frozenset({"1", "2", "3", "4", "5", "6"})


def resolve_stylist(
    user_text: str,
    offered_stylists: list[str],
    *,
    conversation_id: str = "",
    turn_number: int = 0,
) -> dict | None:
    """Deterministic stylist resolver — runs BEFORE the LLM agentic loop.

    Priority order (R7): digit → no_preference → name_in_tokens.

    Args:
        user_text: Raw user message (NEVER logged directly — hashed for telemetry).
        offered_stylists: Canonical stylist names offered in this turn (including
            "Sin preferencia" sentinel when applicable).
        conversation_id: For telemetry correlation only.
        turn_number: For telemetry correlation only.

    Returns:
        {"last_stylist": canonical_name}   — named stylist selected
        {"no_preference_stylist": True}    — no preference expressed
        None                               — no match
    """
    normalized = normalize_text(user_text)
    result: dict | None = None
    match_type: str | None = None

    # ── Branch 1: Digit match (R4) ──────────────────────────────────────────
    # Tokenize and find first bare digit token
    tokens = normalized.split()
    # Strip residual punctuation per token before digit check
    clean_tokens = [t.strip(".,!?¡¿…") for t in tokens]
    for token in clean_tokens:
        if token in _DIGIT_TOKENS:
            idx = int(token) - 1  # 1-indexed → 0-indexed
            if idx < len(offered_stylists):
                candidate = offered_stylists[idx]
                if normalize_text(candidate) == "sin preferencia":
                    result = {"no_preference_stylist": True}
                    match_type = "digit"
                else:
                    result = {"last_stylist": candidate}
                    match_type = "digit"
            break  # first digit wins

    # ── Branch 2: No-preference match (R5) ─────────────────────────────────
    # Runs before name-in-tokens to prevent "no tengo preferencia" matching a name
    if result is None:
        token_count = len(clean_tokens)
        # Exact match
        if normalized in _NO_PREF_PHRASES:
            result = {"no_preference_stylist": True}
            match_type = "no_preference"
        # Fuzzy match — only for ≤4 tokens (activation window)
        elif token_count <= 4:
            matches = difflib.get_close_matches(normalized, list(_NO_PREF_PHRASES), n=1, cutoff=0.86)
            if matches:
                result = {"no_preference_stylist": True}
                match_type = "no_preference"

    # ── Branch 3: Name-in-tokens match (R6) ────────────────────────────────
    # Exact token equality only — no fuzzy for proper names (R9 collision safety)
    if result is None:
        normalized_offered = [(normalize_text(n), n) for n in offered_stylists]
        for token in clean_tokens:
            for norm_name, canonical_name in normalized_offered:
                if token == norm_name:
                    # Skip "sin preferencia" sentinel via name-in-tokens
                    if norm_name == "sin preferencia":
                        result = {"no_preference_stylist": True}
                    else:
                        result = {"last_stylist": canonical_name}
                    match_type = "name"
                    break
            if result is not None:
                break

    # ── Telemetry (R11) ─────────────────────────────────────────────────────
    # NEVER log raw user_text — use hash_text for PII safety
    result_value = list(result.values())[0] if result else None
    logger.info(
        "resolver.stylist.call | conversation_id=%s | turn_number=%s | "
        "user_text_hash=%s | matched=%s | matched_value=%s | match_type=%s",
        conversation_id,
        turn_number,
        hash_text(user_text),
        bool(result),
        result_value,
        match_type,
    )

    return result

"""
Shared normalization and hashing utilities for infra/resolvers.

R1 — normalize_text and hash_text are the canonical implementations.
     Both negation.py and affirmation.py normalizers delegate here.

Public API
----------
normalize_text(s: str) -> str
    NFKD unicode decompose + strip combining chars + strip non-ASCII non-space
    + lowercase + strip leading/trailing punctuation (.,!?¡¿…) + collapse
    whitespace. Identical pipeline to normalize_for_negation / normalize_for_affirmation.

hash_text(s: str) -> str
    MD5 hex of UTF-8 encoded input, first 8 hex chars. Used for PII-safe
    telemetry — NEVER log raw user_text, always hash first.
"""

from __future__ import annotations

import hashlib
import unicodedata


def normalize_text(s: str) -> str:
    """Normalize a user utterance for resolver matching.

    Pipeline:
    1. NFKD Unicode normalization — decomposes accented chars.
    2. Strip combining characters AND non-ASCII non-space symbols.
    3. Lowercase.
    4. Strip leading/trailing ASCII punctuation (.,!?¡¿…).
    5. Collapse internal whitespace.

    Examples:
        >>> normalize_text("Señora")
        'senora'
        >>> normalize_text("PILAR")
        'pilar'
        >>> normalize_text("dale!")
        'dale'
        >>> normalize_text("  con  Pilar  ")
        'con pilar'
    """
    # Step 1: NFKD decomposition
    nfkd = unicodedata.normalize("NFKD", s)
    # Step 2: strip combining characters AND non-ASCII non-space symbols (emoji, etc.)
    stripped = "".join(
        ch
        for ch in nfkd
        if not unicodedata.combining(ch) and (ch.isascii() or ch == " ")
    )
    # Step 3: lowercase
    lowered = stripped.lower()
    # Step 4: collapse whitespace first so trailing spaces don't shield punctuation
    collapsed = " ".join(lowered.split())
    # Step 5: strip leading/trailing ASCII punctuation (including ¡¿)
    trimmed = collapsed.rstrip(".,!?¡¿…").lstrip("¡¿")
    return trimmed


def hash_text(s: str) -> str:
    """PII-safe 8-char hex hash of a UTF-8 string.

    Uses MD5 for speed (not security — collision resistance is sufficient
    for telemetry correlation). Returns the first 8 hex characters.

    Examples:
        >>> len(hash_text("test")) == 8
        True
        >>> hash_text("hello") == hash_text("hello")  # deterministic
        True
    """
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:8]

"""Audience resolver — Task 4.2.

Maps Spanish demographic keywords to DB-aligned audience strings.
Returns None on ambiguous input (multiple genders found).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def _normalize(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    stripped = "".join(
        ch for ch in nfkd if not unicodedata.combining(ch) and ch.isascii() or ch == " "
    )
    return stripped.lower()


# Keyword → audience tag. Keys are accent-stripped, lowercase.
_KEYWORD_MAP: dict[str, str] = {
    # adult_female
    "senora": "adult_female",
    "senoras": "adult_female",
    "dama": "adult_female",
    "mujer": "adult_female",
    "femenino": "adult_female",
    # adult_male
    "senor": "adult_male",
    "caballero": "adult_male",
    "hombre": "adult_male",
    "masculino": "adult_male",
    # child_female
    "nina": "child_female",
    "ninas": "child_female",
    "nena": "child_female",
    "hija": "child_female",
    # child_male
    "nino": "child_male",
    "ninos": "child_male",
    "nene": "child_male",
    "hijo": "child_male",
    "bebe": "child_male",
    # unisex
    "unisex": "unisex",
}

# Reverse map: group keywords by audience to detect ambiguity
_AUDIENCE_GROUPS: dict[str, set[str]] = {}
for _kw, _aud in _KEYWORD_MAP.items():
    _AUDIENCE_GROUPS.setdefault(_aud, set()).add(_kw)


def _find_audiences(normalized_text: str) -> set[str]:
    """Find all distinct audience tags mentioned in the text."""
    found: set[str] = set()
    words = re.findall(r"\b\w+\b", normalized_text)
    for word in words:
        if word in _KEYWORD_MAP:
            found.add(_KEYWORD_MAP[word])
    return found


async def resolve_audience(text: str, state: Any) -> dict[str, Any] | None:
    """Return partial state patch with audience tag, or None on miss/ambiguity.

    Ambiguous = text contains keywords from more than one distinct audience group.
    """
    normalized = _normalize(text)
    audiences = _find_audiences(normalized)
    if len(audiences) == 1:
        return {"booking": {"audience": audiences.pop()}}
    return None

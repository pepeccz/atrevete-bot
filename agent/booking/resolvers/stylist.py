"""Stylist resolver — Task 4.8.

Matches a stylist first name from text against the active stylist roster.
Supports "con {name}", "prefiero a {name}", "que sea {name}", or bare first name
(< 3 words).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def _normalize(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    stripped = "".join(
        ch for ch in nfkd if not unicodedata.combining(ch) and (ch.isascii() or ch == " ")
    )
    return stripped.lower().strip()


# No-preference phrases
_NO_PREFERENCE = frozenset(
    [
        "no preferencia",
        "cualquiera",
        "me da igual",
        "sin preferencia",
        "no tengo preferencia",
        "indiferente",
    ]
)


async def _load_active_stylists() -> list[dict]:
    """Load active stylists from DB. Returns list of {id, name} dicts."""
    from sqlalchemy import select

    from database.connection import get_async_session
    from database.models import Stylist

    async with get_async_session() as session:
        result = await session.execute(
            select(Stylist.id, Stylist.name).where(Stylist.is_active == True)  # noqa: E712
        )
        return [{"id": row[0], "name": row[1]} for row in result.all()]


async def resolve_stylist(text: str, state: Any) -> dict[str, Any] | None:
    """Return patch with stylist_id on exact first-name match, or no_preference signal."""
    normalized = _normalize(text)

    # Check no-preference phrases
    if normalized in _NO_PREFERENCE:
        return {"booking": {"stylist_id": None, "no_preference": True}}

    stylists = await _load_active_stylists()

    # Extract candidate name from patterns
    candidate: str | None = None

    # "con {name}", "prefiero a {name}", "que sea {name}"
    m = re.search(
        r"(?:con|prefiero a|que sea)\s+([A-Za-záéíóúñüÁÉÍÓÚÑÜ]+)",
        text,
        re.IGNORECASE,
    )
    if m:
        candidate = m.group(1)
    elif len(text.split()) < 3:
        # Short bare input — treat the whole thing as a potential name
        candidate = text.strip()

    if candidate is None:
        return None

    candidate_norm = _normalize(candidate)

    for stylist in stylists:
        stylist_norm = _normalize(stylist["name"])
        if stylist_norm == candidate_norm:
            return {"booking": {"stylist_id": stylist["id"]}}

    return None

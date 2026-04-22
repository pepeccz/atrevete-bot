"""Name resolver — Task 4.7.

Extracts (first_name, first_surname) from "me llamo X Y" style phrases.
Returns None when only one name token is given (surname required per decision #2887).
"""

from __future__ import annotations

import re
from typing import Any

# Pattern: intro phrase + at least two capitalized tokens
_NAME_RE = re.compile(
    r"(?:me llamo|soy|(?:me pongo\s+)?de parte de)\s+"
    r"([A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+)"
    r"\s+"
    r"([A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+)"
    r"(?:\s+[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+)*",
    re.IGNORECASE | re.UNICODE,
)


async def resolve_name(text: str, state: Any) -> dict[str, Any] | None:
    """Extract customer full name (first + first surname) from text.

    Three-token names ("me llamo Pepe García López") → "Pepe García"
    (second surname ignored per decision #2887).
    Single-token names → None (surname required).
    """
    match = _NAME_RE.search(text)
    if not match:
        return None

    first_name = match.group(1)
    first_surname = match.group(2)
    full_name = f"{first_name} {first_surname}"

    return {"booking": {"customer_full_name": full_name}}

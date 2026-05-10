"""Locale constants for Atrévete Bot (Spanish/Madrid).

Centralizes locale-specific string mappings to avoid hardcoding across modules.
"""

from __future__ import annotations

# Spanish weekday names indexed by date.weekday() (0=Monday ... 6=Sunday).
# Used by gap_explanation_hint in availability_service and any other consumer
# that needs locale-aware weekday formatting without introducing babel dependency.
SPANISH_WEEKDAYS: list[str] = [
    "lunes",  # 0 — Monday
    "martes",  # 1 — Tuesday
    "miércoles",  # 2 — Wednesday
    "jueves",  # 3 — Thursday
    "viernes",  # 4 — Friday
    "sábado",  # 5 — Saturday
    "domingo",  # 6 — Sunday
]

"""
Shared Spanish date formatting utility.

Provides format_date_spanish() for consistent "weekday DD de month" labels
(no year) across agent tools and middleware.

Importable from both agent/ and shared/ without violating the layer-import gate.
"""

from datetime import date, datetime

_WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MONTHS_ES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


def format_date_spanish(dt: date | datetime) -> str:
    """Return a Spanish natural date label: 'jueves 23 de abril' (no year).

    Accepts both date and datetime objects. When a timezone-aware datetime is
    passed, the weekday is taken from the wall-clock date as-is — the caller
    is responsible for converting to the desired timezone beforehand.
    """
    return f"{_WEEKDAYS_ES[dt.weekday()]} {dt.day} de {_MONTHS_ES[dt.month - 1]}"

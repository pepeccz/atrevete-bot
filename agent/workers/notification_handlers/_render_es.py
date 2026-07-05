"""Shared Spanish/Madrid-local date-time rendering for notification-handler templates.

Centralizes the Europe/Madrid timezone and Spanish day/month name tables so all 3
notification handlers (confirm_48h, reminder_24h, final_warning) render
customer-facing dates identically — e.g. "miércoles 8 de julio" — instead of each
handler duplicating (or, in final_warning's pre-fix case, omitting entirely) the
Madrid-local conversion.

Design: sdd/context-coherence FIX 2 (judgment-day, both judges — MAJOR).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

# Salon-local timezone for customer-facing date/time rendering.
MADRID_TZ = ZoneInfo("Europe/Madrid")

# Spanish day/month names (avoid relying on system locale being installed).
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = [
    "",
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


def to_madrid(dt: datetime | None) -> datetime | None:
    """Convert an aware datetime (typically UTC) to Europe/Madrid local time.

    Returns None when ``dt`` is None, so callers can chain this on optional
    ``appt.start_time`` fields without a separate guard.
    """
    return dt.astimezone(MADRID_TZ) if dt is not None else None


def fecha_es(dt: datetime) -> str:
    """Render a Madrid-local datetime as e.g. 'miércoles 8 de julio'.

    ``dt`` must already be Madrid-local (see ``to_madrid``) — this function only
    reads ``weekday()``/``day``/``month``, it does not convert timezones.
    """
    return f"{DIAS[dt.weekday()]} {dt.day} de {MESES[dt.month]}"


def hora_es(dt: datetime) -> str:
    """Render a Madrid-local datetime's time of day as 'HH:MM'."""
    return dt.strftime("%H:%M")

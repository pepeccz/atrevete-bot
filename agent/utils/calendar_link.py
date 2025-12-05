"""
Google Calendar Link Generator.

Generates public "Add to Google Calendar" URLs that allow customers
to add their appointment to their own Google Calendar with one click.
"""

from datetime import datetime
from urllib.parse import quote


def generate_google_calendar_link(
    title: str,
    start_time: datetime,
    end_time: datetime,
    description: str,
    location: str,
) -> str:
    """
    Generate a Google Calendar "Add Event" URL.

    This creates a public URL that, when clicked, opens Google Calendar
    with a pre-filled event. Works on both mobile (opens app) and web.

    Args:
        title: Event title (e.g., "Cita en Peluquería Atrévete")
        start_time: Event start datetime
        end_time: Event end datetime
        description: Event description (e.g., "Servicios: Corte\nEstilista: Ana")
        location: Event location address

    Returns:
        Full Google Calendar URL ready to share

    Example:
        >>> link = generate_google_calendar_link(
        ...     title="Cita en Peluquería Atrévete",
        ...     start_time=datetime(2025, 12, 9, 10, 0),
        ...     end_time=datetime(2025, 12, 9, 10, 30),
        ...     description="Servicios: Corte de Caballero\nEstilista: Ana",
        ...     location="Calle de la Constitución, 5, 28100 Alcobendas, Madrid",
        ... )
        >>> "calendar.google.com" in link
        True
    """
    base_url = "https://calendar.google.com/calendar/render"

    # Format dates as YYYYMMDDTHHmmss (Google Calendar format)
    date_format = "%Y%m%dT%H%M%S"
    dates = f"{start_time.strftime(date_format)}/{end_time.strftime(date_format)}"

    # Build URL parameters
    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": dates,
        "details": description,
        "location": location,
    }

    # URL-encode and join parameters
    query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    return f"{base_url}?{query}"

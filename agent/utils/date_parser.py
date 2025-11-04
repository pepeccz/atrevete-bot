"""
Natural Date Parser for Spanish Language.

Parses natural language date expressions in Spanish to datetime objects.
Used by check_availability() and book() tools to handle flexible date inputs
like "mañana", "viernes", "8 de noviembre", etc.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Default timezone for all date operations
MADRID_TZ = ZoneInfo("Europe/Madrid")


def parse_natural_date(
    date_str: str,
    timezone: ZoneInfo = MADRID_TZ,
    reference_date: datetime | None = None
) -> datetime:
    """
    Parse natural language date expressions in Spanish to datetime.

    This function handles various date formats that customers might use when
    requesting appointments:
    - ISO 8601: "2025-11-08"
    - Relative: "mañana", "pasado mañana", "hoy"
    - Weekdays: "lunes", "martes", "miércoles", ..., "domingo"
    - Written dates: "8 de noviembre", "15 de diciembre de 2025"
    - Abbreviations: "vie", "sáb", "dom"

    Args:
        date_str: Date expression in natural language or ISO format
        timezone: Timezone for the result (default: Europe/Madrid)
        reference_date: Reference date for relative calculations (default: now in timezone)

    Returns:
        datetime: Parsed date at 00:00 in specified timezone

    Raises:
        ValueError: If the date format cannot be parsed

    Examples:
        Assuming today = 2025-11-04 (Tuesday):

        >>> parse_natural_date("mañana")
        datetime(2025, 11, 5, 0, 0, tzinfo=ZoneInfo('Europe/Madrid'))

        >>> parse_natural_date("viernes")
        datetime(2025, 11, 8, 0, 0, tzinfo=ZoneInfo('Europe/Madrid'))

        >>> parse_natural_date("lunes")  # Monday already passed this week
        datetime(2025, 11, 11, 0, 0, tzinfo=ZoneInfo('Europe/Madrid'))

        >>> parse_natural_date("8 de noviembre")
        datetime(2025, 11, 8, 0, 0, tzinfo=ZoneInfo('Europe/Madrid'))

        >>> parse_natural_date("2025-11-15")
        datetime(2025, 11, 15, 0, 0, tzinfo=ZoneInfo('Europe/Madrid'))

    Rules:
        - For weekdays without specific date:
          - If the weekday already passed this week → next week
          - If the weekday hasn't arrived yet this week → this week
        - All dates are returned at 00:00 (midnight) in the specified timezone
        - Relative dates ("mañana", "hoy") are calculated from reference_date

    Implementation Notes:
        - Uses dateparser library for complex formats
        - Custom logic for Spanish weekday handling
        - Validates that parsed date is not in the past
    """
    # Implementation to be completed in Phase 1, Day 2
    raise NotImplementedError(
        "parse_natural_date() will be implemented in Phase 1, Day 2"
    )


def get_weekday_name(date: datetime, locale: str = "es_ES") -> str:
    """
    Get the Spanish weekday name for a given date.

    Args:
        date: Date to get weekday name for
        locale: Locale for weekday name (default: es_ES)

    Returns:
        str: Lowercase Spanish weekday name (e.g., "lunes", "viernes")

    Example:
        >>> date = datetime(2025, 11, 8)  # Friday
        >>> get_weekday_name(date)
        'viernes'
    """
    # Implementation to be completed in Phase 1, Day 2
    raise NotImplementedError(
        "get_weekday_name() will be implemented in Phase 1, Day 2"
    )


def format_date_spanish(date: datetime) -> str:
    """
    Format a datetime to Spanish readable format.

    Args:
        date: Date to format

    Returns:
        str: Formatted date string in Spanish (e.g., "viernes 8 de noviembre")

    Example:
        >>> date = datetime(2025, 11, 8)
        >>> format_date_spanish(date)
        'viernes 8 de noviembre'
    """
    # Implementation to be completed in Phase 1, Day 2
    raise NotImplementedError(
        "format_date_spanish() will be implemented in Phase 1, Day 2"
    )


# Spanish weekday mappings for parsing
SPANISH_WEEKDAYS = {
    "lunes": 0,
    "martes": 1,
    "miércoles": 2,
    "miercoles": 2,  # Without accent
    "jueves": 3,
    "viernes": 4,
    "sábado": 5,
    "sabado": 5,  # Without accent
    "domingo": 6,
    # Abbreviations
    "lun": 0,
    "mar": 1,
    "mié": 2,
    "mie": 2,
    "jue": 3,
    "vie": 4,
    "sáb": 5,
    "sab": 5,
    "dom": 6,
}

# Spanish month mappings for parsing written dates
SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

# Relative date expressions
RELATIVE_DATES = {
    "hoy": 0,
    "mañana": 1,
    "pasado mañana": 2,
    "pasado manana": 2,  # Without tilde
}

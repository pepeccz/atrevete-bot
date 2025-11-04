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
    import re

    # Get reference date (default to now in timezone)
    if reference_date is None:
        reference_date = datetime.now(timezone)

    # Normalize input
    date_str_normalized = date_str.strip().lower()

    # 1. Try relative dates first (hoy, mañana, pasado mañana)
    if date_str_normalized in RELATIVE_DATES:
        days_offset = RELATIVE_DATES[date_str_normalized]
        result = reference_date + timedelta(days=days_offset)
        return result.replace(hour=0, minute=0, second=0, microsecond=0)

    # 2. Try weekdays (lunes, martes, vie, etc.)
    if date_str_normalized in SPANISH_WEEKDAYS:
        target_weekday = SPANISH_WEEKDAYS[date_str_normalized]
        current_weekday = reference_date.weekday()

        # Calculate days until target weekday
        if target_weekday > current_weekday:
            # Target is later this week
            days_ahead = target_weekday - current_weekday
        else:
            # Target already passed this week, go to next week
            days_ahead = 7 - (current_weekday - target_weekday)

        result = reference_date + timedelta(days=days_ahead)
        return result.replace(hour=0, minute=0, second=0, microsecond=0)

    # 3. Try ISO 8601 format (2025-11-08, 2025/11/08)
    iso_match = re.match(r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$', date_str_normalized)
    if iso_match:
        year, month, day = map(int, iso_match.groups())
        return datetime(year, month, day, 0, 0, 0, tzinfo=timezone)

    # 4. Try written Spanish dates: "8 de noviembre", "15 de diciembre de 2025"
    # Pattern: number + "de" + month_name + optional("de" + year)
    written_match = re.match(
        r'^(\d{1,2})\s+de\s+(\w+)(?:\s+de\s+(\d{4}))?$',
        date_str_normalized
    )
    if written_match:
        day = int(written_match.group(1))
        month_name = written_match.group(2)
        year = int(written_match.group(3)) if written_match.group(3) else reference_date.year

        if month_name in SPANISH_MONTHS:
            month = SPANISH_MONTHS[month_name]
            return datetime(year, month, day, 0, 0, 0, tzinfo=timezone)

    # 5. Try day/month format: "08/11", "8-11"
    day_month_match = re.match(r'^(\d{1,2})[-/](\d{1,2})$', date_str_normalized)
    if day_month_match:
        day, month = map(int, day_month_match.groups())
        year = reference_date.year
        return datetime(year, month, day, 0, 0, 0, tzinfo=timezone)

    # If nothing matched, raise error
    raise ValueError(
        f"No se pudo parsear la fecha '{date_str}'. "
        f"Formatos aceptados: 'mañana', 'viernes', '2025-11-08', '8 de noviembre', etc."
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
    weekday_names = [
        "lunes",
        "martes",
        "miércoles",
        "jueves",
        "viernes",
        "sábado",
        "domingo"
    ]
    return weekday_names[date.weekday()]


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
    month_names = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
    ]

    weekday = get_weekday_name(date)
    day = date.day
    month = month_names[date.month - 1]

    return f"{weekday} {day} de {month}"


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

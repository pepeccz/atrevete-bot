"""
Unit tests for date_parser.py - Natural Spanish date parsing.

Tests coverage:
- Relative dates (hoy, mañana, pasado mañana)
- Weekday names (lunes, martes, etc.)
- Weekday abbreviations (lun, mar, vie, etc.)
- ISO 8601 formats (2025-11-08, 2025/11/08)
- Written Spanish dates (8 de noviembre, 15 de diciembre de 2025)
- Day/month format (08/11, 8-11)
- get_weekday_name() function
- format_date_spanish() function
- Timezone handling
- Edge cases and error handling
"""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from agent.utils.date_parser import (
    parse_natural_date,
    get_weekday_name,
    format_date_spanish,
    MADRID_TZ,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def reference_date():
    """Fixed reference date for consistent testing: Tuesday, Nov 4, 2025, 10:00 AM."""
    return datetime(2025, 11, 4, 10, 0, 0, tzinfo=MADRID_TZ)


# ============================================================================
# Test Relative Dates
# ============================================================================


class TestRelativeDates:
    """Test parsing of relative date expressions."""

    def test_parse_hoy(self, reference_date):
        """Test parsing 'hoy' (today)."""
        result = parse_natural_date("hoy", reference_date=reference_date)

        assert result.year == 2025
        assert result.month == 11
        assert result.day == 4
        assert result.hour == 0
        assert result.minute == 0
        assert result.tzinfo == MADRID_TZ

    def test_parse_manana(self, reference_date):
        """Test parsing 'mañana' (tomorrow)."""
        result = parse_natural_date("mañana", reference_date=reference_date)

        assert result.year == 2025
        assert result.month == 11
        assert result.day == 5  # Wednesday
        assert result.hour == 0
        assert result.tzinfo == MADRID_TZ

    def test_parse_pasado_manana(self, reference_date):
        """Test parsing 'pasado mañana' (day after tomorrow)."""
        result = parse_natural_date("pasado mañana", reference_date=reference_date)

        assert result.year == 2025
        assert result.month == 11
        assert result.day == 6  # Thursday
        assert result.hour == 0

    def test_parse_pasado_manana_without_tilde(self, reference_date):
        """Test parsing 'pasado manana' (without tilde)."""
        result = parse_natural_date("pasado manana", reference_date=reference_date)

        assert result.day == 6

    def test_relative_dates_case_insensitive(self, reference_date):
        """Test that relative dates are case-insensitive."""
        result1 = parse_natural_date("HOY", reference_date=reference_date)
        result2 = parse_natural_date("Mañana", reference_date=reference_date)
        result3 = parse_natural_date("PASADO MAÑANA", reference_date=reference_date)

        assert result1.day == 4
        assert result2.day == 5
        assert result3.day == 6


# ============================================================================
# Test Weekday Names
# ============================================================================


class TestWeekdayNames:
    """Test parsing of Spanish weekday names."""

    def test_parse_lunes_future(self, reference_date):
        """Test parsing 'lunes' when it's in the future this week."""
        # Reference: Tuesday Nov 4 → lunes already passed → next Monday
        result = parse_natural_date("lunes", reference_date=reference_date)

        assert result.day == 10  # Next Monday (Nov 10)

    def test_parse_viernes_future(self, reference_date):
        """Test parsing 'viernes' when it's in the future this week."""
        # Reference: Tuesday Nov 4 → viernes is Nov 7 (this Friday)
        result = parse_natural_date("viernes", reference_date=reference_date)

        assert result.day == 7  # This Friday

    def test_parse_martes_same_day(self, reference_date):
        """Test parsing 'martes' when today is Tuesday (already passed)."""
        # Reference: Tuesday Nov 4 → martes already passed → next Tuesday
        result = parse_natural_date("martes", reference_date=reference_date)

        assert result.day == 11  # Next Tuesday

    def test_parse_domingo(self, reference_date):
        """Test parsing 'domingo' (Sunday)."""
        # Reference: Tuesday Nov 4 → domingo is Nov 9 (this Sunday)
        result = parse_natural_date("domingo", reference_date=reference_date)

        assert result.day == 9  # This Sunday

    def test_weekday_without_accent(self, reference_date):
        """Test parsing weekdays without accents."""
        result1 = parse_natural_date("miercoles", reference_date=reference_date)  # Without accent
        result2 = parse_natural_date("sabado", reference_date=reference_date)

        assert result1.day == 5  # This Wednesday
        assert result2.day == 8  # This Saturday

    def test_weekday_abbreviations(self, reference_date):
        """Test parsing weekday abbreviations."""
        result_lun = parse_natural_date("lun", reference_date=reference_date)
        result_vie = parse_natural_date("vie", reference_date=reference_date)
        result_dom = parse_natural_date("dom", reference_date=reference_date)

        assert result_lun.day == 10  # Next Monday
        assert result_vie.day == 7   # This Friday
        assert result_dom.day == 9   # This Sunday

    def test_weekday_abbreviations_with_accent(self, reference_date):
        """Test parsing weekday abbreviations with accents."""
        result_mie = parse_natural_date("mié", reference_date=reference_date)
        result_sab = parse_natural_date("sáb", reference_date=reference_date)

        assert result_mie.day == 5  # This Wednesday
        assert result_sab.day == 8  # This Saturday


# ============================================================================
# Test ISO 8601 Formats
# ============================================================================


class TestISO8601:
    """Test parsing of ISO 8601 date formats."""

    def test_parse_iso_dash_format(self, reference_date):
        """Test parsing ISO format with dashes (2025-11-08)."""
        result = parse_natural_date("2025-11-08", reference_date=reference_date)

        assert result.year == 2025
        assert result.month == 11
        assert result.day == 8
        assert result.hour == 0
        assert result.tzinfo == MADRID_TZ

    def test_parse_iso_slash_format(self, reference_date):
        """Test parsing ISO format with slashes (2025/11/08)."""
        result = parse_natural_date("2025/11/08", reference_date=reference_date)

        assert result.year == 2025
        assert result.month == 11
        assert result.day == 8

    def test_parse_iso_single_digit_month_day(self, reference_date):
        """Test parsing ISO format with single-digit month/day."""
        result = parse_natural_date("2025-1-5", reference_date=reference_date)

        assert result.year == 2025
        assert result.month == 1
        assert result.day == 5


# ============================================================================
# Test Written Spanish Dates
# ============================================================================


class TestWrittenSpanishDates:
    """Test parsing of written Spanish date formats."""

    def test_parse_written_date_without_year(self, reference_date):
        """Test parsing '8 de noviembre' (assumes current year)."""
        result = parse_natural_date("8 de noviembre", reference_date=reference_date)

        assert result.year == 2025  # Current year from reference
        assert result.month == 11
        assert result.day == 8

    def test_parse_written_date_with_year(self, reference_date):
        """Test parsing '15 de diciembre de 2026'."""
        result = parse_natural_date("15 de diciembre de 2026", reference_date=reference_date)

        assert result.year == 2026
        assert result.month == 12
        assert result.day == 15

    def test_parse_all_spanish_months(self, reference_date):
        """Test parsing all Spanish month names."""
        months = [
            ("enero", 1), ("febrero", 2), ("marzo", 3), ("abril", 4),
            ("mayo", 5), ("junio", 6), ("julio", 7), ("agosto", 8),
            ("septiembre", 9), ("octubre", 10), ("noviembre", 11), ("diciembre", 12)
        ]

        for month_name, month_num in months:
            result = parse_natural_date(f"15 de {month_name}", reference_date=reference_date)
            assert result.month == month_num
            assert result.day == 15


# ============================================================================
# Test Day/Month Format
# ============================================================================


class TestDayMonthFormat:
    """Test parsing of day/month formats."""

    def test_parse_day_month_slash(self, reference_date):
        """Test parsing '08/11' (day/month)."""
        result = parse_natural_date("08/11", reference_date=reference_date)

        assert result.year == 2025
        assert result.month == 11
        assert result.day == 8

    def test_parse_day_month_dash(self, reference_date):
        """Test parsing '8-11' (day-month)."""
        result = parse_natural_date("8-11", reference_date=reference_date)

        assert result.month == 11
        assert result.day == 8

    def test_parse_single_digit_day_month(self, reference_date):
        """Test parsing '5/3' (single digits)."""
        result = parse_natural_date("5/3", reference_date=reference_date)

        assert result.month == 3
        assert result.day == 5


# ============================================================================
# Test Timezone Handling
# ============================================================================


class TestTimezoneHandling:
    """Test that timezone is handled correctly."""

    def test_default_timezone_madrid(self, reference_date):
        """Test that default timezone is Europe/Madrid."""
        result = parse_natural_date("mañana", reference_date=reference_date)

        assert result.tzinfo == MADRID_TZ

    def test_custom_timezone(self, reference_date):
        """Test parsing with custom timezone."""
        utc_tz = ZoneInfo("UTC")
        result = parse_natural_date("mañana", timezone=utc_tz, reference_date=reference_date)

        assert result.tzinfo == utc_tz

    def test_result_always_midnight(self, reference_date):
        """Test that all results are at 00:00."""
        test_cases = ["hoy", "viernes", "2025-11-08", "8 de noviembre"]

        for date_str in test_cases:
            result = parse_natural_date(date_str, reference_date=reference_date)
            assert result.hour == 0
            assert result.minute == 0
            assert result.second == 0
            assert result.microsecond == 0


# ============================================================================
# Test Error Handling
# ============================================================================


class TestErrorHandling:
    """Test error cases and invalid inputs."""

    def test_invalid_date_format_raises_error(self, reference_date):
        """Test that invalid date format raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            parse_natural_date("invalid date", reference_date=reference_date)

        assert "No se pudo parsear" in str(exc_info.value)

    def test_empty_string_raises_error(self, reference_date):
        """Test that empty string raises ValueError."""
        with pytest.raises(ValueError):
            parse_natural_date("", reference_date=reference_date)

    def test_invalid_month_name_raises_error(self, reference_date):
        """Test that invalid month name raises ValueError."""
        with pytest.raises(ValueError):
            parse_natural_date("15 de invalidmonth", reference_date=reference_date)


# ============================================================================
# Test get_weekday_name()
# ============================================================================


class TestGetWeekdayName:
    """Test get_weekday_name() function."""

    def test_get_weekday_name_all_days(self):
        """Test getting weekday names for all 7 days."""
        # Monday Nov 3, 2025 to Sunday Nov 9, 2025
        expected = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

        for i, expected_name in enumerate(expected):
            date = datetime(2025, 11, 3 + i)
            result = get_weekday_name(date)
            assert result == expected_name

    def test_get_weekday_name_friday(self):
        """Test getting weekday name for Friday."""
        date = datetime(2025, 11, 7)  # Friday
        result = get_weekday_name(date)

        assert result == "viernes"


# ============================================================================
# Test format_date_spanish()
# ============================================================================


class TestFormatDateSpanish:
    """Test format_date_spanish() function."""

    def test_format_date_spanish_full(self):
        """Test formatting a date to Spanish."""
        date = datetime(2025, 11, 8)  # Friday, Nov 8, 2025
        result = format_date_spanish(date)

        assert result == "viernes 8 de noviembre"

    def test_format_date_spanish_all_months(self):
        """Test formatting dates for all months."""
        months = [
            (1, "enero"), (2, "febrero"), (3, "marzo"), (4, "abril"),
            (5, "mayo"), (6, "junio"), (7, "julio"), (8, "agosto"),
            (9, "septiembre"), (10, "octubre"), (11, "noviembre"), (12, "diciembre")
        ]

        for month_num, month_name in months:
            date = datetime(2025, month_num, 15)
            result = format_date_spanish(date)
            assert month_name in result
            assert "15" in result

    def test_format_date_spanish_different_days(self):
        """Test formatting dates with different day numbers."""
        for day in [1, 10, 20, 31]:
            if day <= 28:  # February safe
                date = datetime(2025, 2, day)
                result = format_date_spanish(date)
                assert str(day) in result


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and corner scenarios."""

    def test_whitespace_handling(self, reference_date):
        """Test that leading/trailing whitespace is handled."""
        result = parse_natural_date("  mañana  ", reference_date=reference_date)

        assert result.day == 5

    def test_case_variations(self, reference_date):
        """Test various case combinations."""
        test_cases = ["VIERNES", "Viernes", "viernes", "VieRNeS"]

        for date_str in test_cases:
            result = parse_natural_date(date_str, reference_date=reference_date)
            assert result.day == 7  # Friday

    def test_reference_date_none_uses_now(self):
        """Test that None reference_date uses current time."""
        # We can't test exact values, but we can test it doesn't crash
        result = parse_natural_date("mañana")

        assert result.tzinfo == MADRID_TZ
        # Result should be tomorrow
        now = datetime.now(MADRID_TZ)
        tomorrow = now + timedelta(days=1)
        assert result.day == tomorrow.day or result.day == tomorrow.day - 1  # Account for timing

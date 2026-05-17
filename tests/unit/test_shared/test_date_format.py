"""
Tests for shared/date_format.py — format_date_spanish.

TDD RED phase: these tests reference shared.date_format which does not exist yet.
All tests must FAIL before the module is created.
"""

import re
from datetime import date, datetime

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LABEL_PATTERN = re.compile(r"^[a-záéíóú]+ \d{1,2} de [a-záéíóú]+$")

_WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


# ---------------------------------------------------------------------------
# Core format — datetime input
# ---------------------------------------------------------------------------


def test_format_date_spanish_known_datetime():
    """2026-04-23 (Thursday) → 'jueves 23 de abril'."""
    from shared.date_format import format_date_spanish

    result = format_date_spanish(datetime(2026, 4, 23, 10, 0))
    assert result == "jueves 23 de abril"


def test_format_date_spanish_no_year_in_output():
    """Label must NOT contain the year (4-digit number)."""
    from shared.date_format import format_date_spanish

    result = format_date_spanish(datetime(2026, 4, 23, 10, 0))
    assert not re.search(r"\d{4}", result), f"Year found in label: {result!r}"


def test_format_date_spanish_matches_pattern():
    """Label must match '<weekday> <day> de <month>' pattern."""
    from shared.date_format import format_date_spanish

    result = format_date_spanish(datetime(2026, 4, 23, 10, 0))
    assert LABEL_PATTERN.match(result), f"Label {result!r} does not match expected pattern"


# ---------------------------------------------------------------------------
# Accepts date (not just datetime)
# ---------------------------------------------------------------------------


def test_format_date_spanish_accepts_date_object():
    """format_date_spanish must accept a date object, not just datetime."""
    from shared.date_format import format_date_spanish

    result = format_date_spanish(date(2026, 1, 1))
    # 2026-01-01 is Thursday
    assert result == "jueves 1 de enero"


# ---------------------------------------------------------------------------
# All weekdays — triangulation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "d,expected_weekday",
    [
        (date(2026, 4, 20), "lunes"),
        (date(2026, 4, 21), "martes"),
        (date(2026, 4, 22), "miércoles"),
        (date(2026, 4, 23), "jueves"),
        (date(2026, 4, 24), "viernes"),
        (date(2026, 4, 25), "sábado"),
        (date(2026, 4, 26), "domingo"),
    ],
)
def test_format_date_spanish_all_weekdays(d: date, expected_weekday: str):
    """Each weekday index maps to the correct Spanish name."""
    from shared.date_format import format_date_spanish

    result = format_date_spanish(d)
    assert result.startswith(expected_weekday), (
        f"Date {d} should start with '{expected_weekday}', got: {result!r}"
    )


# ---------------------------------------------------------------------------
# All months — triangulation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "month_num,expected_month",
    [
        (1, "enero"),
        (2, "febrero"),
        (3, "marzo"),
        (4, "abril"),
        (5, "mayo"),
        (6, "junio"),
        (7, "julio"),
        (8, "agosto"),
        (9, "septiembre"),
        (10, "octubre"),
        (11, "noviembre"),
        (12, "diciembre"),
    ],
)
def test_format_date_spanish_all_months(month_num: int, expected_month: str):
    """Each month index maps to the correct Spanish name."""
    from shared.date_format import format_date_spanish

    # Use first day of each month (2026-01-01 is Thursday, pick consistent day)
    d = date(2026, month_num, 1)
    result = format_date_spanish(d)
    assert f"de {expected_month}" in result, (
        f"Month {month_num} should produce 'de {expected_month}', got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Day number preserved — no zero-padding
# ---------------------------------------------------------------------------


def test_format_date_spanish_single_digit_day_no_padding():
    """Day 1 should appear as '1', not '01'."""
    from shared.date_format import format_date_spanish

    result = format_date_spanish(date(2026, 5, 1))
    assert " 1 " in result, f"Expected unpadded day '1' in: {result!r}"


def test_format_date_spanish_double_digit_day():
    """Day 23 should appear as '23'."""
    from shared.date_format import format_date_spanish

    result = format_date_spanish(date(2026, 4, 23))
    assert " 23 " in result, f"Expected '23' in: {result!r}"

"""
Unit tests for recurrence_service.

Tests cover:
- expand_recurrence: weekly and monthly patterns, intervals, day constraints
- parse_byday / format_byday: RRULE BYDAY string parsing and formatting
- parse_bymonthday / format_bymonthday: RRULE BYMONTHDAY string parsing and formatting
- get_open_days_of_week: extracting open days from business hours
- validate_time_within_business_hours: time range validation
"""

from datetime import date, time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.services.recurrence_service import (
    expand_recurrence,
    format_byday,
    format_bymonthday,
    get_open_days_of_week,
    parse_byday,
    parse_bymonthday,
    validate_time_within_business_hours,
)


# ============================================================================
# expand_recurrence Tests
# ============================================================================


class TestExpandRecurrence:
    """Tests for expand_recurrence function."""

    def test_weekly_single_day(self):
        """Test weekly recurrence on a single day."""
        # Every Monday for 4 occurrences starting Jan 6, 2025 (a Monday)
        dates = expand_recurrence(
            start_date=date(2025, 1, 6),
            frequency="WEEKLY",
            interval=1,
            days_of_week=[0],  # Monday
            days_of_month=None,
            count=4,
        )

        assert len(dates) == 4
        assert dates[0] == date(2025, 1, 6)
        assert dates[1] == date(2025, 1, 13)
        assert dates[2] == date(2025, 1, 20)
        assert dates[3] == date(2025, 1, 27)

    def test_weekly_multiple_days(self):
        """Test weekly recurrence on multiple days."""
        # Every Monday and Wednesday for 6 occurrences starting Jan 6, 2025
        dates = expand_recurrence(
            start_date=date(2025, 1, 6),
            frequency="WEEKLY",
            interval=1,
            days_of_week=[0, 2],  # Monday, Wednesday
            days_of_month=None,
            count=6,
        )

        assert len(dates) == 6
        assert dates[0] == date(2025, 1, 6)   # Monday
        assert dates[1] == date(2025, 1, 8)   # Wednesday
        assert dates[2] == date(2025, 1, 13)  # Monday
        assert dates[3] == date(2025, 1, 15)  # Wednesday
        assert dates[4] == date(2025, 1, 20)  # Monday
        assert dates[5] == date(2025, 1, 22)  # Wednesday

    def test_weekly_with_interval(self):
        """Test weekly recurrence with interval > 1."""
        # Every other Friday (interval=2) for 3 occurrences starting Jan 3, 2025
        dates = expand_recurrence(
            start_date=date(2025, 1, 3),
            frequency="WEEKLY",
            interval=2,
            days_of_week=[4],  # Friday
            days_of_month=None,
            count=3,
        )

        assert len(dates) == 3
        assert dates[0] == date(2025, 1, 3)   # First Friday
        assert dates[1] == date(2025, 1, 17)  # Two weeks later
        assert dates[2] == date(2025, 1, 31)  # Two weeks later

    def test_weekly_all_workdays(self):
        """Test weekly recurrence on all workdays."""
        # Mon-Fri for 5 occurrences starting Jan 6, 2025 (Monday)
        dates = expand_recurrence(
            start_date=date(2025, 1, 6),
            frequency="WEEKLY",
            interval=1,
            days_of_week=[0, 1, 2, 3, 4],  # Mon-Fri
            days_of_month=None,
            count=5,
        )

        assert len(dates) == 5
        assert dates[0] == date(2025, 1, 6)   # Monday
        assert dates[1] == date(2025, 1, 7)   # Tuesday
        assert dates[2] == date(2025, 1, 8)   # Wednesday
        assert dates[3] == date(2025, 1, 9)   # Thursday
        assert dates[4] == date(2025, 1, 10)  # Friday

    def test_monthly_single_day(self):
        """Test monthly recurrence on a single day of month."""
        # 15th of each month for 3 months starting Jan 15, 2025
        dates = expand_recurrence(
            start_date=date(2025, 1, 15),
            frequency="MONTHLY",
            interval=1,
            days_of_week=None,
            days_of_month=[15],
            count=3,
        )

        assert len(dates) == 3
        assert dates[0] == date(2025, 1, 15)
        assert dates[1] == date(2025, 2, 15)
        assert dates[2] == date(2025, 3, 15)

    def test_monthly_multiple_days(self):
        """Test monthly recurrence on multiple days of month."""
        # 1st and 15th of each month for 4 occurrences starting Jan 1, 2025
        dates = expand_recurrence(
            start_date=date(2025, 1, 1),
            frequency="MONTHLY",
            interval=1,
            days_of_week=None,
            days_of_month=[1, 15],
            count=4,
        )

        assert len(dates) == 4
        assert dates[0] == date(2025, 1, 1)
        assert dates[1] == date(2025, 1, 15)
        assert dates[2] == date(2025, 2, 1)
        assert dates[3] == date(2025, 2, 15)

    def test_monthly_with_interval(self):
        """Test monthly recurrence with interval > 1."""
        # Every 3 months on the 1st for 3 occurrences starting Jan 1, 2025
        dates = expand_recurrence(
            start_date=date(2025, 1, 1),
            frequency="MONTHLY",
            interval=3,
            days_of_week=None,
            days_of_month=[1],
            count=3,
        )

        assert len(dates) == 3
        assert dates[0] == date(2025, 1, 1)
        assert dates[1] == date(2025, 4, 1)
        assert dates[2] == date(2025, 7, 1)

    def test_count_one(self):
        """Test with count=1 returns single date."""
        dates = expand_recurrence(
            start_date=date(2025, 1, 6),
            frequency="WEEKLY",
            interval=1,
            days_of_week=[0],
            days_of_month=None,
            count=1,
        )

        assert len(dates) == 1
        assert dates[0] == date(2025, 1, 6)

    def test_dates_are_sorted(self):
        """Test that returned dates are sorted chronologically."""
        # Multiple days should still be sorted
        dates = expand_recurrence(
            start_date=date(2025, 1, 6),
            frequency="WEEKLY",
            interval=1,
            days_of_week=[4, 0, 2],  # Friday, Monday, Wednesday (unordered)
            days_of_month=None,
            count=6,
        )

        # Verify dates are in ascending order
        for i in range(len(dates) - 1):
            assert dates[i] < dates[i + 1]


# ============================================================================
# parse_byday / format_byday Tests
# ============================================================================


class TestBydayParsing:
    """Tests for BYDAY string parsing and formatting."""

    def test_parse_single_day(self):
        """Test parsing single day."""
        assert parse_byday("MO") == [0]
        assert parse_byday("FR") == [4]
        assert parse_byday("SU") == [6]

    def test_parse_multiple_days(self):
        """Test parsing multiple days."""
        assert parse_byday("MO,WE,FR") == [0, 2, 4]
        assert parse_byday("TU,TH") == [1, 3]

    def test_parse_all_days(self):
        """Test parsing all days of week."""
        assert parse_byday("MO,TU,WE,TH,FR,SA,SU") == [0, 1, 2, 3, 4, 5, 6]

    def test_parse_with_spaces(self):
        """Test parsing with whitespace."""
        assert parse_byday("MO, WE, FR") == [0, 2, 4]

    def test_parse_lowercase(self):
        """Test parsing lowercase."""
        assert parse_byday("mo,we,fr") == [0, 2, 4]

    def test_parse_empty(self):
        """Test parsing empty/None."""
        assert parse_byday("") == []
        assert parse_byday(None) == []

    def test_format_single_day(self):
        """Test formatting single day."""
        assert format_byday([0]) == "MO"
        assert format_byday([4]) == "FR"
        assert format_byday([6]) == "SU"

    def test_format_multiple_days(self):
        """Test formatting multiple days."""
        assert format_byday([0, 2, 4]) == "MO,WE,FR"
        assert format_byday([1, 3]) == "TU,TH"

    def test_format_sorts_days(self):
        """Test that format_byday sorts days."""
        assert format_byday([4, 0, 2]) == "MO,WE,FR"

    def test_roundtrip(self):
        """Test parse -> format roundtrip."""
        original = "MO,WE,FR"
        parsed = parse_byday(original)
        formatted = format_byday(parsed)
        assert formatted == original


# ============================================================================
# parse_bymonthday / format_bymonthday Tests
# ============================================================================


class TestBymonthdayParsing:
    """Tests for BYMONTHDAY string parsing and formatting."""

    def test_parse_single_day(self):
        """Test parsing single day of month."""
        assert parse_bymonthday("1") == [1]
        assert parse_bymonthday("15") == [15]
        assert parse_bymonthday("31") == [31]

    def test_parse_multiple_days(self):
        """Test parsing multiple days of month."""
        assert parse_bymonthday("1,15,30") == [1, 15, 30]

    def test_parse_with_spaces(self):
        """Test parsing with whitespace."""
        assert parse_bymonthday("1, 15, 30") == [1, 15, 30]

    def test_parse_empty(self):
        """Test parsing empty/None."""
        assert parse_bymonthday("") == []
        assert parse_bymonthday(None) == []

    def test_format_single_day(self):
        """Test formatting single day of month."""
        assert format_bymonthday([15]) == "15"

    def test_format_multiple_days(self):
        """Test formatting multiple days of month."""
        assert format_bymonthday([1, 15, 30]) == "1,15,30"

    def test_format_sorts_days(self):
        """Test that format_bymonthday sorts days."""
        assert format_bymonthday([30, 1, 15]) == "1,15,30"

    def test_roundtrip(self):
        """Test parse -> format roundtrip."""
        original = "1,15,30"
        parsed = parse_bymonthday(original)
        formatted = format_bymonthday(parsed)
        assert formatted == original


# ============================================================================
# get_open_days_of_week Tests
# ============================================================================


class TestGetOpenDaysOfWeek:
    """Tests for get_open_days_of_week function."""

    def test_all_days_open(self):
        """Test when all days are open."""
        business_hours = {
            0: {"open": "09:00", "close": "20:00"},
            1: {"open": "09:00", "close": "20:00"},
            2: {"open": "09:00", "close": "20:00"},
            3: {"open": "09:00", "close": "20:00"},
            4: {"open": "09:00", "close": "20:00"},
            5: {"open": "09:00", "close": "20:00"},
            6: {"open": "09:00", "close": "20:00"},
        }

        open_days = get_open_days_of_week(business_hours)
        assert sorted(open_days) == [0, 1, 2, 3, 4, 5, 6]

    def test_workdays_only(self):
        """Test when only workdays are open (Mon-Fri)."""
        business_hours = {
            0: {"open": "09:00", "close": "20:00"},  # Monday
            1: {"open": "09:00", "close": "20:00"},  # Tuesday
            2: {"open": "09:00", "close": "20:00"},  # Wednesday
            3: {"open": "09:00", "close": "20:00"},  # Thursday
            4: {"open": "09:00", "close": "20:00"},  # Friday
            5: None,  # Saturday - closed
            6: None,  # Sunday - closed
        }

        open_days = get_open_days_of_week(business_hours)
        assert sorted(open_days) == [0, 1, 2, 3, 4]

    def test_salon_schedule(self):
        """Test typical salon schedule (Tue-Sat)."""
        business_hours = {
            0: None,  # Monday - closed
            1: {"open": "10:00", "close": "19:00"},  # Tuesday
            2: {"open": "10:00", "close": "19:00"},  # Wednesday
            3: {"open": "10:00", "close": "19:00"},  # Thursday
            4: {"open": "10:00", "close": "19:00"},  # Friday
            5: {"open": "10:00", "close": "14:00"},  # Saturday
            6: None,  # Sunday - closed
        }

        open_days = get_open_days_of_week(business_hours)
        assert sorted(open_days) == [1, 2, 3, 4, 5]

    def test_all_closed(self):
        """Test when all days are closed."""
        business_hours = {i: None for i in range(7)}
        open_days = get_open_days_of_week(business_hours)
        assert open_days == []


# ============================================================================
# validate_time_within_business_hours Tests
# ============================================================================


class TestValidateTimeWithinBusinessHours:
    """Tests for validate_time_within_business_hours function."""

    @pytest.fixture
    def business_hours(self):
        """Sample business hours."""
        return {
            0: None,  # Monday - closed
            1: {"open": "10:00", "close": "19:00"},  # Tuesday
            2: {"open": "10:00", "close": "19:00"},  # Wednesday
            3: {"open": "10:00", "close": "19:00"},  # Thursday
            4: {"open": "10:00", "close": "19:00"},  # Friday
            5: {"open": "10:00", "close": "14:00"},  # Saturday
            6: None,  # Sunday - closed
        }

    def test_valid_time_range(self, business_hours):
        """Test valid time range within business hours."""
        is_valid, error = validate_time_within_business_hours(
            start_time=time(10, 0),
            end_time=time(12, 0),
            day_of_week=1,  # Tuesday
            business_hours=business_hours,
        )
        assert is_valid is True
        assert error is None

    def test_valid_full_day(self, business_hours):
        """Test valid time range covering full business hours."""
        is_valid, error = validate_time_within_business_hours(
            start_time=time(10, 0),
            end_time=time(19, 0),
            day_of_week=1,  # Tuesday
            business_hours=business_hours,
        )
        assert is_valid is True
        assert error is None

    def test_closed_day(self, business_hours):
        """Test booking on closed day."""
        is_valid, error = validate_time_within_business_hours(
            start_time=time(10, 0),
            end_time=time(12, 0),
            day_of_week=0,  # Monday - closed
            business_hours=business_hours,
        )
        assert is_valid is False
        assert "Lunes" in error

    def test_before_opening(self, business_hours):
        """Test start time before opening."""
        is_valid, error = validate_time_within_business_hours(
            start_time=time(9, 0),
            end_time=time(12, 0),
            day_of_week=1,  # Tuesday
            business_hours=business_hours,
        )
        assert is_valid is False
        assert "09:00" in error
        assert "10:00" in error

    def test_after_closing(self, business_hours):
        """Test end time after closing."""
        is_valid, error = validate_time_within_business_hours(
            start_time=time(10, 0),
            end_time=time(20, 0),
            day_of_week=1,  # Tuesday
            business_hours=business_hours,
        )
        assert is_valid is False
        assert "20:00" in error
        assert "19:00" in error

    def test_saturday_short_hours(self, business_hours):
        """Test Saturday with shorter hours."""
        # Valid on Saturday
        is_valid, error = validate_time_within_business_hours(
            start_time=time(10, 0),
            end_time=time(14, 0),
            day_of_week=5,  # Saturday
            business_hours=business_hours,
        )
        assert is_valid is True

        # Invalid - extends past Saturday closing
        is_valid, error = validate_time_within_business_hours(
            start_time=time(10, 0),
            end_time=time(15, 0),
            day_of_week=5,  # Saturday
            business_hours=business_hours,
        )
        assert is_valid is False
        assert "15:00" in error

"""
Unit tests for shared/business_hours_validator.py

Tests the centralized business hours validation module that provides
database-driven closed day detection.

CRITICAL TESTS:
- test_saturday_is_open(): Verifies Saturday (day=5) is NOT hardcoded as closed
- test_sunday_is_closed(): Verifies Sunday (day=6) is closed
- test_monday_is_closed(): Verifies Monday (day=0) is closed
"""

import contextlib
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from shared.business_hours_validator import (
    get_business_hours_for_day,
    get_next_open_date,
    is_date_closed,
    is_day_closed,
    validate_slot_on_open_day,
)

MADRID_TZ = ZoneInfo("Europe/Madrid")

# ---------------------------------------------------------------------------
# Business hours reference data (matches production salon config):
#   Mon (0) = closed, Tue–Fri (1–4) = open 10–20,
#   Sat (5) = open 9–14, Sun (6) = closed
# ---------------------------------------------------------------------------
_BH_DATA = {
    0: {"is_closed": True, "start_hour": None, "end_hour": None},
    1: {"is_closed": False, "start_hour": 10, "end_hour": 20},
    2: {"is_closed": False, "start_hour": 10, "end_hour": 20},
    3: {"is_closed": False, "start_hour": 10, "end_hour": 20},
    4: {"is_closed": False, "start_hour": 10, "end_hour": 20},
    5: {"is_closed": False, "start_hour": 9, "end_hour": 14},
    6: {"is_closed": True, "start_hour": None, "end_hour": None},
}


def _make_bh_row(day_of_week: int) -> MagicMock:
    data = _BH_DATA[day_of_week]
    row = MagicMock()
    row.is_closed = data["is_closed"]
    row.start_hour = data["start_hour"]
    row.end_hour = data["end_hour"]
    row.day_of_week = day_of_week
    return row



def _extract_day_from_stmt(stmt) -> int | None:
    """Extract day_of_week integer from a SQLAlchemy WHERE clause.

    Handles: BusinessHours.day_of_week == <int> (BinaryExpression).
    """
    try:
        # Access the WHERE criteria directly
        criteria = getattr(stmt, "_where_criteria", None) or []
        for clause in criteria:
            # BinaryExpression: left=Column, right=BindParameter
            right = getattr(clause, "right", None)
            if right is not None:
                val = getattr(right, "value", None)
                if isinstance(val, int) and 0 <= val <= 6:
                    return val
    except Exception:
        pass
    return None


@pytest.fixture(autouse=True)
def patch_bh_db():
    """Autouse fixture: patches business_hours_validator.get_async_session for all tests.

    The mock session returns the appropriate seeded BusinessHours data based
    on the day_of_week bound parameter in the WHERE clause.
    """
    from unittest.mock import patch

    def _session_factory():
        session = AsyncMock()

        async def fake_execute(stmt):
            result = MagicMock()
            day = _extract_day_from_stmt(stmt)

            if day is None:
                result.first.return_value = (True,)
                result.scalar_one_or_none.return_value = None
                return result

            row = _make_bh_row(day)
            result.first.return_value = (row.is_closed,)
            result.scalar_one_or_none.return_value = row
            return result

        session.execute = fake_execute
        return session

    @contextlib.asynccontextmanager
    async def _cm():
        yield _session_factory()

    with patch("shared.business_hours_validator.get_async_session", side_effect=lambda: _cm()):
        yield


class TestIsDayClosed:
    """Test is_day_closed() function - core closed day detection."""

    @pytest.mark.asyncio
    async def test_monday_is_closed(self):
        """Monday (day=0) should be closed."""
        assert await is_day_closed(0) is True

    @pytest.mark.asyncio
    async def test_tuesday_is_open(self):
        """Tuesday (day=1) should be open."""
        assert await is_day_closed(1) is False

    @pytest.mark.asyncio
    async def test_wednesday_is_open(self):
        """Wednesday (day=2) should be open."""
        assert await is_day_closed(2) is False

    @pytest.mark.asyncio
    async def test_thursday_is_open(self):
        """Thursday (day=3) should be open."""
        assert await is_day_closed(3) is False

    @pytest.mark.asyncio
    async def test_friday_is_open(self):
        """Friday (day=4) should be open."""
        assert await is_day_closed(4) is False

    @pytest.mark.asyncio
    async def test_saturday_is_open(self):
        """
        CRITICAL: Saturday (day=5) should be OPEN, not hardcoded as closed.

        This test ensures we fix the bug in find_next_available() that
        incorrectly skips Saturday with hardcoded [5, 6] logic.
        """
        assert await is_day_closed(5) is False

    @pytest.mark.asyncio
    async def test_sunday_is_closed(self):
        """Sunday (day=6) should be closed."""
        assert await is_day_closed(6) is True

    @pytest.mark.asyncio
    async def test_invalid_day_of_week_negative(self):
        """Invalid day_of_week (-1) should fail closed (return True)."""
        assert await is_day_closed(-1) is True

    @pytest.mark.asyncio
    async def test_invalid_day_of_week_too_large(self):
        """Invalid day_of_week (7) should fail closed (return True)."""
        assert await is_day_closed(7) is True


class TestIsDateClosed:
    """Test is_date_closed() function - date-based closed day detection."""

    @pytest.mark.asyncio
    async def test_sunday_date_is_closed(self):
        """A Sunday date should be closed."""
        # December 7, 2025 is a Sunday
        sunday = datetime(2025, 12, 7, tzinfo=MADRID_TZ)
        assert await is_date_closed(sunday) is True

    @pytest.mark.asyncio
    async def test_monday_date_is_closed(self):
        """A Monday date should be closed."""
        # December 8, 2025 is a Monday
        monday = datetime(2025, 12, 8, tzinfo=MADRID_TZ)
        assert await is_date_closed(monday) is True

    @pytest.mark.asyncio
    async def test_tuesday_date_is_open(self):
        """A Tuesday date should be open."""
        # December 9, 2025 is a Tuesday
        tuesday = datetime(2025, 12, 9, tzinfo=MADRID_TZ)
        assert await is_date_closed(tuesday) is False

    @pytest.mark.asyncio
    async def test_saturday_date_is_open(self):
        """
        CRITICAL: A Saturday date should be OPEN.

        Verifies Saturday 9:00-14:00 hours are respected.
        """
        # December 6, 2025 is a Saturday
        saturday = datetime(2025, 12, 6, tzinfo=MADRID_TZ)
        assert await is_date_closed(saturday) is False

    @pytest.mark.asyncio
    async def test_date_without_timezone(self):
        """Date without timezone should still work (uses weekday())."""
        from datetime import date
        # December 7, 2025 is a Sunday
        sunday_date = date(2025, 12, 7)
        assert await is_date_closed(sunday_date) is True


class TestGetNextOpenDate:
    """Test get_next_open_date() function - finds next open business day."""

    @pytest.mark.asyncio
    async def test_from_sunday_finds_tuesday(self):
        """
        Starting from Sunday, should find Tuesday (skips Sunday + Monday).
        """
        # December 7, 2025 is Sunday
        sunday = datetime(2025, 12, 7, 10, 0, tzinfo=MADRID_TZ)
        next_open = await get_next_open_date(sunday)

        assert next_open is not None
        # December 9, 2025 is Tuesday (first open day)
        assert next_open.date() == datetime(2025, 12, 9).date()
        assert next_open.weekday() == 1  # Tuesday

    @pytest.mark.asyncio
    async def test_from_monday_finds_tuesday(self):
        """
        Starting from Monday, should find Tuesday.
        """
        # December 8, 2025 is Monday
        monday = datetime(2025, 12, 8, 10, 0, tzinfo=MADRID_TZ)
        next_open = await get_next_open_date(monday)

        assert next_open is not None
        assert next_open.date() == datetime(2025, 12, 9).date()
        assert next_open.weekday() == 1  # Tuesday

    @pytest.mark.asyncio
    async def test_from_tuesday_returns_tuesday(self):
        """
        Starting from Tuesday (open day), should return Tuesday itself.
        """
        # December 9, 2025 is Tuesday
        tuesday = datetime(2025, 12, 9, 10, 0, tzinfo=MADRID_TZ)
        next_open = await get_next_open_date(tuesday)

        assert next_open is not None
        assert next_open.date() == tuesday.date()
        assert next_open.weekday() == 1  # Tuesday

    @pytest.mark.asyncio
    async def test_from_saturday_returns_saturday(self):
        """
        CRITICAL: Starting from Saturday (OPEN), should return Saturday itself.

        This verifies Saturday is not hardcoded as closed.
        """
        # December 6, 2025 is Saturday
        saturday = datetime(2025, 12, 6, 10, 0, tzinfo=MADRID_TZ)
        next_open = await get_next_open_date(saturday)

        assert next_open is not None
        assert next_open.date() == saturday.date()
        assert next_open.weekday() == 5  # Saturday

    @pytest.mark.asyncio
    async def test_max_search_days_exceeded(self):
        """
        If no open date found within max_search_days, should return None.
        """
        # Start from Sunday, only search 1 day (only finds Monday which is closed)
        sunday = datetime(2025, 12, 7, 10, 0, tzinfo=MADRID_TZ)
        next_open = await get_next_open_date(sunday, max_search_days=1)

        assert next_open is None


class TestValidateSlotOnOpenDay:
    """Test validate_slot_on_open_day() function - FSM slot validation."""

    @pytest.mark.asyncio
    async def test_tuesday_slot_is_valid(self):
        """A Tuesday slot should be valid (salon is open)."""
        slot = {
            "start_time": "2025-12-09T10:00:00+01:00",  # Tuesday
            "duration_minutes": 60
        }
        is_valid, error = await validate_slot_on_open_day(slot)

        assert is_valid is True
        assert error is None

    @pytest.mark.asyncio
    async def test_saturday_slot_is_valid(self):
        """
        CRITICAL: A Saturday slot should be valid (salon open 9:00-14:00).
        """
        slot = {
            "start_time": "2025-12-06T10:00:00+01:00",  # Saturday
            "duration_minutes": 60
        }
        is_valid, error = await validate_slot_on_open_day(slot)

        assert is_valid is True
        assert error is None

    @pytest.mark.asyncio
    async def test_sunday_slot_is_invalid(self):
        """
        A Sunday slot should be invalid with Spanish error message.
        """
        slot = {
            "start_time": "2025-12-07T10:00:00+01:00",  # Sunday
            "duration_minutes": 60
        }
        is_valid, error = await validate_slot_on_open_day(slot)

        assert is_valid is False
        assert error is not None
        assert "domingo" in error.lower()
        assert "cerrado" in error.lower()

    @pytest.mark.asyncio
    async def test_monday_slot_is_invalid(self):
        """A Monday slot should be invalid."""
        slot = {
            "start_time": "2025-12-08T10:00:00+01:00",  # Monday
            "duration_minutes": 60
        }
        is_valid, error = await validate_slot_on_open_day(slot)

        assert is_valid is False
        assert error is not None
        assert "lunes" in error.lower()

    @pytest.mark.asyncio
    async def test_slot_without_start_time(self):
        """Slot without start_time should be invalid."""
        slot = {"duration_minutes": 60}
        is_valid, error = await validate_slot_on_open_day(slot)

        assert is_valid is False
        assert error is not None

    @pytest.mark.asyncio
    async def test_slot_with_invalid_iso_format(self):
        """Slot with invalid ISO 8601 format should be invalid."""
        slot = {
            "start_time": "not-a-valid-date",
            "duration_minutes": 60
        }
        is_valid, error = await validate_slot_on_open_day(slot)

        assert is_valid is False
        assert error is not None


class TestGetBusinessHoursForDay:
    """Test get_business_hours_for_day() function - retrieve open hours."""

    @pytest.mark.asyncio
    async def test_tuesday_hours(self):
        """Tuesday should return 10:00-20:00."""
        hours = await get_business_hours_for_day(1)  # Tuesday

        assert hours is not None
        assert hours["start"] == 10
        assert hours["end"] == 20

    @pytest.mark.asyncio
    async def test_wednesday_hours(self):
        """Wednesday should return 10:00-20:00."""
        hours = await get_business_hours_for_day(2)  # Wednesday

        assert hours is not None
        assert hours["start"] == 10
        assert hours["end"] == 20

    @pytest.mark.asyncio
    async def test_saturday_hours(self):
        """
        CRITICAL: Saturday should return 9:00-14:00 (not None).
        """
        hours = await get_business_hours_for_day(5)  # Saturday

        assert hours is not None
        assert hours["start"] == 9
        assert hours["end"] == 14

    @pytest.mark.asyncio
    async def test_sunday_hours(self):
        """Sunday should return None (closed)."""
        hours = await get_business_hours_for_day(6)  # Sunday

        assert hours is None

    @pytest.mark.asyncio
    async def test_monday_hours(self):
        """Monday should return None (closed)."""
        hours = await get_business_hours_for_day(0)  # Monday

        assert hours is None

    @pytest.mark.asyncio
    async def test_invalid_day_of_week(self):
        """Invalid day_of_week should return None."""
        hours = await get_business_hours_for_day(7)  # Invalid

        assert hours is None

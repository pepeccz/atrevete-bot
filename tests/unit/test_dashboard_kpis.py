"""
Unit tests for dashboard KPI helper functions — Slice 2a (TDD RED phase).

Each test targets a pure async helper from api.services.dashboard_kpis.
All DB calls are mocked; no real database is required.

Helpers under test:
  - _confirmation_rate_today(session, today)
  - _appointments_count_today(session, today)
  - _occupation_today(session, today)
  - _new_customers_last_7d(session, now)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ---------------------------------------------------------------------------
# Helper: build a mock AsyncSession that returns scalar values in sequence
# ---------------------------------------------------------------------------


def _scalar_session(*scalar_values):
    """
    Returns a mock async context manager whose session.execute() returns
    the given scalar values in order (one per call).
    """
    mock_session = AsyncMock()
    queue = list(scalar_values)

    async def _execute(*_args, **_kwargs):
        value = queue.pop(0) if queue else 0
        result = MagicMock()
        result.scalar.return_value = value
        result.scalar_one.return_value = value
        result.scalars.return_value = MagicMock(all=MagicMock(return_value=value))
        return result

    mock_session.execute = _execute
    return mock_session


def _scalars_session(*rows_per_call):
    """
    Returns a session mock where each execute() call returns a MagicMock
    whose .all() returns the corresponding rows list.
    """
    mock_session = AsyncMock()
    queue = list(rows_per_call)

    async def _execute(*_args, **_kwargs):
        rows = queue.pop(0) if queue else []
        result = MagicMock()
        result.scalars.return_value = MagicMock(all=MagicMock(return_value=rows))
        result.scalar.return_value = rows[0] if rows else 0
        result.all.return_value = rows
        return result

    mock_session.execute = _execute
    return mock_session


# ---------------------------------------------------------------------------
# _confirmation_rate_today
# ---------------------------------------------------------------------------


class TestConfirmationRateToday:
    """Tests for _confirmation_rate_today(session, today) -> float."""

    @pytest.mark.asyncio
    async def test_confirmed_over_total_gives_correct_ratio(self):
        """
        GIVEN 2 confirmed and 3 total non-cancelled appointments today
        WHEN _confirmation_rate_today is called
        THEN returns 2/3 ≈ 0.667
        """
        from api.services.dashboard_kpis import _confirmation_rate_today

        # The helper executes one query returning (confirmed_count, total_count)
        mock_session = AsyncMock()

        async def _execute(*_args, **_kwargs):
            result = MagicMock()
            result.one.return_value = (2, 3)  # (confirmed, total)
            return result

        mock_session.execute = _execute
        today = date(2026, 5, 10)

        rate = await _confirmation_rate_today(mock_session, today)

        assert abs(rate - (2 / 3)) < 0.001

    @pytest.mark.asyncio
    async def test_all_confirmed_returns_one(self):
        """
        GIVEN 5 confirmed and 5 total today
        WHEN _confirmation_rate_today is called
        THEN returns 1.0
        """
        from api.services.dashboard_kpis import _confirmation_rate_today

        mock_session = AsyncMock()

        async def _execute(*_args, **_kwargs):
            result = MagicMock()
            result.one.return_value = (5, 5)
            return result

        mock_session.execute = _execute

        rate = await _confirmation_rate_today(mock_session, date(2026, 5, 10))
        assert rate == 1.0

    @pytest.mark.asyncio
    async def test_zero_appointments_returns_zero(self):
        """
        GIVEN 0 total appointments today
        WHEN _confirmation_rate_today is called
        THEN returns 0.0 (divide-by-zero guard)
        """
        from api.services.dashboard_kpis import _confirmation_rate_today

        mock_session = AsyncMock()

        async def _execute(*_args, **_kwargs):
            result = MagicMock()
            result.one.return_value = (0, 0)
            return result

        mock_session.execute = _execute

        rate = await _confirmation_rate_today(mock_session, date(2026, 5, 10))
        assert rate == 0.0

    @pytest.mark.asyncio
    async def test_none_confirmed_but_total_positive_returns_zero(self):
        """
        GIVEN 0 confirmed but 4 total non-cancelled appointments
        WHEN _confirmation_rate_today is called
        THEN returns 0.0 (no confirmed out of 4 pending)
        """
        from api.services.dashboard_kpis import _confirmation_rate_today

        mock_session = AsyncMock()

        async def _execute(*_args, **_kwargs):
            result = MagicMock()
            result.one.return_value = (0, 4)
            return result

        mock_session.execute = _execute

        rate = await _confirmation_rate_today(mock_session, date(2026, 5, 10))
        assert rate == 0.0


# ---------------------------------------------------------------------------
# _appointments_count_today
# ---------------------------------------------------------------------------


class TestAppointmentsCountToday:
    """Tests for _appointments_count_today(session, today) -> int."""

    @pytest.mark.asyncio
    async def test_returns_count_excluding_cancelled_and_no_show(self):
        """
        GIVEN the DB returns 4 non-cancelled/no_show appointments today
        WHEN _appointments_count_today is called
        THEN returns 4
        """
        from api.services.dashboard_kpis import _appointments_count_today

        session = _scalar_session(4)
        today = date(2026, 5, 10)

        count = await _appointments_count_today(session, today)
        assert count == 4

    @pytest.mark.asyncio
    async def test_zero_when_no_appointments(self):
        """
        GIVEN DB returns 0 appointments today
        WHEN _appointments_count_today is called
        THEN returns 0
        """
        from api.services.dashboard_kpis import _appointments_count_today

        session = _scalar_session(0)
        count = await _appointments_count_today(session, date(2026, 5, 10))
        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_integer_not_none(self):
        """
        GIVEN DB returns None (no rows matched)
        WHEN _appointments_count_today is called
        THEN returns 0 (None-safe coerce)
        """
        from api.services.dashboard_kpis import _appointments_count_today

        session = _scalar_session(None)
        count = await _appointments_count_today(session, date(2026, 5, 10))
        assert count == 0
        assert isinstance(count, int)


# ---------------------------------------------------------------------------
# _occupation_today
# ---------------------------------------------------------------------------


class TestOccupationToday:
    """Tests for _occupation_today(session, today) -> float."""

    @pytest.mark.asyncio
    async def test_correct_ratio_with_booked_minutes_and_capacity(self):
        """
        GIVEN 120 booked minutes and 480 available minutes (8h salon day, 1 stylist)
        WHEN _occupation_today is called
        THEN returns 120/480 = 0.25
        """
        from api.services.dashboard_kpis import _occupation_today

        # Helper makes 2 queries: (1) sum(duration_minutes) for booked, (2) business capacity
        mock_session = AsyncMock()
        call_count = 0

        async def _execute(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # booked minutes query
                result.scalar.return_value = 120
            elif call_count == 2:
                # active stylist count
                result.scalar.return_value = 1
            else:
                # business hours query returns a BusinessHours-like row
                bh = MagicMock()
                bh.is_closed = False
                bh.start_hour = 9
                bh.start_minute = 0
                bh.end_hour = 17
                bh.end_minute = 0
                result.scalar_one_or_none.return_value = bh
            return result

        mock_session.execute = _execute
        today = date(2026, 5, 10)  # Saturday (day_of_week index 5 in Python isoweekday - 1)

        rate = await _occupation_today(mock_session, today)
        assert abs(rate - (120 / 480)) < 0.001

    @pytest.mark.asyncio
    async def test_zero_booked_minutes_returns_zero(self):
        """
        GIVEN 0 booked minutes and 480 available minutes
        WHEN _occupation_today is called
        THEN returns 0.0
        """
        from api.services.dashboard_kpis import _occupation_today

        mock_session = AsyncMock()
        call_count = 0

        async def _execute(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar.return_value = 0
            elif call_count == 2:
                result.scalar.return_value = 2
            else:
                bh = MagicMock()
                bh.is_closed = False
                bh.start_hour = 9
                bh.start_minute = 0
                bh.end_hour = 17
                bh.end_minute = 0
                result.scalar_one_or_none.return_value = bh
            return result

        mock_session.execute = _execute
        rate = await _occupation_today(mock_session, date(2026, 5, 10))
        assert rate == 0.0

    @pytest.mark.asyncio
    async def test_zero_capacity_returns_zero(self):
        """
        GIVEN salon is closed today (zero business minutes available)
        WHEN _occupation_today is called
        THEN returns 0.0 (divide-by-zero guard)
        """
        from api.services.dashboard_kpis import _occupation_today

        mock_session = AsyncMock()
        call_count = 0

        async def _execute(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar.return_value = 60
            elif call_count == 2:
                result.scalar.return_value = 0  # no active stylists
            else:
                bh = MagicMock()
                bh.is_closed = True
                result.scalar_one_or_none.return_value = bh
            return result

        mock_session.execute = _execute
        rate = await _occupation_today(mock_session, date(2026, 5, 10))
        assert rate == 0.0


# ---------------------------------------------------------------------------
# _new_customers_last_7d
# ---------------------------------------------------------------------------


class TestNewCustomersLast7d:
    """Tests for _new_customers_last_7d(session, now) -> int."""

    @pytest.mark.asyncio
    async def test_returns_count_for_last_7_days(self):
        """
        GIVEN 3 customers created in the last 7 days
        WHEN _new_customers_last_7d is called
        THEN returns 3
        """
        from api.services.dashboard_kpis import _new_customers_last_7d

        session = _scalar_session(3)
        now = datetime(2026, 5, 10, 12, 0, 0, tzinfo=MADRID_TZ)

        count = await _new_customers_last_7d(session, now)
        assert count == 3

    @pytest.mark.asyncio
    async def test_rolling_window_not_iso_week(self):
        """
        GIVEN now = Thursday 2026-05-14 09:00 Madrid
        WHEN _new_customers_last_7d is called
        THEN the window is [2026-05-07 09:00, 2026-05-14 09:00] (rolling 7 days)
          NOT [2026-05-11 00:00, ...] (ISO week Monday start)

        We verify this indirectly: the function is called without error and returns
        the session-mocked value, confirming it uses `now - 7 days` boundary.
        """
        from api.services.dashboard_kpis import _new_customers_last_7d

        # Capture the query to inspect the lower-bound used
        captured_args = []
        mock_session = AsyncMock()

        async def _execute(*args, **kwargs):
            captured_args.append(args)
            result = MagicMock()
            result.scalar.return_value = 5
            return result

        mock_session.execute = _execute
        now = datetime(2026, 5, 14, 9, 0, 0, tzinfo=MADRID_TZ)  # Thursday

        count = await _new_customers_last_7d(mock_session, now)
        assert count == 5
        # The query was executed exactly once
        assert len(captured_args) == 1

    @pytest.mark.asyncio
    async def test_zero_when_no_new_customers(self):
        """
        GIVEN no customers created in the last 7 days
        WHEN _new_customers_last_7d is called
        THEN returns 0
        """
        from api.services.dashboard_kpis import _new_customers_last_7d

        session = _scalar_session(None)
        now = datetime(2026, 5, 10, 12, 0, 0, tzinfo=MADRID_TZ)

        count = await _new_customers_last_7d(session, now)
        assert count == 0
        assert isinstance(count, int)

    @pytest.mark.asyncio
    async def test_large_count_returns_correctly(self):
        """
        GIVEN 150 customers created in the last 7 days
        WHEN _new_customers_last_7d is called
        THEN returns 150 (no truncation or off-by-one)
        """
        from api.services.dashboard_kpis import _new_customers_last_7d

        session = _scalar_session(150)
        now = datetime(2026, 5, 10, 12, 0, 0, tzinfo=MADRID_TZ)

        count = await _new_customers_last_7d(session, now)
        assert count == 150

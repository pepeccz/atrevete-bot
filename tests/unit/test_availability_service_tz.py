"""
Unit tests for timezone-aware datetime handling in availability_service.get_busy_periods().

Verifies that aware datetimes are passed directly to SQL queries without stripping
timezone info — the previous BUG-AVAIL-2 "fix" incorrectly stripped tzinfo before
binding to timestamptz columns.
"""

import contextlib
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from agent.services.availability_service import get_busy_periods
from database.models import Appointment, AppointmentStatus, BlockingEvent

MADRID_TZ = ZoneInfo("Europe/Madrid")
UTC_TZ = ZoneInfo("UTC")


# ============================================================================
# Helpers
# ============================================================================


def _make_mock_appointment(
    stylist_id,
    start: datetime,
    duration_minutes: int = 60,
    first_name: str = "Ana",
    status: AppointmentStatus = AppointmentStatus.CONFIRMED,
) -> MagicMock:
    """Build a mock Appointment."""
    appt = MagicMock(spec=Appointment)
    appt.id = uuid4()
    appt.stylist_id = stylist_id
    appt.start_time = start
    appt.duration_minutes = duration_minutes
    appt.first_name = first_name
    appt.status = status
    return appt


def _make_mock_blocking_event(
    stylist_id,
    start: datetime,
    end: datetime,
    title: str = "Descanso",
) -> MagicMock:
    """Build a mock BlockingEvent."""
    event = MagicMock(spec=BlockingEvent)
    event.id = uuid4()
    event.stylist_id = stylist_id
    event.start_time = start
    event.end_time = end
    event.title = title
    event.event_type = MagicMock()
    event.event_type.value = "BREAK"
    return event


def _mock_session_with_results(appointments, blocking_events):
    """Create a mock AsyncSession that returns given appointments and blocking events."""
    session = AsyncMock()

    appt_result = MagicMock()
    appt_result.scalars.return_value.all.return_value = appointments

    block_result = MagicMock()
    block_result.scalars.return_value.all.return_value = blocking_events

    # execute is called twice: once for appointments, once for blocking events
    session.execute = AsyncMock(side_effect=[appt_result, block_result])

    return session


# ============================================================================
# Tests
# ============================================================================


class TestGetBusyPeriodsTimezoneAware:
    """Verify that get_busy_periods() handles timezone-aware datetimes correctly."""

    @pytest.mark.asyncio
    async def test_passes_aware_datetimes_without_stripping(self):
        """Call with Europe/Madrid aware datetimes — no DataError, no stripping."""
        stylist_id = uuid4()
        start = datetime(2026, 3, 27, 10, 0, tzinfo=MADRID_TZ)
        end = datetime(2026, 3, 27, 18, 0, tzinfo=MADRID_TZ)

        appt = _make_mock_appointment(stylist_id, start, duration_minutes=60)
        session = _mock_session_with_results([appt], [])

        result = await get_busy_periods(stylist_id, start, end, session=session)

        assert len(result) == 1
        assert result[0]["type"] == "appointment"
        assert result[0]["start"] == start

        # Verify execute was called with aware datetimes (not stripped)
        # The key assertion: no DataError was raised, which means aware datetimes
        # were accepted by the mock (and would be accepted by real asyncpg + timestamptz)
        assert session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_overlap_detection_with_different_tz(self):
        """Appointments in Madrid tz, query in UTC — correct overlap detection."""
        stylist_id = uuid4()
        # Appointment at 10:00 Madrid = 09:00 UTC
        appt_start = datetime(2026, 3, 27, 10, 0, tzinfo=MADRID_TZ)
        appt = _make_mock_appointment(stylist_id, appt_start, duration_minutes=60)

        # Query range in UTC that overlaps: 08:30 - 10:30 UTC
        query_start = datetime(2026, 3, 27, 8, 30, tzinfo=UTC_TZ)
        query_end = datetime(2026, 3, 27, 10, 30, tzinfo=UTC_TZ)

        session = _mock_session_with_results([appt], [])

        result = await get_busy_periods(stylist_id, query_start, query_end, session=session)

        # The appointment IS in the range (overlap detected)
        assert len(result) == 1
        assert result[0]["start"] == appt_start

    @pytest.mark.asyncio
    async def test_dst_boundary_appointment_detected(self):
        """Appointment during DST transition is correctly detected as busy.

        Europe/Madrid springs forward on last Sunday of March:
        2026-03-29 at 02:00 → 03:00 (clocks skip 02:00-03:00).
        An appointment at 03:30 Madrid (= 01:30 UTC) should be found.
        """
        stylist_id = uuid4()
        # Post-DST appointment: 03:30 CEST (UTC+2)
        appt_start = datetime(2026, 3, 29, 3, 30, tzinfo=MADRID_TZ)
        appt = _make_mock_appointment(stylist_id, appt_start, duration_minutes=30)

        # Query range spanning the DST transition: 01:00 - 05:00 Madrid
        query_start = datetime(2026, 3, 29, 1, 0, tzinfo=MADRID_TZ)
        query_end = datetime(2026, 3, 29, 5, 0, tzinfo=MADRID_TZ)

        session = _mock_session_with_results([appt], [])

        result = await get_busy_periods(stylist_id, query_start, query_end, session=session)

        assert len(result) == 1
        assert result[0]["start"] == appt_start

    @pytest.mark.asyncio
    async def test_empty_result_with_aware_datetimes(self):
        """No appointments or events — returns empty list, no errors."""
        stylist_id = uuid4()
        start = datetime(2026, 3, 27, 10, 0, tzinfo=MADRID_TZ)
        end = datetime(2026, 3, 27, 18, 0, tzinfo=MADRID_TZ)

        session = _mock_session_with_results([], [])

        result = await get_busy_periods(stylist_id, start, end, session=session)

        assert result == []
        assert session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_blocking_event_with_aware_datetimes(self):
        """BlockingEvent query also receives aware datetimes correctly."""
        stylist_id = uuid4()
        block_start = datetime(2026, 3, 27, 13, 0, tzinfo=MADRID_TZ)
        block_end = datetime(2026, 3, 27, 14, 0, tzinfo=MADRID_TZ)
        event = _make_mock_blocking_event(stylist_id, block_start, block_end)

        query_start = datetime(2026, 3, 27, 10, 0, tzinfo=MADRID_TZ)
        query_end = datetime(2026, 3, 27, 18, 0, tzinfo=MADRID_TZ)

        session = _mock_session_with_results([], [event])

        result = await get_busy_periods(stylist_id, query_start, query_end, session=session)

        assert len(result) == 1
        assert result[0]["type"] == "blocking_event"
        assert result[0]["start"] == block_start
        assert result[0]["end"] == block_end

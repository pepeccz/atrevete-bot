"""
Unit tests for timezone-aware datetime handling in availability_service.get_busy_periods().

Verifies that aware datetimes are passed directly to SQL queries without stripping
timezone info — the previous BUG-AVAIL-2 "fix" incorrectly stripped tzinfo before
binding to timestamptz columns.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
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


class TestGetBusyPeriodsOverlapDetection:
    """REQ-BAF-2: Verify Python-side overlap filter correctness after broad-range SQL fetch."""

    @pytest.mark.asyncio
    async def test_overlapping_appointment_included(self):
        """Appointment that overlaps the query range is included in result (REQ-BAF-2)."""
        stylist_id = uuid4()
        # Appointment starts before our range end and ends after our range start → overlap
        appt_start = datetime(2026, 3, 27, 10, 0, tzinfo=MADRID_TZ)  # 10:00
        duration = 60  # ends at 11:00
        appt = _make_mock_appointment(stylist_id, appt_start, duration_minutes=duration)

        # Range: 09:30 – 11:30 (appointment at 10:00–11:00 overlaps)
        query_start = datetime(2026, 3, 27, 9, 30, tzinfo=MADRID_TZ)
        query_end = datetime(2026, 3, 27, 11, 30, tzinfo=MADRID_TZ)

        session = _mock_session_with_results([appt], [])
        result = await get_busy_periods(stylist_id, query_start, query_end, session=session)

        assert len(result) == 1
        assert result[0]["type"] == "appointment"
        assert result[0]["start"] == appt_start

    @pytest.mark.asyncio
    async def test_appointment_ending_exactly_at_range_start_excluded(self):
        """Appointment that ends exactly at range start is NOT an overlap (REQ-BAF-2).

        The Python filter uses strict `>` (appointment end > range start).
        An appointment ending at exactly the range start is NOT overlapping.
        """
        stylist_id = uuid4()
        # Appointment ends at 10:00 (range start) — NOT overlapping
        appt_start = datetime(2026, 3, 27, 9, 0, tzinfo=MADRID_TZ)  # 09:00
        duration = 60  # ends at 10:00
        appt = _make_mock_appointment(stylist_id, appt_start, duration_minutes=duration)

        # Range starts exactly when the appointment ends
        query_start = datetime(2026, 3, 27, 10, 0, tzinfo=MADRID_TZ)
        query_end = datetime(2026, 3, 27, 18, 0, tzinfo=MADRID_TZ)

        # The broad SQL fetch would include this appointment (start >= start - 12h)
        # but the Python filter must exclude it (appointment end NOT > range start)
        session = _mock_session_with_results([appt], [])
        result = await get_busy_periods(stylist_id, query_start, query_end, session=session)

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_appointment_entirely_outside_range_excluded(self):
        """Appointment with end_time before range start is excluded by Python filter (REQ-BAF-2)."""
        stylist_id = uuid4()
        # Appointment starts at 07:00 and ends at 08:00 — entirely before query range 10:00–18:00
        appt_start = datetime(2026, 3, 27, 7, 0, tzinfo=MADRID_TZ)
        duration = 60  # ends at 08:00
        appt = _make_mock_appointment(stylist_id, appt_start, duration_minutes=duration)

        query_start = datetime(2026, 3, 27, 10, 0, tzinfo=MADRID_TZ)
        query_end = datetime(2026, 3, 27, 18, 0, tzinfo=MADRID_TZ)

        # Broad SQL fetch would include it (07:00 >= 10:00 - 12h = 22:00 prev day → yes)
        session = _mock_session_with_results([appt], [])
        result = await get_busy_periods(stylist_id, query_start, query_end, session=session)

        # Python filter: appt end (08:00) > range start (10:00) → False → excluded
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_multiple_appointments_some_overlapping(self):
        """Only overlapping appointments are returned; outside ones are excluded (REQ-BAF-2)."""
        stylist_id = uuid4()

        # Appointment 1: overlaps (10:00 – 11:00, range 10:30 – 18:00)
        appt_overlap = _make_mock_appointment(
            stylist_id,
            datetime(2026, 3, 27, 10, 0, tzinfo=MADRID_TZ),
            duration_minutes=60,
            first_name="Overlap",
        )
        # Appointment 2: outside range (07:00 – 08:00, range 10:30 – 18:00)
        appt_outside = _make_mock_appointment(
            stylist_id,
            datetime(2026, 3, 27, 7, 0, tzinfo=MADRID_TZ),
            duration_minutes=60,
            first_name="Outside",
        )

        query_start = datetime(2026, 3, 27, 10, 30, tzinfo=MADRID_TZ)
        query_end = datetime(2026, 3, 27, 18, 0, tzinfo=MADRID_TZ)

        session = _mock_session_with_results([appt_overlap, appt_outside], [])
        result = await get_busy_periods(stylist_id, query_start, query_end, session=session)

        assert len(result) == 1
        assert result[0]["title"] == "Cita: Overlap"


# ============================================================================
# HOLD-related busy period tests (REQ-14)
# ============================================================================


class TestGetBusyPeriodsHoldStatus:
    """REQ-14: get_busy_periods includes active HOLDs and excludes expired HOLDs."""

    @pytest.mark.asyncio
    async def test_active_hold_appears_in_busy_periods(self):
        """REQ-14: HOLD with hold_expires_at in future is included as a busy period."""

        stylist_id = uuid4()
        query_start = datetime(2026, 4, 15, 9, 0, tzinfo=MADRID_TZ)
        query_end = datetime(2026, 4, 15, 18, 0, tzinfo=MADRID_TZ)

        hold_start = datetime(2026, 4, 15, 10, 0, tzinfo=MADRID_TZ)
        future_expires = datetime.now(UTC) + timedelta(minutes=3)

        hold_appt = _make_mock_appointment(
            stylist_id,
            hold_start,
            duration_minutes=60,
            first_name="HoldCustomer",
            status=AppointmentStatus.HOLD,
        )
        hold_appt.hold_expires_at = future_expires

        session = _mock_session_with_results([hold_appt], [])
        result = await get_busy_periods(stylist_id, query_start, query_end, session=session)

        # Active HOLD must appear as a busy period
        assert len(result) == 1
        assert result[0]["type"] == "appointment"
        assert result[0]["status"] == "hold"

    @pytest.mark.asyncio
    async def test_expired_hold_excluded_from_busy_periods(self):
        """REQ-14: HOLD with hold_expires_at in past is excluded from busy periods."""

        stylist_id = uuid4()
        query_start = datetime(2026, 4, 15, 9, 0, tzinfo=MADRID_TZ)
        query_end = datetime(2026, 4, 15, 18, 0, tzinfo=MADRID_TZ)

        hold_start = datetime(2026, 4, 15, 10, 0, tzinfo=MADRID_TZ)
        past_expires = datetime.now(UTC) - timedelta(minutes=10)  # Expired 10 min ago

        expired_hold = _make_mock_appointment(
            stylist_id,
            hold_start,
            duration_minutes=60,
            first_name="ExpiredHold",
            status=AppointmentStatus.HOLD,
        )
        expired_hold.hold_expires_at = past_expires

        session = _mock_session_with_results([expired_hold], [])
        result = await get_busy_periods(stylist_id, query_start, query_end, session=session)

        # Expired HOLD must NOT appear (treated as free slot)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_hold_with_none_expires_at_excluded(self):
        """HOLD with hold_expires_at=None is treated as expired and excluded."""
        stylist_id = uuid4()
        query_start = datetime(2026, 4, 15, 9, 0, tzinfo=MADRID_TZ)
        query_end = datetime(2026, 4, 15, 18, 0, tzinfo=MADRID_TZ)

        hold_start = datetime(2026, 4, 15, 10, 0, tzinfo=MADRID_TZ)

        hold_no_expiry = _make_mock_appointment(
            stylist_id,
            hold_start,
            duration_minutes=60,
            first_name="NoExpiry",
            status=AppointmentStatus.HOLD,
        )
        hold_no_expiry.hold_expires_at = None  # Missing expiry — treat as expired

        session = _mock_session_with_results([hold_no_expiry], [])
        result = await get_busy_periods(stylist_id, query_start, query_end, session=session)

        # HOLD with None expiry is excluded (defensive behavior)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_mixed_active_and_expired_holds(self):
        """Active HOLD is included; expired HOLD is excluded in the same query result."""

        stylist_id = uuid4()
        query_start = datetime(2026, 4, 15, 9, 0, tzinfo=MADRID_TZ)
        query_end = datetime(2026, 4, 15, 18, 0, tzinfo=MADRID_TZ)

        active_start = datetime(2026, 4, 15, 10, 0, tzinfo=MADRID_TZ)
        expired_start = datetime(2026, 4, 15, 11, 0, tzinfo=MADRID_TZ)

        active_hold = _make_mock_appointment(
            stylist_id,
            active_start,
            duration_minutes=60,
            first_name="ActiveHold",
            status=AppointmentStatus.HOLD,
        )
        active_hold.hold_expires_at = datetime.now(UTC) + timedelta(minutes=3)

        expired_hold = _make_mock_appointment(
            stylist_id,
            expired_start,
            duration_minutes=60,
            first_name="ExpiredHold",
            status=AppointmentStatus.HOLD,
        )
        expired_hold.hold_expires_at = datetime.now(UTC) - timedelta(minutes=5)

        session = _mock_session_with_results([active_hold, expired_hold], [])
        result = await get_busy_periods(stylist_id, query_start, query_end, session=session)

        # Only active hold appears
        assert len(result) == 1
        assert result[0]["title"] == "Cita: ActiveHold"

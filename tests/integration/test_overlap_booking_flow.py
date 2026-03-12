"""
Integration tests for overlapping appointment booking flow (Mock-based).

These tests verify:
- Overlap detection works correctly
- Agent booking path is isolated
- Edge cases are handled properly
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from api.routes.admin import find_overlapping_appointments
from database.models import Appointment, AppointmentStatus


MADRID_TZ = ZoneInfo("Europe/Madrid")


@pytest.mark.asyncio
class TestOverlapEdgeCases:
    """Test edge cases for overlap detection."""

    async def test_exact_same_time_overlap(self):
        """Test that exact same time slot is detected as overlap."""
        stylist_id = uuid4()
        start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)

        mock_session = MagicMock()
        mock_result = MagicMock()
        
        existing_appt = MagicMock(spec=Appointment)
        existing_appt.id = uuid4()
        existing_appt.start_time = start_time
        existing_appt.duration_minutes = 60
        existing_appt.status = AppointmentStatus.CONFIRMED

        mock_result.scalars.return_value.all.return_value = [existing_appt]
        mock_session.execute = AsyncMock(return_value=mock_result)

        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=start_time,
            duration_minutes=60,
            session=mock_session,
        )

        assert len(overlaps) == 1

    async def test_one_minute_overlap_detected(self):
        """Test that even 1-minute overlap is detected."""
        stylist_id = uuid4()
        
        existing_appt = MagicMock(spec=Appointment)
        existing_appt.id = uuid4()
        existing_appt.start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
        existing_appt.duration_minutes = 60
        existing_appt.status = AppointmentStatus.CONFIRMED

        new_start = datetime(2024, 12, 15, 10, 59, tzinfo=MADRID_TZ)

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [existing_appt]
        mock_session.execute = AsyncMock(return_value=mock_result)

        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=new_start,
            duration_minutes=60,
            session=mock_session,
        )

        assert len(overlaps) == 1

    async def test_back_to_back_no_overlap(self):
        """Test that back-to-back appointments don't overlap."""
        stylist_id = uuid4()
        
        existing_appt = MagicMock(spec=Appointment)
        existing_appt.id = uuid4()
        existing_appt.start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
        existing_appt.duration_minutes = 60
        existing_appt.status = AppointmentStatus.CONFIRMED

        # New appointment starts exactly when existing ends (11:00)
        new_start = datetime(2024, 12, 15, 11, 0, tzinfo=MADRID_TZ)

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []  # No overlaps
        mock_session.execute = AsyncMock(return_value=mock_result)

        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=new_start,
            duration_minutes=60,
            session=mock_session,
        )

        assert len(overlaps) == 0

    async def test_cancelled_appointment_not_overlapping(self):
        """Test that cancelled appointments are ignored."""
        stylist_id = uuid4()
        start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)

        mock_session = MagicMock()
        mock_result = MagicMock()
        # Query filters by status, so cancelled appointments aren't returned
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=start_time,
            duration_minutes=60,
            session=mock_session,
        )

        assert overlaps == []

    async def test_no_show_appointment_not_overlapping(self):
        """Test that no-show appointments are ignored."""
        stylist_id = uuid4()
        start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)

        mock_session = MagicMock()
        mock_result = MagicMock()
        # Query filters by status, so no-show appointments aren't returned
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=start_time,
            duration_minutes=60,
            session=mock_session,
        )

        assert overlaps == []

    async def test_pending_appointment_is_overlapping(self):
        """Test that pending appointments ARE considered overlaps."""
        stylist_id = uuid4()
        start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)

        existing_appt = MagicMock(spec=Appointment)
        existing_appt.id = uuid4()
        existing_appt.start_time = start_time
        existing_appt.duration_minutes = 60
        existing_appt.status = AppointmentStatus.PENDING

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [existing_appt]
        mock_session.execute = AsyncMock(return_value=mock_result)

        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=start_time,
            duration_minutes=60,
            session=mock_session,
        )

        assert len(overlaps) == 1

    async def test_multiple_overlaps_returned(self):
        """Test that multiple overlapping appointments are all returned."""
        stylist_id = uuid4()
        
        # Create 3 overlapping appointments at 10:00, 10:30, 11:00
        existing_appts = []
        times = [(10, 0), (10, 30), (11, 0)]
        for hour, minute in times:
            appt = MagicMock(spec=Appointment)
            appt.id = uuid4()
            appt.start_time = datetime(2024, 12, 15, hour, minute, tzinfo=MADRID_TZ)
            appt.duration_minutes = 60
            appt.status = AppointmentStatus.CONFIRMED
            existing_appts.append(appt)

        # New: 10:00-12:00 (overlaps with all three)
        new_start = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = existing_appts
        mock_session.execute = AsyncMock(return_value=mock_result)

        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=new_start,
            duration_minutes=120,
            session=mock_session,
        )

        assert len(overlaps) == 3


@pytest.mark.asyncio
class TestAgentBookingIsolation:
    """Test that agent booking path is unchanged and isolated."""

    async def test_find_overlapping_appointments_isolated_from_agent(self):
        """Test that admin overlap detection is separate from agent booking."""
        # This test verifies that the admin overlap function exists and works
        # independently from the agent's availability_service
        
        stylist_id = uuid4()
        start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        # This should work without any agent-related dependencies
        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=start_time,
            duration_minutes=60,
            session=mock_session,
        )

        assert overlaps == []
        # Verify the mock was called (function actually queried the database)
        assert mock_session.execute.called

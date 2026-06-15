"""
Unit tests for overlap detection functionality.

Tests coverage:
- find_overlapping_appointments() with various overlap scenarios
- GET /api/admin/appointments/check-overlaps endpoint
- POST /api/admin/appointments with overlap validation
- Edge cases: exact same time, 1-minute overlap, back-to-back no overlap
- Cancelled/No-show appointments (should NOT trigger overlap)
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from api.routes.admin import (
    OverlapCheckResponse,
    OverlapConflict,
    find_overlapping_appointments,
    parse_datetime_as_madrid,
)
from database.models import Appointment, AppointmentStatus, Customer, Service, Stylist

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ============================================================================
# Test find_overlapping_appointments()
# ============================================================================


class TestFindOverlappingAppointments:
    """Test the core overlap detection function."""

    @pytest.mark.asyncio
    async def test_no_overlaps_returns_empty_list(self):
        """Test that when no appointments exist, returns empty list."""
        # Arrange
        stylist_id = uuid4()
        start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
        duration_minutes = 60

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Act
        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=start_time,
            duration_minutes=duration_minutes,
            session=mock_session,
        )

        # Assert
        assert overlaps == []
        assert mock_session.execute.called

    @pytest.mark.asyncio
    async def test_exact_same_time_overlap(self):
        """Test that exact same time slot is detected as overlap."""
        # Arrange
        stylist_id = uuid4()
        start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
        duration_minutes = 60

        # Create existing appointment at exact same time
        existing_appt = MagicMock(spec=Appointment)
        existing_appt.id = uuid4()
        existing_appt.start_time = start_time
        existing_appt.duration_minutes = 60
        existing_appt.status = AppointmentStatus.CONFIRMED

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [existing_appt]
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Act
        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=start_time,
            duration_minutes=duration_minutes,
            session=mock_session,
        )

        # Assert
        assert len(overlaps) == 1
        assert overlaps[0].id == existing_appt.id

    @pytest.mark.asyncio
    async def test_partial_overlap_start(self):
        """Test when new appointment starts during existing appointment."""
        # Arrange
        stylist_id = uuid4()
        # Existing: 10:00-11:00
        existing_appt = MagicMock(spec=Appointment)
        existing_appt.id = uuid4()
        existing_appt.start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
        existing_appt.duration_minutes = 60
        existing_appt.status = AppointmentStatus.CONFIRMED

        # New: 10:30-11:30 (overlaps with 10:00-11:00)
        new_start = datetime(2024, 12, 15, 10, 30, tzinfo=MADRID_TZ)
        new_duration = 60

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [existing_appt]
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Act
        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=new_start,
            duration_minutes=new_duration,
            session=mock_session,
        )

        # Assert
        assert len(overlaps) == 1

    @pytest.mark.asyncio
    async def test_partial_overlap_end(self):
        """Test when new appointment ends during existing appointment."""
        # Arrange
        stylist_id = uuid4()
        # Existing: 11:00-12:00
        existing_appt = MagicMock(spec=Appointment)
        existing_appt.id = uuid4()
        existing_appt.start_time = datetime(2024, 12, 15, 11, 0, tzinfo=MADRID_TZ)
        existing_appt.duration_minutes = 60
        existing_appt.status = AppointmentStatus.CONFIRMED

        # New: 10:30-11:30 (overlaps with 11:00-12:00)
        new_start = datetime(2024, 12, 15, 10, 30, tzinfo=MADRID_TZ)
        new_duration = 60

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [existing_appt]
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Act
        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=new_start,
            duration_minutes=new_duration,
            session=mock_session,
        )

        # Assert
        assert len(overlaps) == 1

    @pytest.mark.asyncio
    async def test_complete_containment_overlap(self):
        """Test when new appointment completely contains existing appointment."""
        # Arrange
        stylist_id = uuid4()
        # Existing: 10:30-11:00
        existing_appt = MagicMock(spec=Appointment)
        existing_appt.id = uuid4()
        existing_appt.start_time = datetime(2024, 12, 15, 10, 30, tzinfo=MADRID_TZ)
        existing_appt.duration_minutes = 30
        existing_appt.status = AppointmentStatus.CONFIRMED

        # New: 10:00-12:00 (completely contains 10:30-11:00)
        new_start = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
        new_duration = 120

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [existing_appt]
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Act
        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=new_start,
            duration_minutes=new_duration,
            session=mock_session,
        )

        # Assert
        assert len(overlaps) == 1

    @pytest.mark.asyncio
    async def test_one_minute_overlap_detected(self):
        """Test that even 1-minute overlap is detected."""
        # Arrange
        stylist_id = uuid4()
        # Existing: 10:00-11:00
        existing_appt = MagicMock(spec=Appointment)
        existing_appt.id = uuid4()
        existing_appt.start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
        existing_appt.duration_minutes = 60
        existing_appt.status = AppointmentStatus.CONFIRMED

        # New: 10:59-11:59 (overlaps 1 minute with 10:00-11:00)
        new_start = datetime(2024, 12, 15, 10, 59, tzinfo=MADRID_TZ)
        new_duration = 60

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [existing_appt]
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Act
        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=new_start,
            duration_minutes=new_duration,
            session=mock_session,
        )

        # Assert
        assert len(overlaps) == 1

    @pytest.mark.asyncio
    async def test_back_to_back_no_overlap(self):
        """Test that back-to-back appointments don't overlap."""
        # Arrange
        stylist_id = uuid4()
        # Existing: 10:00-11:00
        existing_appt = MagicMock(spec=Appointment)
        existing_appt.id = uuid4()
        existing_appt.start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
        existing_appt.duration_minutes = 60
        existing_appt.status = AppointmentStatus.CONFIRMED

        # New: 11:00-12:00 (starts exactly when existing ends - NO overlap)
        new_start = datetime(2024, 12, 15, 11, 0, tzinfo=MADRID_TZ)
        new_duration = 60

        mock_session = MagicMock()
        mock_result = MagicMock()
        # Should return empty since there's no actual overlap
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Act
        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=new_start,
            duration_minutes=new_duration,
            session=mock_session,
        )

        # Assert
        assert len(overlaps) == 0

    @pytest.mark.asyncio
    async def test_cancelled_appointment_ignored(self):
        """Test that cancelled appointments are not considered overlaps."""
        # Arrange
        stylist_id = uuid4()
        start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
        duration_minutes = 60

        mock_session = MagicMock()
        mock_result = MagicMock()
        # Query filters by status, so cancelled appointments aren't returned
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Act
        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=start_time,
            duration_minutes=duration_minutes,
            session=mock_session,
        )

        # Assert
        assert overlaps == []

    @pytest.mark.asyncio
    async def test_no_show_appointment_ignored(self):
        """Test that no-show appointments are not considered overlaps."""
        # Arrange
        stylist_id = uuid4()
        start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
        duration_minutes = 60

        mock_session = MagicMock()
        mock_result = MagicMock()
        # Query filters by status, so no-show appointments aren't returned
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Act
        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=start_time,
            duration_minutes=duration_minutes,
            session=mock_session,
        )

        # Assert
        assert overlaps == []

    @pytest.mark.asyncio
    async def test_multiple_overlaps_returned(self):
        """Test that multiple overlapping appointments are all returned."""
        # Arrange
        stylist_id = uuid4()
        # Multiple existing appointments that overlap with new one
        # Stagger by 30 minutes: 10:00, 10:30, 11:00 - all overlap with 10:00-12:00
        existing_appts = []
        for i in range(3):
            appt = MagicMock(spec=Appointment)
            appt.id = uuid4()
            appt.start_time = datetime(2024, 12, 15, 10 + i//2, (i % 2) * 30, tzinfo=MADRID_TZ)
            appt.duration_minutes = 60
            appt.status = AppointmentStatus.CONFIRMED
            existing_appts.append(appt)

        # New: 10:00-12:00 (overlaps with all three)
        new_start = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
        new_duration = 120

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = existing_appts
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Act
        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=new_start,
            duration_minutes=new_duration,
            session=mock_session,
        )

        # Assert
        assert len(overlaps) == 3


# ============================================================================
# Test OverlapCheckResponse models
# ============================================================================


class TestOverlapCheckResponse:
    """Test Pydantic response models."""

    def test_overlap_conflict_creation(self):
        """Test creating OverlapConflict model."""
        conflict = OverlapConflict(
            appointment_id=uuid4(),
            customer_name="Jane Doe",
            service_names="Cortar, Mechas",
            start_time=datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ),
            end_time=datetime(2024, 12, 15, 11, 0, tzinfo=MADRID_TZ),
            status="confirmed",
        )

        assert conflict.customer_name == "Jane Doe"
        assert conflict.status == "confirmed"

    def test_overlap_check_response_creation(self):
        """Test creating OverlapCheckResponse model."""
        conflict = OverlapConflict(
            appointment_id=uuid4(),
            customer_name="Jane Doe",
            service_names="Cortar",
            start_time=datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ),
            end_time=datetime(2024, 12, 15, 11, 0, tzinfo=MADRID_TZ),
            status="confirmed",
        )

        response = OverlapCheckResponse(
            has_overlaps=True,
            conflicts=[conflict],
            checked_range={
                "start_time": "2024-12-15T10:00:00+01:00",
                "end_time": "2024-12-15T11:00:00+01:00",
                "duration_minutes": 60,
            }
        )

        assert response.has_overlaps is True
        assert len(response.conflicts) == 1

    def test_no_overlaps_response(self):
        """Test response when no overlaps."""
        response = OverlapCheckResponse(
            has_overlaps=False,
            conflicts=[],
            checked_range={
                "start_time": "2024-12-15T10:00:00+01:00",
                "end_time": "2024-12-15T11:00:00+01:00",
                "duration_minutes": 60,
            }
        )

        assert response.has_overlaps is False
        assert response.conflicts == []


# ============================================================================
# Test GET /api/admin/appointments/check-overlaps endpoint
# ============================================================================


class TestCheckOverlapsEndpoint:
    """Test the check-overlaps API endpoint."""

    @pytest.mark.asyncio
    async def test_check_overlaps_no_conflicts(self):
        """Test endpoint returns no overlaps when slot is free."""
        with patch("api.routes.admin.get_async_session") as mock_session_ctx, \
             patch("api.routes.admin.find_overlapping_appointments") as mock_find:

            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            # Mock stylist exists — use explicit MagicMock to avoid AsyncMock chaining issues
            mock_stylist = MagicMock()
            mock_stylist.id = uuid4()
            mock_stylist.name = "Test Stylist"
            stylist_result = MagicMock()
            stylist_result.scalar_one_or_none.return_value = mock_stylist
            mock_session.execute = AsyncMock(return_value=stylist_result)

            # No overlaps
            mock_find.return_value = []

            # Import here to avoid circular import issues
            from api.routes.admin import check_overlaps

            # Act
            result = await check_overlaps(
                stylist_id=uuid4(),
                start_time=datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ),
                duration_minutes=60,
                current_user={"username": "admin"},
            )

            # Assert
            assert result.has_overlaps is False
            assert result.conflicts == []

    @pytest.mark.asyncio
    async def test_check_overlaps_with_conflicts(self):
        """Test endpoint returns overlaps when they exist."""
        with patch("api.routes.admin.get_async_session") as mock_session_ctx, \
             patch("api.routes.admin.find_overlapping_appointments") as mock_find:

            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            # Mock stylist exists
            mock_stylist = MagicMock()
            mock_stylist.id = uuid4()
            mock_stylist.name = "Test Stylist"

            # Mock service query
            mock_service = MagicMock(spec=Service)
            mock_service.name = "Cortar"

            # Use explicit MagicMock return values to avoid AsyncMock chaining issues
            stylist_result = MagicMock()
            stylist_result.scalar_one_or_none.return_value = mock_stylist

            services_result = MagicMock()
            services_result.scalars.return_value.all.return_value = [mock_service]

            mock_session.execute = AsyncMock(side_effect=[stylist_result, services_result])

            # Create overlapping appointment
            mock_appt = MagicMock(spec=Appointment)
            mock_appt.id = uuid4()
            mock_appt.start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
            mock_appt.duration_minutes = 60
            mock_appt.status = AppointmentStatus.CONFIRMED
            mock_appt.first_name = "Jane"
            mock_appt.last_name = "Doe"
            mock_appt.service_ids = [uuid4()]

            mock_find.return_value = [mock_appt]

            # Import here to avoid circular import issues
            from api.routes.admin import check_overlaps

            # Act
            result = await check_overlaps(
                stylist_id=uuid4(),
                start_time=datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ),
                duration_minutes=60,
                current_user={"username": "admin"},
            )

            # Assert
            assert result.has_overlaps is True
            assert len(result.conflicts) == 1
            assert result.conflicts[0].customer_name == "Jane Doe"

    @pytest.mark.asyncio
    async def test_check_overlaps_invalid_duration(self):
        """Test endpoint validates duration is positive."""
        from api.routes.admin import check_overlaps

        with pytest.raises(HTTPException) as exc_info:
            await check_overlaps(
                stylist_id=uuid4(),
                start_time=datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ),
                duration_minutes=0,
                current_user={"username": "admin"},
            )

        assert exc_info.value.status_code == 400
        assert "duration_minutes must be greater than 0" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_check_overlaps_invalid_stylist(self):
        """Test endpoint returns 404 for non-existent stylist."""
        with patch("api.routes.admin.get_async_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            # Stylist doesn't exist — use explicit MagicMock to avoid AsyncMock chaining issues
            not_found_result = MagicMock()
            not_found_result.scalar_one_or_none.return_value = None
            mock_session.execute = AsyncMock(return_value=not_found_result)

            from api.routes.admin import check_overlaps

            with pytest.raises(HTTPException) as exc_info:
                await check_overlaps(
                    stylist_id=uuid4(),
                    start_time=datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ),
                    duration_minutes=60,
                    current_user={"username": "admin"},
                )

            assert exc_info.value.status_code == 404
            assert "Stylist not found" in exc_info.value.detail


# ============================================================================
# Test POST /api/admin/appointments endpoint
# ============================================================================


class TestCreateAppointmentEndpoint:
    """Test the create appointment endpoint with overlap validation."""

    @pytest.mark.asyncio
    async def test_create_appointment_no_overlap(self):
        """Test creating appointment when slot is free."""
        with patch("api.routes.admin.get_async_session") as mock_session_ctx, \
             patch("api.routes.admin.find_overlapping_appointments") as mock_find, \
             patch("api.routes.admin._safe_send_admin_appointment_template") as mock_notify, \
             patch("shared.gcal_push_service.push_appointment_to_gcal", new_callable=AsyncMock, return_value=None):

            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            customer_id = uuid4()
            stylist_id = uuid4()
            service_id = uuid4()

            # Mock customer exists
            mock_customer = MagicMock(spec=Customer)
            mock_customer.id = customer_id
            mock_customer.phone = "+34600123456"
            mock_customer.first_name = "John"
            mock_session.execute.return_value.scalar_one_or_none.return_value = mock_customer

            # Mock stylist exists and active
            mock_stylist = MagicMock(spec=Stylist)
            mock_stylist.id = stylist_id
            mock_stylist.is_active = True
            mock_stylist.google_calendar_id = "test_calendar"

            # Mock service exists
            mock_service = MagicMock(spec=Service)
            mock_service.id = service_id
            mock_service.name = "Corte"
            mock_service.duration_minutes = 60

            # Setup sequential query results
            async def mock_execute(stmt):
                mock_result = MagicMock()
                # First query: customer
                if "customers" in str(stmt):
                    mock_result.scalar_one_or_none.return_value = mock_customer
                # Second query: stylist
                elif "stylists" in str(stmt):
                    mock_result.scalar_one_or_none.return_value = mock_stylist
                # Third query: services
                elif "services" in str(stmt):
                    mock_result.scalars.return_value.all.return_value = [mock_service]
                return mock_result

            mock_session.execute = mock_execute

            # No overlaps
            mock_find.return_value = []

            # Mock the created appointment
            mock_appt = MagicMock(spec=Appointment)
            mock_appt.id = uuid4()
            mock_appt.first_name = "John"
            mock_session.add = MagicMock()
            mock_session.commit = AsyncMock()
            mock_session.refresh = AsyncMock()

            from api.routes.admin import CreateAppointmentRequest, create_appointment

            request = CreateAppointmentRequest(
                customer_id=customer_id,
                stylist_id=stylist_id,
                service_ids=[service_id],
                start_time=datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ),
                first_name="John",
                last_name="Doe",
                allow_overlap=False,
            )

            # Act - should not raise
            result = await create_appointment(
                request=request,
                current_user={"username": "admin"},
            )

            # Assert
            assert result is not None
            mock_find.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_appointment_with_overlap_rejected(self):
        """Test creating appointment fails when overlaps exist and allow_overlap=false."""
        with patch("api.routes.admin.get_async_session") as mock_session_ctx, \
             patch("api.routes.admin.find_overlapping_appointments") as mock_find:

            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            customer_id = uuid4()
            stylist_id = uuid4()
            service_id = uuid4()

            # Mock customer exists
            mock_customer = MagicMock(spec=Customer)
            mock_customer.id = customer_id
            mock_customer.phone = "+34600123456"
            mock_customer.first_name = "John"

            # Mock stylist exists and active
            mock_stylist = MagicMock(spec=Stylist)
            mock_stylist.id = stylist_id
            mock_stylist.is_active = True

            # Mock service exists
            mock_service = MagicMock(spec=Service)
            mock_service.id = service_id
            mock_service.duration_minutes = 60
            mock_service.name = "Cortar"

            async def mock_execute(stmt):
                mock_result = MagicMock()
                if "customers" in str(stmt):
                    mock_result.scalar_one_or_none.return_value = mock_customer
                elif "stylists" in str(stmt):
                    mock_result.scalar_one_or_none.return_value = mock_stylist
                elif "services" in str(stmt):
                    mock_result.scalars.return_value.all.return_value = [mock_service]
                return mock_result

            mock_session.execute = mock_execute

            # Create overlapping appointment
            mock_overlap_appt = MagicMock(spec=Appointment)
            mock_overlap_appt.id = uuid4()
            mock_overlap_appt.start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
            mock_overlap_appt.duration_minutes = 60
            mock_overlap_appt.status = AppointmentStatus.CONFIRMED
            mock_overlap_appt.first_name = "Jane"
            mock_overlap_appt.last_name = "Doe"
            mock_overlap_appt.service_ids = [service_id]

            mock_find.return_value = [mock_overlap_appt]

            from api.routes.admin import CreateAppointmentRequest, create_appointment

            request = CreateAppointmentRequest(
                customer_id=customer_id,
                stylist_id=stylist_id,
                service_ids=[service_id],
                start_time=datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ),
                first_name="John",
                allow_overlap=False,  # Don't allow overlap
            )

            # Act - should raise 409
            with pytest.raises(HTTPException) as exc_info:
                await create_appointment(
                    request=request,
                    current_user={"username": "admin"},
                )

            # Assert
            assert exc_info.value.status_code == 409
            assert "overlaps" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_create_appointment_with_overlap_allowed(self):
        """Test creating appointment succeeds when overlaps exist and allow_overlap=true."""
        with patch("api.routes.admin.get_async_session") as mock_session_ctx, \
             patch("api.routes.admin.find_overlapping_appointments") as mock_find, \
             patch("api.routes.admin._safe_send_admin_appointment_template") as mock_notify, \
             patch("shared.gcal_push_service.push_appointment_to_gcal", new_callable=AsyncMock, return_value=None):

            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            customer_id = uuid4()
            stylist_id = uuid4()
            service_id = uuid4()

            # Mock customer exists
            mock_customer = MagicMock(spec=Customer)
            mock_customer.id = customer_id
            mock_customer.phone = "+34600123456"
            mock_customer.first_name = "John"

            # Mock stylist exists and active
            mock_stylist = MagicMock(spec=Stylist)
            mock_stylist.id = stylist_id
            mock_stylist.is_active = True
            mock_stylist.google_calendar_id = "test_calendar"

            # Mock service exists
            mock_service = MagicMock(spec=Service)
            mock_service.id = service_id
            mock_service.name = "Corte"
            mock_service.duration_minutes = 60

            async def mock_execute(stmt):
                mock_result = MagicMock()
                if "customers" in str(stmt):
                    mock_result.scalar_one_or_none.return_value = mock_customer
                elif "stylists" in str(stmt):
                    mock_result.scalar_one_or_none.return_value = mock_stylist
                elif "services" in str(stmt):
                    mock_result.scalars.return_value.all.return_value = [mock_service]
                return mock_result

            mock_session.execute = mock_execute

            # Create overlapping appointment (but we allow it)
            mock_overlap_appt = MagicMock(spec=Appointment)
            mock_overlap_appt.id = uuid4()
            mock_overlap_appt.start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
            mock_overlap_appt.duration_minutes = 60
            mock_overlap_appt.status = AppointmentStatus.CONFIRMED
            mock_overlap_appt.first_name = "Jane"
            mock_overlap_appt.last_name = "Doe"
            mock_overlap_appt.service_ids = [service_id]

            mock_find.return_value = [mock_overlap_appt]

            from api.routes.admin import CreateAppointmentRequest, create_appointment

            request = CreateAppointmentRequest(
                customer_id=customer_id,
                stylist_id=stylist_id,
                service_ids=[service_id],
                start_time=datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ),
                first_name="John",
                allow_overlap=True,  # Allow overlap
            )

            # Act - should not raise (overlap is allowed)
            result = await create_appointment(
                request=request,
                current_user={"username": "admin"},
            )

            # Assert - appointment created successfully
            assert result is not None

    @pytest.mark.asyncio
    async def test_create_appointment_customer_not_found(self):
        """Test 404 when customer doesn't exist."""
        with patch("api.routes.admin.get_async_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            # Customer doesn't exist — use explicit MagicMock to avoid AsyncMock chaining issues
            not_found_result = MagicMock()
            not_found_result.scalar_one_or_none.return_value = None
            mock_session.execute = AsyncMock(return_value=not_found_result)

            from api.routes.admin import CreateAppointmentRequest, create_appointment

            request = CreateAppointmentRequest(
                customer_id=uuid4(),
                stylist_id=uuid4(),
                service_ids=[uuid4()],
                start_time=datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ),
                first_name="John",
            )

            with pytest.raises(HTTPException) as exc_info:
                await create_appointment(
                    request=request,
                    current_user={"username": "admin"},
                )

            assert exc_info.value.status_code == 404
            assert "Customer not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_create_appointment_inactive_stylist(self):
        """Test 400 when stylist is not active."""
        with patch("api.routes.admin.get_async_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            customer_id = uuid4()
            stylist_id = uuid4()

            # Mock customer exists
            mock_customer = MagicMock(spec=Customer)
            mock_customer.id = customer_id

            # Mock stylist exists but inactive
            mock_stylist = MagicMock(spec=Stylist)
            mock_stylist.id = stylist_id
            mock_stylist.is_active = False

            async def mock_execute(stmt):
                mock_result = MagicMock()
                if "customers" in str(stmt):
                    mock_result.scalar_one_or_none.return_value = mock_customer
                elif "stylists" in str(stmt):
                    mock_result.scalar_one_or_none.return_value = mock_stylist
                return mock_result

            mock_session.execute = mock_execute

            from api.routes.admin import CreateAppointmentRequest, create_appointment

            request = CreateAppointmentRequest(
                customer_id=customer_id,
                stylist_id=stylist_id,
                service_ids=[uuid4()],
                start_time=datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ),
                first_name="John",
            )

            with pytest.raises(HTTPException) as exc_info:
                await create_appointment(
                    request=request,
                    current_user={"username": "admin"},
                )

            assert exc_info.value.status_code == 400
            assert "Stylist is not active" in exc_info.value.detail


# ============================================================================
# Test parse_datetime_as_madrid helper
# ============================================================================


class TestParseDatetimeAsMadrid:
    """Test datetime parsing helper."""

    def test_parse_naive_datetime(self):
        """Test that naive datetime gets Madrid timezone."""
        dt = parse_datetime_as_madrid("2024-12-15T10:00:00")
        assert dt.tzinfo is not None
        assert str(dt.tzinfo) == "Europe/Madrid"

    def test_parse_iso_with_timezone(self):
        """Test datetime with timezone is preserved."""
        dt = parse_datetime_as_madrid("2024-12-15T10:00:00+01:00")
        assert dt.tzinfo is not None

    def test_parse_datetime_object(self):
        """Test parsing datetime object."""
        input_dt = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
        dt = parse_datetime_as_madrid(input_dt)
        assert dt == input_dt

    def test_parse_none_returns_none(self):
        """Test None input returns None."""
        dt = parse_datetime_as_madrid(None)
        assert dt is None

    def test_parse_z_suffix(self):
        """Test Z suffix is handled correctly."""
        dt = parse_datetime_as_madrid("2024-12-15T10:00:00Z")
        assert dt.tzinfo is not None


# ============================================================================
# Edge case tests
# ============================================================================


class TestEdgeCases:
    """Test edge cases for overlap detection."""

    @pytest.mark.asyncio
    async def test_completed_appointment_ignored(self):
        """Test that completed appointments are not considered overlaps."""
        # Arrange
        stylist_id = uuid4()
        start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
        duration_minutes = 60

        mock_session = MagicMock()
        mock_result = MagicMock()
        # Query filters by status, so completed appointments aren't returned
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Act
        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=start_time,
            duration_minutes=duration_minutes,
            session=mock_session,
        )

        # Assert
        assert overlaps == []

    @pytest.mark.asyncio
    async def test_overlap_with_pending_status(self):
        """Test that pending appointments ARE considered overlaps."""
        # Arrange
        stylist_id = uuid4()
        start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
        duration_minutes = 60

        # Create pending appointment at same time
        existing_appt = MagicMock(spec=Appointment)
        existing_appt.id = uuid4()
        existing_appt.start_time = start_time
        existing_appt.duration_minutes = 60
        existing_appt.status = AppointmentStatus.PENDING

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [existing_appt]
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Act
        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=start_time,
            duration_minutes=duration_minutes,
            session=mock_session,
        )

        # Assert
        assert len(overlaps) == 1

    @pytest.mark.asyncio
    async def test_overlap_with_confirmed_status(self):
        """Test that confirmed appointments ARE considered overlaps."""
        # Arrange
        stylist_id = uuid4()
        start_time = datetime(2024, 12, 15, 10, 0, tzinfo=MADRID_TZ)
        duration_minutes = 60

        # Create confirmed appointment at same time
        existing_appt = MagicMock(spec=Appointment)
        existing_appt.id = uuid4()
        existing_appt.start_time = start_time
        existing_appt.duration_minutes = 60
        existing_appt.status = AppointmentStatus.CONFIRMED

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [existing_appt]
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Act
        overlaps = await find_overlapping_appointments(
            stylist_id=stylist_id,
            start_time=start_time,
            duration_minutes=duration_minutes,
            session=mock_session,
        )

        # Assert
        assert len(overlaps) == 1

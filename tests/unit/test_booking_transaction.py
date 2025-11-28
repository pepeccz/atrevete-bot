"""
Unit tests for booking_transaction.py - Atomic booking transaction handler.

Tests coverage:
- BookingTransaction.execute() - Complete atomic transaction flow
- Success path: All validations pass, calendar created, DB committed
- Validation failures: 3-day rule, category consistency, slot availability
- Service/stylist not found errors
- Calendar event creation failure with rollback
- Database errors (IntegrityError, SQLAlchemyError) with rollback
- Transaction isolation (SERIALIZABLE)
- Rollback cleanup (calendar event deletion)
- Duration calculation with buffer
- Friendly confirmation message formatting
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from agent.transactions.booking_transaction import BookingTransaction, BUFFER_MINUTES
from database.models import AppointmentStatus, ServiceCategory

# Madrid timezone
MADRID_TZ = ZoneInfo("Europe/Madrid")


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def customer_id():
    """Fixed customer UUID for testing."""
    return UUID("550e8400-e29b-41d4-a716-446655440000")


@pytest.fixture
def stylist_id():
    """Fixed stylist UUID for testing."""
    return UUID("660e8400-e29b-41d4-a716-446655440001")


@pytest.fixture
def service_ids():
    """List of service UUIDs for testing."""
    return [
        UUID("770e8400-e29b-41d4-a716-446655440002"),
        UUID("880e8400-e29b-41d4-a716-446655440003")
    ]


@pytest.fixture
def valid_start_time():
    """Valid start time (5 days in future)."""
    return datetime.now(MADRID_TZ) + timedelta(days=5)


@pytest.fixture
def mock_services():
    """Mock Service database models."""
    service1 = MagicMock()
    service1.id = UUID("770e8400-e29b-41d4-a716-446655440002")
    service1.name = "Corte de Caballero"
    service1.duration_minutes = 30
    service1.category = ServiceCategory.PELUQUERIA

    service2 = MagicMock()
    service2.id = UUID("880e8400-e29b-41d4-a716-446655440003")
    service2.name = "Barba"
    service2.duration_minutes = 15
    service2.category = ServiceCategory.PELUQUERIA

    return [service1, service2]


@pytest.fixture
def mock_stylist():
    """Mock Stylist database model."""
    stylist = MagicMock()
    stylist.id = UUID("660e8400-e29b-41d4-a716-446655440001")
    stylist.name = "María García"
    stylist.google_calendar_id = "maria@salon.com"
    return stylist


# ============================================================================
# Test Success Path
# ============================================================================


class TestBookingTransactionSuccess:
    """Test successful booking transaction flow."""

    @pytest.mark.asyncio
    async def test_successful_booking_complete_flow(
        self, customer_id, stylist_id, service_ids, valid_start_time, mock_services, mock_stylist
    ):
        """Test complete successful booking flow."""
        # Mock validators - all pass
        with patch("agent.transactions.booking_transaction.validate_3_day_rule") as mock_3day, \
             patch("agent.transactions.booking_transaction.validate_category_consistency") as mock_category, \
             patch("agent.transactions.booking_transaction.validate_slot_availability") as mock_slot, \
             patch("agent.transactions.booking_transaction.create_calendar_event") as mock_calendar, \
             patch("agent.transactions.booking_transaction.get_async_session") as mock_session:

            # Setup validator mocks
            mock_3day.return_value = {"valid": True, "days_until_appointment": 5}
            mock_category.return_value = {"valid": True}
            mock_slot.return_value = {"available": True}

            # Setup calendar mock
            mock_calendar.return_value = {"success": True, "event_id": "google_event_123"}

            # Setup database session mock
            session = AsyncMock()
            mock_session.return_value.__aenter__.return_value = session

            # Mock Service query
            service_result = AsyncMock()
            service_result.scalars.return_value.all.return_value = mock_services
            session.execute.return_value = service_result

            # Mock Stylist query (second execute call)
            stylist_result = AsyncMock()
            stylist_result.scalar_one_or_none.return_value = mock_stylist

            # Setup execute to return different results based on call
            call_count = [0]

            async def execute_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    return AsyncMock()  # SET TRANSACTION
                elif call_count[0] == 2:
                    return service_result  # Services query
                elif call_count[0] == 3:
                    return stylist_result  # Stylist query
                else:
                    return AsyncMock()  # Customer query

            session.execute.side_effect = execute_side_effect

            # Mock appointment creation
            new_appointment = MagicMock()
            new_appointment.id = uuid4()

            # Execute transaction
            result = await BookingTransaction.execute(
                customer_id=customer_id,
                service_ids=service_ids,
                stylist_id=stylist_id,
                start_time=valid_start_time,
                first_name="Pepe",
                last_name="Cabeza",
                notes="Sin alergia"
            )

            # Assertions
            assert result["success"] is True
            assert "appointment_id" in result
            assert result["google_calendar_event_id"] == "google_event_123"
            assert result["duration_minutes"] == 45  # 30 + 15
            assert result["status"] == "pending"
            assert "message" in result
            assert "¡Cita confirmada!" in result["message"]

            # Verify validators were called
            mock_3day.assert_called_once()
            mock_category.assert_called_once_with(service_ids)
            mock_slot.assert_called_once()

            # Verify calendar event was created
            mock_calendar.assert_called_once()

            # Verify session.commit() was called
            session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_duration_calculation_with_buffer(
        self, customer_id, stylist_id, service_ids, valid_start_time, mock_services, mock_stylist
    ):
        """Test that duration is calculated correctly with buffer."""
        with patch("agent.transactions.booking_transaction.validate_3_day_rule") as mock_3day, \
             patch("agent.transactions.booking_transaction.validate_category_consistency") as mock_category, \
             patch("agent.transactions.booking_transaction.validate_slot_availability") as mock_slot, \
             patch("agent.transactions.booking_transaction.create_calendar_event") as mock_calendar, \
             patch("agent.transactions.booking_transaction.get_async_session") as mock_session:

            mock_3day.return_value = {"valid": True, "days_until_appointment": 5}
            mock_category.return_value = {"valid": True}
            mock_slot.return_value = {"available": True}
            mock_calendar.return_value = {"success": True, "event_id": "google_event_123"}

            session = AsyncMock()
            mock_session.return_value.__aenter__.return_value = session

            service_result = AsyncMock()
            service_result.scalars.return_value.all.return_value = mock_services
            stylist_result = AsyncMock()
            stylist_result.scalar_one_or_none.return_value = mock_stylist

            call_count = [0]

            async def execute_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 2:
                    return service_result
                elif call_count[0] == 3:
                    return stylist_result
                return AsyncMock()

            session.execute.side_effect = execute_side_effect

            result = await BookingTransaction.execute(
                customer_id=customer_id,
                service_ids=service_ids,
                stylist_id=stylist_id,
                start_time=valid_start_time,
                first_name="Pepe",
                last_name=None,
                notes=None
            )

            # Total duration should be 45 (30 + 15)
            assert result["duration_minutes"] == 45

            # Calendar should be called with buffer (45 + 10 = 55)
            calendar_call = mock_calendar.call_args
            assert calendar_call[1]["duration_minutes"] == 55

    @pytest.mark.asyncio
    async def test_friendly_confirmation_message_format(
        self, customer_id, stylist_id, service_ids, mock_services, mock_stylist
    ):
        """Test that confirmation message is properly formatted in Spanish."""
        # Use specific date for predictable formatting
        specific_date = datetime(2025, 11, 22, 10, 0, 0, tzinfo=MADRID_TZ)  # Friday Nov 22

        with patch("agent.transactions.booking_transaction.validate_3_day_rule") as mock_3day, \
             patch("agent.transactions.booking_transaction.validate_category_consistency") as mock_category, \
             patch("agent.transactions.booking_transaction.validate_slot_availability") as mock_slot, \
             patch("agent.transactions.booking_transaction.create_calendar_event") as mock_calendar, \
             patch("agent.transactions.booking_transaction.get_async_session") as mock_session:

            mock_3day.return_value = {"valid": True, "days_until_appointment": 5}
            mock_category.return_value = {"valid": True}
            mock_slot.return_value = {"available": True}
            mock_calendar.return_value = {"success": True, "event_id": "google_event_123"}

            session = AsyncMock()
            mock_session.return_value.__aenter__.return_value = session

            service_result = AsyncMock()
            service_result.scalars.return_value.all.return_value = mock_services
            stylist_result = AsyncMock()
            stylist_result.scalar_one_or_none.return_value = mock_stylist

            call_count = [0]

            async def execute_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 2:
                    return service_result
                elif call_count[0] == 3:
                    return stylist_result
                return AsyncMock()

            session.execute.side_effect = execute_side_effect

            result = await BookingTransaction.execute(
                customer_id=customer_id,
                service_ids=service_ids,
                stylist_id=stylist_id,
                start_time=specific_date,
                first_name="Pepe",
                last_name="Cabeza",
                notes=None
            )

            # Check message format
            message = result["message"]
            assert "¡Cita confirmada!" in message
            assert "viernes 22 de noviembre a las 10:00" in message
            assert "María García" in message
            assert "Corte de Caballero, Barba" in message


# ============================================================================
# Test Validation Failures
# ============================================================================


class TestValidationFailures:
    """Test validation failure scenarios."""

    @pytest.mark.asyncio
    async def test_3_day_rule_validation_failure(
        self, customer_id, stylist_id, service_ids
    ):
        """Test booking fails when 3-day rule is violated."""
        tomorrow = datetime.now(MADRID_TZ) + timedelta(days=1)

        with patch("agent.transactions.booking_transaction.validate_3_day_rule") as mock_3day:
            mock_3day.return_value = {
                "valid": False,
                "error_code": "DATE_TOO_SOON",
                "error_message": "La cita debe ser con al menos 3 días de antelación",
                "days_until_appointment": 1,
                "minimum_required_days": 3
            }

            result = await BookingTransaction.execute(
                customer_id=customer_id,
                service_ids=service_ids,
                stylist_id=stylist_id,
                start_time=tomorrow,
                first_name="Pepe",
                last_name=None,
                notes=None
            )

            assert result["success"] is False
            assert result["error_code"] == "DATE_TOO_SOON"
            assert "3 días" in result["error_message"]
            assert result["details"]["days_until_appointment"] == 1

    @pytest.mark.asyncio
    async def test_category_consistency_validation_failure(
        self, customer_id, stylist_id, service_ids, valid_start_time
    ):
        """Test booking fails when services have mixed categories."""
        with patch("agent.transactions.booking_transaction.validate_3_day_rule") as mock_3day, \
             patch("agent.transactions.booking_transaction.validate_category_consistency") as mock_category:

            mock_3day.return_value = {"valid": True}
            mock_category.return_value = {
                "valid": False,
                "error_code": "CATEGORY_MISMATCH",
                "error_message": "No se pueden combinar servicios de Peluquería y Estética",
                "categories_found": ["PELUQUERIA", "ESTETICA"]
            }

            result = await BookingTransaction.execute(
                customer_id=customer_id,
                service_ids=service_ids,
                stylist_id=stylist_id,
                start_time=valid_start_time,
                first_name="Pepe",
                last_name=None,
                notes=None
            )

            assert result["success"] is False
            assert result["error_code"] == "CATEGORY_MISMATCH"
            assert result["details"]["categories_found"] == ["PELUQUERIA", "ESTETICA"]

    @pytest.mark.asyncio
    async def test_slot_availability_validation_failure(
        self, customer_id, stylist_id, service_ids, valid_start_time, mock_services, mock_stylist
    ):
        """Test booking fails when slot is already taken."""
        with patch("agent.transactions.booking_transaction.validate_3_day_rule") as mock_3day, \
             patch("agent.transactions.booking_transaction.validate_category_consistency") as mock_category, \
             patch("agent.transactions.booking_transaction.validate_slot_availability") as mock_slot, \
             patch("agent.transactions.booking_transaction.get_async_session") as mock_session:

            mock_3day.return_value = {"valid": True}
            mock_category.return_value = {"valid": True}
            mock_slot.return_value = {
                "available": False,
                "error_code": "SLOT_TAKEN",
                "error_message": "El horario seleccionado ya está ocupado",
                "conflicting_appointment_id": uuid4()
            }

            session = AsyncMock()
            mock_session.return_value.__aenter__.return_value = session

            service_result = AsyncMock()
            service_result.scalars.return_value.all.return_value = mock_services
            stylist_result = AsyncMock()
            stylist_result.scalar_one_or_none.return_value = mock_stylist

            call_count = [0]

            async def execute_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 2:
                    return service_result
                elif call_count[0] == 3:
                    return stylist_result
                return AsyncMock()

            session.execute.side_effect = execute_side_effect

            result = await BookingTransaction.execute(
                customer_id=customer_id,
                service_ids=service_ids,
                stylist_id=stylist_id,
                start_time=valid_start_time,
                first_name="Pepe",
                last_name=None,
                notes=None
            )

            assert result["success"] is False
            assert result["error_code"] == "SLOT_TAKEN"
            assert "conflicting_appointment_id" in result["details"]

            # Verify rollback was called
            session.rollback.assert_called_once()


# ============================================================================
# Test Service/Stylist Not Found
# ============================================================================


class TestNotFoundErrors:
    """Test scenarios where services or stylist are not found."""

    @pytest.mark.asyncio
    async def test_service_ids_not_found(
        self, customer_id, stylist_id, service_ids, valid_start_time
    ):
        """Test booking fails when service IDs don't exist."""
        with patch("agent.transactions.booking_transaction.validate_3_day_rule") as mock_3day, \
             patch("agent.transactions.booking_transaction.validate_category_consistency") as mock_category, \
             patch("agent.transactions.booking_transaction.get_async_session") as mock_session:

            mock_3day.return_value = {"valid": True}
            mock_category.return_value = {"valid": True}

            session = AsyncMock()
            mock_session.return_value.__aenter__.return_value = session

            # Return only 1 service instead of 2
            partial_service = MagicMock()
            partial_service.id = service_ids[0]

            service_result = AsyncMock()
            service_result.scalars.return_value.all.return_value = [partial_service]

            call_count = [0]

            async def execute_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 2:
                    return service_result
                return AsyncMock()

            session.execute.side_effect = execute_side_effect

            result = await BookingTransaction.execute(
                customer_id=customer_id,
                service_ids=service_ids,
                stylist_id=stylist_id,
                start_time=valid_start_time,
                first_name="Pepe",
                last_name=None,
                notes=None
            )

            assert result["success"] is False
            assert result["error_code"] == "INVALID_SERVICE_IDS"
            assert "missing_service_ids" in result["details"]

    @pytest.mark.asyncio
    async def test_stylist_not_found(
        self, customer_id, stylist_id, service_ids, valid_start_time, mock_services
    ):
        """Test booking fails when stylist doesn't exist."""
        with patch("agent.transactions.booking_transaction.validate_3_day_rule") as mock_3day, \
             patch("agent.transactions.booking_transaction.validate_category_consistency") as mock_category, \
             patch("agent.transactions.booking_transaction.get_async_session") as mock_session:

            mock_3day.return_value = {"valid": True}
            mock_category.return_value = {"valid": True}

            session = AsyncMock()
            mock_session.return_value.__aenter__.return_value = session

            service_result = AsyncMock()
            service_result.scalars.return_value.all.return_value = mock_services

            stylist_result = AsyncMock()
            stylist_result.scalar_one_or_none.return_value = None  # Stylist not found

            call_count = [0]

            async def execute_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 2:
                    return service_result
                elif call_count[0] == 3:
                    return stylist_result
                return AsyncMock()

            session.execute.side_effect = execute_side_effect

            result = await BookingTransaction.execute(
                customer_id=customer_id,
                service_ids=service_ids,
                stylist_id=stylist_id,
                start_time=valid_start_time,
                first_name="Pepe",
                last_name=None,
                notes=None
            )

            assert result["success"] is False
            assert result["error_code"] == "STYLIST_NOT_FOUND"


# ============================================================================
# Test Calendar Event Failure
# ============================================================================


class TestCalendarEventFailure:
    """Test calendar event creation failure with rollback."""

    @pytest.mark.asyncio
    async def test_calendar_event_creation_fails(
        self, customer_id, stylist_id, service_ids, valid_start_time, mock_services, mock_stylist
    ):
        """Test that booking fails and rolls back when calendar event creation fails."""
        with patch("agent.transactions.booking_transaction.validate_3_day_rule") as mock_3day, \
             patch("agent.transactions.booking_transaction.validate_category_consistency") as mock_category, \
             patch("agent.transactions.booking_transaction.validate_slot_availability") as mock_slot, \
             patch("agent.transactions.booking_transaction.create_calendar_event") as mock_calendar, \
             patch("agent.transactions.booking_transaction.get_async_session") as mock_session:

            mock_3day.return_value = {"valid": True}
            mock_category.return_value = {"valid": True}
            mock_slot.return_value = {"available": True}

            # Calendar creation fails
            mock_calendar.return_value = {
                "success": False,
                "error": "Google Calendar API error"
            }

            session = AsyncMock()
            mock_session.return_value.__aenter__.return_value = session

            service_result = AsyncMock()
            service_result.scalars.return_value.all.return_value = mock_services
            stylist_result = AsyncMock()
            stylist_result.scalar_one_or_none.return_value = mock_stylist

            call_count = [0]

            async def execute_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 2:
                    return service_result
                elif call_count[0] == 3:
                    return stylist_result
                return AsyncMock()

            session.execute.side_effect = execute_side_effect

            result = await BookingTransaction.execute(
                customer_id=customer_id,
                service_ids=service_ids,
                stylist_id=stylist_id,
                start_time=valid_start_time,
                first_name="Pepe",
                last_name=None,
                notes=None
            )

            assert result["success"] is False
            assert result["error_code"] == "CALENDAR_EVENT_FAILED"
            assert "Google Calendar API error" in result["details"]["calendar_error"]

            # Verify commit was NOT called (implicit rollback on exit)
            session.commit.assert_not_called()


# ============================================================================
# Test Database Errors with Rollback
# ============================================================================


class TestDatabaseErrorsRollback:
    """Test database error handling with proper rollback and cleanup."""

    @pytest.mark.asyncio
    async def test_integrity_error_triggers_rollback(
        self, customer_id, stylist_id, service_ids, valid_start_time, mock_services, mock_stylist
    ):
        """Test that IntegrityError triggers rollback."""
        from sqlalchemy.exc import IntegrityError

        with patch("agent.transactions.booking_transaction.validate_3_day_rule") as mock_3day, \
             patch("agent.transactions.booking_transaction.validate_category_consistency") as mock_category, \
             patch("agent.transactions.booking_transaction.validate_slot_availability") as mock_slot, \
             patch("agent.transactions.booking_transaction.create_calendar_event") as mock_calendar, \
             patch("agent.transactions.booking_transaction.get_async_session") as mock_session, \
             patch("agent.transactions.booking_transaction.delete_calendar_event") as mock_delete:

            mock_3day.return_value = {"valid": True}
            mock_category.return_value = {"valid": True}
            mock_slot.return_value = {"available": True}
            mock_calendar.return_value = {"success": True, "event_id": "google_event_123"}

            session = AsyncMock()
            mock_session.return_value.__aenter__.return_value = session

            service_result = AsyncMock()
            service_result.scalars.return_value.all.return_value = mock_services
            stylist_result = AsyncMock()
            stylist_result.scalar_one_or_none.return_value = mock_stylist

            # session.flush() raises IntegrityError
            session.flush.side_effect = IntegrityError("Duplicate appointment", None, None)

            call_count = [0]

            async def execute_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 2:
                    return service_result
                elif call_count[0] == 3:
                    return stylist_result
                return AsyncMock()

            session.execute.side_effect = execute_side_effect

            result = await BookingTransaction.execute(
                customer_id=customer_id,
                service_ids=service_ids,
                stylist_id=stylist_id,
                start_time=valid_start_time,
                first_name="Pepe",
                last_name=None,
                notes=None
            )

            assert result["success"] is False
            assert result["error_code"] == "DATABASE_INTEGRITY_ERROR"

            # Verify rollback was called
            session.rollback.assert_called_once()

            # Verify calendar event cleanup was attempted
            mock_delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_sqlalchemy_error_triggers_rollback(
        self, customer_id, stylist_id, service_ids, valid_start_time, mock_services, mock_stylist
    ):
        """Test that SQLAlchemyError triggers rollback."""
        from sqlalchemy.exc import SQLAlchemyError

        with patch("agent.transactions.booking_transaction.validate_3_day_rule") as mock_3day, \
             patch("agent.transactions.booking_transaction.validate_category_consistency") as mock_category, \
             patch("agent.transactions.booking_transaction.validate_slot_availability") as mock_slot, \
             patch("agent.transactions.booking_transaction.create_calendar_event") as mock_calendar, \
             patch("agent.transactions.booking_transaction.get_async_session") as mock_session, \
             patch("agent.transactions.booking_transaction.delete_calendar_event") as mock_delete:

            mock_3day.return_value = {"valid": True}
            mock_category.return_value = {"valid": True}
            mock_slot.return_value = {"available": True}
            mock_calendar.return_value = {"success": True, "event_id": "google_event_123"}

            session = AsyncMock()
            mock_session.return_value.__aenter__.return_value = session

            service_result = AsyncMock()
            service_result.scalars.return_value.all.return_value = mock_services
            stylist_result = AsyncMock()
            stylist_result.scalar_one_or_none.return_value = mock_stylist

            # session.commit() raises SQLAlchemyError
            session.commit.side_effect = SQLAlchemyError("Database connection lost")

            call_count = [0]

            async def execute_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 2:
                    return service_result
                elif call_count[0] == 3:
                    return stylist_result
                return AsyncMock()

            session.execute.side_effect = execute_side_effect

            result = await BookingTransaction.execute(
                customer_id=customer_id,
                service_ids=service_ids,
                stylist_id=stylist_id,
                start_time=valid_start_time,
                first_name="Pepe",
                last_name=None,
                notes=None
            )

            assert result["success"] is False
            assert result["error_code"] == "DATABASE_ERROR"

            # Verify rollback was called
            session.rollback.assert_called_once()

            # Verify calendar event cleanup was attempted
            mock_delete.assert_called_once()


# ============================================================================
# Test Transaction Isolation
# ============================================================================


class TestTransactionIsolation:
    """Test SERIALIZABLE transaction isolation."""

    @pytest.mark.asyncio
    async def test_serializable_isolation_set(
        self, customer_id, stylist_id, service_ids, valid_start_time, mock_services, mock_stylist
    ):
        """Test that SERIALIZABLE isolation level is set."""
        with patch("agent.transactions.booking_transaction.validate_3_day_rule") as mock_3day, \
             patch("agent.transactions.booking_transaction.validate_category_consistency") as mock_category, \
             patch("agent.transactions.booking_transaction.validate_slot_availability") as mock_slot, \
             patch("agent.transactions.booking_transaction.create_calendar_event") as mock_calendar, \
             patch("agent.transactions.booking_transaction.get_async_session") as mock_session:

            mock_3day.return_value = {"valid": True}
            mock_category.return_value = {"valid": True}
            mock_slot.return_value = {"available": True}
            mock_calendar.return_value = {"success": True, "event_id": "google_event_123"}

            session = AsyncMock()
            mock_session.return_value.__aenter__.return_value = session

            service_result = AsyncMock()
            service_result.scalars.return_value.all.return_value = mock_services
            stylist_result = AsyncMock()
            stylist_result.scalar_one_or_none.return_value = mock_stylist

            call_count = [0]

            async def execute_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 2:
                    return service_result
                elif call_count[0] == 3:
                    return stylist_result
                return AsyncMock()

            session.execute.side_effect = execute_side_effect

            await BookingTransaction.execute(
                customer_id=customer_id,
                service_ids=service_ids,
                stylist_id=stylist_id,
                start_time=valid_start_time,
                first_name="Pepe",
                last_name=None,
                notes=None
            )

            # Verify SERIALIZABLE isolation was set (first execute call)
            first_execute_call = session.execute.call_args_list[0]
            sql = str(first_execute_call[0][0])
            assert "SERIALIZABLE" in sql


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_optional_fields_none(
        self, customer_id, stylist_id, service_ids, valid_start_time, mock_services, mock_stylist
    ):
        """Test booking with optional fields set to None."""
        with patch("agent.transactions.booking_transaction.validate_3_day_rule") as mock_3day, \
             patch("agent.transactions.booking_transaction.validate_category_consistency") as mock_category, \
             patch("agent.transactions.booking_transaction.validate_slot_availability") as mock_slot, \
             patch("agent.transactions.booking_transaction.create_calendar_event") as mock_calendar, \
             patch("agent.transactions.booking_transaction.get_async_session") as mock_session:

            mock_3day.return_value = {"valid": True}
            mock_category.return_value = {"valid": True}
            mock_slot.return_value = {"available": True}
            mock_calendar.return_value = {"success": True, "event_id": "google_event_123"}

            session = AsyncMock()
            mock_session.return_value.__aenter__.return_value = session

            service_result = AsyncMock()
            service_result.scalars.return_value.all.return_value = mock_services
            stylist_result = AsyncMock()
            stylist_result.scalar_one_or_none.return_value = mock_stylist

            call_count = [0]

            async def execute_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 2:
                    return service_result
                elif call_count[0] == 3:
                    return stylist_result
                return AsyncMock()

            session.execute.side_effect = execute_side_effect

            result = await BookingTransaction.execute(
                customer_id=customer_id,
                service_ids=service_ids,
                stylist_id=stylist_id,
                start_time=valid_start_time,
                first_name="Pepe",
                last_name=None,  # Optional
                notes=None,       # Optional
                conversation_id=None  # Optional
            )

            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_single_service_booking(
        self, customer_id, stylist_id, valid_start_time, mock_stylist
    ):
        """Test booking with only one service."""
        single_service_id = [UUID("770e8400-e29b-41d4-a716-446655440002")]

        single_service = MagicMock()
        single_service.id = single_service_id[0]
        single_service.name = "Corte de Caballero"
        single_service.duration_minutes = 30

        with patch("agent.transactions.booking_transaction.validate_3_day_rule") as mock_3day, \
             patch("agent.transactions.booking_transaction.validate_category_consistency") as mock_category, \
             patch("agent.transactions.booking_transaction.validate_slot_availability") as mock_slot, \
             patch("agent.transactions.booking_transaction.create_calendar_event") as mock_calendar, \
             patch("agent.transactions.booking_transaction.get_async_session") as mock_session:

            mock_3day.return_value = {"valid": True}
            mock_category.return_value = {"valid": True}
            mock_slot.return_value = {"available": True}
            mock_calendar.return_value = {"success": True, "event_id": "google_event_123"}

            session = AsyncMock()
            mock_session.return_value.__aenter__.return_value = session

            service_result = AsyncMock()
            service_result.scalars.return_value.all.return_value = [single_service]
            stylist_result = AsyncMock()
            stylist_result.scalar_one_or_none.return_value = mock_stylist

            call_count = [0]

            async def execute_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 2:
                    return service_result
                elif call_count[0] == 3:
                    return stylist_result
                return AsyncMock()

            session.execute.side_effect = execute_side_effect

            result = await BookingTransaction.execute(
                customer_id=customer_id,
                service_ids=single_service_id,
                stylist_id=stylist_id,
                start_time=valid_start_time,
                first_name="Pepe",
                last_name=None,
                notes=None
            )

            assert result["success"] is True
            assert result["duration_minutes"] == 30

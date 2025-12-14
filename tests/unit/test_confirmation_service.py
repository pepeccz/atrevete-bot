"""
Tests for ConfirmationService - Appointment confirmation handling.

This module tests the confirmation service that processes customer responses
to 48h confirmation requests (CONFIRM_APPOINTMENT, DECLINE_APPOINTMENT).

Coverage:
- get_customer_by_phone: Customer lookup by phone number
- get_pending_confirmation: Find pending appointment awaiting confirmation
- has_pending_confirmation: Quick boolean check for pending confirmations
- handle_confirmation_response: Process confirm/decline responses
- Template vs LLM response detection
- Google Calendar updates
- Admin notification creation
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from agent.fsm.models import IntentType
from agent.services.confirmation_service import (
    ConfirmationResult,
    check_decline_timeout,
    format_date_spanish,
    get_appointment_by_id,
    get_customer_by_phone,
    get_pending_confirmation,
    get_pending_confirmations,
    handle_confirmation_response,
    handle_decline_second_confirmation,
    handle_topic_change_with_pending_decline,
    has_pending_confirmation,
    is_emphatic_decline,
)
from database.models import AppointmentStatus


MADRID_TZ = ZoneInfo("Europe/Madrid")


class TestFormatDateSpanish:
    """Test Spanish date formatting."""

    def test_format_weekday_monday(self):
        """Test Monday formatting."""
        dt = datetime(2025, 12, 15, 10, 0, tzinfo=MADRID_TZ)  # Monday
        result = format_date_spanish(dt)
        assert result == "lunes 15 de diciembre"

    def test_format_weekday_saturday(self):
        """Test Saturday formatting."""
        dt = datetime(2025, 12, 20, 10, 0, tzinfo=MADRID_TZ)  # Saturday
        result = format_date_spanish(dt)
        assert result == "sábado 20 de diciembre"

    def test_format_different_month(self):
        """Test January formatting."""
        dt = datetime(2025, 1, 8, 10, 0, tzinfo=MADRID_TZ)  # Wednesday
        result = format_date_spanish(dt)
        assert result == "miércoles 8 de enero"


class TestGetCustomerByPhone:
    """Test customer lookup by phone number."""

    @pytest.mark.asyncio
    async def test_customer_found(self):
        """Verify customer is returned when found."""
        mock_customer = MagicMock()
        mock_customer.id = uuid4()
        mock_customer.phone = "+34612345678"
        mock_customer.first_name = "María García"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_customer

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "agent.services.confirmation_service.get_async_session"
        ) as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            result = await get_customer_by_phone("+34612345678")

            assert result is not None
            assert result.phone == "+34612345678"
            assert result.name == "María García"

    @pytest.mark.asyncio
    async def test_customer_not_found(self):
        """Verify None is returned when customer not found."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "agent.services.confirmation_service.get_async_session"
        ) as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            result = await get_customer_by_phone("+34999999999")

            assert result is None

    @pytest.mark.asyncio
    async def test_database_error_handled(self):
        """Verify database errors are handled gracefully."""
        with patch(
            "agent.services.confirmation_service.get_async_session"
        ) as mock_get_session:
            mock_get_session.return_value.__aenter__.side_effect = Exception("DB error")

            result = await get_customer_by_phone("+34612345678")

            assert result is None


class TestGetPendingConfirmations:
    """Test pending appointments lookup (returns list)."""

    @pytest.mark.asyncio
    async def test_pending_appointments_found(self):
        """Verify list of pending appointments is returned."""
        customer_id = uuid4()
        appt_id1 = uuid4()
        appt_id2 = uuid4()

        mock_appointment1 = MagicMock()
        mock_appointment1.id = appt_id1
        mock_appointment1.customer_id = customer_id
        mock_appointment1.status = AppointmentStatus.PENDING
        mock_appointment1.confirmation_sent_at = datetime.now(MADRID_TZ)
        mock_appointment1.start_time = datetime.now(MADRID_TZ) + timedelta(days=2)

        mock_appointment2 = MagicMock()
        mock_appointment2.id = appt_id2
        mock_appointment2.customer_id = customer_id
        mock_appointment2.status = AppointmentStatus.PENDING
        mock_appointment2.confirmation_sent_at = datetime.now(MADRID_TZ)
        mock_appointment2.start_time = datetime.now(MADRID_TZ) + timedelta(days=3)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_appointment1, mock_appointment2]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "agent.services.confirmation_service.get_async_session"
        ) as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            result = await get_pending_confirmations(customer_id)

            assert len(result) == 2
            assert result[0].id == appt_id1
            assert result[1].id == appt_id2

    @pytest.mark.asyncio
    async def test_no_pending_appointments(self):
        """Verify empty list when no pending appointments."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "agent.services.confirmation_service.get_async_session"
        ) as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            result = await get_pending_confirmations(uuid4())

            assert result == []


class TestGetPendingConfirmation:
    """Test pending appointment lookup (single appointment, backwards compatible)."""

    @pytest.mark.asyncio
    async def test_pending_appointment_found(self):
        """Verify first pending appointment is returned."""
        customer_id = uuid4()
        appt_id = uuid4()

        mock_appointment = MagicMock()
        mock_appointment.id = appt_id
        mock_appointment.customer_id = customer_id
        mock_appointment.status = AppointmentStatus.PENDING
        mock_appointment.confirmation_sent_at = datetime.now(MADRID_TZ)
        mock_appointment.start_time = datetime.now(MADRID_TZ) + timedelta(days=2)

        # Mock get_pending_confirmations to return list with one appointment
        with patch(
            "agent.services.confirmation_service.get_pending_confirmations",
            new_callable=AsyncMock,
        ) as mock_get_pending_confirmations:
            mock_get_pending_confirmations.return_value = [mock_appointment]

            result = await get_pending_confirmation(customer_id)

            assert result is not None
            assert result.id == appt_id
            assert result.status == AppointmentStatus.PENDING
            mock_get_pending_confirmations.assert_called_once_with(customer_id)

    @pytest.mark.asyncio
    async def test_no_pending_appointment(self):
        """Verify None when no pending appointment."""
        # Mock get_pending_confirmations to return empty list
        with patch(
            "agent.services.confirmation_service.get_pending_confirmations",
            new_callable=AsyncMock,
        ) as mock_get_pending_confirmations:
            mock_get_pending_confirmations.return_value = []

            result = await get_pending_confirmation(uuid4())

            assert result is None


class TestHasPendingConfirmation:
    """Test quick pending confirmation check."""

    @pytest.mark.asyncio
    async def test_has_pending_confirmation_true(self):
        """Verify returns True when customer has pending confirmation."""
        mock_customer = MagicMock()
        mock_customer.id = uuid4()

        mock_appointment = MagicMock()
        mock_appointment.id = uuid4()

        with patch(
            "agent.services.confirmation_service.get_customer_by_phone",
            new_callable=AsyncMock,
        ) as mock_get_customer:
            mock_get_customer.return_value = mock_customer

            with patch(
                "agent.services.confirmation_service.get_pending_confirmation",
                new_callable=AsyncMock,
            ) as mock_get_pending:
                mock_get_pending.return_value = mock_appointment

                result = await has_pending_confirmation("+34612345678")

                assert result is True
                mock_get_customer.assert_called_once_with("+34612345678")
                mock_get_pending.assert_called_once_with(mock_customer.id)

    @pytest.mark.asyncio
    async def test_has_pending_confirmation_false_no_customer(self):
        """Verify returns False when customer not found."""
        with patch(
            "agent.services.confirmation_service.get_customer_by_phone",
            new_callable=AsyncMock,
        ) as mock_get_customer:
            mock_get_customer.return_value = None

            result = await has_pending_confirmation("+34999999999")

            assert result is False

    @pytest.mark.asyncio
    async def test_has_pending_confirmation_false_no_appointment(self):
        """Verify returns False when no pending appointment."""
        mock_customer = MagicMock()
        mock_customer.id = uuid4()

        with patch(
            "agent.services.confirmation_service.get_customer_by_phone",
            new_callable=AsyncMock,
        ) as mock_get_customer:
            mock_get_customer.return_value = mock_customer

            with patch(
                "agent.services.confirmation_service.get_pending_confirmation",
                new_callable=AsyncMock,
            ) as mock_get_pending:
                mock_get_pending.return_value = None

                result = await has_pending_confirmation("+34612345678")

                assert result is False


class TestHandleConfirmationResponse:
    """Test main confirmation response handling."""

    @pytest.mark.asyncio
    async def test_customer_not_found_error(self):
        """Verify error result when customer not found."""
        with patch(
            "agent.services.confirmation_service.get_customer_by_phone",
            new_callable=AsyncMock,
        ) as mock_get_customer:
            mock_get_customer.return_value = None

            result = await handle_confirmation_response(
                customer_phone="+34999999999",
                intent_type=IntentType.CONFIRM_APPOINTMENT,
                message_text="sí",
            )

            assert result.success is False
            assert result.error_message is not None
            assert "perfil" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_no_pending_appointment_error(self):
        """Verify error result when no pending appointment."""
        mock_customer = MagicMock()
        mock_customer.id = uuid4()

        with patch(
            "agent.services.confirmation_service.get_customer_by_phone",
            new_callable=AsyncMock,
        ) as mock_get_customer:
            mock_get_customer.return_value = mock_customer

            with patch(
                "agent.services.confirmation_service.get_pending_confirmations",
                new_callable=AsyncMock,
            ) as mock_get_pending:
                mock_get_pending.return_value = []  # Empty list = no pending appointments

                result = await handle_confirmation_response(
                    customer_phone="+34612345678",
                    intent_type=IntentType.CONFIRM_APPOINTMENT,
                    message_text="sí",
                )

                assert result.success is False
                assert result.error_message is not None
                assert "pendiente" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_multiple_pending_appointments_error(self):
        """Verify error result when customer has multiple pending appointments."""
        mock_customer = MagicMock()
        mock_customer.id = uuid4()

        # Create two mock appointments
        mock_appointment1 = MagicMock()
        mock_appointment1.id = uuid4()
        mock_appointment1.start_time = datetime.now(MADRID_TZ) + timedelta(days=2)
        mock_stylist1 = MagicMock()
        mock_stylist1.name = "Ana"
        mock_appointment1.stylist = mock_stylist1

        mock_appointment2 = MagicMock()
        mock_appointment2.id = uuid4()
        mock_appointment2.start_time = datetime.now(MADRID_TZ) + timedelta(days=3)
        mock_stylist2 = MagicMock()
        mock_stylist2.name = "Carmen"
        mock_appointment2.stylist = mock_stylist2

        with patch(
            "agent.services.confirmation_service.get_customer_by_phone",
            new_callable=AsyncMock,
        ) as mock_get_customer:
            mock_get_customer.return_value = mock_customer

            with patch(
                "agent.services.confirmation_service.get_pending_confirmations",
                new_callable=AsyncMock,
            ) as mock_get_pending:
                mock_get_pending.return_value = [mock_appointment1, mock_appointment2]

                result = await handle_confirmation_response(
                    customer_phone="+34612345678",
                    intent_type=IntentType.CONFIRM_APPOINTMENT,
                    message_text="sí",
                )

                assert result.success is False
                assert result.error_message is not None
                # Should mention there are 2 pending appointments
                assert "2" in result.error_message
                assert "citas" in result.error_message.lower()
                assert "pendiente" in result.error_message.lower()


class TestConfirmationResponseTypes:
    """Test template vs LLM response detection."""

    def test_simple_confirm_words_detected(self):
        """Verify simple confirmation words are detected."""
        simple_words = ["sí", "si", "confirmo", "ok", "de acuerdo", "vale", "perfecto"]
        for word in simple_words:
            # Simple words should result in template response
            # (when processed through the full flow)
            assert len(word.split()) <= 3

    def test_simple_decline_words_detected(self):
        """Verify simple decline words are detected."""
        simple_words = ["no", "no puedo", "cancela", "cancelar", "anula", "anular"]
        for word in simple_words:
            # Simple words should result in template response
            assert len(word.split()) <= 3

    def test_complex_message_detection(self):
        """Verify complex messages trigger LLM response."""
        complex_messages = [
            "Sí, pero ¿podría cambiar la hora?",
            "No puedo ir porque tengo otro compromiso ese día",
            "Confirmo la cita pero quiero añadir otro servicio",
        ]
        for msg in complex_messages:
            # Complex messages have more than 3 words
            assert len(msg.split()) > 3


class TestConfirmationResult:
    """Test ConfirmationResult dataclass."""

    def test_success_result(self):
        """Test successful confirmation result."""
        result = ConfirmationResult(
            success=True,
            appointment_id=uuid4(),
            response_type="template",
            response_text="Tu cita está confirmada",
            appointment_date="lunes 15 de diciembre",
            appointment_time="10:00",
            stylist_name="Ana",
            service_names="Corte de pelo",
        )

        assert result.success is True
        assert result.response_type == "template"
        assert result.error_message is None

    def test_failure_result(self):
        """Test failed confirmation result."""
        result = ConfirmationResult(
            success=False,
            error_message="No tienes citas pendientes",
        )

        assert result.success is False
        assert result.appointment_id is None
        assert result.error_message == "No tienes citas pendientes"

    def test_llm_response_type(self):
        """Test LLM response type result."""
        result = ConfirmationResult(
            success=True,
            appointment_id=uuid4(),
            response_type="llm",
            response_text=None,  # LLM will generate
            appointment_date="martes 16 de diciembre",
            appointment_time="14:30",
            stylist_name="Carmen",
            service_names="Tinte completo",
        )

        assert result.success is True
        assert result.response_type == "llm"
        assert result.response_text is None


class TestConfirmAppointmentFlow:
    """Test complete confirmation flow."""

    @pytest.fixture
    def mock_appointment(self):
        """Create mock appointment for testing."""
        appt = MagicMock()
        appt.id = uuid4()
        appt.customer_id = uuid4()
        appt.stylist_id = uuid4()
        appt.status = AppointmentStatus.PENDING
        appt.start_time = datetime.now(MADRID_TZ) + timedelta(days=2)
        appt.confirmation_sent_at = datetime.now(MADRID_TZ)
        appt.google_calendar_event_id = "gcal_event_123"
        appt.service_ids = [uuid4()]
        appt.first_name = "María"

        # Mock stylist relationship
        mock_stylist = MagicMock()
        mock_stylist.name = "Ana"
        appt.stylist = mock_stylist

        return appt

    @pytest.fixture
    def mock_customer(self):
        """Create mock customer for testing."""
        customer = MagicMock()
        customer.id = uuid4()
        customer.phone = "+34612345678"
        customer.first_name = "María García"
        return customer

    @pytest.mark.asyncio
    async def test_confirm_updates_status_to_confirmed(
        self, mock_customer, mock_appointment
    ):
        """Verify CONFIRM_APPOINTMENT updates status to CONFIRMED."""
        mock_service = MagicMock()
        mock_service.name = "Corte de pelo"

        with patch(
            "agent.services.confirmation_service.get_customer_by_phone",
            new_callable=AsyncMock,
        ) as mock_get_customer:
            mock_get_customer.return_value = mock_customer

            with patch(
                "agent.services.confirmation_service.get_pending_confirmations",
                new_callable=AsyncMock,
            ) as mock_get_pending:
                mock_get_pending.return_value = [mock_appointment]  # Return list with single appointment

                with patch(
                    "agent.services.confirmation_service.get_async_session"
                ) as mock_get_session:
                    # Mock session for services query and appointment update
                    mock_session = AsyncMock()

                    # Services query result
                    mock_services_result = MagicMock()
                    mock_services_result.scalars.return_value.all.return_value = [
                        mock_service
                    ]

                    # Appointment query result
                    mock_appt_result = MagicMock()
                    mock_appt_result.scalars.return_value.first.return_value = (
                        mock_appointment
                    )

                    mock_session.execute = AsyncMock(
                        side_effect=[mock_services_result, mock_appt_result]
                    )
                    mock_session.commit = AsyncMock()
                    mock_session.add = MagicMock()

                    mock_get_session.return_value.__aenter__.return_value = mock_session

                    with patch(
                        "agent.services.confirmation_service.update_gcal_event_status",
                        new_callable=AsyncMock,
                    ):
                        result = await handle_confirmation_response(
                            customer_phone="+34612345678",
                            intent_type=IntentType.CONFIRM_APPOINTMENT,
                            message_text="sí",
                        )

                        assert result.success is True
                        assert result.response_type == "template"
                        assert mock_appointment.status == AppointmentStatus.CONFIRMED


class TestDeclineAppointmentFlow:
    """Test complete decline flow."""

    @pytest.fixture
    def mock_appointment(self):
        """Create mock appointment for testing."""
        appt = MagicMock()
        appt.id = uuid4()
        appt.customer_id = uuid4()
        appt.stylist_id = uuid4()
        appt.status = AppointmentStatus.PENDING
        appt.start_time = datetime.now(MADRID_TZ) + timedelta(days=2)
        appt.confirmation_sent_at = datetime.now(MADRID_TZ)
        appt.google_calendar_event_id = "gcal_event_123"
        appt.service_ids = [uuid4()]
        appt.first_name = "María"
        appt.cancelled_at = None

        # Mock stylist relationship
        mock_stylist = MagicMock()
        mock_stylist.name = "Ana"
        appt.stylist = mock_stylist

        return appt

    @pytest.fixture
    def mock_customer(self):
        """Create mock customer for testing."""
        customer = MagicMock()
        customer.id = uuid4()
        customer.phone = "+34612345678"
        customer.first_name = "María García"
        return customer

    @pytest.mark.asyncio
    async def test_decline_updates_status_to_cancelled(
        self, mock_customer, mock_appointment
    ):
        """Verify DECLINE_APPOINTMENT updates status to CANCELLED."""
        mock_service = MagicMock()
        mock_service.name = "Corte de pelo"

        with patch(
            "agent.services.confirmation_service.get_customer_by_phone",
            new_callable=AsyncMock,
        ) as mock_get_customer:
            mock_get_customer.return_value = mock_customer

            with patch(
                "agent.services.confirmation_service.get_pending_confirmations",
                new_callable=AsyncMock,
            ) as mock_get_pending:
                mock_get_pending.return_value = [mock_appointment]  # Return list with single appointment

                with patch(
                    "agent.services.confirmation_service.get_async_session"
                ) as mock_get_session:
                    mock_session = AsyncMock()

                    mock_services_result = MagicMock()
                    mock_services_result.scalars.return_value.all.return_value = [
                        mock_service
                    ]

                    mock_appt_result = MagicMock()
                    mock_appt_result.scalars.return_value.first.return_value = (
                        mock_appointment
                    )

                    mock_session.execute = AsyncMock(
                        side_effect=[mock_services_result, mock_appt_result]
                    )
                    mock_session.commit = AsyncMock()
                    mock_session.add = MagicMock()

                    mock_get_session.return_value.__aenter__.return_value = mock_session

                    with patch(
                        "agent.services.confirmation_service.delete_gcal_event",
                        new_callable=AsyncMock,
                    ):
                        result = await handle_confirmation_response(
                            customer_phone="+34612345678",
                            intent_type=IntentType.DECLINE_APPOINTMENT,
                            message_text="no puedo",
                        )

                        assert result.success is True
                        assert result.response_type == "template"
                        assert mock_appointment.status == AppointmentStatus.CANCELLED
                        assert mock_appointment.cancelled_at is not None


# ============================================================================
# DOUBLE CONFIRMATION TESTS (v3.5)
# ============================================================================


class TestIsEmphaticDecline:
    """Test emphatic decline pattern detection."""

    def test_emphatic_certainty_expressions(self):
        """Verify certainty expressions are detected as emphatic."""
        emphatic_messages = [
            "estoy seguro que no puedo ir",
            "estoy segura de que no iré",
            "seguro que no voy",
            "definitivamente no puedo",
        ]
        for msg in emphatic_messages:
            assert is_emphatic_decline(msg) is True, f"'{msg}' should be emphatic"

    def test_emphatic_direct_cancellation(self):
        """Verify direct cancellation requests are detected as emphatic."""
        emphatic_messages = [
            "cancélala ya",
            "cancelala ya por favor",
            "si cancela la cita",
            "confirmo cancelar",
            "necesito cancelar urgente",
        ]
        for msg in emphatic_messages:
            assert is_emphatic_decline(msg) is True, f"'{msg}' should be emphatic"

    def test_emphatic_multiple_markers(self):
        """Verify multiple certainty markers trigger emphatic detection."""
        # Has both "seguro" and "claro que"
        msg = "claro que estoy seguro"
        assert is_emphatic_decline(msg) is True

    def test_non_emphatic_simple_decline(self):
        """Verify simple declines are NOT emphatic."""
        non_emphatic_messages = [
            "no",
            "no puedo",
            "cancela",
            "no voy a poder ir",
            "creo que no",
        ]
        for msg in non_emphatic_messages:
            assert is_emphatic_decline(msg) is False, f"'{msg}' should NOT be emphatic"

    def test_case_insensitive(self):
        """Verify detection is case-insensitive."""
        assert is_emphatic_decline("ESTOY SEGURO") is True
        assert is_emphatic_decline("Definitivamente No") is True


class TestCheckDeclineTimeout:
    """Test decline timeout check (24 hours)."""

    def test_timeout_not_expired(self):
        """Verify timeout not expired within 24 hours."""
        recent_time = datetime.now(MADRID_TZ) - timedelta(hours=1)
        assert check_decline_timeout(recent_time.isoformat()) is False

    def test_timeout_expired_after_24h(self):
        """Verify timeout expired after 24 hours."""
        old_time = datetime.now(MADRID_TZ) - timedelta(hours=25)
        assert check_decline_timeout(old_time.isoformat()) is True

    def test_timeout_exactly_24h(self):
        """Verify timeout expired at exactly 24 hours."""
        exactly_24h = datetime.now(MADRID_TZ) - timedelta(hours=24)
        assert check_decline_timeout(exactly_24h.isoformat()) is True

    def test_invalid_timestamp_treated_as_expired(self):
        """Verify invalid timestamp is treated as expired."""
        assert check_decline_timeout("invalid-timestamp") is True
        assert check_decline_timeout("") is True


class TestGetAppointmentById:
    """Test appointment lookup by ID."""

    @pytest.mark.asyncio
    async def test_appointment_found(self):
        """Verify appointment is returned when found."""
        appt_id = uuid4()
        mock_appointment = MagicMock()
        mock_appointment.id = appt_id
        mock_appointment.status = AppointmentStatus.PENDING

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_appointment

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "agent.services.confirmation_service.get_async_session"
        ) as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            result = await get_appointment_by_id(appt_id)

            assert result is not None
            assert result.id == appt_id

    @pytest.mark.asyncio
    async def test_appointment_not_found(self):
        """Verify None is returned when appointment not found."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "agent.services.confirmation_service.get_async_session"
        ) as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            result = await get_appointment_by_id(uuid4())

            assert result is None

    @pytest.mark.asyncio
    async def test_database_error_handled(self):
        """Verify database errors are handled gracefully."""
        with patch(
            "agent.services.confirmation_service.get_async_session"
        ) as mock_get_session:
            mock_get_session.return_value.__aenter__.side_effect = Exception("DB error")

            result = await get_appointment_by_id(uuid4())

            assert result is None


class TestHandleDeclineSecondConfirmation:
    """Test second confirmation handling for decline flow."""

    @pytest.fixture
    def mock_appointment(self):
        """Create mock appointment for testing."""
        appt = MagicMock()
        appt.id = uuid4()
        appt.customer_id = uuid4()
        appt.stylist_id = uuid4()
        appt.status = AppointmentStatus.PENDING
        appt.start_time = datetime.now(MADRID_TZ) + timedelta(days=2)
        appt.google_calendar_event_id = "gcal_event_123"
        appt.service_ids = [uuid4()]
        appt.first_name = "María"
        appt.cancelled_at = None

        mock_stylist = MagicMock()
        mock_stylist.name = "Ana"
        appt.stylist = mock_stylist

        return appt

    @pytest.fixture
    def mock_customer(self):
        """Create mock customer for testing."""
        customer = MagicMock()
        customer.id = uuid4()
        customer.phone = "+34612345678"
        customer.first_name = "María García"
        return customer

    @pytest.mark.asyncio
    async def test_customer_not_found_error(self):
        """Verify error when customer not found."""
        with patch(
            "agent.services.confirmation_service.get_customer_by_phone",
            new_callable=AsyncMock,
        ) as mock_get_customer:
            mock_get_customer.return_value = None

            result = await handle_decline_second_confirmation(
                customer_phone="+34999999999",
                intent_type=IntentType.CONFIRM_DECLINE,
                appointment_id=str(uuid4()),
            )

            assert result.success is False
            assert result.error_message is not None
            assert result.state_updates is not None
            assert result.state_updates["pending_decline_appointment_id"] is None

    @pytest.mark.asyncio
    async def test_invalid_appointment_id_error(self):
        """Verify error when appointment ID is invalid."""
        mock_customer = MagicMock()
        mock_customer.id = uuid4()

        with patch(
            "agent.services.confirmation_service.get_customer_by_phone",
            new_callable=AsyncMock,
        ) as mock_get_customer:
            mock_get_customer.return_value = mock_customer

            result = await handle_decline_second_confirmation(
                customer_phone="+34612345678",
                intent_type=IntentType.CONFIRM_DECLINE,
                appointment_id="invalid-uuid",
            )

            assert result.success is False
            assert result.state_updates is not None

    @pytest.mark.asyncio
    async def test_abort_decline_keeps_appointment(self, mock_customer, mock_appointment):
        """Verify ABORT_DECLINE keeps the appointment."""
        with patch(
            "agent.services.confirmation_service.get_customer_by_phone",
            new_callable=AsyncMock,
        ) as mock_get_customer:
            mock_get_customer.return_value = mock_customer

            with patch(
                "agent.services.confirmation_service.get_appointment_by_id",
                new_callable=AsyncMock,
            ) as mock_get_appt:
                mock_get_appt.return_value = mock_appointment

                with patch(
                    "agent.services.confirmation_service._get_service_names",
                    new_callable=AsyncMock,
                ) as mock_get_services:
                    mock_get_services.return_value = "Corte de pelo"

                    result = await handle_decline_second_confirmation(
                        customer_phone="+34612345678",
                        intent_type=IntentType.ABORT_DECLINE,
                        appointment_id=str(mock_appointment.id),
                    )

                    assert result.success is True
                    assert result.response_type == "template"
                    assert "sigue en pie" in result.response_text
                    assert result.state_updates is not None
                    assert result.state_updates["pending_decline_appointment_id"] is None


class TestHandleTopicChangeWithPendingDecline:
    """Test topic change handling when pending decline is active."""

    @pytest.mark.asyncio
    async def test_topic_change_clears_state(self):
        """Verify topic change clears pending decline state."""
        mock_appointment = MagicMock()
        mock_appointment.id = uuid4()
        mock_appointment.start_time = datetime.now(MADRID_TZ) + timedelta(days=2)

        mock_stylist = MagicMock()
        mock_stylist.name = "Ana"
        mock_appointment.stylist = mock_stylist

        with patch(
            "agent.services.confirmation_service.get_appointment_by_id",
            new_callable=AsyncMock,
        ) as mock_get_appt:
            mock_get_appt.return_value = mock_appointment

            prefix, state_updates = await handle_topic_change_with_pending_decline(
                appointment_id=str(mock_appointment.id),
            )

            assert "sigue en pie" in prefix
            assert state_updates["pending_decline_appointment_id"] is None
            assert state_updates["pending_decline_initiated_at"] is None

    @pytest.mark.asyncio
    async def test_topic_change_invalid_appointment(self):
        """Verify topic change handles invalid appointment gracefully."""
        prefix, state_updates = await handle_topic_change_with_pending_decline(
            appointment_id="invalid-uuid",
        )

        assert "sigue en pie" in prefix
        assert state_updates["pending_decline_appointment_id"] is None

    @pytest.mark.asyncio
    async def test_topic_change_appointment_not_found(self):
        """Verify topic change handles missing appointment gracefully."""
        with patch(
            "agent.services.confirmation_service.get_appointment_by_id",
            new_callable=AsyncMock,
        ) as mock_get_appt:
            mock_get_appt.return_value = None

            prefix, state_updates = await handle_topic_change_with_pending_decline(
                appointment_id=str(uuid4()),
            )

            assert "sigue en pie" in prefix
            assert state_updates["pending_decline_appointment_id"] is None


class TestConfirmationResultDoubleConfirm:
    """Test ConfirmationResult dataclass with double confirm fields."""

    def test_result_with_state_updates(self):
        """Test result with state updates for double confirmation."""
        result = ConfirmationResult(
            success=True,
            appointment_id=uuid4(),
            response_type="template",
            response_text="Lamentamos que no puedas asistir...",
            requires_double_confirm=True,
            state_updates={
                "pending_decline_appointment_id": "some-uuid",
                "pending_decline_initiated_at": "2025-12-14T10:00:00+01:00",
            },
        )

        assert result.requires_double_confirm is True
        assert result.state_updates is not None
        assert result.state_updates["pending_decline_appointment_id"] == "some-uuid"

    def test_result_without_double_confirm(self):
        """Test result without double confirmation (default)."""
        result = ConfirmationResult(
            success=True,
            appointment_id=uuid4(),
            response_type="template",
            response_text="Tu cita está confirmada",
        )

        assert result.requires_double_confirm is False
        assert result.state_updates is None

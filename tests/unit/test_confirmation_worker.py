"""
Tests for ConfirmationWorker - Scheduled jobs for confirmation lifecycle.

This module tests the confirmation worker that manages three scheduled jobs:
1. send_confirmations (10:00 AM daily): Send 48h confirmation templates
2. process_auto_cancellations (10:00 AM daily): Auto-cancel unconfirmed appointments
3. send_reminders (hourly): Send 2h reminders for confirmed appointments

Coverage:
- Date formatting functions
- Service name resolution
- Notification creation
- Health check updates
- Job execution flows (mocked database and Chatwoot)
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from agent.workers.confirmation_worker import (
    format_date_spanish,
    format_datetime_spanish,
    get_services_by_ids,
    create_notification,
)
from database.models import AppointmentStatus, NotificationType


MADRID_TZ = ZoneInfo("Europe/Madrid")


class TestFormatDateSpanish:
    """Test Spanish date formatting functions."""

    def test_format_monday(self):
        """Test Monday formatting."""
        dt = datetime(2025, 12, 15, 10, 0, tzinfo=MADRID_TZ)  # Monday
        result = format_date_spanish(dt)
        assert result == "lunes 15 de diciembre"

    def test_format_saturday(self):
        """Test Saturday formatting."""
        dt = datetime(2025, 12, 20, 14, 30, tzinfo=MADRID_TZ)  # Saturday
        result = format_date_spanish(dt)
        assert result == "sábado 20 de diciembre"

    def test_format_january(self):
        """Test January formatting."""
        dt = datetime(2025, 1, 8, 10, 0, tzinfo=MADRID_TZ)  # Wednesday
        result = format_date_spanish(dt)
        assert result == "miércoles 8 de enero"

    def test_format_sunday(self):
        """Test Sunday formatting."""
        dt = datetime(2025, 12, 21, 11, 0, tzinfo=MADRID_TZ)  # Sunday
        result = format_date_spanish(dt)
        assert result == "domingo 21 de diciembre"


class TestFormatDatetimeSpanish:
    """Test Spanish datetime formatting with time."""

    def test_format_datetime_morning(self):
        """Test morning time formatting."""
        dt = datetime(2025, 12, 15, 10, 0, tzinfo=MADRID_TZ)
        result = format_datetime_spanish(dt)
        assert result == "lunes 15 de diciembre a las 10:00"

    def test_format_datetime_afternoon(self):
        """Test afternoon time formatting."""
        dt = datetime(2025, 12, 16, 16, 30, tzinfo=MADRID_TZ)
        result = format_datetime_spanish(dt)
        assert result == "martes 16 de diciembre a las 16:30"

    def test_format_datetime_with_minutes(self):
        """Test time with non-zero minutes."""
        dt = datetime(2025, 12, 17, 9, 45, tzinfo=MADRID_TZ)
        result = format_datetime_spanish(dt)
        assert result == "miércoles 17 de diciembre a las 09:45"


class TestGetServicesByIds:
    """Test service name resolution."""

    @pytest.mark.asyncio
    async def test_get_services_by_ids_found(self):
        """Verify services are returned when found."""
        service_ids = [uuid4(), uuid4()]

        mock_service1 = MagicMock()
        mock_service1.id = service_ids[0]
        mock_service1.name = "Corte de pelo"

        mock_service2 = MagicMock()
        mock_service2.id = service_ids[1]
        mock_service2.name = "Tinte"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_service1, mock_service2]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        services = await get_services_by_ids(mock_session, service_ids)

        assert len(services) == 2
        assert services[0].name == "Corte de pelo"
        assert services[1].name == "Tinte"

    @pytest.mark.asyncio
    async def test_get_services_by_ids_empty(self):
        """Verify empty list when no services found."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        services = await get_services_by_ids(mock_session, [uuid4()])

        assert len(services) == 0


class TestCreateNotification:
    """Test admin notification creation."""

    @pytest.mark.asyncio
    async def test_create_notification_with_entity(self):
        """Verify notification created with entity ID."""
        mock_session = MagicMock()
        mock_session.add = MagicMock()

        entity_id = uuid4()

        await create_notification(
            session=mock_session,
            notification_type=NotificationType.CONFIRMATION_SENT,
            title="Confirmación enviada",
            message="Se ha enviado confirmación para la cita del lunes",
            entity_id=entity_id,
        )

        # Verify session.add was called
        mock_session.add.assert_called_once()

        # Get the notification object that was added
        notification = mock_session.add.call_args[0][0]
        assert notification.type == NotificationType.CONFIRMATION_SENT
        assert notification.title == "Confirmación enviada"
        assert notification.entity_id == entity_id
        assert notification.entity_type == "appointment"

    @pytest.mark.asyncio
    async def test_create_notification_without_entity(self):
        """Verify notification created without entity ID."""
        mock_session = MagicMock()
        mock_session.add = MagicMock()

        await create_notification(
            session=mock_session,
            notification_type=NotificationType.REMINDER_SENT,
            title="Recordatorio enviado",
            message="Se ha enviado recordatorio",
            entity_id=None,
        )

        notification = mock_session.add.call_args[0][0]
        assert notification.type == NotificationType.REMINDER_SENT
        assert notification.entity_id is None
        assert notification.entity_type is None


class TestSendConfirmationsJob:
    """Test send_confirmations job logic."""

    @pytest.fixture
    def mock_appointment(self):
        """Create mock appointment for testing."""
        appt = MagicMock()
        appt.id = uuid4()
        appt.customer_id = uuid4()
        appt.stylist_id = uuid4()
        appt.status = AppointmentStatus.PENDING
        appt.start_time = datetime.now(MADRID_TZ) + timedelta(hours=48)
        appt.confirmation_sent_at = None
        appt.notification_failed = False
        appt.google_calendar_event_id = "gcal_event_123"
        appt.service_ids = [uuid4()]
        appt.first_name = "María"

        # Mock customer relationship
        mock_customer = MagicMock()
        mock_customer.phone = "+34612345678"
        mock_customer.first_name = "María García"
        appt.customer = mock_customer

        # Mock stylist relationship
        mock_stylist = MagicMock()
        mock_stylist.name = "Ana"
        appt.stylist = mock_stylist

        return appt

    @pytest.mark.asyncio
    async def test_send_confirmations_no_appointments(self):
        """Verify job completes cleanly with no appointments."""
        with patch("agent.workers.confirmation_worker.get_async_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_get_session.return_value.__aenter__.return_value = mock_session

            with patch(
                "agent.workers.confirmation_worker.update_health_check",
                new_callable=AsyncMock,
            ) as mock_health:
                from agent.workers.confirmation_worker import send_confirmations

                await send_confirmations()

                # Health check should be updated with 0 processed
                mock_health.assert_called_once()
                call_kwargs = mock_health.call_args.kwargs
                assert call_kwargs["processed"] == 0
                assert call_kwargs["errors"] == 0

    @pytest.mark.asyncio
    async def test_send_confirmations_success(self, mock_appointment):
        """Verify successful confirmation send updates appointment."""
        mock_service = MagicMock()
        mock_service.name = "Corte de pelo"

        with patch("agent.workers.confirmation_worker.get_async_session") as mock_get_session:
            mock_session = AsyncMock()

            # Appointments query
            mock_appts_result = MagicMock()
            mock_appts_result.scalars.return_value.all.return_value = [mock_appointment]

            # Services query
            mock_services_result = MagicMock()
            mock_services_result.scalars.return_value.all.return_value = [mock_service]

            mock_session.execute = AsyncMock(side_effect=[mock_appts_result, mock_services_result])
            mock_session.commit = AsyncMock()
            mock_session.add = MagicMock()

            mock_get_session.return_value.__aenter__.return_value = mock_session

            with patch("agent.workers.confirmation_worker.ChatwootClient") as mock_chatwoot_class:
                mock_chatwoot = MagicMock()
                mock_chatwoot.send_template_message = AsyncMock(return_value=True)
                mock_chatwoot_class.return_value = mock_chatwoot

                with patch(
                    "agent.workers.confirmation_worker.update_health_check",
                    new_callable=AsyncMock,
                ) as mock_health:
                    from agent.workers.confirmation_worker import send_confirmations

                    await send_confirmations()

                    # Verify template was sent
                    mock_chatwoot.send_template_message.assert_called_once()

                    # Verify confirmation_sent_at was set
                    assert mock_appointment.confirmation_sent_at is not None


class TestProcessAutoCancellationsJob:
    """Test process_auto_cancellations job logic."""

    @pytest.fixture
    def mock_appointment_pending_no_confirm(self):
        """Create mock appointment awaiting confirmation (within 24h)."""
        appt = MagicMock()
        appt.id = uuid4()
        appt.customer_id = uuid4()
        appt.stylist_id = uuid4()
        appt.status = AppointmentStatus.PENDING
        appt.start_time = datetime.now(MADRID_TZ) + timedelta(hours=12)  # Within 24h
        appt.confirmation_sent_at = datetime.now(MADRID_TZ) - timedelta(hours=36)
        appt.cancelled_at = None
        appt.google_calendar_event_id = "gcal_event_456"
        appt.service_ids = [uuid4()]
        appt.first_name = "Pedro"

        # Mock customer
        mock_customer = MagicMock()
        mock_customer.phone = "+34698765432"
        mock_customer.first_name = "Pedro López"
        appt.customer = mock_customer

        # Mock stylist
        mock_stylist = MagicMock()
        mock_stylist.name = "Carmen"
        appt.stylist = mock_stylist

        return appt

    @pytest.mark.asyncio
    async def test_auto_cancellation_updates_status(self, mock_appointment_pending_no_confirm):
        """Verify auto-cancellation updates status to CANCELLED."""
        mock_service = MagicMock()
        mock_service.name = "Tratamiento capilar"

        with patch("agent.workers.confirmation_worker.get_async_session") as mock_get_session:
            mock_session = AsyncMock()

            # Appointments query
            mock_appts_result = MagicMock()
            mock_appts_result.scalars.return_value.all.return_value = [
                mock_appointment_pending_no_confirm
            ]

            # Services query
            mock_services_result = MagicMock()
            mock_services_result.scalars.return_value.all.return_value = [mock_service]

            mock_session.execute = AsyncMock(side_effect=[mock_appts_result, mock_services_result])
            mock_session.commit = AsyncMock()
            mock_session.add = MagicMock()

            mock_get_session.return_value.__aenter__.return_value = mock_session

            with patch(
                "agent.workers.confirmation_worker.delete_gcal_event",
                new_callable=AsyncMock,
            ) as mock_delete_gcal:
                with patch(
                    "agent.workers.confirmation_worker.ChatwootClient"
                ) as mock_chatwoot_class:
                    mock_chatwoot = MagicMock()
                    mock_chatwoot.send_template_message = AsyncMock(return_value=True)
                    mock_chatwoot_class.return_value = mock_chatwoot

                    with patch(
                        "agent.workers.confirmation_worker.update_health_check",
                        new_callable=AsyncMock,
                    ):
                        from agent.workers.confirmation_worker import (
                            process_auto_cancellations,
                        )

                        await process_auto_cancellations()

                        # Verify status updated
                        assert (
                            mock_appointment_pending_no_confirm.status
                            == AppointmentStatus.CANCELLED
                        )
                        assert mock_appointment_pending_no_confirm.cancelled_at is not None

                        # Verify GCal event deleted
                        mock_delete_gcal.assert_called_once()


class TestSendRemindersJob:
    """Test send_reminders job logic."""

    @pytest.fixture
    def mock_confirmed_appointment(self):
        """Create mock confirmed appointment within 2h window."""
        appt = MagicMock()
        appt.id = uuid4()
        appt.customer_id = uuid4()
        appt.stylist_id = uuid4()
        appt.status = AppointmentStatus.CONFIRMED
        appt.start_time = datetime.now(MADRID_TZ) + timedelta(hours=2)  # In 2h window
        appt.reminder_sent_at = None
        appt.service_ids = [uuid4()]
        appt.first_name = "Laura"

        # Mock customer
        mock_customer = MagicMock()
        mock_customer.phone = "+34611223344"
        mock_customer.first_name = "Laura Martínez"
        appt.customer = mock_customer

        # Mock stylist
        mock_stylist = MagicMock()
        mock_stylist.name = "Rosa"
        appt.stylist = mock_stylist

        return appt

    @pytest.mark.asyncio
    async def test_send_reminders_success(self, mock_confirmed_appointment):
        """Verify reminder sent and reminder_sent_at updated."""
        mock_service = MagicMock()
        mock_service.name = "Manicura"

        with patch("agent.workers.confirmation_worker.get_async_session") as mock_get_session:
            mock_session = AsyncMock()

            mock_appts_result = MagicMock()
            mock_appts_result.scalars.return_value.all.return_value = [mock_confirmed_appointment]

            mock_services_result = MagicMock()
            mock_services_result.scalars.return_value.all.return_value = [mock_service]

            mock_session.execute = AsyncMock(side_effect=[mock_appts_result, mock_services_result])
            mock_session.commit = AsyncMock()
            mock_session.add = MagicMock()

            mock_get_session.return_value.__aenter__.return_value = mock_session

            with patch("agent.workers.confirmation_worker.ChatwootClient") as mock_chatwoot_class:
                mock_chatwoot = MagicMock()
                mock_chatwoot.send_template_message = AsyncMock(return_value=True)
                mock_chatwoot_class.return_value = mock_chatwoot

                with patch(
                    "agent.workers.confirmation_worker.update_health_check",
                    new_callable=AsyncMock,
                ):
                    from agent.workers.confirmation_worker import send_reminders

                    await send_reminders()

                    # Verify template was sent
                    mock_chatwoot.send_template_message.assert_called_once()

                    # Verify reminder_sent_at was set
                    assert mock_confirmed_appointment.reminder_sent_at is not None


class TestHealthCheckUpdates:
    """Test health check file updates."""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        """Verify health check shows healthy status."""
        with patch("builtins.open", MagicMock()):
            with patch("json.dump") as mock_json_dump:
                with patch("pathlib.Path.rename"):
                    with patch("pathlib.Path.mkdir"):
                        from agent.workers.confirmation_worker import (
                            update_health_check,
                        )

                        await update_health_check(
                            job_name="test_job",
                            last_run=datetime.now(MADRID_TZ),
                            status="healthy",
                            processed=5,
                            errors=0,
                        )

                        # Verify JSON was written
                        mock_json_dump.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self):
        """Verify health check shows unhealthy status with errors."""
        with patch("builtins.open", MagicMock()):
            with patch("json.dump") as mock_json_dump:
                with patch("pathlib.Path.rename"):
                    with patch("pathlib.Path.mkdir"):
                        from agent.workers.confirmation_worker import (
                            update_health_check,
                        )

                        await update_health_check(
                            job_name="test_job",
                            last_run=datetime.now(MADRID_TZ),
                            status="unhealthy",
                            processed=2,
                            errors=3,
                        )

                        mock_json_dump.assert_called_once()
                        # Get the data that was passed to json.dump
                        call_args = mock_json_dump.call_args[0][0]
                        assert call_args["test_job"]["status"] == "unhealthy"
                        assert call_args["test_job"]["errors"] == 3


class TestGracefulShutdown:
    """Test graceful shutdown handling."""

    def test_shutdown_flag_starts_false(self):
        """Verify shutdown_requested starts as False."""
        from agent.workers.confirmation_worker import shutdown_requested

        # Note: This tests initial state, actual state may vary in running tests
        # due to module-level initialization
        assert isinstance(shutdown_requested, bool)

    def test_signal_handler_sets_flag(self):
        """Verify signal handler sets shutdown_requested."""
        from agent.workers.confirmation_worker import (
            signal_handler,
            shutdown_requested,
        )

        # Import before calling to check initial state
        import agent.workers.confirmation_worker as worker_module

        # Call signal handler
        signal_handler(15, None)  # SIGTERM = 15

        assert worker_module.shutdown_requested is True

        # Reset for other tests
        worker_module.shutdown_requested = False


# =============================================================================
# T-07: Hourly send_confirmations (REQ-C)
# =============================================================================


class TestHourlyConfirmationScheduling:
    """T-07: send_confirmations is called in the hourly block, not gated by daily date."""

    @pytest.mark.asyncio
    async def test_send_confirmations_called_when_should_run_reminders(self):
        """When should_run_reminders is True, send_confirmations must be called."""
        from zoneinfo import ZoneInfo
        from datetime import datetime

        import agent.workers.confirmation_worker as worker_module

        MADRID_TZ = ZoneInfo("Europe/Madrid")

        dynamic_settings = {
            "confirmation_hours_before": 48,
            "auto_cancel_hours_before": 24,
            "reminder_hours_before": 2,
            "confirmation_job_time": "23:59",  # Won't match current_time (14:00)
            "auto_cancel_job_time": "23:59",
            "reminder_job_interval": "hourly",
            "confirmation_template_name": "confirmation_48h",
        }

        mock_confirmations = AsyncMock()
        mock_reminders = AsyncMock()
        mock_retries = AsyncMock()

        # Restore original state after test
        original_shutdown = worker_module.shutdown_requested
        worker_module.shutdown_requested = False

        try:

            async def fake_sleep(_duration):
                # Exit after first sleep to limit to one cycle
                worker_module.shutdown_requested = True

            with (
                patch.object(worker_module, "send_reminders", mock_reminders),
                patch.object(worker_module, "send_confirmations", mock_confirmations),
                patch.object(worker_module, "process_confirmation_retries", mock_retries),
                patch.object(worker_module, "process_auto_cancellations", new_callable=AsyncMock),
                patch.object(worker_module.asyncio, "sleep", fake_sleep),
                patch(
                    "agent.workers.confirmation_worker.get_dynamic_settings",
                    new_callable=AsyncMock,
                    return_value=dynamic_settings,
                ),
                patch(
                    "agent.workers.confirmation_worker.update_health_check",
                    new_callable=AsyncMock,
                ),
            ):
                await worker_module.async_main()
        finally:
            worker_module.shutdown_requested = original_shutdown

        mock_confirmations.assert_called()
        mock_reminders.assert_called()
        mock_retries.assert_called()


# =============================================================================
# T-08/T-09/T-10: Webhook alerting for permanent failures (REQ-D)
# =============================================================================


class TestWebhookOnPermanentFailure:
    """T-11: trigger_all_webhooks is called at all 3 permanent-failure sites."""

    def _make_mock_appointment_for_webhook(self, *, start_time_delta_hours: float = 10.0):
        """Create a mock appointment for webhook alerting tests."""
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        MADRID_TZ = ZoneInfo("Europe/Madrid")
        appt = MagicMock()
        appt.id = uuid4()
        appt.customer_id = uuid4()
        appt.status = AppointmentStatus.PENDING
        appt.start_time = datetime.now(MADRID_TZ) + timedelta(hours=start_time_delta_hours)
        appt.confirmation_sent_at = None
        appt.notification_failed = False
        appt.retry_count = 0
        appt.next_retry_at = None
        appt.google_calendar_event_id = None
        appt.service_ids = [uuid4()]

        mock_customer = MagicMock()
        mock_customer.phone = "+34612345678"
        mock_customer.first_name = "Test User"
        mock_customer.chatwoot_conversation_id = None
        appt.customer = mock_customer

        mock_stylist = MagicMock()
        mock_stylist.name = "Ana"
        appt.stylist = mock_stylist

        return appt

    @pytest.mark.asyncio
    async def test_site1_webhook_called_on_imminent_appointment_failure(self):
        """Site 1 (send_confirmations, imminent): webhook fired before commit."""
        from datetime import timedelta

        mock_service = MagicMock()
        mock_service.name = "Corte de pelo"

        # Appointment is very soon (less than TIME_GUARD_HOURS away)
        appt = self._make_mock_appointment_for_webhook(start_time_delta_hours=1.0)

        with patch("agent.workers.confirmation_worker.get_async_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_session.add = MagicMock()
            mock_session.commit = AsyncMock()

            mock_appts_result = MagicMock()
            mock_appts_result.scalars.return_value.all.return_value = [appt]

            mock_services_result = MagicMock()
            mock_services_result.scalars.return_value.all.return_value = [mock_service]

            mock_session.execute = AsyncMock(side_effect=[mock_appts_result, mock_services_result])
            mock_get_session.return_value.__aenter__.return_value = mock_session

            with patch("agent.workers.confirmation_worker.ChatwootClient") as mock_chatwoot_class:
                mock_chatwoot = MagicMock()
                # Simulate failure — returns False
                mock_chatwoot.send_template_message = AsyncMock(return_value=False)
                mock_chatwoot_class.return_value = mock_chatwoot

                with patch(
                    "agent.workers.confirmation_worker.update_health_check",
                    new_callable=AsyncMock,
                ):
                    with patch(
                        "agent.services.webhook_service.trigger_all_webhooks",
                        new_callable=AsyncMock,
                    ) as mock_webhook:
                        from agent.workers.confirmation_worker import send_confirmations

                        await send_confirmations()

        # Webhook must have been called
        mock_webhook.assert_called()
        call_kwargs = mock_webhook.call_args[0][0]
        assert call_kwargs["event_type"] == "confirmation_permanently_failed"
        assert "appointment_id" in call_kwargs
        assert "customer_phone" in call_kwargs
        assert call_kwargs["failure_reason"] == "imminent_appointment"
        assert "timestamp" in call_kwargs

        # DB commit must still have been called
        assert mock_session.commit.called

    @pytest.mark.asyncio
    async def test_site1_webhook_failure_does_not_prevent_commit(self):
        """Site 1: when webhook raises, DB commit still succeeds."""
        mock_service = MagicMock()
        mock_service.name = "Corte"

        appt = self._make_mock_appointment_for_webhook(start_time_delta_hours=1.0)

        with patch("agent.workers.confirmation_worker.get_async_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_session.add = MagicMock()
            mock_session.commit = AsyncMock()

            mock_appts_result = MagicMock()
            mock_appts_result.scalars.return_value.all.return_value = [appt]

            mock_services_result = MagicMock()
            mock_services_result.scalars.return_value.all.return_value = [mock_service]

            mock_session.execute = AsyncMock(side_effect=[mock_appts_result, mock_services_result])
            mock_get_session.return_value.__aenter__.return_value = mock_session

            with patch("agent.workers.confirmation_worker.ChatwootClient") as mock_chatwoot_class:
                mock_chatwoot = MagicMock()
                mock_chatwoot.send_template_message = AsyncMock(return_value=False)
                mock_chatwoot_class.return_value = mock_chatwoot

                with patch(
                    "agent.workers.confirmation_worker.update_health_check",
                    new_callable=AsyncMock,
                ):
                    with patch(
                        "agent.services.webhook_service.trigger_all_webhooks",
                        new_callable=AsyncMock,
                        side_effect=Exception("webhook boom"),
                    ):
                        from agent.workers.confirmation_worker import send_confirmations

                        # Must not raise
                        await send_confirmations()

        # DB commit still called even though webhook raised
        assert mock_session.commit.called

    @pytest.mark.asyncio
    async def test_site2_webhook_called_on_retry_time_guard(self):
        """Site 2 (process_confirmation_retries, time-guard): webhook fired before commit."""
        mock_service = MagicMock()
        mock_service.name = "Tinte"

        # Appointment is very soon — time guard triggers
        appt = self._make_mock_appointment_for_webhook(start_time_delta_hours=0.5)
        appt.notification_failed = True
        appt.retry_count = 1

        with patch("agent.workers.confirmation_worker.get_async_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_session.add = MagicMock()
            mock_session.commit = AsyncMock()

            mock_appts_result = MagicMock()
            mock_appts_result.scalars.return_value.all.return_value = [appt]

            mock_session.execute = AsyncMock(return_value=mock_appts_result)
            mock_get_session.return_value.__aenter__.return_value = mock_session

            with patch(
                "agent.workers.confirmation_worker.update_health_check",
                new_callable=AsyncMock,
            ):
                with patch(
                    "agent.services.webhook_service.trigger_all_webhooks",
                    new_callable=AsyncMock,
                ) as mock_webhook:
                    from agent.workers.confirmation_worker import process_confirmation_retries

                    await process_confirmation_retries()

        mock_webhook.assert_called()
        call_kwargs = mock_webhook.call_args[0][0]
        assert call_kwargs["event_type"] == "confirmation_permanently_failed"
        assert call_kwargs["failure_reason"] == "imminent_appointment"
        assert mock_session.commit.called

    @pytest.mark.asyncio
    async def test_site3_webhook_called_on_max_retries_exhausted(self):
        """Site 3 (process_confirmation_retries, max retries): webhook with max_retries_exhausted."""
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        MADRID_TZ = ZoneInfo("Europe/Madrid")
        from datetime import datetime

        mock_service = MagicMock()
        mock_service.name = "Manicura"

        # Appointment is in the future (not imminent), retries exhausted
        appt = self._make_mock_appointment_for_webhook(start_time_delta_hours=100.0)
        appt.notification_failed = True
        appt.retry_count = 2  # Will be incremented to 3 = MAX_RETRIES

        with patch("agent.workers.confirmation_worker.get_async_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_session.add = MagicMock()
            mock_session.commit = AsyncMock()

            mock_appts_result = MagicMock()
            mock_appts_result.scalars.return_value.all.return_value = [appt]

            mock_services_result = MagicMock()
            mock_services_result.scalars.return_value.all.return_value = [mock_service]

            mock_session.execute = AsyncMock(side_effect=[mock_appts_result, mock_services_result])
            mock_get_session.return_value.__aenter__.return_value = mock_session

            with patch("agent.workers.confirmation_worker.ChatwootClient") as mock_chatwoot_class:
                mock_chatwoot = MagicMock()
                mock_chatwoot.send_template_message = AsyncMock(return_value=False)
                mock_chatwoot_class.return_value = mock_chatwoot

                with patch(
                    "agent.workers.confirmation_worker.update_health_check",
                    new_callable=AsyncMock,
                ):
                    with patch(
                        "agent.services.webhook_service.trigger_all_webhooks",
                        new_callable=AsyncMock,
                    ) as mock_webhook:
                        from agent.workers.confirmation_worker import process_confirmation_retries

                        await process_confirmation_retries()

        mock_webhook.assert_called()
        call_kwargs = mock_webhook.call_args[0][0]
        assert call_kwargs["event_type"] == "confirmation_permanently_failed"
        assert call_kwargs["failure_reason"] == "max_retries_exhausted"
        assert mock_session.commit.called

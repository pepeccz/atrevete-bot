"""
Unit tests for agent/middleware/appointment_context.py

Four cases:
1. test_no_customer_id_passes_through — no customer_id in state → handler called with original request
2. test_customer_id_no_appointments — customer_id set but no appointments → no block appended
3. test_customer_with_appointments_appends_block — 2 appointments → ## Citas próximas block injected
4. test_db_error_passes_through — DB error in fetch → warning logged, no propagation
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

MADRID_TZ = ZoneInfo("Europe/Madrid")


def _make_mock_appointment(
    hours_from_now: float = 72.0,
    stylist_name: str = "María",
    service_names: str = "Corte de Mujer",
    status: str = "PENDING",
    confirmation_sent_at: datetime | None = None,
    reminder_sent_at: datetime | None = None,
) -> MagicMock:
    """Build a minimal mock Appointment for middleware tests."""
    from database.models import AppointmentStatus

    appt = MagicMock()
    appt.id = uuid4()
    appt.start_time = datetime.now(MADRID_TZ) + timedelta(hours=hours_from_now)
    appt.stylist = MagicMock()
    appt.stylist.name = stylist_name
    appt.service_ids = [uuid4()]
    appt._service_names = service_names  # used by mock
    appt.status = AppointmentStatus[status]
    appt.confirmation_sent_at = confirmation_sent_at
    appt.reminder_sent_at = reminder_sent_at
    return appt


def _make_request(customer_id=None, system_content: str = "base prompt") -> MagicMock:
    """Build a minimal mock ModelRequest."""
    request = MagicMock()
    request.state = {"customer_id": customer_id} if customer_id is not None else {}
    system_msg = MagicMock()
    system_msg.content = system_content
    request.system_message = system_msg

    # override() returns a new mock capturing the args
    def _override(**kwargs):
        new_req = MagicMock()
        new_req.state = kwargs.get("state", request.state)
        new_req.system_message = kwargs.get("system_message", request.system_message)
        new_req._override_kwargs = kwargs
        return new_req

    request.override = MagicMock(side_effect=_override)
    return request


class TestAppointmentContextMiddlewareNoCustomer:
    """test_no_customer_id_passes_through"""

    @pytest.mark.asyncio
    async def test_no_customer_id_passes_through(self):
        """When state has no customer_id, handler is called with the original request unchanged."""
        from agent.middleware.appointment_context import AppointmentContextMiddleware

        middleware = AppointmentContextMiddleware()
        request = _make_request(customer_id=None)
        handler = AsyncMock(return_value=MagicMock())

        with patch(
            "agent.middleware.appointment_context._fetch_upcoming_appointments",
            new_callable=AsyncMock,
        ) as mock_fetch:
            await middleware.awrap_model_call(request, handler)

        # handler called once with the original request
        handler.assert_called_once_with(request)
        # no DB fetch attempted
        mock_fetch.assert_not_called()
        # no override called
        request.override.assert_not_called()


class TestAppointmentContextMiddlewareNoAppointments:
    """test_customer_id_no_appointments"""

    @pytest.mark.asyncio
    async def test_customer_id_no_appointments_passes_through(self):
        """When customer has no appointments, handler is called with original request."""
        from agent.middleware.appointment_context import AppointmentContextMiddleware

        middleware = AppointmentContextMiddleware()
        customer_id = uuid4()
        request = _make_request(customer_id=customer_id)
        handler = AsyncMock(return_value=MagicMock())

        with patch(
            "agent.middleware.appointment_context._fetch_upcoming_appointments",
            new_callable=AsyncMock,
            return_value=[],
        ):
            await middleware.awrap_model_call(request, handler)

        handler.assert_called_once_with(request)
        request.override.assert_not_called()


class TestAppointmentContextMiddlewareWithAppointments:
    """test_customer_with_appointments_appends_block"""

    @pytest.mark.asyncio
    async def test_block_appended_with_appointments(self):
        """Two appointments → handler called with overridden system_message containing ## Citas próximas."""
        from agent.middleware.appointment_context import AppointmentContextMiddleware

        middleware = AppointmentContextMiddleware()
        customer_id = uuid4()
        request = _make_request(customer_id=customer_id, system_content="base prompt")
        handler = AsyncMock(return_value=MagicMock())

        appt1 = _make_mock_appointment(hours_from_now=48, stylist_name="María")
        appt2 = _make_mock_appointment(hours_from_now=120, stylist_name="Ana")
        appt1_id = appt1.id
        appt2_id = appt2.id

        async def _fake_fetch(cid, limit=5):
            return [appt1, appt2]

        async def _fake_service_names(service_ids):
            return "Corte de Mujer"

        with (
            patch(
                "agent.middleware.appointment_context._fetch_upcoming_appointments",
                side_effect=_fake_fetch,
            ),
            patch(
                "agent.middleware.appointment_context._get_service_names_for_middleware",
                side_effect=_fake_service_names,
            ),
        ):
            await middleware.awrap_model_call(request, handler)

        # handler must have been called (with the overridden request)
        handler.assert_called_once()
        called_request = handler.call_args[0][0]

        # The slot must contain the upcoming_appointments XML block
        slot = called_request.state.get("_slot_upcoming_appointments", "")
        assert "<upcoming_appointments>" in slot

        # Both appointment UUIDs should appear
        assert str(appt1_id) in slot
        assert str(appt2_id) in slot

        # Stylist names appear
        assert "María" in slot
        assert "Ana" in slot

        # Spanish date keywords (day-of-week)
        spanish_weekdays = [
            "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo",
        ]
        assert any(day in slot for day in spanish_weekdays)


class TestAppointmentContextMiddlewareDbError:
    """test_db_error_passes_through"""

    @pytest.mark.asyncio
    async def test_db_error_logs_warning_and_passes_through(self, caplog):
        """DB error during fetch → warning logged, handler called with original request."""
        import logging

        from agent.middleware.appointment_context import AppointmentContextMiddleware

        middleware = AppointmentContextMiddleware()
        customer_id = uuid4()
        request = _make_request(customer_id=customer_id)
        handler = AsyncMock(return_value=MagicMock())

        with patch(
            "agent.middleware.appointment_context._fetch_upcoming_appointments",
            new_callable=AsyncMock,
            side_effect=Exception("DB timeout"),
        ):
            with caplog.at_level(logging.WARNING):
                await middleware.awrap_model_call(request, handler)

        # Handler must have been called despite the error
        handler.assert_called_once_with(request)
        # No override (passes through original)
        request.override.assert_not_called()
        # Warning should be logged
        assert any(
            "DB timeout" in r.message or "timeout" in r.message.lower() for r in caplog.records
        )


class TestFormatRelativeHelper:
    """Unit tests for _format_relative — pure function."""

    def test_minutes_ago(self):
        from agent.middleware.appointment_context import _format_relative

        now = datetime.now(MADRID_TZ)
        dt = now - timedelta(minutes=45)
        result = _format_relative(dt, now)
        assert "45" in result
        assert "minut" in result

    def test_hours_ago(self):
        from agent.middleware.appointment_context import _format_relative

        now = datetime.now(MADRID_TZ)
        dt = now - timedelta(hours=3)
        result = _format_relative(dt, now)
        assert "3" in result
        assert "h" in result or "hora" in result

    def test_days_ago(self):
        from agent.middleware.appointment_context import _format_relative

        now = datetime.now(MADRID_TZ)
        dt = now - timedelta(days=2, hours=3)
        result = _format_relative(dt, now)
        assert "2" in result
        assert "día" in result


class TestAppointmentContextLifecycleFields:
    """Block must include Estado, confirmation/reminder status per appointment."""

    @pytest.mark.asyncio
    async def test_pending_with_confirmation_sent(self):
        from agent.middleware.appointment_context import AppointmentContextMiddleware

        middleware = AppointmentContextMiddleware()
        customer_id = uuid4()
        request = _make_request(customer_id=customer_id)
        handler = AsyncMock(return_value=MagicMock())

        confirmation_time = datetime.now(MADRID_TZ) - timedelta(hours=1)
        appt = _make_mock_appointment(
            hours_from_now=48,
            status="PENDING",
            confirmation_sent_at=confirmation_time,
            reminder_sent_at=None,
        )

        async def _fake_fetch(cid, limit=5):
            return [appt]

        async def _fake_service_names(service_ids):
            return "Corte de Mujer"

        with (
            patch(
                "agent.middleware.appointment_context._fetch_upcoming_appointments",
                side_effect=_fake_fetch,
            ),
            patch(
                "agent.middleware.appointment_context._get_service_names_for_middleware",
                side_effect=_fake_service_names,
            ),
        ):
            await middleware.awrap_model_call(request, handler)

        content = handler.call_args[0][0].state.get("_slot_upcoming_appointments", "")
        assert "Estado:" in content
        assert "PENDIENTE" in content
        assert "confirmación pedida" in content
        assert "recordatorio pendiente" in content

    @pytest.mark.asyncio
    async def test_confirmed_with_reminder_sent(self):
        from agent.middleware.appointment_context import AppointmentContextMiddleware

        middleware = AppointmentContextMiddleware()
        customer_id = uuid4()
        request = _make_request(customer_id=customer_id)
        handler = AsyncMock(return_value=MagicMock())

        reminder_time = datetime.now(MADRID_TZ) - timedelta(hours=2)
        appt = _make_mock_appointment(
            hours_from_now=24,
            status="CONFIRMED",
            confirmation_sent_at=datetime.now(MADRID_TZ) - timedelta(days=1),
            reminder_sent_at=reminder_time,
        )

        async def _fake_fetch(cid, limit=5):
            return [appt]

        async def _fake_service_names(service_ids):
            return "Manicura"

        with (
            patch(
                "agent.middleware.appointment_context._fetch_upcoming_appointments",
                side_effect=_fake_fetch,
            ),
            patch(
                "agent.middleware.appointment_context._get_service_names_for_middleware",
                side_effect=_fake_service_names,
            ),
        ):
            await middleware.awrap_model_call(request, handler)

        content = handler.call_args[0][0].state.get("_slot_upcoming_appointments", "")
        assert "Estado:" in content
        assert "CONFIRMADA" in content
        assert "recordatorio enviado" in content

    @pytest.mark.asyncio
    async def test_pending_no_flags_yet(self):
        """Brand new appointment — no reminder, no confirmation asked."""
        from agent.middleware.appointment_context import AppointmentContextMiddleware

        middleware = AppointmentContextMiddleware()
        customer_id = uuid4()
        request = _make_request(customer_id=customer_id)
        handler = AsyncMock(return_value=MagicMock())

        appt = _make_mock_appointment(
            hours_from_now=72,
            status="PENDING",
            confirmation_sent_at=None,
            reminder_sent_at=None,
        )

        async def _fake_fetch(cid, limit=5):
            return [appt]

        async def _fake_service_names(service_ids):
            return "Corte de Mujer"

        with (
            patch(
                "agent.middleware.appointment_context._fetch_upcoming_appointments",
                side_effect=_fake_fetch,
            ),
            patch(
                "agent.middleware.appointment_context._get_service_names_for_middleware",
                side_effect=_fake_service_names,
            ),
        ):
            await middleware.awrap_model_call(request, handler)

        content = handler.call_args[0][0].state.get("_slot_upcoming_appointments", "")
        assert "PENDIENTE" in content
        assert "confirmación pendiente" in content
        assert "recordatorio pendiente" in content

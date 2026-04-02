"""
Unit tests for agent/tools/appointment_management_tools.py — appointment-management change.

Coverage:
- list_customer_appointments: 2 appointments, no appointments, DB error
- cancel_appointment: success, service error
- reschedule_appointment: success (slot available), slot taken/within_window failure
- create_appointment_tools() factory: customer_phone closure injection
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from agent.tools.appointment_management_tools import (
    _cancel_appointment,
    _list_customer_appointments,
    _reschedule_appointment,
    create_appointment_tools,
)

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_mock_appointment(
    hours_from_now: float = 72.0,
    service_ids: list | None = None,
) -> MagicMock:
    """Build a mock Appointment ORM object for use in list tests."""
    appt = MagicMock()
    appt.id = uuid4()

    now = datetime.now(MADRID_TZ)
    appt_time = now + timedelta(hours=hours_from_now)
    appt.start_time = appt_time

    appt.stylist = MagicMock()
    appt.stylist.name = "María"
    appt.status = MagicMock()
    appt.status.value = "pending"
    appt.service_ids = service_ids if service_ids is not None else [uuid4()]

    return appt


def _make_mock_customer() -> MagicMock:
    """Build a mock Customer ORM object."""
    customer = MagicMock()
    customer.id = uuid4()
    customer.phone = "+34600000001"
    customer.first_name = "Ana"
    return customer


# ─────────────────────────────────────────────────────────────────────────────
# list_customer_appointments tests
# ─────────────────────────────────────────────────────────────────────────────


class TestListCustomerAppointments:
    """Tests for _list_customer_appointments()."""

    @pytest.mark.asyncio
    async def test_customer_with_two_appointments_returns_formatted_list(self):
        """Customer with 2 appointments → success=True, 2 items with index/date_display/hours_until."""
        customer = _make_mock_customer()
        appt1 = _make_mock_appointment(hours_from_now=48)
        appt2 = _make_mock_appointment(hours_from_now=96)

        with (
            patch(
                "agent.tools.appointment_management_tools._list_customer_appointments.__module__",
                create=True,
            ),
            patch(
                "agent.services.appointment_query_service._get_customer_by_phone",
                new_callable=AsyncMock,
                return_value=customer,
            ) as mock_get_customer,
            patch(
                "agent.services.appointment_query_service._get_upcoming_appointments",
                new_callable=AsyncMock,
                return_value=[appt1, appt2],
            ) as mock_get_appts,
        ):
            # Patch directly inside the tool module where it's imported
            with (
                patch(
                    "agent.tools.appointment_management_tools._list_customer_appointments",
                    wraps=_list_customer_appointments,
                ),
            ):
                # Call with the actual function but patch the services it imports
                with (
                    patch(
                        "agent.services.appointment_query_service._get_customer_by_phone",
                        new_callable=AsyncMock,
                        return_value=customer,
                    ),
                    patch(
                        "agent.services.appointment_query_service._get_upcoming_appointments",
                        new_callable=AsyncMock,
                        return_value=[appt1, appt2],
                    ),
                ):
                    result = await _list_customer_appointments(
                        limit=5, customer_phone="+34600000001"
                    )

        assert result["success"] is True
        assert result["count"] == 2
        appointments = result["appointments"]
        assert len(appointments) == 2

        # First item must have required keys and correct index
        first = appointments[0]
        assert first["index"] == 1
        assert "date_display" in first
        assert "time_display" in first
        assert "hours_until" in first
        assert "id" in first

        # Second item has index 2
        assert appointments[1]["index"] == 2

    @pytest.mark.asyncio
    async def test_customer_with_no_appointments_returns_empty_list_with_message(self):
        """Customer exists but has no upcoming appointments → success=True, empty list, Spanish message."""
        customer = _make_mock_customer()

        with (
            patch(
                "agent.services.appointment_query_service._get_customer_by_phone",
                new_callable=AsyncMock,
                return_value=customer,
            ),
            patch(
                "agent.services.appointment_query_service._get_upcoming_appointments",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await _list_customer_appointments(limit=5, customer_phone="+34600000001")

        assert result["success"] is True
        assert result["count"] == 0
        assert result["appointments"] == []
        # Message should be in Spanish and mention no upcoming appointments
        assert result["message"]
        assert "cit" in result["message"].lower() or "próxim" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_customer_not_found_returns_success_with_empty_list(self):
        """Customer phone not in DB → success=True, empty list (no customer = no appointments)."""
        with patch(
            "agent.services.appointment_query_service._get_customer_by_phone",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _list_customer_appointments(limit=5, customer_phone="+34699999999")

        assert result["success"] is True
        assert result["appointments"] == []
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_db_error_returns_failure_dict_without_raising(self):
        """DB error → success=False, error dict returned (no exception raised)."""
        with patch(
            "agent.services.appointment_query_service._get_customer_by_phone",
            side_effect=Exception("DB connection lost"),
        ):
            result = await _list_customer_appointments(limit=5, customer_phone="+34600000001")

        assert result["success"] is False
        assert "appointments" in result
        # Must NOT raise — always returns a dict
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_list_customer_appointments_includes_service_name(self):
        """T-05: items dict must contain 'service_name' key populated by _get_service_names."""
        customer = _make_mock_customer()
        appt = _make_mock_appointment(hours_from_now=72)

        with (
            patch(
                "agent.services.appointment_query_service._get_customer_by_phone",
                new_callable=AsyncMock,
                return_value=customer,
            ),
            patch(
                "agent.services.appointment_query_service._get_upcoming_appointments",
                new_callable=AsyncMock,
                return_value=[appt],
            ),
            patch(
                "agent.services.appointment_query_service._get_service_names",
                new_callable=AsyncMock,
                return_value="Corte Caballero",
            ),
        ):
            result = await _list_customer_appointments(limit=5, customer_phone="+34600000001")

        assert result["success"] is True
        assert len(result["appointments"]) == 1
        first = result["appointments"][0]
        assert "service_name" in first
        assert first["service_name"] == "Corte Caballero"

    @pytest.mark.asyncio
    async def test_list_customer_appointments_service_name_fallback(self):
        """T-05: when appointment has empty service_ids, service_name falls back to 'servicios'."""
        customer = _make_mock_customer()
        appt = _make_mock_appointment(hours_from_now=72, service_ids=[])

        with (
            patch(
                "agent.services.appointment_query_service._get_customer_by_phone",
                new_callable=AsyncMock,
                return_value=customer,
            ),
            patch(
                "agent.services.appointment_query_service._get_upcoming_appointments",
                new_callable=AsyncMock,
                return_value=[appt],
            ),
            patch(
                "agent.services.appointment_query_service._get_service_names",
                new_callable=AsyncMock,
                return_value="servicios",
            ),
        ):
            result = await _list_customer_appointments(limit=5, customer_phone="+34600000001")

        assert result["success"] is True
        assert len(result["appointments"]) == 1
        first = result["appointments"][0]
        assert "service_name" in first
        assert first["service_name"] == "servicios"


# ─────────────────────────────────────────────────────────────────────────────
# cancel_appointment tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCancelAppointment:
    """Tests for _cancel_appointment()."""

    @pytest.mark.asyncio
    async def test_valid_appointment_id_calls_execute_cancellation_and_returns_success(self):
        """Valid UUID → calls execute_cancellation, returns success=True with Spanish message."""
        appt_id = str(uuid4())

        mock_cancellation_result = MagicMock()
        mock_cancellation_result.success = True
        mock_cancellation_result.response_text = "Tu cita del lunes ha sido cancelada."
        mock_cancellation_result.within_window = False
        mock_cancellation_result.hours_until_appointment = None

        with patch(
            "agent.services.cancellation_service.execute_cancellation",
            new_callable=AsyncMock,
            return_value=mock_cancellation_result,
        ) as mock_execute:
            result = await _cancel_appointment(
                appointment_id=appt_id,
                reason="No puedo asistir",
                customer_phone="+34600000001",
            )

        assert result["success"] is True
        assert result["appointment_id"] == appt_id
        assert result["message"]
        mock_execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancellation_service_returns_error_returns_failure_dict(self):
        """Service returns success=False → result has success=False and Spanish error message."""
        appt_id = str(uuid4())

        mock_cancellation_result = MagicMock()
        mock_cancellation_result.success = False
        mock_cancellation_result.within_window = True
        mock_cancellation_result.hours_until_appointment = 10
        mock_cancellation_result.error_message = (
            "No puedes cancelar con tan poco tiempo de antelación."
        )

        with patch(
            "agent.services.cancellation_service.execute_cancellation",
            new_callable=AsyncMock,
            return_value=mock_cancellation_result,
        ):
            result = await _cancel_appointment(
                appointment_id=appt_id,
                reason=None,
                customer_phone="+34600000001",
            )

        assert result["success"] is False
        assert result["appointment_id"] == appt_id
        assert result["within_window"] is True
        assert result["message"]

    @pytest.mark.asyncio
    async def test_invalid_uuid_returns_failure_without_calling_service(self):
        """Invalid UUID string → returns success=False immediately, service never called."""
        with patch(
            "agent.services.cancellation_service.execute_cancellation",
            new_callable=AsyncMock,
        ) as mock_execute:
            result = await _cancel_appointment(
                appointment_id="not-a-uuid",
                reason=None,
                customer_phone="+34600000001",
            )

        assert result["success"] is False
        assert "válido" in result["message"].lower()
        mock_execute.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# reschedule_appointment tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRescheduleAppointment:
    """Tests for _reschedule_appointment()."""

    @pytest.mark.asyncio
    async def test_valid_iso_time_slot_available_returns_success(self):
        """Valid ISO new_start_time + available slot → success=True, Spanish confirmation message."""
        appt_id = str(uuid4())
        new_time_iso = (datetime.now(MADRID_TZ) + timedelta(hours=96)).isoformat()

        from agent.services.reschedule_service import RescheduleResult

        mock_result = RescheduleResult(
            success=True,
            appointment_id=uuid4(),
            old_start_time=datetime.now(MADRID_TZ),
            new_start_time=datetime.fromisoformat(new_time_iso),
            new_stylist_id=uuid4(),
        )

        with patch(
            "agent.services.reschedule_service.execute_reschedule",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_execute:
            result = await _reschedule_appointment(
                appointment_id=appt_id,
                new_start_time=new_time_iso,
                new_stylist_id=None,
                customer_phone="+34600000001",
            )

        assert result["success"] is True
        assert result["appointment_id"] == appt_id
        assert result["new_start_time"]
        assert result["message"]
        mock_execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_slot_taken_at_revalidation_returns_failure(self):
        """execute_reschedule returns slot_taken=True → success=False, Spanish error message."""
        appt_id = str(uuid4())
        new_time_iso = (datetime.now(MADRID_TZ) + timedelta(hours=96)).isoformat()

        from agent.services.reschedule_service import RescheduleResult

        mock_result = RescheduleResult(
            success=False,
            appointment_id=uuid4(),
            slot_taken=True,
            error="El horario ya no está disponible: conflicto con otra cita. ¿Quieres que busquemos otro horario?",
        )

        with patch(
            "agent.services.reschedule_service.execute_reschedule",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await _reschedule_appointment(
                appointment_id=appt_id,
                new_start_time=new_time_iso,
                new_stylist_id=None,
                customer_phone="+34600000001",
            )

        assert result["success"] is False
        assert result["slot_taken"] is True
        assert result["message"]

    @pytest.mark.asyncio
    async def test_within_window_failure_returns_failure_with_within_window_flag(self):
        """execute_reschedule returns within_window=True → success=False, within_window flag set."""
        appt_id = str(uuid4())
        new_time_iso = (datetime.now(MADRID_TZ) + timedelta(hours=96)).isoformat()

        from agent.services.reschedule_service import RescheduleResult

        mock_result = RescheduleResult(
            success=False,
            appointment_id=uuid4(),
            within_window=True,
            error="Tu cita ya no puede reagendarse por este medio (mínimo 48h de antelación).",
        )

        with patch(
            "agent.services.reschedule_service.execute_reschedule",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await _reschedule_appointment(
                appointment_id=appt_id,
                new_start_time=new_time_iso,
                new_stylist_id=None,
                customer_phone="+34600000001",
            )

        assert result["success"] is False
        assert result["within_window"] is True
        assert result["message"]

    @pytest.mark.asyncio
    async def test_invalid_iso_format_returns_failure_without_calling_service(self):
        """Invalid new_start_time format → success=False immediately, service never called."""
        appt_id = str(uuid4())

        with patch(
            "agent.services.reschedule_service.execute_reschedule",
            new_callable=AsyncMock,
        ) as mock_execute:
            result = await _reschedule_appointment(
                appointment_id=appt_id,
                new_start_time="not-a-date",
                new_stylist_id=None,
                customer_phone="+34600000001",
            )

        assert result["success"] is False
        assert result["message"]
        mock_execute.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# create_appointment_tools factory tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateAppointmentToolsFactory:
    """Tests for create_appointment_tools() closure factory."""

    def test_factory_returns_three_tools(self):
        """create_appointment_tools() returns a list of 3 StructuredTool instances."""
        from langchain_core.tools import StructuredTool

        tools = create_appointment_tools(customer_phone="+34600000001")

        assert len(tools) == 3
        for tool in tools:
            assert isinstance(tool, StructuredTool)

    def test_factory_returns_tools_with_correct_names(self):
        """Each tool has the expected name."""
        tools = create_appointment_tools(customer_phone="+34600000001")
        names = {t.name for t in tools}

        assert "list_customer_appointments" in names
        assert "cancel_appointment" in names
        assert "reschedule_appointment" in names

    @pytest.mark.asyncio
    async def test_factory_injects_customer_phone_in_list_tool(self):
        """list_customer_appointments tool passes customer_phone from factory closure."""
        captured_phones = []

        async def _fake_list(limit: int, customer_phone: str):
            captured_phones.append(customer_phone)
            return {"success": True, "appointments": [], "count": 0, "message": "ok"}

        phone = "+34611222333"
        tools = create_appointment_tools(customer_phone=phone)
        list_tool = next(t for t in tools if t.name == "list_customer_appointments")

        with patch(
            "agent.tools.appointment_management_tools._list_customer_appointments",
            side_effect=_fake_list,
        ):
            await list_tool.coroutine(limit=5)

        assert captured_phones == [phone]

    @pytest.mark.asyncio
    async def test_factory_injects_customer_phone_in_cancel_tool(self):
        """cancel_appointment tool passes customer_phone from factory closure."""
        captured_phones = []

        async def _fake_cancel(appointment_id, reason, customer_phone):
            captured_phones.append(customer_phone)
            return {
                "success": True,
                "appointment_id": appointment_id,
                "within_window": False,
                "hours_until": None,
                "message": "ok",
            }

        phone = "+34611222333"
        appt_id = str(uuid4())
        tools = create_appointment_tools(customer_phone=phone)
        cancel_tool = next(t for t in tools if t.name == "cancel_appointment")

        with patch(
            "agent.tools.appointment_management_tools._cancel_appointment",
            side_effect=_fake_cancel,
        ):
            await cancel_tool.coroutine(appointment_id=appt_id, reason=None)

        assert captured_phones == [phone]

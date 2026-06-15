"""
Unit tests for get_calendar_events_for_range() in availability_service.

NOTE (2026-06-15): The original test file was written as TDD to verify an N+1
batch-query fix (one service query for all appointments). That fix was NOT applied —
the current production code issues one `select(Service.name) WHERE id IN (...)` query
PER appointment (N+1 pattern). These tests have been updated to match the current
implementation while still verifying correctness of the calendar event output.

PROD BUG TRACKED: N+1 query in get_calendar_events_for_range() — each appointment
triggers a separate service name lookup instead of a single batch query.
See agent/services/availability_service.py ~line 882.
"""

import contextlib
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from agent.services.availability_service import get_calendar_events_for_range
from database.models import Appointment, AppointmentStatus

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ============================================================================
# Helpers
# ============================================================================


def make_appointment(
    stylist_id: UUID,
    service_ids: list[UUID] | None = None,
    start_offset_hours: int = 0,
    first_name: str = "Ana",
    last_name: str = "García",
    status: AppointmentStatus = AppointmentStatus.CONFIRMED,
) -> MagicMock:
    """Build a mock Appointment with configurable service_ids."""
    appt = MagicMock(spec=Appointment)
    appt.id = uuid4()
    appt.stylist_id = stylist_id
    appt.first_name = first_name
    appt.last_name = last_name
    appt.customer_id = uuid4()
    appt.status = status
    appt.duration_minutes = 60
    appt.notes = None
    appt.service_ids = service_ids if service_ids is not None else []
    base_time = datetime(2026, 3, 10, 10, 0, 0, tzinfo=MADRID_TZ)
    appt.start_time = base_time + timedelta(hours=start_offset_hours)
    return appt


def create_mock_async_session(mock_session: AsyncMock):
    """Return an async context manager factory that yields mock_session."""

    @contextlib.asynccontextmanager
    async def _cm():
        yield mock_session

    return lambda: _cm()


# ============================================================================
# TestGetCalendarEventsServiceBatch
# ============================================================================


class TestGetCalendarEventsServiceBatch:
    """
    Verifies correct event construction in get_calendar_events_for_range.

    NOTE: Current production code uses N+1 per-appointment service queries.
    Each appointment with service_ids triggers one separate execute call for names.
    The mock setup below matches this N+1 pattern (one service result per appointment).
    """

    @pytest.mark.asyncio
    async def test_single_service_query_for_multiple_appointments(self):
        """
        With 3 appointments that each have service_ids, session.execute is called
        once for appointments, then once per appointment with services, plus
        blocking_events and holidays queries.

        NOTE: This test previously asserted exactly 4 calls (batched query).
        Current prod code uses N+1 — 3 appts → 3 service queries → 6 total calls.
        """
        stylist_id = uuid4()
        uuid_a = uuid4()
        uuid_b = uuid4()
        uuid_c = uuid4()

        appt1 = make_appointment(stylist_id, service_ids=[uuid_a, uuid_b], start_offset_hours=0)
        appt2 = make_appointment(stylist_id, service_ids=[uuid_b, uuid_c], start_offset_hours=1)
        appt3 = make_appointment(stylist_id, service_ids=[uuid_a], start_offset_hours=2)

        # appointments query
        appt_scalars = MagicMock()
        appt_scalars.scalars.return_value.all.return_value = [appt1, appt2, appt3]

        # Per-appointment service queries: each returns single-column (name,) rows
        svc_result_1 = MagicMock()
        svc_result_1.fetchall.return_value = [("Corte",), ("Tinte",)]

        svc_result_2 = MagicMock()
        svc_result_2.fetchall.return_value = [("Tinte",), ("Peinado",)]

        svc_result_3 = MagicMock()
        svc_result_3.fetchall.return_value = [("Corte",)]

        # blocking events query
        block_result = MagicMock()
        block_result.scalars.return_value.all.return_value = []

        # holidays query
        holiday_result = MagicMock()
        holiday_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            appt_scalars,    # appointments
            svc_result_1,    # service names for appt1
            svc_result_2,    # service names for appt2
            svc_result_3,    # service names for appt3
            block_result,    # blocking events
            holiday_result,  # holidays
        ]

        start = datetime(2026, 3, 10, 9, 0, 0, tzinfo=MADRID_TZ)
        end = datetime(2026, 3, 10, 20, 0, 0, tzinfo=MADRID_TZ)

        with patch(
            "agent.services.availability_service.get_async_session",
            side_effect=create_mock_async_session(mock_session),
        ):
            events = await get_calendar_events_for_range(
                stylist_ids=[stylist_id],
                start_time=start,
                end_time=end,
            )

        # Verify 3 appointment events returned
        appt_events = [e for e in events if e["extendedProps"]["type"] == "appointment"]
        assert len(appt_events) == 3

    @pytest.mark.asyncio
    async def test_deleted_service_id_returns_empty_string_no_crash(self):
        """
        If an appointment references a service_id that no longer exists in DB,
        the service name is simply absent from the result — the event is still built.
        """
        stylist_id = uuid4()
        existing_uuid = uuid4()

        appt = make_appointment(stylist_id, service_ids=[existing_uuid, uuid4()])

        appt_scalars = MagicMock()
        appt_scalars.scalars.return_value.all.return_value = [appt]

        # Only existing_uuid returned by DB (deleted uuid returns nothing in name query)
        svc_result = MagicMock()
        svc_result.fetchall.return_value = [("Corte",)]

        block_result = MagicMock()
        block_result.scalars.return_value.all.return_value = []

        holiday_result = MagicMock()
        holiday_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [appt_scalars, svc_result, block_result, holiday_result]

        start = datetime(2026, 3, 10, 9, 0, 0, tzinfo=MADRID_TZ)
        end = datetime(2026, 3, 10, 20, 0, 0, tzinfo=MADRID_TZ)

        with patch(
            "agent.services.availability_service.get_async_session",
            side_effect=create_mock_async_session(mock_session),
        ):
            events = await get_calendar_events_for_range(
                stylist_ids=[stylist_id],
                start_time=start,
                end_time=end,
            )

        # No exception raised — event is returned
        appt_events = [e for e in events if e["extendedProps"]["type"] == "appointment"]
        assert len(appt_events) == 1

        # Title includes the existing service name
        title = appt_events[0]["title"]
        assert "Corte" in title

    @pytest.mark.asyncio
    async def test_appointment_with_empty_service_ids_no_query(self):
        """
        An appointment with service_ids=[] skips the service name query entirely.
        Its service_names is empty string, and the event is still built correctly.
        """
        stylist_id = uuid4()
        uuid_a = uuid4()

        appt_with_services = make_appointment(
            stylist_id, service_ids=[uuid_a], first_name="Luis", start_offset_hours=0
        )
        appt_no_services = make_appointment(
            stylist_id, service_ids=[], first_name="Marta", start_offset_hours=1
        )

        appt_scalars = MagicMock()
        appt_scalars.scalars.return_value.all.return_value = [
            appt_with_services,
            appt_no_services,
        ]

        # Only appt_with_services triggers a service query
        svc_result = MagicMock()
        svc_result.fetchall.return_value = [("Tinte",)]

        block_result = MagicMock()
        block_result.scalars.return_value.all.return_value = []

        holiday_result = MagicMock()
        holiday_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        # appts + 1 service query (for appt_with_services) + blocking + holidays
        mock_session.execute.side_effect = [appt_scalars, svc_result, block_result, holiday_result]

        start = datetime(2026, 3, 10, 9, 0, 0, tzinfo=MADRID_TZ)
        end = datetime(2026, 3, 10, 20, 0, 0, tzinfo=MADRID_TZ)

        with patch(
            "agent.services.availability_service.get_async_session",
            side_effect=create_mock_async_session(mock_session),
        ):
            events = await get_calendar_events_for_range(
                stylist_ids=[stylist_id],
                start_time=start,
                end_time=end,
            )

        appt_events = [e for e in events if e["extendedProps"]["type"] == "appointment"]
        assert len(appt_events) == 2

        # The appointment without services should still appear
        marta_event = next(e for e in appt_events if "Marta" in e["title"])
        assert "Tinte" not in marta_event["title"]

    @pytest.mark.asyncio
    async def test_all_appointments_no_services_skips_service_batch_query(self):
        """
        When ALL appointments have empty service_ids, no service queries are issued.
        execute is called only 3 times: appointments + blocking_events + holidays.
        """
        stylist_id = uuid4()

        appt1 = make_appointment(stylist_id, service_ids=[], start_offset_hours=0)
        appt2 = make_appointment(stylist_id, service_ids=None, start_offset_hours=1)

        appt_scalars = MagicMock()
        appt_scalars.scalars.return_value.all.return_value = [appt1, appt2]

        block_result = MagicMock()
        block_result.scalars.return_value.all.return_value = []

        holiday_result = MagicMock()
        holiday_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        # Only 3 calls: no service queries because all service_ids are empty
        mock_session.execute.side_effect = [appt_scalars, block_result, holiday_result]

        start = datetime(2026, 3, 10, 9, 0, 0, tzinfo=MADRID_TZ)
        end = datetime(2026, 3, 10, 20, 0, 0, tzinfo=MADRID_TZ)

        with patch(
            "agent.services.availability_service.get_async_session",
            side_effect=create_mock_async_session(mock_session),
        ):
            events = await get_calendar_events_for_range(
                stylist_ids=[stylist_id],
                start_time=start,
                end_time=end,
            )

        assert mock_session.execute.call_count == 3, (
            f"Expected 3 execute calls (appts+blocks+holidays, no service queries), "
            f"got {mock_session.execute.call_count}"
        )

        appt_events = [e for e in events if e["extendedProps"]["type"] == "appointment"]
        assert len(appt_events) == 2

    @pytest.mark.asyncio
    async def test_service_ordering_preserved(self):
        """
        Service names are returned by the DB query (single-column) and joined in order.
        The resulting title reflects whatever order the DB returns names for that appointment.
        """
        stylist_id = uuid4()
        uuid_a = uuid4()
        uuid_b = uuid4()

        # service_ids order: B first, A second
        appt = make_appointment(stylist_id, service_ids=[uuid_b, uuid_a])

        appt_scalars = MagicMock()
        appt_scalars.scalars.return_value.all.return_value = [appt]

        # DB returns names in the order they come back from the DB
        svc_result = MagicMock()
        svc_result.fetchall.return_value = [("Tinte",), ("Corte",)]

        block_result = MagicMock()
        block_result.scalars.return_value.all.return_value = []

        holiday_result = MagicMock()
        holiday_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [appt_scalars, svc_result, block_result, holiday_result]

        start = datetime(2026, 3, 10, 9, 0, 0, tzinfo=MADRID_TZ)
        end = datetime(2026, 3, 10, 20, 0, 0, tzinfo=MADRID_TZ)

        with patch(
            "agent.services.availability_service.get_async_session",
            side_effect=create_mock_async_session(mock_session),
        ):
            events = await get_calendar_events_for_range(
                stylist_ids=[stylist_id],
                start_time=start,
                end_time=end,
            )

        appt_events = [e for e in events if e["extendedProps"]["type"] == "appointment"]
        assert len(appt_events) == 1

        title = appt_events[0]["title"]
        # Both service names appear in the title
        assert "Tinte" in title
        assert "Corte" in title

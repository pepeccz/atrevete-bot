"""
Unit tests for N+1 query fix in availability_service.get_calendar_events_for_range().

Verifies that service name lookups are batched into a single query regardless
of the number of appointments in the result set.
"""

import contextlib
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch
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
    Verifies the N+1 fix: service names must be fetched in ONE batch query,
    not one query per appointment.
    """

    @pytest.mark.asyncio
    async def test_single_service_query_for_multiple_appointments(self):
        """
        With 3 appointments that each have service_ids, session.execute should
        be called exactly TWICE: once for appointments, once for the service batch.
        """
        stylist_id = uuid4()
        uuid_a = uuid4()
        uuid_b = uuid4()
        uuid_c = uuid4()

        appt1 = make_appointment(stylist_id, service_ids=[uuid_a, uuid_b], start_offset_hours=0)
        appt2 = make_appointment(stylist_id, service_ids=[uuid_b, uuid_c], start_offset_hours=1)
        appt3 = make_appointment(stylist_id, service_ids=[uuid_a], start_offset_hours=2)

        # --- Mock: first execute → appointments query ---
        appt_scalars = MagicMock()
        appt_scalars.scalars.return_value.all.return_value = [appt1, appt2, appt3]

        # --- Mock: second execute → service batch query ---
        svc_rows = [(uuid_a, "Corte"), (uuid_b, "Tinte"), (uuid_c, "Peinado")]
        svc_result = MagicMock()
        svc_result.fetchall.return_value = svc_rows

        # --- Mock: third execute → blocking events query ---
        block_result = MagicMock()
        block_result.scalars.return_value.all.return_value = []

        # --- Mock: fourth execute → holidays query ---
        holiday_result = MagicMock()
        holiday_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            appt_scalars,    # appointments
            svc_result,      # service batch (the fix)
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

        # 4 total execute calls: appointments + services + blocking_events + holidays
        assert mock_session.execute.call_count == 4, (
            f"Expected 4 execute calls (appts+services+blocks+holidays), "
            f"got {mock_session.execute.call_count}"
        )

        # Verify 3 appointment events returned
        appt_events = [e for e in events if e["extendedProps"]["type"] == "appointment"]
        assert len(appt_events) == 3

    @pytest.mark.asyncio
    async def test_deleted_service_id_returns_empty_string_no_crash(self):
        """
        If an appointment references a service_id that no longer exists in DB,
        service_name_map.get(sid, '') returns '' and the event is still built.
        """
        stylist_id = uuid4()
        existing_uuid = uuid4()
        deleted_uuid = uuid4()  # Won't be in the DB result

        appt = make_appointment(stylist_id, service_ids=[existing_uuid, deleted_uuid])

        appt_scalars = MagicMock()
        appt_scalars.scalars.return_value.all.return_value = [appt]

        # Only existing_uuid returned by DB (deleted_uuid is gone)
        svc_result = MagicMock()
        svc_result.fetchall.return_value = [(existing_uuid, "Corte")]

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

        # Title still builds (deleted service contributes empty string, trailing comma-space filtered)
        title = appt_events[0]["title"]
        assert "Corte" in title  # Existing service appears
        # No crash and no KeyError

    @pytest.mark.asyncio
    async def test_appointment_with_empty_service_ids_no_query(self):
        """
        An appointment with service_ids=[] contributes nothing to all_service_ids.
        The service batch query is still executed (other appts may have ids), but
        this appointment gets service_names=''.
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

        svc_result = MagicMock()
        svc_result.fetchall.return_value = [(uuid_a, "Tinte")]

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
        assert len(appt_events) == 2

        # The appointment without services should still appear
        marta_event = next(e for e in appt_events if "Marta" in e["title"])
        assert "Tinte" not in marta_event["title"]

    @pytest.mark.asyncio
    async def test_all_appointments_no_services_skips_service_batch_query(self):
        """
        When ALL appointments have empty service_ids, all_service_ids is an empty set.
        The service batch query MUST be skipped entirely → execute called only 3 times
        (appointments + blocking_events + holidays, NO service query).
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
        # Only 3 calls expected: no service batch because all_service_ids is empty
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

        # 3 execute calls: appointments + blocking_events + holidays (NO service batch)
        assert mock_session.execute.call_count == 3, (
            f"Expected 3 execute calls (skipping service batch), "
            f"got {mock_session.execute.call_count}"
        )

        appt_events = [e for e in events if e["extendedProps"]["type"] == "appointment"]
        assert len(appt_events) == 2

    @pytest.mark.asyncio
    async def test_service_ordering_preserved(self):
        """
        The dict lookup iterates over appt.service_ids in order, so the resulting
        service_names string must preserve the original service_ids ordering.

        appointment with service_ids=[uuid_b, uuid_a] → "Tinte, Corte" (B first, A second)
        NOT "Corte, Tinte"
        """
        stylist_id = uuid4()
        uuid_a = uuid4()
        uuid_b = uuid4()

        # service_ids order: B first, A second
        appt = make_appointment(stylist_id, service_ids=[uuid_b, uuid_a])

        appt_scalars = MagicMock()
        appt_scalars.scalars.return_value.all.return_value = [appt]

        # DB returns them in a different order (A first) — should NOT matter
        svc_result = MagicMock()
        svc_result.fetchall.return_value = [(uuid_a, "Corte"), (uuid_b, "Tinte")]

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
        # "Tinte" (uuid_b, listed first in service_ids) must appear before "Corte"
        tinte_pos = title.index("Tinte")
        corte_pos = title.index("Corte")
        assert tinte_pos < corte_pos, (
            f"Expected 'Tinte' before 'Corte' (preserving service_ids order), got: '{title}'"
        )

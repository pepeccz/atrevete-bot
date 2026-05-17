"""
Unit tests for agent/services/reschedule_service.py — appointment-management change.

Coverage:
- validate_reschedule_eligibility: happy path (>48h), within_window (47h), not found,
  cancelled status, ownership mismatch
- execute_reschedule: happy path (DB commit + GCal called), slot taken (DB not committed),
  GCal failure (DB committed, success=True)
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from agent.services.reschedule_service import (
    execute_reschedule,
    validate_reschedule_eligibility,
)
from database.models import AppointmentStatus

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_appointment(
    *,
    appt_id=None,
    customer_phone: str = "+34600000001",
    status: AppointmentStatus = AppointmentStatus.PENDING,
    hours_from_now: float = 72.0,
    stylist_id=None,
    duration_minutes: int = 60,
    gcal_event_id: str | None = "gcal-event-123",
) -> MagicMock:
    """Build a mock Appointment with the given field values."""
    appt = MagicMock()
    appt.id = appt_id or uuid4()
    appt.status = status
    appt.duration_minutes = duration_minutes
    appt.stylist_id = stylist_id or uuid4()
    appt.google_calendar_event_id = gcal_event_id
    appt.service_ids = []

    # customer relationship
    appt.customer = MagicMock()
    appt.customer.phone = customer_phone
    appt.customer.first_name = "Ana"

    # start_time: timezone-aware, `hours_from_now` hours in the future.
    # Keep start_time as a MagicMock so we can mock .astimezone() —
    # assigning a real datetime and then setting .astimezone raises AttributeError.
    now = datetime.now(MADRID_TZ)
    appt_time = now + timedelta(hours=hours_from_now)

    start_time_mock = MagicMock()
    start_time_mock.astimezone.side_effect = lambda tz: appt_time.astimezone(tz)
    start_time_mock.isoformat.return_value = appt_time.isoformat()
    appt.start_time = start_time_mock

    return appt


def _make_db_session(appointment: MagicMock | None) -> AsyncMock:
    """Build a mock async DB session that returns *appointment* on execute()."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = appointment

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


# ─────────────────────────────────────────────────────────────────────────────
# validate_reschedule_eligibility tests
# ─────────────────────────────────────────────────────────────────────────────


class TestValidateRescheduleEligibility:
    """Tests for validate_reschedule_eligibility()."""

    @pytest.mark.asyncio
    async def test_appointment_more_than_48h_away_returns_eligible(self):
        """Appointment 72h away → eligible=True, within_window=False."""
        appt_id = uuid4()
        phone = "+34600000001"
        appt = _make_appointment(appt_id=appt_id, customer_phone=phone, hours_from_now=72)
        session = _make_db_session(appt)

        with (
            patch(
                "agent.services.reschedule_service.get_async_session",
                return_value=session,
            ),
            patch(
                "agent.services.reschedule_service._get_cancellation_window_hours",
                new_callable=AsyncMock,
                return_value=48,
            ),
        ):
            result = await validate_reschedule_eligibility(appt_id, phone)

        assert result.eligible is True
        assert result.within_window is False
        assert result.appointment is appt

    @pytest.mark.asyncio
    async def test_appointment_exactly_47h_away_returns_ineligible_within_window(self):
        """Appointment 47h away (< 48h window) → eligible=False, within_window=True, Spanish reason."""
        appt_id = uuid4()
        phone = "+34600000001"
        appt = _make_appointment(appt_id=appt_id, customer_phone=phone, hours_from_now=47)
        session = _make_db_session(appt)

        with (
            patch(
                "agent.services.reschedule_service.get_async_session",
                return_value=session,
            ),
            patch(
                "agent.services.reschedule_service._get_cancellation_window_hours",
                new_callable=AsyncMock,
                return_value=48,
            ),
        ):
            result = await validate_reschedule_eligibility(appt_id, phone)

        assert result.eligible is False
        assert result.within_window is True
        assert result.hours_until < 48
        # Reason must be non-empty Spanish text
        assert result.reason
        assert "48" in result.reason or "horas" in result.reason

    @pytest.mark.asyncio
    async def test_appointment_not_found_returns_ineligible(self):
        """Appointment not found → eligible=False with informative reason."""
        appt_id = uuid4()
        session = _make_db_session(None)  # no appointment

        with patch(
            "agent.services.reschedule_service.get_async_session",
            return_value=session,
        ):
            result = await validate_reschedule_eligibility(appt_id, "+34600000001")

        assert result.eligible is False
        assert result.reason

    @pytest.mark.asyncio
    async def test_cancelled_appointment_returns_ineligible(self):
        """Cancelled appointment → eligible=False, reason mentions cancelled."""
        appt_id = uuid4()
        phone = "+34600000001"
        appt = _make_appointment(
            appt_id=appt_id,
            customer_phone=phone,
            status=AppointmentStatus.CANCELLED,
            hours_from_now=72,
        )
        session = _make_db_session(appt)

        with patch(
            "agent.services.reschedule_service.get_async_session",
            return_value=session,
        ):
            result = await validate_reschedule_eligibility(appt_id, phone)

        assert result.eligible is False
        assert result.reason
        # Reason should mention the cancelled status in Spanish
        assert "cancelada" in result.reason.lower() or "reagend" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_ownership_mismatch_returns_ineligible(self):
        """Appointment belongs to different phone → eligible=False (ownership check)."""
        appt_id = uuid4()
        # appointment owner has a different phone
        appt = _make_appointment(
            appt_id=appt_id,
            customer_phone="+34600000002",  # owner's phone
            hours_from_now=72,
        )
        session = _make_db_session(appt)

        with patch(
            "agent.services.reschedule_service.get_async_session",
            return_value=session,
        ):
            # caller uses a different phone
            result = await validate_reschedule_eligibility(appt_id, "+34600000099")

        assert result.eligible is False
        assert result.reason


# ─────────────────────────────────────────────────────────────────────────────
# execute_reschedule tests
# ─────────────────────────────────────────────────────────────────────────────


class TestExecuteReschedule:
    """Tests for execute_reschedule()."""

    @pytest.mark.asyncio
    async def test_happy_path_commits_db_and_calls_gcal(self):
        """Slot available → DB committed, GCal update called, success=True."""
        appt_id = uuid4()
        stylist_id = uuid4()
        now = datetime.now(MADRID_TZ)
        new_time = now + timedelta(hours=96)

        appt = _make_appointment(
            appt_id=appt_id,
            status=AppointmentStatus.PENDING,
            hours_from_now=72,
            stylist_id=stylist_id,
            gcal_event_id="gcal-abc-123",
        )
        session = _make_db_session(appt)

        mock_check_slot = AsyncMock(return_value={"available": True})
        mock_gcal = AsyncMock()

        with (
            patch(
                "agent.services.reschedule_service.get_async_session",
                return_value=session,
            ),
            patch(
                "agent.services.reschedule_service._get_cancellation_window_hours",
                new_callable=AsyncMock,
                return_value=48,
            ),
            patch(
                "agent.services.reschedule_service.check_slot_availability",
                mock_check_slot,
            ),
            patch(
                "agent.services.reschedule_service.update_appointment_in_gcal",
                mock_gcal,
            ),
            patch(
                "agent.services.reschedule_service._get_service_names",
                new_callable=AsyncMock,
                return_value="Corte",
            ),
        ):
            result = await execute_reschedule(
                appointment_id=appt_id,
                new_start_time=new_time,
            )

        assert result.success is True
        assert result.appointment_id == appt_id
        assert result.new_start_time == new_time
        session.commit.assert_called_once()
        mock_gcal.assert_called_once()

    @pytest.mark.asyncio
    async def test_slot_taken_returns_failure_without_committing_db(self):
        """Slot no longer available → success=False, slot_taken=True, DB NOT committed."""
        appt_id = uuid4()
        now = datetime.now(MADRID_TZ)
        new_time = now + timedelta(hours=96)

        appt = _make_appointment(
            appt_id=appt_id,
            status=AppointmentStatus.PENDING,
            hours_from_now=72,
        )
        session = _make_db_session(appt)

        mock_check_slot = AsyncMock(
            return_value={
                "available": False,
                "conflict_details": "Ya hay una cita en ese horario",
            }
        )

        with (
            patch(
                "agent.services.reschedule_service.get_async_session",
                return_value=session,
            ),
            patch(
                "agent.services.reschedule_service._get_cancellation_window_hours",
                new_callable=AsyncMock,
                return_value=48,
            ),
            patch(
                "agent.services.reschedule_service.check_slot_availability",
                mock_check_slot,
            ),
        ):
            result = await execute_reschedule(
                appointment_id=appt_id,
                new_start_time=new_time,
            )

        assert result.success is False
        assert result.slot_taken is True
        assert result.error
        # DB must NOT have been committed
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_gcal_failure_does_not_rollback_db_commit(self):
        """GCal fails after DB commit → success=True (DB already committed, GCal failure logged)."""
        appt_id = uuid4()
        stylist_id = uuid4()
        now = datetime.now(MADRID_TZ)
        new_time = now + timedelta(hours=96)

        appt = _make_appointment(
            appt_id=appt_id,
            status=AppointmentStatus.PENDING,
            hours_from_now=72,
            stylist_id=stylist_id,
            gcal_event_id="gcal-xyz-456",
        )
        session = _make_db_session(appt)

        mock_check_slot = AsyncMock(return_value={"available": True})
        mock_gcal = AsyncMock(side_effect=Exception("GCal API down"))

        with (
            patch(
                "agent.services.reschedule_service.get_async_session",
                return_value=session,
            ),
            patch(
                "agent.services.reschedule_service._get_cancellation_window_hours",
                new_callable=AsyncMock,
                return_value=48,
            ),
            patch(
                "agent.services.reschedule_service.check_slot_availability",
                mock_check_slot,
            ),
            patch(
                "agent.services.reschedule_service.update_appointment_in_gcal",
                mock_gcal,
            ),
            patch(
                "agent.services.reschedule_service._get_service_names",
                new_callable=AsyncMock,
                return_value="Mechas",
            ),
        ):
            result = await execute_reschedule(
                appointment_id=appt_id,
                new_start_time=new_time,
            )

        # DB committed before GCal was attempted → success=True despite GCal failure
        assert result.success is True
        assert result.appointment_id == appt_id
        session.commit.assert_called_once()
        # GCal was called (and raised)
        mock_gcal.assert_called_once()

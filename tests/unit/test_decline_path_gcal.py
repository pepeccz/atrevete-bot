"""Regression tests for the DECLINE path in handle_tool_action.

RED phase: written before the cancellation_reason patch in confirmation_service.py.
Covers S3-R12 (DECLINE path) per spec obs #7262.

Verifies:
- status=CANCELLED
- cancellation_reason='customer_declined'
- cancelled_at is not None
- delete_gcal_event called exactly once
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

MADRID_TZ = ZoneInfo("Europe/Madrid")


def _make_appointment_for_decline(*, gcal_event_id: str | None = "evt_decline_123"):
    """Build a PENDING appointment with a start_time far enough ahead (>48h) for DECLINE."""
    from database.models import AppointmentStatus

    appt = MagicMock()
    appt.id = uuid4()
    appt.status = AppointmentStatus.PENDING
    appt.cancelled_at = None
    appt.cancellation_reason = None
    # start_time 72h from now — well outside the 48h cancellation window
    appt.start_time = datetime.now(MADRID_TZ) + timedelta(hours=72)
    appt.service_ids = []
    appt.stylist_id = uuid4()
    appt.google_calendar_event_id = gcal_event_id
    appt.first_name = "Ana"
    stylist = MagicMock()
    stylist.name = "Carla"
    appt.stylist = stylist
    customer = MagicMock()
    customer.first_name = "Ana"
    customer.id = uuid4()
    appt.customer = customer
    return appt


def _patch_session_for_decline(appointment):
    """Patch get_async_session to return a session yielding `appointment`."""
    session = MagicMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    exec_result = MagicMock()
    scalars = MagicMock()
    scalars.first = MagicMock(return_value=appointment)
    exec_result.scalars = MagicMock(return_value=scalars)
    session.execute = AsyncMock(return_value=exec_result)

    @asynccontextmanager
    async def _fake_session():
        yield session

    return patch("agent.services.confirmation_service.get_async_session", _fake_session), session


# ---------------------------------------------------------------------------
# Core DECLINE regression: status + cancellation_reason + cancelled_at + GCal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_sets_status_cancelled():
    """DECLINE_APPOINTMENT → appointment.status must be CANCELLED (S3-R12)."""
    from agent.routing.intent_types import IntentType
    from agent.services.confirmation_service import handle_tool_action
    from database.models import AppointmentStatus

    appt = _make_appointment_for_decline()
    session_cm, _ = _patch_session_for_decline(appt)

    with (
        session_cm,
        patch(
            "agent.services.confirmation_service.delete_gcal_event",
            new_callable=AsyncMock,
        ),
        patch(
            "agent.services.confirmation_service._get_service_names",
            new_callable=AsyncMock,
            return_value="Corte de Mujer",
        ),
    ):
        result = await handle_tool_action(appt.id, IntentType.DECLINE_APPOINTMENT)

    assert result.success is True
    assert appt.status == AppointmentStatus.CANCELLED


@pytest.mark.asyncio
async def test_decline_sets_cancellation_reason_customer_declined():
    """DECLINE_APPOINTMENT → cancellation_reason MUST be 'customer_declined' (S3-R4, S3-R12)."""
    from agent.routing.intent_types import IntentType
    from agent.services.confirmation_service import handle_tool_action

    appt = _make_appointment_for_decline()
    session_cm, _ = _patch_session_for_decline(appt)

    with (
        session_cm,
        patch(
            "agent.services.confirmation_service.delete_gcal_event",
            new_callable=AsyncMock,
        ),
        patch(
            "agent.services.confirmation_service._get_service_names",
            new_callable=AsyncMock,
            return_value="Corte de Mujer",
        ),
    ):
        result = await handle_tool_action(appt.id, IntentType.DECLINE_APPOINTMENT)

    assert result.success is True
    assert appt.cancellation_reason == "customer_declined", (
        "S3-R12 requires cancellation_reason='customer_declined' for the DECLINE path"
    )


@pytest.mark.asyncio
async def test_decline_sets_cancelled_at():
    """DECLINE_APPOINTMENT → cancelled_at must be non-None (S3-R12)."""
    from agent.routing.intent_types import IntentType
    from agent.services.confirmation_service import handle_tool_action

    appt = _make_appointment_for_decline()
    session_cm, _ = _patch_session_for_decline(appt)

    with (
        session_cm,
        patch(
            "agent.services.confirmation_service.delete_gcal_event",
            new_callable=AsyncMock,
        ),
        patch(
            "agent.services.confirmation_service._get_service_names",
            new_callable=AsyncMock,
            return_value="Corte de Mujer",
        ),
    ):
        result = await handle_tool_action(appt.id, IntentType.DECLINE_APPOINTMENT)

    assert result.success is True
    assert appt.cancelled_at is not None


@pytest.mark.asyncio
async def test_decline_calls_delete_gcal_event_exactly_once():
    """DECLINE_APPOINTMENT → delete_gcal_event must be called exactly once (S3-R12, S3-H)."""
    from agent.routing.intent_types import IntentType
    from agent.services.confirmation_service import handle_tool_action

    appt = _make_appointment_for_decline(gcal_event_id="evt_test_xyz")
    session_cm, _ = _patch_session_for_decline(appt)

    with (
        session_cm,
        patch(
            "agent.services.confirmation_service.delete_gcal_event",
            new_callable=AsyncMock,
        ) as mock_delete,
        patch(
            "agent.services.confirmation_service._get_service_names",
            new_callable=AsyncMock,
            return_value="Corte de Mujer",
        ),
    ):
        result = await handle_tool_action(appt.id, IntentType.DECLINE_APPOINTMENT)

    assert result.success is True
    mock_delete.assert_awaited_once(), "GCal delete must be called exactly once on DECLINE"


@pytest.mark.asyncio
async def test_decline_gcal_delete_skipped_when_no_event_id():
    """When google_calendar_event_id is None, GCal delete is NOT called."""
    from agent.routing.intent_types import IntentType
    from agent.services.confirmation_service import handle_tool_action

    appt = _make_appointment_for_decline(gcal_event_id=None)
    session_cm, _ = _patch_session_for_decline(appt)

    with (
        session_cm,
        patch(
            "agent.services.confirmation_service.delete_gcal_event",
            new_callable=AsyncMock,
        ) as mock_delete,
        patch(
            "agent.services.confirmation_service._get_service_names",
            new_callable=AsyncMock,
            return_value="Corte de Mujer",
        ),
    ):
        result = await handle_tool_action(appt.id, IntentType.DECLINE_APPOINTMENT)

    assert result.success is True
    mock_delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_decline_gcal_failure_does_not_roll_back_db():
    """GCal delete failure must be logged but MUST NOT roll back the DB transition (S3-H)."""
    from agent.routing.intent_types import IntentType
    from agent.services.confirmation_service import handle_tool_action
    from database.models import AppointmentStatus

    appt = _make_appointment_for_decline()
    session_cm, session = _patch_session_for_decline(appt)

    with (
        session_cm,
        patch(
            "agent.services.confirmation_service.delete_gcal_event",
            new_callable=AsyncMock,
            side_effect=Exception("GCal 503"),
        ),
        patch(
            "agent.services.confirmation_service._get_service_names",
            new_callable=AsyncMock,
            return_value="Corte de Mujer",
        ),
    ):
        result = await handle_tool_action(appt.id, IntentType.DECLINE_APPOINTMENT)

    # DB committed (session.commit called) even when GCal raises
    session.commit.assert_awaited()
    assert appt.status == AppointmentStatus.CANCELLED


# ---------------------------------------------------------------------------
# Reason marker uniqueness (S3-I)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_reason_distinct_from_auto_cancel_and_operator_cancel():
    """'customer_declined' must be distinct from 'auto_cancelled_no_confirmation' and
    'operator_cancelled' (S3-I, S3-R4)."""
    from agent.routing.intent_types import IntentType
    from agent.services.confirmation_service import handle_tool_action

    appt = _make_appointment_for_decline()
    session_cm, _ = _patch_session_for_decline(appt)

    with (
        session_cm,
        patch(
            "agent.services.confirmation_service.delete_gcal_event",
            new_callable=AsyncMock,
        ),
        patch(
            "agent.services.confirmation_service._get_service_names",
            new_callable=AsyncMock,
            return_value="Corte de Mujer",
        ),
    ):
        await handle_tool_action(appt.id, IntentType.DECLINE_APPOINTMENT)

    assert appt.cancellation_reason == "customer_declined"
    assert appt.cancellation_reason != "auto_cancelled_no_confirmation"
    assert appt.cancellation_reason != "operator_cancelled"

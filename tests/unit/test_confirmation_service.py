"""
Unit tests for `agent.services.confirmation_service.handle_tool_action`.

Covers the tool-driven entry point that bypasses keyword parsing and dispatches
directly on an IntentType decision.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from agent.routing.intent_types import IntentType

MADRID_TZ = ZoneInfo("Europe/Madrid")


def _make_appointment(status, *, gcal_event_id: str | None = "evt_123"):

    appt = MagicMock()
    appt.id = uuid4()
    appt.status = status
    appt.cancelled_at = None
    appt.start_time = datetime.now(MADRID_TZ) + timedelta(days=3)
    appt.service_ids = []
    appt.stylist_id = uuid4()
    appt.google_calendar_event_id = gcal_event_id
    appt.first_name = "Ana"
    # stylist with name
    stylist = MagicMock()
    stylist.name = "Carla"
    appt.stylist = stylist
    # customer
    customer = MagicMock()
    customer.first_name = "Ana"
    customer.id = uuid4()
    appt.customer = customer
    # Enum-valued status: compare via AppointmentStatus enum below
    return appt


def _patch_session(appointment):
    """Patch get_async_session to return a session that yields `appointment`."""
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


@pytest.mark.asyncio
async def test_confirm_pending_appointment():
    """PENDING appt + CONFIRM_APPOINTMENT → status=CONFIRMED, GCal updated."""
    from agent.services.confirmation_service import handle_tool_action
    from database.models import AppointmentStatus

    appt = _make_appointment(AppointmentStatus.PENDING)
    session_cm, session = _patch_session(appt)

    with (
        session_cm,
        patch(
            "agent.services.confirmation_service.update_gcal_event_status",
            new_callable=AsyncMock,
        ) as mock_update_gcal,
        patch(
            "agent.services.confirmation_service._get_service_names",
            new_callable=AsyncMock,
            return_value="Corte de Mujer",
        ),
    ):
        result = await handle_tool_action(appt.id, IntentType.CONFIRM_APPOINTMENT)

    assert result.success is True
    assert appt.status == AppointmentStatus.CONFIRMED
    mock_update_gcal.assert_awaited()


@pytest.mark.asyncio
async def test_decline_pending_appointment():
    """PENDING appt + DECLINE_APPOINTMENT → status=CANCELLED, GCal deleted."""
    from agent.services.confirmation_service import handle_tool_action
    from database.models import AppointmentStatus

    appt = _make_appointment(AppointmentStatus.PENDING)
    session_cm, session = _patch_session(appt)

    with (
        session_cm,
        patch(
            "agent.services.confirmation_service.delete_gcal_event",
            new_callable=AsyncMock,
        ) as mock_delete_gcal,
        patch(
            "agent.services.confirmation_service._get_service_names",
            new_callable=AsyncMock,
            return_value="Corte de Mujer",
        ),
    ):
        result = await handle_tool_action(appt.id, IntentType.DECLINE_APPOINTMENT)

    assert result.success is True
    assert appt.status == AppointmentStatus.CANCELLED
    assert appt.cancelled_at is not None
    mock_delete_gcal.assert_awaited()


@pytest.mark.asyncio
async def test_appointment_not_found():
    """Non-existent UUID → success=False with APPOINTMENT_NOT_FOUND."""
    from agent.services.confirmation_service import handle_tool_action

    session_cm, session = _patch_session(None)

    with session_cm:
        result = await handle_tool_action(uuid4(), IntentType.CONFIRM_APPOINTMENT)

    assert result.success is False
    assert result.state_updates is not None
    assert result.state_updates.get("error_code") == "APPOINTMENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_already_cancelled_returns_error():
    """Already CANCELLED → error, no status change."""
    from agent.services.confirmation_service import handle_tool_action
    from database.models import AppointmentStatus

    appt = _make_appointment(AppointmentStatus.CANCELLED)
    session_cm, session = _patch_session(appt)

    with (
        session_cm,
        patch(
            "agent.services.confirmation_service.update_gcal_event_status",
            new_callable=AsyncMock,
        ) as mock_update_gcal,
        patch(
            "agent.services.confirmation_service.delete_gcal_event",
            new_callable=AsyncMock,
        ) as mock_delete_gcal,
    ):
        result = await handle_tool_action(appt.id, IntentType.CONFIRM_APPOINTMENT)

    assert result.success is False
    assert appt.status == AppointmentStatus.CANCELLED
    mock_update_gcal.assert_not_awaited()
    mock_delete_gcal.assert_not_awaited()


@pytest.mark.asyncio
async def test_decline_within_48h_window_rejected():
    """DECLINE within 48h window → error, status unchanged, GCal not touched."""
    from agent.services.confirmation_service import handle_tool_action
    from database.models import AppointmentStatus

    appt = _make_appointment(AppointmentStatus.PENDING)
    # Inside 48h window — should be rejected
    appt.start_time = datetime.now(MADRID_TZ) + timedelta(hours=12)
    session_cm, session = _patch_session(appt)

    with (
        session_cm,
        patch(
            "agent.services.confirmation_service.delete_gcal_event",
            new_callable=AsyncMock,
        ) as mock_delete_gcal,
        patch(
            "agent.services.confirmation_service._get_service_names",
            new_callable=AsyncMock,
            return_value="Corte de Mujer",
        ),
    ):
        result = await handle_tool_action(appt.id, IntentType.DECLINE_APPOINTMENT)

    assert result.success is False
    assert appt.status == AppointmentStatus.PENDING  # not mutated
    assert result.state_updates is not None
    assert result.state_updates.get("error_code") == "WINDOW"
    mock_delete_gcal.assert_not_awaited()


@pytest.mark.asyncio
async def test_decline_outside_48h_window_allowed():
    """DECLINE outside 48h window → success, status=CANCELLED."""
    from agent.services.confirmation_service import handle_tool_action
    from database.models import AppointmentStatus

    appt = _make_appointment(AppointmentStatus.PENDING)
    appt.start_time = datetime.now(MADRID_TZ) + timedelta(hours=72)
    session_cm, session = _patch_session(appt)

    with (
        session_cm,
        patch(
            "agent.services.confirmation_service.delete_gcal_event",
            new_callable=AsyncMock,
        ) as mock_delete_gcal,
        patch(
            "agent.services.confirmation_service._get_service_names",
            new_callable=AsyncMock,
            return_value="Corte de Mujer",
        ),
    ):
        result = await handle_tool_action(appt.id, IntentType.DECLINE_APPOINTMENT)

    assert result.success is True
    assert appt.status == AppointmentStatus.CANCELLED
    mock_delete_gcal.assert_awaited()

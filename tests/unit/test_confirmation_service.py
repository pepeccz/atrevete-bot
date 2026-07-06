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
    assert (
        appt.cancellation_reason == "customer_declined"
    ), "S3-R4: cancellation_reason must be 'customer_declined' for all customer-decline paths"
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


# ─────────────────────────────────────────────────────────────────────────────
# F2-hotfix (PR-5) — get_future_pending_appointments
#
# Original bug (engram #7518): get_pending_confirmations() filters
# WHERE confirmation_sent_at IS NOT NULL, so freshly-booked PENDING
# appointments (>48h out, notification not yet sent) return 0 rows and the
# F2 disambiguation gate in manage_appointments_tool never fires — the
# unguarded fallback then trusts the LLM-supplied appointment_id, silently
# confirming the wrong appointment. This new query's precondition is
# broader: PENDING + start_time in the future, regardless of whether a
# confirmation request was ever sent.
# ─────────────────────────────────────────────────────────────────────────────


def _make_future_pending_appointment(*, confirmation_sent_at=None):
    from database.models import AppointmentStatus

    appt = MagicMock()
    appt.id = uuid4()
    appt.status = AppointmentStatus.PENDING
    appt.confirmation_sent_at = confirmation_sent_at
    appt.start_time = datetime.now(MADRID_TZ) + timedelta(days=3)
    stylist = MagicMock()
    stylist.name = "Ana"
    appt.stylist = stylist
    return appt


def _patch_session_scalars_all(appointments):
    """Patch get_async_session to return a session whose execute().scalars().all()
    yields `appointments`, and CAPTURE the Select statement passed to execute()
    so tests can assert on its compiled SQL (SQL-level filter assertions)."""
    session = MagicMock()
    captured_stmt: dict = {}

    exec_result = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=appointments)
    exec_result.scalars = MagicMock(return_value=scalars)

    async def _execute(stmt):
        captured_stmt["stmt"] = stmt
        return exec_result

    session.execute = AsyncMock(side_effect=_execute)

    @asynccontextmanager
    async def _fake_session():
        yield session

    return (
        patch("agent.services.confirmation_service.get_async_session", _fake_session),
        captured_stmt,
    )


@pytest.mark.asyncio
async def test_get_future_pending_appointments_ignores_confirmation_sent_at_null():
    """CRITICAL regression test (engram #7518): both pending appointments have
    confirmation_sent_at=None (freshly booked, notification not yet sent) —
    the new query MUST still return both, unlike get_pending_confirmations()
    which would return an empty list for this exact fixture."""
    from agent.services.confirmation_service import get_future_pending_appointments

    appt_a = _make_future_pending_appointment(confirmation_sent_at=None)
    appt_b = _make_future_pending_appointment(confirmation_sent_at=None)
    session_cm, _captured = _patch_session_scalars_all([appt_a, appt_b])

    with session_cm:
        result = await get_future_pending_appointments(uuid4())

    assert len(result) == 2
    assert appt_a in result
    assert appt_b in result


@pytest.mark.asyncio
async def test_get_future_pending_appointments_query_excludes_confirmation_sent_at_filter():
    """SQL-level assertion: the compiled query for get_future_pending_appointments
    MUST NOT filter on confirmation_sent_at at all — this is precisely the
    filter that hid the original bug (get_pending_confirmations() DOES filter
    on it, see engram #7518). Asserts the column name is absent from the
    compiled WHERE clause, and that status/start_time ARE present."""
    from agent.services.confirmation_service import get_future_pending_appointments

    session_cm, captured = _patch_session_scalars_all([])

    with session_cm:
        await get_future_pending_appointments(uuid4())

    stmt = captured["stmt"]
    compiled_sql = str(stmt)
    # select(Appointment) always includes confirmation_sent_at in the SELECTED
    # column list (it's a mapped column on the entity) — that is NOT what this
    # test guards against. The bug-relevant assertion is about the WHERE
    # clause specifically: it must not filter/constrain on that column.
    assert "WHERE" in compiled_sql
    where_clause = compiled_sql.split("WHERE", 1)[1]
    assert "confirmation_sent_at" not in where_clause, (
        "get_future_pending_appointments's WHERE clause must NOT filter on "
        "confirmation_sent_at (that filter is exactly what hid the original "
        "bug, engram #7518)"
    )
    assert "status" in where_clause
    assert "start_time" in where_clause


@pytest.mark.asyncio
async def test_get_future_pending_appointments_orders_by_start_time_asc():
    """Ordering MUST be start_time ascending to match the guided disambiguation
    list order so ordinal selectors (REQ-F2-2b) resolve correctly against the
    same fetched set."""
    from agent.services.confirmation_service import get_future_pending_appointments

    session_cm, captured = _patch_session_scalars_all([])

    with session_cm:
        await get_future_pending_appointments(uuid4())

    stmt = captured["stmt"]
    compiled_sql = str(stmt).lower()
    assert "order by" in compiled_sql
    assert "start_time" in compiled_sql.split("order by")[-1]

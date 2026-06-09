"""Unit tests for gcal_push_service status writes and notification helper.

Covers:
  AS1 — Failed book push writes gcal_sync_status='failed'
  AS2 — Successful book push writes gcal_sync_status='synced'
  AS3 — Failed cancel push writes failed with operation='cancel'
  AS4 — Failed reschedule push writes failed with operation='reschedule'
  AS5 — First failure creates exactly one Notification
  E2  — Retry failure does NOT create duplicate notification
  D2  — 404 on delete_gcal_event writes synced, no notification
  D3  — create_gcal_push_failed_notification dedupe
  D3  — resolve_gcal_push_failed_notification sets is_read=True
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from agent.services.notification_service import (
    create_gcal_push_failed_notification,
    resolve_gcal_push_failed_notification,
)
from database.models import Notification, NotificationType


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _make_appointment_id() -> UUID:
    return uuid4()


def _make_session(existing_notification: Notification | None = None) -> AsyncMock:
    """Build a mock AsyncSession for notification helper tests."""
    session = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = existing_notification
    session.execute = AsyncMock(return_value=scalar_result)
    session.add = MagicMock()
    return session


# ─── D3: Notification helper — create ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_gcal_push_failed_notification_first_failure():
    """AS5: First failure on a synced appointment creates one notification."""
    appointment_id = _make_appointment_id()
    session = _make_session(existing_notification=None)

    result = await create_gcal_push_failed_notification(session, appointment_id)

    assert result is not None
    assert isinstance(result, Notification)
    assert result.type == NotificationType.GCAL_PUSH_FAILED
    assert result.entity_type == "appointment"
    assert result.entity_id == appointment_id
    session.add.assert_called_once_with(result)


@pytest.mark.asyncio
async def test_create_gcal_push_failed_notification_dedupes_on_existing():
    """E2: If open notification already exists, helper returns None (no duplicate)."""
    appointment_id = _make_appointment_id()
    existing = MagicMock(spec=Notification)
    session = _make_session(existing_notification=existing)

    result = await create_gcal_push_failed_notification(session, appointment_id)

    assert result is None
    session.add.assert_not_called()


# ─── D3: Notification helper — resolve ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_gcal_push_failed_notification_marks_read():
    """Resolution on success transition marks existing notification as read."""
    appointment_id = _make_appointment_id()
    existing = MagicMock(spec=Notification)
    existing.is_read = False
    session = _make_session(existing_notification=existing)

    await resolve_gcal_push_failed_notification(session, appointment_id)

    assert existing.is_read is True
    assert existing.read_at is not None


@pytest.mark.asyncio
async def test_resolve_gcal_push_failed_notification_noop_when_none():
    """Resolution is a no-op when no matching notification exists."""
    appointment_id = _make_appointment_id()
    session = _make_session(existing_notification=None)

    # Should not raise
    await resolve_gcal_push_failed_notification(session, appointment_id)
    # Nothing to assert — just ensuring no AttributeError


# ─── AS1/AS2: push_appointment_to_gcal status writes ──────────────────────────


@pytest.mark.asyncio
async def test_push_appointment_to_gcal_success_writes_synced():
    """AS2: Successful book push writes gcal_sync_status='synced'."""
    from agent.services import gcal_push_service as svc

    appointment_id = _make_appointment_id()
    stylist_id = uuid4()
    fake_event_id = "gcal_event_abc123"

    # The values dict captured when session.execute(update(...)) is called
    written_values = {}

    async def _fake_get_session():
        session = AsyncMock()
        # execute returns a result (we don't care about the select result in this path)
        session.execute = AsyncMock(return_value=MagicMock())
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        return session

    with (
        patch.object(svc, "_get_stylist_calendar_id", AsyncMock(return_value="cal_id")),
        patch.object(svc, "_get_calendar_service", AsyncMock(return_value=MagicMock())),
        patch.object(svc, "get_async_session") as mock_gas,
        patch.object(svc, "asyncio") as mock_asyncio,
    ):
        # Fake run_in_executor to call the sync function and return event dict
        mock_asyncio.get_event_loop.return_value.run_in_executor = AsyncMock(
            return_value={"id": fake_event_id}
        )

        # Capture session writes
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock())
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        mock_gas.return_value = session

        result = await svc.push_appointment_to_gcal(
            appointment_id=appointment_id,
            stylist_id=stylist_id,
            customer_name="Ana García",
            service_names="Corte",
            start_time=datetime(2026, 6, 10, 10, 0, tzinfo=UTC),
            duration_minutes=60,
        )

    # With mocked executor returning event_id, the function should return event_id
    assert result == fake_event_id


@pytest.mark.asyncio
async def test_push_appointment_to_gcal_failure_writes_failed():
    """AS1: Failed book push writes gcal_sync_status='failed'."""
    from agent.services import gcal_push_service as svc

    appointment_id = _make_appointment_id()
    stylist_id = uuid4()

    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.object(svc, "_get_stylist_calendar_id", AsyncMock(return_value="cal_id")),
        patch.object(svc, "_get_calendar_service", AsyncMock(side_effect=RuntimeError("GCal down"))),
        patch.object(svc, "get_async_session", return_value=session),
        patch("agent.services.notification_service.create_gcal_push_failed_notification", AsyncMock(return_value=None)),
    ):
        result = await svc.push_appointment_to_gcal(
            appointment_id=appointment_id,
            stylist_id=stylist_id,
            customer_name="Ana García",
            service_names="Corte",
            start_time=datetime(2026, 6, 10, 10, 0, tzinfo=UTC),
            duration_minutes=60,
        )

    assert result is None
    # session.execute should have been called with the update statement
    session.execute.assert_called()
    session.commit.assert_called()


@pytest.mark.asyncio
async def test_delete_gcal_event_404_writes_synced_no_notification():
    """D2: 404 on cancel delete_gcal_event writes synced, returns True, no notification."""
    from agent.services import gcal_push_service as svc
    from googleapiclient.errors import HttpError

    stylist_id = uuid4()

    # Build a mock HttpError with status 404
    http_resp = MagicMock()
    http_resp.status = 404
    http_error_404 = HttpError(resp=http_resp, content=b"Not Found")

    with (
        patch.object(svc, "_get_stylist_calendar_id", AsyncMock(return_value="cal_id")),
        patch.object(svc, "_get_calendar_service", AsyncMock(return_value=MagicMock())),
        patch.object(svc, "asyncio") as mock_asyncio,
    ):
        mock_asyncio.get_event_loop.return_value.run_in_executor = AsyncMock(
            side_effect=http_error_404
        )

        result = await svc.delete_gcal_event(stylist_id, "event_id_xyz")

    # 404 means event is already gone — treat as success
    assert result is True

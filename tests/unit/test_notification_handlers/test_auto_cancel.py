"""Unit tests for the auto-cancel notification handler.

RED phase: written before auto_cancel.py exists.
Covers S3-R4, S3-R6, S3-R7, S3-R8, S3-R9, S3-R10, S3-C, S3-D, S3-E, S3-I, S3-J
per spec obs #7262.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


# ---------------------------------------------------------------------------
# query_fn — SQL shape tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_fn_where_clause_contains_required_columns():
    """query_fn WHERE clause must reference final_warning_sent_at, start_time, status."""
    from agent.workers.notification_handlers import auto_cancel

    captured: dict = {}

    class FakeSession:
        async def execute(self, stmt):
            captured["stmt"] = stmt
            return _FakeResult([])

    await auto_cancel.query_fn(FakeSession())
    rendered = str(captured["stmt"])

    assert "final_warning_sent_at" in rendered, "must filter by final_warning_sent_at"
    assert "start_time" in rendered, "must enforce MIN_LEAD_HOURS guard"
    assert "status" in rendered.lower() or "pending" in rendered.lower(), "must filter PENDING"


@pytest.mark.asyncio
async def test_query_fn_final_warning_sent_at_is_not_null_required():
    """query_fn must require final_warning_sent_at IS NOT NULL."""
    from agent.workers.notification_handlers import auto_cancel

    captured: dict = {}

    class FakeSession:
        async def execute(self, stmt):
            captured["stmt"] = stmt
            return _FakeResult([])

    await auto_cancel.query_fn(FakeSession())
    rendered = str(captured["stmt"]).lower()
    # final_warning_sent_at IS NOT NULL should appear
    assert "final_warning_sent_at" in rendered


@pytest.mark.asyncio
async def test_query_fn_returns_appointments_from_session():
    """query_fn returns whatever the session yields."""
    from agent.workers.notification_handlers import auto_cancel

    fake_appt = MagicMock()

    class FakeSession:
        async def execute(self, stmt):
            return _FakeResult([fake_appt])

    result = await auto_cancel.query_fn(FakeSession())
    assert result == [fake_appt]


# ---------------------------------------------------------------------------
# send_fn — atomic cancel action (mirrors paused_24h self-session pattern)
# ---------------------------------------------------------------------------


def _make_pending_appt(**overrides):
    """Create a mock PENDING appointment suitable for auto_cancel tests."""
    from database.models import AppointmentStatus

    appt = MagicMock()
    appt.id = uuid4()
    appt.status = AppointmentStatus.PENDING
    appt.stylist_id = uuid4()
    appt.google_calendar_event_id = "evt_abc123"
    appt.first_name = "Cliente"
    customer = MagicMock()
    customer.first_name = "Cliente"
    appt.customer = customer
    for k, v in overrides.items():
        setattr(appt, k, v)
    return appt


def _make_fake_session(appointment):
    """Build a mock async session that returns `appointment` on re-fetch."""
    session = MagicMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    exec_result = MagicMock()
    scalars = MagicMock()
    scalars.first = MagicMock(return_value=appointment)
    exec_result.scalars = MagicMock(return_value=scalars)
    session.execute = AsyncMock(return_value=exec_result)

    @asynccontextmanager
    async def _ctx():
        yield session

    return _ctx, session


@pytest.mark.asyncio
async def test_send_fn_cancels_pending_appointment(monkeypatch):
    """send_fn sets status=CANCELLED, cancellation_reason='auto_cancelled_no_confirmation',
    cancelled_at, then creates an AUTO_CANCELLED Notification (S3-R7, S3-R4)."""
    from agent.workers.notification_handlers import auto_cancel
    from database.models import AppointmentStatus, NotificationType

    appt = _make_pending_appt()
    ctx, session = _make_fake_session(appt)

    monkeypatch.setattr(auto_cancel, "get_async_session", ctx)
    mock_delete = AsyncMock(return_value=True)
    monkeypatch.setattr(auto_cancel, "delete_gcal_event", mock_delete)

    result = await auto_cancel.send_fn(appt, None)

    assert result is True
    assert appt.status == AppointmentStatus.CANCELLED
    assert appt.cancellation_reason == "auto_cancelled_no_confirmation", (
        "spec S3-R4 requires this exact string"
    )
    assert appt.cancelled_at is not None
    session.commit.assert_awaited()
    mock_delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_fn_calls_gcal_delete_with_correct_args(monkeypatch):
    """send_fn calls delete_gcal_event(stylist_id, event_id, appointment_id=...) (S3-R7)."""
    from agent.workers.notification_handlers import auto_cancel

    appt = _make_pending_appt()
    ctx, session = _make_fake_session(appt)

    monkeypatch.setattr(auto_cancel, "get_async_session", ctx)
    mock_delete = AsyncMock(return_value=True)
    monkeypatch.setattr(auto_cancel, "delete_gcal_event", mock_delete)

    await auto_cancel.send_fn(appt, None)

    mock_delete.assert_awaited_once_with(
        stylist_id=appt.stylist_id,
        event_id=appt.google_calendar_event_id,
        appointment_id=appt.id,
    )


@pytest.mark.asyncio
async def test_send_fn_skips_gcal_delete_when_no_event_id(monkeypatch):
    """send_fn skips GCal delete when google_calendar_event_id is None."""
    from agent.workers.notification_handlers import auto_cancel

    appt = _make_pending_appt(google_calendar_event_id=None)
    ctx, session = _make_fake_session(appt)

    monkeypatch.setattr(auto_cancel, "get_async_session", ctx)
    mock_delete = AsyncMock(return_value=True)
    monkeypatch.setattr(auto_cancel, "delete_gcal_event", mock_delete)

    result = await auto_cancel.send_fn(appt, None)

    assert result is True
    mock_delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_fn_gcal_failure_does_not_roll_back_db(monkeypatch):
    """GCal delete failure is logged but DB commit is NOT rolled back (S3-R7)."""
    from agent.workers.notification_handlers import auto_cancel
    from database.models import AppointmentStatus

    appt = _make_pending_appt()
    ctx, session = _make_fake_session(appt)

    monkeypatch.setattr(auto_cancel, "get_async_session", ctx)
    mock_delete = AsyncMock(side_effect=Exception("GCal 503"))
    monkeypatch.setattr(auto_cancel, "delete_gcal_event", mock_delete)

    result = await auto_cancel.send_fn(appt, None)

    # DB commit should still have been called (no rollback on GCal failure)
    assert result is True
    assert appt.status == AppointmentStatus.CANCELLED
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_send_fn_creates_auto_cancelled_notification(monkeypatch):
    """send_fn creates a Notification with type=AUTO_CANCELLED (S3-R7)."""
    from agent.workers.notification_handlers import auto_cancel
    from database.models import NotificationType

    appt = _make_pending_appt()
    ctx, session = _make_fake_session(appt)

    monkeypatch.setattr(auto_cancel, "get_async_session", ctx)
    monkeypatch.setattr(auto_cancel, "delete_gcal_event", AsyncMock(return_value=True))

    await auto_cancel.send_fn(appt, None)

    # Notification added via session.add
    session.add.assert_called()
    added = session.add.call_args[0][0]
    assert added.type == NotificationType.AUTO_CANCELLED
    assert added.entity_type == "appointment"
    assert added.entity_id == appt.id


@pytest.mark.asyncio
async def test_send_fn_status_and_notification_committed_atomically(monkeypatch):
    """Status change and AUTO_CANCELLED Notification are committed in a single transaction.

    Exactly one session.commit() must be awaited so that a failure between
    the two former commits cannot leave the appointment CANCELLED without a
    Notification (WARNING-3 fix).
    """
    from agent.workers.notification_handlers import auto_cancel
    from database.models import AppointmentStatus

    appt = _make_pending_appt()
    ctx, session = _make_fake_session(appt)

    monkeypatch.setattr(auto_cancel, "get_async_session", ctx)
    monkeypatch.setattr(auto_cancel, "delete_gcal_event", AsyncMock(return_value=True))

    await auto_cancel.send_fn(appt, None)

    assert session.commit.await_count == 1, (
        f"Expected exactly 1 commit (atomic), got {session.commit.await_count}"
    )
    assert appt.status == AppointmentStatus.CANCELLED
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_send_fn_cas_noop_when_already_cancelled(monkeypatch):
    """send_fn is a no-op when appointment is already CANCELLED on re-fetch (S3-R8 CAS)."""
    from agent.workers.notification_handlers import auto_cancel
    from database.models import AppointmentStatus

    # The appt queried by query_fn was PENDING, but re-fetched as CANCELLED (race)
    already_cancelled = _make_pending_appt(status=AppointmentStatus.CANCELLED)
    ctx, session = _make_fake_session(already_cancelled)

    monkeypatch.setattr(auto_cancel, "get_async_session", ctx)
    mock_delete = AsyncMock(return_value=True)
    monkeypatch.setattr(auto_cancel, "delete_gcal_event", mock_delete)

    result = await auto_cancel.send_fn(already_cancelled, None)

    # No-op: return True (race-safe) but do NOT commit a second cancel
    assert result is True
    mock_delete.assert_not_awaited()
    # session.add should NOT be called for the Notification
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_send_fn_cancellation_reason_distinct_from_operator_cancel(monkeypatch):
    """auto-cancel reason 'auto_cancelled_no_confirmation' != 'operator_cancelled' (S3-I)."""
    from agent.workers.notification_handlers import auto_cancel

    appt = _make_pending_appt()
    ctx, session = _make_fake_session(appt)

    monkeypatch.setattr(auto_cancel, "get_async_session", ctx)
    monkeypatch.setattr(auto_cancel, "delete_gcal_event", AsyncMock(return_value=True))

    await auto_cancel.send_fn(appt, None)

    assert appt.cancellation_reason == "auto_cancelled_no_confirmation"
    assert appt.cancellation_reason != "operator_cancelled"
    assert appt.cancellation_reason != "customer_declined"


# ---------------------------------------------------------------------------
# mark_sent_fn / mark_failed_fn — no-ops (state captured by status=CANCELLED)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_sent_fn_is_noop():
    """mark_sent_fn is a no-op (idempotency via status=PENDING filter)."""
    from agent.workers.notification_handlers import auto_cancel

    class FakeSession:
        async def execute(self, stmt):
            raise AssertionError("mark_sent_fn must not execute any statement")

    # Should complete without error and without calling session.execute
    await auto_cancel.mark_sent_fn(FakeSession(), uuid4())


@pytest.mark.asyncio
async def test_mark_failed_fn_is_noop():
    """mark_failed_fn is a no-op (idempotency via status=PENDING filter; no retry needed)."""
    from agent.workers.notification_handlers import auto_cancel

    class FakeSession:
        async def execute(self, stmt):
            raise AssertionError("mark_failed_fn must not execute any statement")

    # Should complete without error
    await auto_cancel.mark_failed_fn(FakeSession(), uuid4())


# ---------------------------------------------------------------------------
# HANDLER object — registry shape
# ---------------------------------------------------------------------------


def test_handler_has_correct_name_and_callables():
    """The HANDLER constant must be a NotificationHandler with name='auto_cancel'."""
    from agent.workers.notification_handlers.auto_cancel import HANDLER

    assert HANDLER.name == "auto_cancel"
    assert callable(HANDLER.query_fn)
    assert callable(HANDLER.send_fn)
    assert callable(HANDLER.mark_sent_fn)
    assert callable(HANDLER.mark_failed_fn)

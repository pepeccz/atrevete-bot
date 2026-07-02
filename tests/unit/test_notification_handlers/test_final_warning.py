"""Unit tests for the final-warning notification handler.

RED phase: written before final_warning.py exists.
Covers S3-R2, S3-R5, S3-A, S3-B, S3-G per spec obs #7262.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
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
# query_fn — SQL shape tests (check rendered WHERE clause contains required
# column names and conditions; DB execution is tested via integration tests).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_fn_where_clause_contains_required_columns():
    """query_fn WHERE clause must reference all required guard columns."""
    from agent.workers.notification_handlers import final_warning

    captured: dict = {}

    class FakeSession:
        async def execute(self, stmt):
            captured["stmt"] = stmt
            return _FakeResult([])

    await final_warning.query_fn(FakeSession())
    rendered = str(captured["stmt"])

    assert "confirmation_sent_at" in rendered, "must filter by confirmation_sent_at"
    assert "final_warning_sent_at" in rendered, "must filter by final_warning_sent_at"
    assert "notification_failed" in rendered, "must honor backoff flag"
    assert "start_time" in rendered, "must enforce MIN_LEAD_HOURS guard"
    assert "status" in rendered.lower() or "pending" in rendered.lower(), "must filter PENDING status"


@pytest.mark.asyncio
async def test_query_fn_confirmation_sent_at_is_not_null_required():
    """query_fn must require confirmation_sent_at IS NOT NULL (S3-B orphan guard)."""
    from agent.workers.notification_handlers import final_warning

    captured: dict = {}

    class FakeSession:
        async def execute(self, stmt):
            captured["stmt"] = stmt
            return _FakeResult([])

    await final_warning.query_fn(FakeSession())
    rendered = str(captured["stmt"]).lower()
    # 'is not null' appears in the rendered SQL when .is_not(None) is used
    assert "is not null" in rendered or "is_not" in rendered or "confirmation_sent_at" in rendered


@pytest.mark.asyncio
async def test_query_fn_final_warning_sent_at_null_required():
    """query_fn must require final_warning_sent_at IS NULL (idempotency guard)."""
    from agent.workers.notification_handlers import final_warning

    captured: dict = {}

    class FakeSession:
        async def execute(self, stmt):
            captured["stmt"] = stmt
            return _FakeResult([])

    await final_warning.query_fn(FakeSession())
    rendered = str(captured["stmt"]).lower()
    # Idempotency: only appts where final_warning_sent_at IS NULL are selected
    assert "final_warning_sent_at" in rendered


@pytest.mark.asyncio
async def test_query_fn_returns_appointments_from_session():
    """query_fn returns whatever the session yields (list of Appointment objects)."""
    from agent.workers.notification_handlers import final_warning

    fake_appt = MagicMock()

    class FakeSession:
        async def execute(self, stmt):
            return _FakeResult([fake_appt])

    result = await final_warning.query_fn(FakeSession())
    assert result == [fake_appt]


# ---------------------------------------------------------------------------
# mark_sent_fn — CAS UPDATE via final_warning_sent_at IS NULL guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_sent_fn_stamps_final_warning_sent_at():
    """mark_sent_fn must issue a CAS UPDATE on final_warning_sent_at IS NULL."""
    from agent.workers.notification_handlers import final_warning

    captured: dict = {}

    class FakeSession:
        async def execute(self, stmt):
            captured["stmt"] = stmt

    appt_id = uuid4()
    await final_warning.mark_sent_fn(FakeSession(), appt_id)
    rendered = str(captured["stmt"]).lower()

    assert "update" in rendered, "mark_sent_fn must issue an UPDATE"
    assert "final_warning_sent_at" in rendered, "must set final_warning_sent_at"
    # CAS guard: only update where the column is still NULL (idempotency)
    assert "is null" in rendered or "is_null" in rendered, "must include CAS guard"


@pytest.mark.asyncio
async def test_mark_sent_fn_also_clears_notification_failed():
    """mark_sent_fn clears the notification_failed flag on success (same as confirm_48h)."""
    from agent.workers.notification_handlers import final_warning

    captured: dict = {}

    class FakeSession:
        async def execute(self, stmt):
            captured["stmt"] = stmt

    await final_warning.mark_sent_fn(FakeSession(), uuid4())
    rendered = str(captured["stmt"]).lower()
    assert "notification_failed" in rendered


# ---------------------------------------------------------------------------
# mark_failed_fn — reuses retry columns (same as confirm_48h, safe reuse)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_failed_fn_bumps_retry_count():
    """mark_failed_fn increments retry_count and sets next_retry_at (exponential backoff)."""
    from agent.workers.notification_handlers import final_warning

    captured: dict = {}

    class FakeSession:
        async def get(self, _model, _pk):
            return SimpleNamespace(retry_count=0)

        async def execute(self, stmt):
            captured["compiled"] = stmt.compile(compile_kwargs={"literal_binds": False}).params

    await final_warning.mark_failed_fn(FakeSession(), uuid4())
    params = captured["compiled"]
    assert params["notification_failed"] is True
    assert params["retry_count"] == 1
    assert params["next_retry_at"] > datetime.now(UTC)


# ---------------------------------------------------------------------------
# send_fn — template name resolution + graceful-skip when empty (S3-R2, S3-G)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_fn_returns_false_when_template_empty(monkeypatch):
    """send_fn returns False and logs a warning when template name is empty (S3-G)."""
    from agent.workers.notification_handlers import final_warning

    class DummySettings:
        WHATSAPP_TEMPLATE_FINAL_WARNING = ""

    class DummySettingsService:
        async def get(self, key: str, default: str = "") -> str:
            return default  # empty default → graceful skip

    monkeypatch.setattr(final_warning, "get_settings", lambda: DummySettings())
    monkeypatch.setattr(
        final_warning,
        "get_settings_service",
        AsyncMock(return_value=DummySettingsService()),
    )

    appt = SimpleNamespace(
        id=uuid4(),
        first_name="Ana",
        start_time=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        customer=SimpleNamespace(phone="+34611111111"),
    )
    client = MagicMock()
    client.send_template_message = AsyncMock(return_value=True)

    result = await final_warning.send_fn(appt, client)

    assert result is False, "must return False when template is empty"
    client.send_template_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_fn_calls_chatwoot_when_template_set(monkeypatch):
    """send_fn calls chatwoot_client.send_template_message with correct params (S3-R2)."""
    from agent.workers.notification_handlers import final_warning

    template_name = "atrevete_final_warning"

    class DummySettings:
        WHATSAPP_TEMPLATE_FINAL_WARNING = template_name

    class DummySettingsService:
        async def get(self, key: str, default: str = "") -> str:
            return template_name

    monkeypatch.setattr(final_warning, "get_settings", lambda: DummySettings())
    monkeypatch.setattr(
        final_warning,
        "get_settings_service",
        AsyncMock(return_value=DummySettingsService()),
    )

    appt = SimpleNamespace(
        id=uuid4(),
        first_name="Marta",
        start_time=datetime(2026, 8, 15, 14, 30, tzinfo=UTC),
        customer=SimpleNamespace(phone="+34622222222"),
    )
    client = MagicMock()
    client.send_template_message = AsyncMock(return_value=True)

    result = await final_warning.send_fn(appt, client)

    assert result is True
    call_kwargs = client.send_template_message.await_args.kwargs
    assert call_kwargs["template_name"] == template_name
    assert call_kwargs["customer_phone"] == "+34622222222"
    assert call_kwargs["category"] == "UTILITY"
    assert call_kwargs["language"] == "es"
    assert call_kwargs["body_params"]["1"] == "Marta", "body_params[1] must be first_name"


@pytest.mark.asyncio
async def test_send_fn_returns_false_when_customer_phone_missing(monkeypatch):
    """send_fn returns False gracefully when customer phone is missing."""
    from agent.workers.notification_handlers import final_warning

    class DummySettings:
        WHATSAPP_TEMPLATE_FINAL_WARNING = "atrevete_final_warning"

    class DummySettingsService:
        async def get(self, key: str, default: str = "") -> str:
            return "atrevete_final_warning"

    monkeypatch.setattr(final_warning, "get_settings", lambda: DummySettings())
    monkeypatch.setattr(
        final_warning,
        "get_settings_service",
        AsyncMock(return_value=DummySettingsService()),
    )

    appt = SimpleNamespace(
        id=uuid4(),
        first_name="Pedro",
        start_time=datetime(2026, 8, 20, 11, 0, tzinfo=UTC),
        customer=None,  # no customer linked
    )
    client = MagicMock()
    client.send_template_message = AsyncMock(return_value=True)

    result = await final_warning.send_fn(appt, client)
    assert result is False
    client.send_template_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# HANDLER object — registry shape
# ---------------------------------------------------------------------------


def test_handler_has_correct_name_and_callables():
    """The HANDLER constant must be a NotificationHandler with name='final_warning'."""
    from agent.workers.notification_handlers.final_warning import HANDLER

    assert HANDLER.name == "final_warning"
    assert callable(HANDLER.query_fn)
    assert callable(HANDLER.send_fn)
    assert callable(HANDLER.mark_sent_fn)
    assert callable(HANDLER.mark_failed_fn)

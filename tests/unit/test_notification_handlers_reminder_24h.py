"""Unit tests for the 24h-reminder handler."""

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


@pytest.mark.asyncio
async def test_query_filters_correct_window(monkeypatch):
    from agent.workers.notification_handlers import reminder_24h

    captured: dict = {}

    class FakeSession:
        async def execute(self, stmt):
            captured["stmt"] = stmt
            return _FakeResult([])

    result = await reminder_24h.query_fn(FakeSession())

    assert result == []
    rendered = str(captured["stmt"])
    assert "appointments" in rendered
    assert "reminder_sent_at" in rendered
    assert "reminder_failed" in rendered
    assert "start_time" in rendered


@pytest.mark.asyncio
async def test_mark_sent_sets_timestamp_when_null():
    from agent.workers.notification_handlers import reminder_24h

    captured: dict = {}

    class FakeSession:
        async def execute(self, stmt):
            captured["stmt"] = stmt

    await reminder_24h.mark_sent_fn(FakeSession(), uuid4())
    rendered = str(captured["stmt"]).lower()
    assert "update" in rendered
    assert "reminder_sent_at is null" in rendered


@pytest.mark.asyncio
async def test_mark_failed_bumps_retry(monkeypatch):
    from agent.workers.notification_handlers import reminder_24h

    now = datetime.now(UTC)
    captured: dict = {}

    class FakeSession:
        async def get(self, _model, _pk):
            return SimpleNamespace(reminder_retry_count=2)

        async def execute(self, stmt):
            captured["stmt"] = stmt
            captured["compiled"] = stmt.compile(compile_kwargs={"literal_binds": False}).params

    await reminder_24h.mark_failed_fn(FakeSession(), uuid4())

    params = captured["compiled"]
    assert params["reminder_failed"] is True
    assert params["reminder_retry_count"] == 3
    assert params["reminder_next_retry_at"] > now


@pytest.mark.asyncio
async def test_send_success_calls_template_with_correct_params(monkeypatch):
    from agent.workers.notification_handlers import reminder_24h

    class DummySettings:
        WHATSAPP_TEMPLATE_REMINDER_24H = "atrevete_reminder_24h"

    class DummySettingsService:
        async def get(self, key: str, default: str = "") -> str:
            return default

    monkeypatch.setattr(reminder_24h, "get_settings", lambda: DummySettings())
    # Patch the name as imported in reminder_24h (not in the source module)
    monkeypatch.setattr(
        reminder_24h, "get_settings_service", AsyncMock(return_value=DummySettingsService())
    )
    # send_fn now routes through deliver_template (sdd/context-coherence Stream 1) — the
    # conversation-threading behavior itself is covered by tests/unit/test_delivery.py.
    deliver_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(reminder_24h, "deliver_template", deliver_mock)

    appt = SimpleNamespace(
        id=uuid4(),
        customer_id=uuid4(),
        first_name="Ana",
        service_ids=[],
        start_time=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        customer=SimpleNamespace(phone="+34600000000"),
    )
    client = MagicMock()
    client.send_template_message = AsyncMock(return_value=True)

    success = await reminder_24h.send_fn(appt, client)

    assert success is True
    deliver_mock.assert_awaited_once()
    args = deliver_mock.await_args.args
    assert args[0] is client
    assert args[1] is appt
    assert args[2] == "atrevete_reminder_24h"
    assert args[3]["1"] == "Ana"
    assert "Ana" in args[4]  # fallback_content mentions the customer's name


@pytest.mark.asyncio
async def test_send_returns_false_when_template_unset(monkeypatch):
    from agent.workers.notification_handlers import reminder_24h

    class DummySettings:
        WHATSAPP_TEMPLATE_REMINDER_24H = ""

    class DummySettingsService:
        async def get(self, key: str, default: str = "") -> str:
            # Return the default value (which is "")
            return default

    monkeypatch.setattr(reminder_24h, "get_settings", lambda: DummySettings())
    # Patch the name as imported in reminder_24h (not in the source module)
    monkeypatch.setattr(
        reminder_24h, "get_settings_service", AsyncMock(return_value=DummySettingsService())
    )
    appt = SimpleNamespace(
        id=uuid4(),
        first_name="Ana",
        start_time=datetime.now(UTC) + timedelta(hours=24),
        customer=SimpleNamespace(phone="+34600000000"),
    )
    client = MagicMock()
    client.send_template_message = AsyncMock(return_value=True)

    success = await reminder_24h.send_fn(appt, client)

    assert success is False
    client.send_template_message.assert_not_called()

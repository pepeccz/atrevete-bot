"""Unit tests for the 48h-confirmation handler."""

from __future__ import annotations

from datetime import UTC, datetime
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
async def test_query_filters_pending_only_and_48h_window():
    from agent.workers.notification_handlers import confirm_48h

    captured: dict = {}

    class FakeSession:
        async def execute(self, stmt):
            captured["stmt"] = stmt
            return _FakeResult([])

    await confirm_48h.query_fn(FakeSession())
    rendered = str(captured["stmt"])
    assert "confirmation_sent_at" in rendered
    assert "notification_failed" in rendered
    assert "start_time" in rendered


@pytest.mark.asyncio
async def test_mark_sent_sets_confirmation_timestamp_when_null():
    from agent.workers.notification_handlers import confirm_48h

    captured: dict = {}

    class FakeSession:
        async def execute(self, stmt):
            captured["stmt"] = stmt

    await confirm_48h.mark_sent_fn(FakeSession(), uuid4())
    rendered = str(captured["stmt"]).lower()
    assert "update" in rendered
    assert "confirmation_sent_at is null" in rendered


@pytest.mark.asyncio
async def test_mark_failed_bumps_retry_count():
    from agent.workers.notification_handlers import confirm_48h

    captured: dict = {}

    class FakeSession:
        async def get(self, _model, _pk):
            return SimpleNamespace(retry_count=0)

        async def execute(self, stmt):
            captured["compiled"] = stmt.compile(compile_kwargs={"literal_binds": False}).params

    await confirm_48h.mark_failed_fn(FakeSession(), uuid4())
    params = captured["compiled"]
    assert params["notification_failed"] is True
    assert params["retry_count"] == 1
    assert params["next_retry_at"] > datetime.now(UTC)


@pytest.mark.asyncio
async def test_send_success_calls_template_with_correct_params(monkeypatch):
    from agent.workers.notification_handlers import confirm_48h

    class DummySettings:
        WHATSAPP_TEMPLATE_CONFIRM_48H = "atrevete_confirm_48h"

    class DummySettingsService:
        async def get(self, key: str, default: str = "") -> str:
            return default

    monkeypatch.setattr(confirm_48h, "get_settings", lambda: DummySettings())
    # Patch the name as imported in confirm_48h (not in the source module)
    monkeypatch.setattr(
        confirm_48h, "get_settings_service", AsyncMock(return_value=DummySettingsService())
    )
    # send_fn now routes through deliver_template (sdd/context-coherence Stream 1) — the
    # conversation-threading behavior itself is covered by tests/unit/test_delivery.py.
    deliver_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(confirm_48h, "deliver_template", deliver_mock)

    appt = SimpleNamespace(
        id=uuid4(),
        customer_id=uuid4(),
        first_name="Luis",
        stylist_id=None,
        service_ids=[],
        start_time=datetime(2026, 5, 3, 12, 30, tzinfo=UTC),
        customer=SimpleNamespace(phone="+34611111111"),
    )
    client = MagicMock()
    client.send_template_message = AsyncMock(return_value=True)

    success = await confirm_48h.send_fn(appt, client)

    assert success is True
    deliver_mock.assert_awaited_once()
    args = deliver_mock.await_args.args
    assert args[0] is client
    assert args[1] is appt
    assert args[2] == "atrevete_confirm_48h"
    assert args[3]["1"] == "Luis"
    assert "Luis" in args[4]  # fallback_content mentions the customer's name

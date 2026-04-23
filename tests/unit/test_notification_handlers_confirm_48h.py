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

    monkeypatch.setattr(confirm_48h, "get_settings", lambda: DummySettings())

    appt = SimpleNamespace(
        id=uuid4(),
        first_name="Luis",
        start_time=datetime(2026, 5, 3, 12, 30, tzinfo=UTC),
        customer=SimpleNamespace(phone="+34611111111"),
    )
    client = MagicMock()
    client.send_template_message = AsyncMock(return_value=True)

    success = await confirm_48h.send_fn(appt, client)

    assert success is True
    kwargs = client.send_template_message.await_args.kwargs
    assert kwargs["template_name"] == "atrevete_confirm_48h"
    assert kwargs["customer_phone"] == "+34611111111"
    assert kwargs["body_params"]["1"] == "Luis"

"""Unit tests for the 48h-confirmation handler."""

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
        AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS = 12
        AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS = 6

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


class TestAutoCancelDeadlineMath:
    """FIX 3 (judge A, MAJOR): {{6}} must reflect the earliest instant the
    auto-cancel tail could actually fire (anchored on "now", composing both
    grace periods), NOT a fixed T-24h offset from start_time — which can be
    hours earlier than the promised deadline with non-default settings."""

    @pytest.mark.asyncio
    async def test_deadline_uses_now_plus_both_grace_periods_not_fixed_t24h(self):
        # Deliberately does NOT use freezegun: freeze_time's global datetime
        # patch was observed to corrupt pydantic schema generation and the
        # wall clock for OTHER tests running later in the same session.
        # Instead, bracket the call with real before/after timestamps and
        # assert the rendered deadline matches one of them (a same-process,
        # microsecond-scale call is exceedingly unlikely to straddle a
        # minute boundary between the two).
        from agent.workers.notification_handlers import confirm_48h
        from agent.workers.notification_handlers._render_es import MADRID_TZ, fecha_es, hora_es

        class DummySettings:
            AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS = 5
            AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS = 3

        appt = SimpleNamespace(
            id=uuid4(),
            customer_id=uuid4(),
            first_name="Ana",
            stylist_id=None,
            service_ids=[],
            # Appointment is 48h out — a fixed T-24h deadline would be very
            # different from now+8h (5+3 grace hours).
            start_time=datetime(2026, 7, 9, 12, 30, tzinfo=UTC),
            customer=SimpleNamespace(phone="+34611111111"),
        )

        before = datetime.now(UTC)
        params = await confirm_48h._build_body_params(appt, DummySettings())
        after = datetime.now(UTC)

        def _render(dt_utc: datetime) -> str:
            dt_madrid = dt_utc.astimezone(MADRID_TZ)
            return f"{fecha_es(dt_madrid)} a las {hora_es(dt_madrid)}"

        expected_candidates = {
            _render(before + timedelta(hours=5 + 3)),
            _render(after + timedelta(hours=5 + 3)),
        }
        assert params["6"] in expected_candidates
        # Regression guard: the deadline must NOT equal the old fixed T-24h value.
        old_wrong_deadline = appt.start_time.astimezone(UTC) - timedelta(hours=24)
        assert params["6"] != _render(old_wrong_deadline)

    @pytest.mark.asyncio
    async def test_deadline_phrase_includes_month_name(self):
        """Judge nit: the phrase must include the month, e.g. 'martes 7 de julio
        a las 10:40', not just a bare day number."""
        from agent.workers.notification_handlers import confirm_48h

        class DummySettings:
            AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS = 12
            AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS = 6

        appt = SimpleNamespace(
            id=uuid4(),
            customer_id=uuid4(),
            first_name="Ana",
            stylist_id=None,
            service_ids=[],
            start_time=datetime(2026, 7, 9, 12, 30, tzinfo=UTC),
            customer=SimpleNamespace(phone="+34611111111"),
        )

        params = await confirm_48h._build_body_params(appt, DummySettings())

        assert " de " in params["6"], "deadline phrase must include the month name"
        assert "a las" in params["6"]

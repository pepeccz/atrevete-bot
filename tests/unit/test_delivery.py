"""Unit tests for agent/workers/notification_handlers/_delivery.py.

Covers (sdd/context-coherence Stream 1 + Stream 2):
- resolve_conversation: latest ConversationHistory row for a customer, no ended_at/
  paused_at filter (D1).
- deliver_template: existing-conversation send (D2), resolver-miss fallback (D3),
  Chatwoot-rejection fallback (D3), int(conversation_id) cast, and — once the 3
  send_fns are wired (TASK-06) — that they route through deliver_template instead of
  calling chatwoot_client.send_template_message directly.
- ConversationMessage persistence on a successful send (D6, TASK-07/08).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from shared.chatwoot_client import ConversationSendOutcome


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalars(self):
        return self

    def first(self):
        return self._row


class _FakeSession:
    """Minimal async-session stand-in: records execute() calls, no-ops add/commit."""

    def __init__(self, execute_result=None):
        self._execute_result = execute_result if execute_result is not None else _FakeResult(None)
        self.executed_statements: list = []
        self.added: list = []
        self.committed = False
        self.refreshed: list = []

    async def execute(self, stmt):
        self.executed_statements.append(stmt)
        return self._execute_result

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass

    async def refresh(self, obj):
        self.refreshed.append(obj)
        if not getattr(obj, "id", None):
            obj.id = uuid4()


def _fake_get_async_session_factory(session: _FakeSession):
    @asynccontextmanager
    async def _fake_get_async_session():
        yield session

    return _fake_get_async_session


def _make_appt(customer_id=None, phone="+34611111111"):
    return SimpleNamespace(
        id=uuid4(),
        customer_id=customer_id or uuid4(),
        customer=SimpleNamespace(phone=phone),
    )


@pytest.mark.asyncio
async def test_resolve_conversation_orders_by_started_at_and_created_at_desc():
    from agent.workers.notification_handlers import _delivery

    session = _FakeSession(execute_result=_FakeResult(None))
    await _delivery.resolve_conversation(session, uuid4())

    rendered = str(session.executed_statements[0])
    assert "ORDER BY" in rendered.upper()
    assert "started_at" in rendered
    assert "DESC" in rendered.upper()
    # No ended_at / paused_at WHERE filter — see D1 (ended_at is "last activity", not a
    # closed flag). Columns still appear in the SELECT list, so only assert no filter.
    assert "ended_at is" not in rendered.lower()
    assert "paused_at is" not in rendered.lower()


@pytest.mark.asyncio
async def test_deliver_template_sends_to_existing_conversation(monkeypatch):
    from agent.workers.notification_handlers import _delivery

    history = SimpleNamespace(id=uuid4(), conversation_id="125", customer_id=uuid4())
    session = _FakeSession(execute_result=_FakeResult(history))
    monkeypatch.setattr(_delivery, "get_async_session", _fake_get_async_session_factory(session))

    chatwoot = MagicMock()
    chatwoot.send_template_to_conversation_checked = AsyncMock(
        return_value=ConversationSendOutcome.SENT
    )
    chatwoot.create_conversation_with_template = AsyncMock()

    appt = _make_appt()
    result = await _delivery.deliver_template(
        chatwoot, appt, "appointment_confirmation_48h", {"1": "Ana"}, "Hola Ana"
    )

    assert result is True
    chatwoot.send_template_to_conversation_checked.assert_awaited_once()
    kwargs = chatwoot.send_template_to_conversation_checked.await_args.kwargs
    assert kwargs["conversation_id"] == 125
    assert isinstance(kwargs["conversation_id"], int)
    chatwoot.create_conversation_with_template.assert_not_called()


@pytest.mark.asyncio
async def test_deliver_template_resolver_miss_falls_back_to_create(monkeypatch):
    from agent.workers.notification_handlers import _delivery

    session = _FakeSession(execute_result=_FakeResult(None))
    monkeypatch.setattr(_delivery, "get_async_session", _fake_get_async_session_factory(session))

    chatwoot = MagicMock()
    chatwoot.send_template_to_conversation_checked = AsyncMock()
    chatwoot.create_conversation_with_template = AsyncMock(return_value=(555, True))

    appt = _make_appt()
    result = await _delivery.deliver_template(
        chatwoot, appt, "appointment_confirmation_48h", {"1": "Ana"}, "Hola Ana"
    )

    assert result is True
    chatwoot.send_template_to_conversation_checked.assert_not_called()
    chatwoot.create_conversation_with_template.assert_awaited_once()
    # A minimal ConversationHistory row must be persisted so the new id becomes canonical.
    assert any(getattr(obj, "conversation_id", None) == "555" for obj in session.added)


@pytest.mark.asyncio
async def test_deliver_template_chatwoot_rejection_falls_back_to_create(monkeypatch):
    from agent.workers.notification_handlers import _delivery

    history = SimpleNamespace(id=uuid4(), conversation_id="99999999", customer_id=uuid4())
    session = _FakeSession(execute_result=_FakeResult(history))
    monkeypatch.setattr(_delivery, "get_async_session", _fake_get_async_session_factory(session))

    chatwoot = MagicMock()
    chatwoot.send_template_to_conversation_checked = AsyncMock(
        return_value=ConversationSendOutcome.REJECTED
    )
    chatwoot.create_conversation_with_template = AsyncMock(return_value=(777, True))

    appt = _make_appt()
    result = await _delivery.deliver_template(
        chatwoot, appt, "appointment_confirmation_48h", {"1": "Ana"}, "Hola Ana"
    )

    assert result is True
    chatwoot.send_template_to_conversation_checked.assert_awaited_once()
    chatwoot.create_conversation_with_template.assert_awaited_once()


@pytest.mark.asyncio
async def test_deliver_template_transient_failure_does_not_fall_back(monkeypatch):
    """FIX 1 (MAJOR, both judges): a TRANSIENT outcome must NOT trigger the
    fallback-create path — it must return False so the worker's own backoff
    retries the SAME conversation on the next poll cycle, instead of
    fragmenting the customer's history on a transient 5xx/timeout."""
    from agent.workers.notification_handlers import _delivery

    history = SimpleNamespace(id=uuid4(), conversation_id="125", customer_id=uuid4())
    session = _FakeSession(execute_result=_FakeResult(history))
    monkeypatch.setattr(_delivery, "get_async_session", _fake_get_async_session_factory(session))

    chatwoot = MagicMock()
    chatwoot.send_template_to_conversation_checked = AsyncMock(
        return_value=ConversationSendOutcome.TRANSIENT
    )
    chatwoot.create_conversation_with_template = AsyncMock(return_value=(777, True))

    appt = _make_appt()
    result = await _delivery.deliver_template(
        chatwoot, appt, "appointment_confirmation_48h", {"1": "Ana"}, "Hola Ana"
    )

    assert result is False
    chatwoot.send_template_to_conversation_checked.assert_awaited_once()
    chatwoot.create_conversation_with_template.assert_not_called()
    # No fallback ConversationHistory persisted — the resolved history stays canonical.
    assert session.added == []


class TestNonNumericConversationIdGuard:
    """FIX 7 (sdd/context-coherence, MINOR): int(history.conversation_id) must
    never raise — a corrupt/non-numeric value falls back to a new conversation
    exactly like a resolver-miss, instead of propagating a ValueError."""

    @pytest.mark.asyncio
    async def test_non_numeric_conversation_id_falls_back_to_create(self, monkeypatch):
        from agent.workers.notification_handlers import _delivery

        history = SimpleNamespace(id=uuid4(), conversation_id="not-a-number", customer_id=uuid4())
        session = _FakeSession(execute_result=_FakeResult(history))
        monkeypatch.setattr(
            _delivery, "get_async_session", _fake_get_async_session_factory(session)
        )

        chatwoot = MagicMock()
        chatwoot.send_template_to_conversation_checked = AsyncMock()
        chatwoot.create_conversation_with_template = AsyncMock(return_value=(999, True))

        appt = _make_appt()
        result = await _delivery.deliver_template(
            chatwoot, appt, "appointment_confirmation_48h", {"1": "Ana"}, "Hola Ana"
        )

        assert result is True
        chatwoot.send_template_to_conversation_checked.assert_not_called()
        chatwoot.create_conversation_with_template.assert_awaited_once()


@pytest.mark.asyncio
async def test_deliver_template_fallback_create_failure_returns_false(monkeypatch):
    from agent.workers.notification_handlers import _delivery

    session = _FakeSession(execute_result=_FakeResult(None))
    monkeypatch.setattr(_delivery, "get_async_session", _fake_get_async_session_factory(session))

    chatwoot = MagicMock()
    chatwoot.create_conversation_with_template = AsyncMock(return_value=(None, False))

    appt = _make_appt()
    result = await _delivery.deliver_template(
        chatwoot, appt, "appointment_confirmation_48h", {"1": "Ana"}, "Hola Ana"
    )

    assert result is False
    # No history to persist when the fallback send itself failed.
    assert session.added == []


@pytest.mark.asyncio
async def test_deliver_template_no_phone_returns_false_without_any_send(monkeypatch):
    from agent.workers.notification_handlers import _delivery

    chatwoot = MagicMock()
    chatwoot.send_template_to_conversation_checked = AsyncMock()
    chatwoot.create_conversation_with_template = AsyncMock()

    appt = SimpleNamespace(id=uuid4(), customer_id=uuid4(), customer=None)
    result = await _delivery.deliver_template(
        chatwoot, appt, "appointment_confirmation_48h", {"1": "Ana"}, "Hola Ana"
    )

    assert result is False
    chatwoot.send_template_to_conversation_checked.assert_not_called()
    chatwoot.create_conversation_with_template.assert_not_called()


class TestConversationMessagePersistence:
    """TASK-07/08 — best-effort ConversationMessage persistence on a successful send."""

    @pytest.mark.asyncio
    async def test_persists_conversation_message_on_existing_conversation_send(self, monkeypatch):
        from agent.workers.notification_handlers import _delivery

        history = SimpleNamespace(id=uuid4(), conversation_id="125", customer_id=uuid4())
        resolve_session = _FakeSession(execute_result=_FakeResult(history))
        persist_session = _FakeSession()

        sessions = [resolve_session, persist_session]

        @asynccontextmanager
        async def _fake_get_async_session():
            yield sessions.pop(0)

        monkeypatch.setattr(_delivery, "get_async_session", _fake_get_async_session)

        chatwoot = MagicMock()
        chatwoot.send_template_to_conversation_checked = AsyncMock(
            return_value=ConversationSendOutcome.SENT
        )

        appt = _make_appt()
        result = await _delivery.deliver_template(
            chatwoot, appt, "appointment_confirmation_48h", {"1": "Ana"}, "Hola Ana"
        )

        assert result is True
        assert len(persist_session.added) == 1
        msg = persist_session.added[0]
        assert msg.role == "assistant"
        assert msg.author_type == "bot"
        assert msg.author_user_id is None
        assert msg.content == "Hola Ana"
        assert msg.conversation_history_id == history.id
        assert persist_session.committed is True

    @pytest.mark.asyncio
    async def test_persistence_failure_is_best_effort_send_still_succeeds(self, monkeypatch):
        from agent.workers.notification_handlers import _delivery

        history = SimpleNamespace(id=uuid4(), conversation_id="125", customer_id=uuid4())
        resolve_session = _FakeSession(execute_result=_FakeResult(history))

        class _BrokenSession(_FakeSession):
            async def commit(self):
                raise RuntimeError("db unavailable")

        sessions = [resolve_session, _BrokenSession()]

        @asynccontextmanager
        async def _fake_get_async_session():
            yield sessions.pop(0)

        monkeypatch.setattr(_delivery, "get_async_session", _fake_get_async_session)

        chatwoot = MagicMock()
        chatwoot.send_template_to_conversation_checked = AsyncMock(
            return_value=ConversationSendOutcome.SENT
        )

        appt = _make_appt()
        result = await _delivery.deliver_template(
            chatwoot, appt, "appointment_confirmation_48h", {"1": "Ana"}, "Hola Ana"
        )

        # Send is already delivered — persistence failure must not flip the result.
        assert result is True


class TestCreateFallbackHistoryRace:
    """FIX 5 (judge A MAJOR / judge B MINOR): the worker's fallback-create path
    and the webhook's upsert_conversation_history can race on the same unique
    conversation_id. On IntegrityError, reuse the row that won the race instead
    of dropping this send's ConversationMessage persistence."""

    @pytest.mark.asyncio
    async def test_integrity_error_on_commit_reuses_existing_row(self, monkeypatch):
        from agent.workers.notification_handlers import _delivery

        existing_id = uuid4()
        existing_row = SimpleNamespace(id=existing_id, conversation_id="555")

        class _RacingSession(_FakeSession):
            async def commit(self):
                raise IntegrityError("INSERT ...", {}, Exception("duplicate key"))

        resolve_session = _FakeSession(execute_result=_FakeResult(None))  # resolver miss
        racing_session = _RacingSession(execute_result=_FakeResult(existing_row))
        persist_session = _FakeSession()

        sessions = [resolve_session, racing_session, persist_session]

        @asynccontextmanager
        async def _fake_get_async_session():
            yield sessions.pop(0)

        monkeypatch.setattr(_delivery, "get_async_session", _fake_get_async_session)

        chatwoot = MagicMock()
        chatwoot.create_conversation_with_template = AsyncMock(return_value=(555, True))

        appt = _make_appt()
        result = await _delivery.deliver_template(
            chatwoot, appt, "appointment_confirmation_48h", {"1": "Ana"}, "Hola Ana"
        )

        assert result is True
        assert len(persist_session.added) == 1
        msg = persist_session.added[0]
        assert msg.conversation_history_id == existing_id


class TestSendFnsRouteThroughDeliverTemplate:
    """Regression: each of the 3 send_fns must route through deliver_template and
    never call a no-id chatwoot send when a history row would exist (TASK-06)."""

    @pytest.mark.asyncio
    async def test_confirm_48h_send_fn_routes_through_deliver_template(self, monkeypatch):
        from agent.workers.notification_handlers import confirm_48h

        class DummySettings:
            WHATSAPP_TEMPLATE_CONFIRM_48H = "appointment_confirmation_48h"
            AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS = 12
            AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS = 6

        class DummySettingsService:
            async def get(self, key, default=""):
                return default

        monkeypatch.setattr(confirm_48h, "get_settings", lambda: DummySettings())
        monkeypatch.setattr(
            confirm_48h, "get_settings_service", AsyncMock(return_value=DummySettingsService())
        )
        deliver_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(confirm_48h, "deliver_template", deliver_mock)

        appt = SimpleNamespace(
            id=uuid4(),
            customer_id=uuid4(),
            first_name="Ana",
            stylist_id=None,
            service_ids=[],
            start_time=datetime(2026, 5, 3, 12, 30, tzinfo=UTC),
            customer=SimpleNamespace(phone="+34611111111"),
        )
        client = MagicMock()
        client.send_template_message = AsyncMock()

        success = await confirm_48h.send_fn(appt, client)

        assert success is True
        deliver_mock.assert_awaited_once()
        client.send_template_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_reminder_24h_send_fn_routes_through_deliver_template(self, monkeypatch):
        from agent.workers.notification_handlers import reminder_24h

        class DummySettings:
            WHATSAPP_TEMPLATE_REMINDER_24H = "appointment_reminder_2h"

        class DummySettingsService:
            async def get(self, key, default=""):
                return default

        monkeypatch.setattr(reminder_24h, "get_settings", lambda: DummySettings())
        monkeypatch.setattr(
            reminder_24h, "get_settings_service", AsyncMock(return_value=DummySettingsService())
        )
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
        client.send_template_message = AsyncMock()

        success = await reminder_24h.send_fn(appt, client)

        assert success is True
        deliver_mock.assert_awaited_once()
        client.send_template_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_final_warning_send_fn_routes_through_deliver_template(self, monkeypatch):
        from agent.workers.notification_handlers import final_warning

        class DummySettings:
            WHATSAPP_TEMPLATE_FINAL_WARNING = "whatsapp_template_final_warning"

        class DummySettingsService:
            async def get(self, key, default=""):
                return default

        monkeypatch.setattr(final_warning, "get_settings", lambda: DummySettings())
        monkeypatch.setattr(
            final_warning,
            "get_settings_service",
            AsyncMock(return_value=DummySettingsService()),
        )
        deliver_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(final_warning, "deliver_template", deliver_mock)

        appt = SimpleNamespace(
            id=uuid4(),
            customer_id=uuid4(),
            first_name="Ana",
            start_time=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
            customer=SimpleNamespace(phone="+34600000000"),
        )
        client = MagicMock()
        client.send_template_message = AsyncMock()

        success = await final_warning.send_fn(appt, client)

        assert success is True
        deliver_mock.assert_awaited_once()
        client.send_template_message.assert_not_called()

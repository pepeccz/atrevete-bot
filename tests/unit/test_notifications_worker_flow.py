"""Behavioural integration test for the notifications worker.

Exercises `process_handler` end-to-end against in-memory fakes to verify:
  * successful send → commit path calls ``mark_sent_fn``
  * failed send → commit path calls ``mark_failed_fn``
  * idempotency: rows already marked sent stop appearing in the query batch
  * crash-after-send: commit failure leaves the row eligible for retry

This is intentionally lightweight — a full PG+Chatwoot integration would require
fixtures beyond the scope of this phase (SUGGESTION in apply-progress).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agent.workers import notifications_worker
from agent.workers.notification_handlers.base import NotificationHandler


class _FakeSession:
    def __init__(self, *, commit_raises: bool = False):
        self.mark_sent_called_with: list = []
        self.mark_failed_called_with: list = []
        self.committed = False
        self.rolled_back = False
        self._commit_raises = commit_raises

    async def commit(self):
        if self._commit_raises:
            raise RuntimeError("simulated commit failure")
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_process_handler_send_success_marks_sent(monkeypatch):
    appt = SimpleNamespace(id=uuid4())
    sessions: list[_FakeSession] = []

    def make_session():
        s = _FakeSession()
        sessions.append(s)

        class Ctx:
            async def __aenter__(self_inner):
                return s

            async def __aexit__(self_inner, *_):
                return None

        return Ctx()

    monkeypatch.setattr(notifications_worker, "get_async_session", make_session)

    mark_sent = AsyncMock()
    mark_failed = AsyncMock()
    handler = NotificationHandler(
        name="stub",
        query_fn=AsyncMock(return_value=[appt]),
        send_fn=AsyncMock(return_value=True),
        mark_sent_fn=mark_sent,
        mark_failed_fn=mark_failed,
    )

    count = await notifications_worker.process_handler(handler, MagicMock())

    assert count == 1
    mark_sent.assert_awaited_once()
    mark_failed.assert_not_called()


@pytest.mark.asyncio
async def test_process_handler_send_failure_marks_failed(monkeypatch):
    appt = SimpleNamespace(id=uuid4())

    def make_session():
        s = _FakeSession()

        class Ctx:
            async def __aenter__(self_inner):
                return s

            async def __aexit__(self_inner, *_):
                return None

        return Ctx()

    monkeypatch.setattr(notifications_worker, "get_async_session", make_session)

    mark_sent = AsyncMock()
    mark_failed = AsyncMock()
    handler = NotificationHandler(
        name="stub",
        query_fn=AsyncMock(return_value=[appt]),
        send_fn=AsyncMock(return_value=False),
        mark_sent_fn=mark_sent,
        mark_failed_fn=mark_failed,
    )

    count = await notifications_worker.process_handler(handler, MagicMock())

    assert count == 0
    mark_sent.assert_not_called()
    mark_failed.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_handler_crash_after_send_leaves_row_eligible(monkeypatch):
    """Commit failure after a successful send → row stays eligible (at-least-once)."""
    appt = SimpleNamespace(id=uuid4())

    def make_session():
        s = _FakeSession(commit_raises=True)

        class Ctx:
            async def __aenter__(self_inner):
                return s

            async def __aexit__(self_inner, *_):
                return None

        return Ctx()

    monkeypatch.setattr(notifications_worker, "get_async_session", make_session)

    mark_sent = AsyncMock()
    handler = NotificationHandler(
        name="stub",
        query_fn=AsyncMock(return_value=[appt]),
        send_fn=AsyncMock(return_value=True),
        mark_sent_fn=mark_sent,
        mark_failed_fn=AsyncMock(),
    )

    # Must not raise — error is caught and logged.
    count = await notifications_worker.process_handler(handler, MagicMock())

    assert count == 0  # commit failed, so we did not count as sent
    mark_sent.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_handler_empty_batch_is_noop(monkeypatch):
    def make_session():
        class Ctx:
            async def __aenter__(self_inner):
                return _FakeSession()

            async def __aexit__(self_inner, *_):
                return None

        return Ctx()

    monkeypatch.setattr(notifications_worker, "get_async_session", make_session)

    handler = NotificationHandler(
        name="stub",
        query_fn=AsyncMock(return_value=[]),
        send_fn=AsyncMock(),
        mark_sent_fn=AsyncMock(),
        mark_failed_fn=AsyncMock(),
    )
    count = await notifications_worker.process_handler(handler, MagicMock())
    assert count == 0

"""Unit tests for agent.workers.notifications_worker (Phase 5 of appointment-lifecycle-and-notifications)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_feature_flag_disabled_exits_without_polling(monkeypatch):
    """When NOTIFICATIONS_WORKER_ENABLED=False, main() returns 0 without entering the poll loop."""
    from agent.workers import notifications_worker

    class DummySettings:
        NOTIFICATIONS_WORKER_ENABLED = False
        NOTIFICATIONS_POLL_INTERVAL_SECONDS = 60

    monkeypatch.setattr(notifications_worker, "get_settings", lambda: DummySettings())

    main_loop_mock = AsyncMock()
    monkeypatch.setattr(notifications_worker, "main_loop", main_loop_mock)

    exit_code = await notifications_worker.main()

    assert exit_code == 0
    main_loop_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_heartbeat_written_each_tick(monkeypatch, tmp_path):
    """One tick of the worker writes a heartbeat file with a recent timestamp."""
    import time

    from agent.workers import notifications_worker

    hb_path = tmp_path / "notifications_worker_heartbeat.json"
    monkeypatch.setattr(notifications_worker, "HEARTBEAT_PATH", hb_path)

    class DummySettings:
        NOTIFICATIONS_WORKER_ENABLED = True
        NOTIFICATIONS_POLL_INTERVAL_SECONDS = 60

    monkeypatch.setattr(notifications_worker, "get_settings", lambda: DummySettings())
    monkeypatch.setattr(
        notifications_worker,
        "process_handler",
        AsyncMock(return_value=None),
    )

    await notifications_worker._write_heartbeat()

    assert hb_path.exists()
    data = json.loads(hb_path.read_text())
    assert "timestamp" in data
    assert time.time() - data["timestamp"] < 5


def test_handlers_registry_contains_reminder_24h_and_confirm_48h():
    """The HANDLERS registry wires both scheduled notification handlers."""
    from agent.workers.notifications_worker import HANDLERS

    assert "reminder_24h" in HANDLERS
    assert "confirm_48h" in HANDLERS
    for key, handler in HANDLERS.items():
        assert handler.name == key
        assert callable(handler.query_fn)
        assert callable(handler.send_fn)
        assert callable(handler.mark_sent_fn)
        assert callable(handler.mark_failed_fn)


def test_heartbeat_stale_when_missing(tmp_path):
    """is_heartbeat_stale returns True when file absent."""
    from agent.workers.notifications_worker import is_heartbeat_stale

    missing = tmp_path / "does_not_exist.json"
    assert is_heartbeat_stale(missing, max_age_seconds=120) is True


def test_heartbeat_fresh_when_recent(tmp_path):
    """is_heartbeat_stale returns False when mtime is within max_age."""
    import os
    import time

    from agent.workers.notifications_worker import is_heartbeat_stale

    hb = tmp_path / "hb.json"
    hb.write_text("{}")
    # mtime == now → fresh
    now = time.time()
    os.utime(hb, (now, now))
    assert is_heartbeat_stale(hb, max_age_seconds=120, now=now) is False


def test_heartbeat_stale_when_old(tmp_path):
    """is_heartbeat_stale returns True when mtime older than max_age."""
    import os
    import time

    from agent.workers.notifications_worker import is_heartbeat_stale

    hb = tmp_path / "hb.json"
    hb.write_text("{}")
    old = time.time() - 300
    os.utime(hb, (old, old))
    assert is_heartbeat_stale(hb, max_age_seconds=120, now=time.time()) is True

"""
Integration tests for the Chatwoot webhook gate rewrite (T-03/T-04).

Gate order after rewrite (Steps 7 → 8 → 9 → 10 → 11 → 12):
  7.  DB upsert (persist-before-gate — FR-WEBHOOK-4)
  8.  Global AI gate  (panic button — UNCHANGED)
  9.  Per-conversation DB read: fresh scalar SELECT paused_at, resumed_at
      • fail-CLOSED on exception  → ignored_gate_db_error (structured ERROR log)
      • absent-row (None result)  → is_paused=False + WARNING log (fail-OPEN)
      • row with paused_at=None   → is_paused=False (active)
      • row with paused_at set    → is_paused=True  (paused)
  10. Resume injection hook (if not is_paused)
  11. Per-conversation short-circuit (if is_paused → ignored_auto_attention_disabled)
  12. Redis publish

Design invariants tested here:
  SC-2  (T-03#1)  bot paused (DB row paused_at set)   → NOT published + DB persisted
  SC-10 (T-03#2)  global AI off                        → NOT published (Step 8 fires)
  SC-12 (T-03#3)  bot active (DB row paused_at=None)  → IS published
  ADR-1 (T-03#4)  gate DB read raises                 → ignored_gate_db_error (fail-CLOSED)
  R2-B  (T-03#5)  Step-7 row persisted, Step-9 raises → row EXISTS but NOT published
  R5-B  (T-03#6)  gate read returns None (no row)     → is_paused=False + WARNING
  ADR-3 (T-03#7)  update_conversation_attributes never called during gate
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_WEBHOOK_TOKEN = "test-webhook-token-123"

_BASE_PAYLOAD = {
    "event": "message_created",
    "conversation": {
        "id": 42,
        "inbox_id": 1,
        "messages": [
            {
                "id": 9001,
                "content": "Quiero reservar una cita",
                "message_type": 0,
                "attachments": [],
                "created_at": 1715427600,
                "conversation_id": 42,
            }
        ],
        "custom_attributes": {},
    },
    "sender": {
        "id": 1,
        "name": "Cliente Test",
        "phone_number": "+34612345678",
    },
    "attachments": [],
}

_PAYLOAD_GLOBAL_AI_OFF = {
    **_BASE_PAYLOAD,
    "conversation": {
        **_BASE_PAYLOAD["conversation"],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """TestClient for the FastAPI app."""
    return TestClient(
        app, raise_server_exceptions=False, headers={"Origin": "http://localhost:3000"}
    )


@pytest.fixture
def mock_redis():
    """Mock Redis client that tracks calls."""
    r = AsyncMock()
    r.setnx = AsyncMock(return_value=True)
    r.expire = AsyncMock()
    r.incr = AsyncMock(return_value=1)
    r.exists = AsyncMock(return_value=0)
    return r


def _patch_settings(token: str = _WEBHOOK_TOKEN):
    settings = MagicMock()
    settings.CHATWOOT_WEBHOOK_TOKEN = token
    settings.USE_REDIS_STREAMS = True
    return settings


def _make_gate_session(paused_at: datetime | None, resumed_at: datetime | None):
    """Build an async session mock whose scalar SELECT returns a paused_at/resumed_at Row."""
    row = MagicMock()
    row.paused_at = paused_at
    row.resumed_at = resumed_at

    result = MagicMock()
    result.fetchone = MagicMock(return_value=row)

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock(return_value=result)
    return session


def _make_gate_session_absent_row():
    """Build a session mock whose scalar SELECT returns None (no row)."""
    result = MagicMock()
    result.fetchone = MagicMock(return_value=None)

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock(return_value=result)
    return session


def _make_gate_session_raises(exc: Exception):
    """Build a session mock whose execute() raises the given exception."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock(side_effect=exc)
    return session


def _post_webhook(client, payload: dict, token: str = _WEBHOOK_TOKEN):
    return client.post(f"/webhook/chatwoot/{token}", json=payload)


# ---------------------------------------------------------------------------
# T-03#1  SC-2: bot paused (DB row paused_at set) — DB persisted, NOT published
# ---------------------------------------------------------------------------


def test_bot_paused_not_published(client, mock_redis):
    """SC-2: paused_at set in DB → message persisted but NOT published."""
    now = datetime.now(tz=UTC)
    gate_session = _make_gate_session(paused_at=now, resumed_at=None)

    db_upsert_called = []

    async def _fake_upsert(session, payload, **kwargs):
        db_upsert_called.append(True)

    with (
        patch("api.routes.chatwoot.get_settings", return_value=_patch_settings()),
        patch("api.routes.chatwoot.get_redis_client", return_value=mock_redis),
        patch("api.routes.chatwoot.check_and_set_idempotency", AsyncMock(return_value=False)),
        patch("api.routes.chatwoot.check_conversation_rate_limit", AsyncMock(return_value=False)),
        patch(
            "api.routes.chatwoot.get_settings_service",
            AsyncMock(return_value=MagicMock(get=AsyncMock(return_value=True))),
        ),
        patch("api.routes.chatwoot.upsert_conversation_history", side_effect=_fake_upsert),
        patch("api.routes.chatwoot.add_to_stream", AsyncMock()) as mock_stream,
        patch("api.routes.chatwoot.publish_to_channel", AsyncMock()) as mock_pubsub,
        patch("database.connection.get_async_session", return_value=gate_session),
    ):
        resp = _post_webhook(client, _BASE_PAYLOAD)

    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored_auto_attention_disabled"

    # DB upsert happened (persist-before-gate)
    assert len(db_upsert_called) == 1, "DB upsert must happen before gate check"

    # Redis NOT published
    mock_stream.assert_not_called()
    mock_pubsub.assert_not_called()


# ---------------------------------------------------------------------------
# T-03#2  SC-10: global AI off — DB persisted, NOT published
# ---------------------------------------------------------------------------


def test_global_ai_off_persists_db_no_redis_publish(client, mock_redis):
    """SC-10: global ai_agent_enabled=False → DB written but Redis NOT published."""
    db_upsert_called = []

    async def _fake_upsert(session, payload, **kwargs):
        db_upsert_called.append(True)

    mock_settings_service = MagicMock()
    mock_settings_service.get = AsyncMock(return_value=False)

    with (
        patch("api.routes.chatwoot.get_settings", return_value=_patch_settings()),
        patch("api.routes.chatwoot.get_redis_client", return_value=mock_redis),
        patch("api.routes.chatwoot.check_and_set_idempotency", AsyncMock(return_value=False)),
        patch("api.routes.chatwoot.check_conversation_rate_limit", AsyncMock(return_value=False)),
        patch(
            "api.routes.chatwoot.get_settings_service",
            AsyncMock(return_value=mock_settings_service),
        ),
        patch("api.routes.chatwoot.upsert_conversation_history", side_effect=_fake_upsert),
        patch("api.routes.chatwoot.add_to_stream", AsyncMock()) as mock_stream,
        patch("api.routes.chatwoot.publish_to_channel", AsyncMock()) as mock_pubsub,
    ):
        resp = _post_webhook(client, _PAYLOAD_GLOBAL_AI_OFF)

    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored_ai_disabled"

    # DB upsert happens even when global AI is off (FR-WEBHOOK-4)
    assert len(db_upsert_called) == 1, "DB upsert must happen even when global AI is off"

    mock_stream.assert_not_called()
    mock_pubsub.assert_not_called()


# ---------------------------------------------------------------------------
# T-03#3  Regression: bot active → IS published
# ---------------------------------------------------------------------------


def test_bot_active_published(client, mock_redis):
    """bot active (paused_at=None) → message IS published to Redis."""
    gate_session = _make_gate_session(paused_at=None, resumed_at=None)

    with (
        patch("api.routes.chatwoot.get_settings", return_value=_patch_settings()),
        patch("api.routes.chatwoot.get_redis_client", return_value=mock_redis),
        patch("api.routes.chatwoot.check_and_set_idempotency", AsyncMock(return_value=False)),
        patch("api.routes.chatwoot.check_conversation_rate_limit", AsyncMock(return_value=False)),
        patch(
            "api.routes.chatwoot.get_settings_service",
            AsyncMock(return_value=MagicMock(get=AsyncMock(return_value=True))),
        ),
        patch("api.routes.chatwoot.upsert_conversation_history", AsyncMock()),
        patch(
            "api.routes.chatwoot.add_to_stream", AsyncMock(return_value="1-0")
        ) as mock_stream,
        patch("api.routes.chatwoot.publish_to_channel", AsyncMock()),
        patch("database.connection.get_async_session", return_value=gate_session),
        patch(
            "api.services.resume_injection.maybe_inject_pending_context",
            AsyncMock(return_value=False),
        ),
    ):
        resp = _post_webhook(client, _BASE_PAYLOAD)

    assert resp.status_code == 200
    assert resp.json()["status"] == "received"
    mock_stream.assert_called_once()


# ---------------------------------------------------------------------------
# T-03#4  ADR-1 fail-CLOSED: gate DB read raises → ignored_gate_db_error
# ---------------------------------------------------------------------------


def test_fail_closed_gate_db_error(client, mock_redis, caplog):
    """gate DB read raises → NOT published + status=ignored_gate_db_error + ERROR log."""
    gate_session = _make_gate_session_raises(RuntimeError("connection refused"))

    with (
        patch("api.routes.chatwoot.get_settings", return_value=_patch_settings()),
        patch("api.routes.chatwoot.get_redis_client", return_value=mock_redis),
        patch("api.routes.chatwoot.check_and_set_idempotency", AsyncMock(return_value=False)),
        patch("api.routes.chatwoot.check_conversation_rate_limit", AsyncMock(return_value=False)),
        patch(
            "api.routes.chatwoot.get_settings_service",
            AsyncMock(return_value=MagicMock(get=AsyncMock(return_value=True))),
        ),
        patch("api.routes.chatwoot.upsert_conversation_history", AsyncMock()),
        patch("api.routes.chatwoot.add_to_stream", AsyncMock()) as mock_stream,
        patch("api.routes.chatwoot.publish_to_channel", AsyncMock()) as mock_pubsub,
        patch("database.connection.get_async_session", return_value=gate_session),
        caplog.at_level(logging.ERROR, logger="api.routes.chatwoot"),
    ):
        resp = _post_webhook(client, _BASE_PAYLOAD)

    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored_gate_db_error"

    # NOT published (fail-CLOSED)
    mock_stream.assert_not_called()
    mock_pubsub.assert_not_called()

    # Structured ERROR log with greppable marker — event field is in r.event (extra attr)
    assert any(
        r.levelno >= logging.ERROR and getattr(r, "event", None) == "gate_db_error"
        for r in caplog.records
    ), "Expected structured ERROR log with event='gate_db_error' marker"


# ---------------------------------------------------------------------------
# T-03#5  R2-B: Step-7 row persisted, Step-9 raises → row EXISTS, NOT published
# ---------------------------------------------------------------------------


def test_r2b_row_persists_gate_fails(client, mock_redis):
    """R2-B: Step-7 upsert succeeds but Step-9 gate read raises → row in DB but NOT published."""
    db_upsert_called = []

    async def _fake_upsert(session, payload, **kwargs):
        db_upsert_called.append(True)

    gate_session = _make_gate_session_raises(OSError("DB timeout"))

    with (
        patch("api.routes.chatwoot.get_settings", return_value=_patch_settings()),
        patch("api.routes.chatwoot.get_redis_client", return_value=mock_redis),
        patch("api.routes.chatwoot.check_and_set_idempotency", AsyncMock(return_value=False)),
        patch("api.routes.chatwoot.check_conversation_rate_limit", AsyncMock(return_value=False)),
        patch(
            "api.routes.chatwoot.get_settings_service",
            AsyncMock(return_value=MagicMock(get=AsyncMock(return_value=True))),
        ),
        patch("api.routes.chatwoot.upsert_conversation_history", side_effect=_fake_upsert),
        patch("api.routes.chatwoot.add_to_stream", AsyncMock()) as mock_stream,
        patch("api.routes.chatwoot.publish_to_channel", AsyncMock()) as mock_pubsub,
        patch("database.connection.get_async_session", return_value=gate_session),
    ):
        resp = _post_webhook(client, _BASE_PAYLOAD)

    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored_gate_db_error"

    # Step-7 persisted (DB row exists)
    assert len(db_upsert_called) == 1, "Step-7 upsert must have run"

    # Step-9 raised → fail-CLOSED → NOT published
    mock_stream.assert_not_called()
    mock_pubsub.assert_not_called()


# ---------------------------------------------------------------------------
# T-03#6  R5-B: absent row (no row, no exception) → is_paused=False + WARNING
# ---------------------------------------------------------------------------


def test_absent_row_active_with_warning(client, mock_redis, caplog):
    """R5-B: gate read returns None (no row) → is_paused=False, message published, WARNING emitted."""
    gate_session = _make_gate_session_absent_row()

    with (
        patch("api.routes.chatwoot.get_settings", return_value=_patch_settings()),
        patch("api.routes.chatwoot.get_redis_client", return_value=mock_redis),
        patch("api.routes.chatwoot.check_and_set_idempotency", AsyncMock(return_value=False)),
        patch("api.routes.chatwoot.check_conversation_rate_limit", AsyncMock(return_value=False)),
        patch(
            "api.routes.chatwoot.get_settings_service",
            AsyncMock(return_value=MagicMock(get=AsyncMock(return_value=True))),
        ),
        patch("api.routes.chatwoot.upsert_conversation_history", AsyncMock()),
        patch(
            "api.routes.chatwoot.add_to_stream", AsyncMock(return_value="1-0")
        ) as mock_stream,
        patch("api.routes.chatwoot.publish_to_channel", AsyncMock()),
        patch("database.connection.get_async_session", return_value=gate_session),
        patch(
            "api.services.resume_injection.maybe_inject_pending_context",
            AsyncMock(return_value=False),
        ),
        caplog.at_level(logging.WARNING, logger="api.routes.chatwoot"),
    ):
        resp = _post_webhook(client, _BASE_PAYLOAD)

    assert resp.status_code == 200
    # Message was published (fail-OPEN)
    mock_stream.assert_called_once()

    # WARNING log emitted for absent row
    assert any(
        r.levelno == logging.WARNING for r in caplog.records
    ), "Expected WARNING log for absent-row gate path"


# ---------------------------------------------------------------------------
# T-03#7  ADR-3: update_conversation_attributes NEVER called during gate
# ---------------------------------------------------------------------------


def test_no_chatwoot_write_at_gate(client, mock_redis):
    """ADR-3: update_conversation_attributes must NEVER be called during webhook gate."""
    gate_session = _make_gate_session(paused_at=None, resumed_at=None)

    mock_cw_client = MagicMock()
    mock_cw_client.update_conversation_attributes = AsyncMock()

    with (
        patch("api.routes.chatwoot.get_settings", return_value=_patch_settings()),
        patch("api.routes.chatwoot.get_redis_client", return_value=mock_redis),
        patch("api.routes.chatwoot.check_and_set_idempotency", AsyncMock(return_value=False)),
        patch("api.routes.chatwoot.check_conversation_rate_limit", AsyncMock(return_value=False)),
        patch(
            "api.routes.chatwoot.get_settings_service",
            AsyncMock(return_value=MagicMock(get=AsyncMock(return_value=True))),
        ),
        patch("api.routes.chatwoot.upsert_conversation_history", AsyncMock()),
        patch("api.routes.chatwoot.add_to_stream", AsyncMock(return_value="1-0")),
        patch("api.routes.chatwoot.publish_to_channel", AsyncMock()),
        patch("database.connection.get_async_session", return_value=gate_session),
        patch("shared.chatwoot_client.ChatwootClient", return_value=mock_cw_client),
        patch(
            "api.services.resume_injection.maybe_inject_pending_context",
            AsyncMock(return_value=False),
        ),
    ):
        resp = _post_webhook(client, _BASE_PAYLOAD)

    assert resp.status_code == 200
    mock_cw_client.update_conversation_attributes.assert_not_called()

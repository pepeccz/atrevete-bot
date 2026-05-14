"""
Integration tests for the Chatwoot webhook gate refactor.

Covers:
- SC-2: bot-off inbound → DB row persisted, Redis NOT published
- SC-10: global AI off → DB row persisted, Redis NOT published
- Regression: bot-on inbound → Redis IS published

These tests use FastAPI TestClient with patched Redis, settings service,
and DB session — no live Postgres or Redis required.

Gate order (post-refactor):
  1. Token auth
  2. Parse payload
  3. Idempotency check
  4. Rate limit
  5. Phone guard
  6. Audio transcription (BEFORE gate)
  7. DB upsert (BEFORE gate)
  8. Global AI gate (short-circuits without publish)
  9. atencion_automatica=None → enable bot + continue
  10. Resume injection hook
  11. atencion_automatica=False gate (short-circuits without publish)
  12. Redis publish
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app

# ---------------------------------------------------------------------------
# Helpers
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
        "custom_attributes": {"atencion_automatica": False},
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
        "custom_attributes": {"atencion_automatica": True},
    },
}


@pytest.fixture
def client():
    """TestClient for the FastAPI app with allowed Origin header."""
    return TestClient(
        app, raise_server_exceptions=False, headers={"Origin": "http://localhost:3000"}
    )


@pytest.fixture
def mock_redis():
    """Mock Redis client that tracks calls."""
    r = AsyncMock()
    r.setnx = AsyncMock(return_value=True)  # Not duplicate
    r.expire = AsyncMock()
    r.incr = AsyncMock(return_value=1)  # Under rate limit
    r.exists = AsyncMock(return_value=0)  # No pending injection flag
    return r


def _make_db_session_mock():
    """Return a mock async session context manager."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


def _post_webhook(client, payload: dict, token: str = _WEBHOOK_TOKEN):
    """Helper to POST to the chatwoot webhook (mounted at /webhook prefix)."""
    return client.post(f"/webhook/chatwoot/{token}", json=payload)


def _patch_settings(token: str = _WEBHOOK_TOKEN):
    """Return a mock settings object for chatwoot."""
    settings = MagicMock()
    settings.CHATWOOT_WEBHOOK_TOKEN = token
    settings.USE_REDIS_STREAMS = True
    return settings


# ---------------------------------------------------------------------------
# SC-2: Bot off — DB persisted, Redis NOT published
# ---------------------------------------------------------------------------


def test_bot_off_inbound_persists_db_no_redis_publish(client, mock_redis):
    """SC-2: When atencion_automatica=False, DB is written but Redis is NOT published."""
    db_upsert_called = []

    async def _fake_upsert(
        session, payload, message_text=None, chatwoot_message_id=None, attachments_payload=None
    ):
        db_upsert_called.append({"message_text": message_text})

    mock_db_session = _make_db_session_mock()

    with (
        patch("api.routes.chatwoot.get_settings", return_value=_patch_settings()),
        patch("api.routes.chatwoot.get_redis_client", return_value=mock_redis),
        patch(
            "api.routes.chatwoot.check_and_set_idempotency",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "api.routes.chatwoot.check_conversation_rate_limit",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "api.routes.chatwoot.get_settings_service",
            new_callable=AsyncMock,
            return_value=MagicMock(get=AsyncMock(return_value=True)),
        ),
        patch("api.routes.chatwoot.upsert_conversation_history", side_effect=_fake_upsert),
        patch("api.routes.chatwoot.add_to_stream", new_callable=AsyncMock) as mock_stream,
        patch("api.routes.chatwoot.publish_to_channel", new_callable=AsyncMock) as mock_pubsub,
        patch("database.connection.get_async_session", return_value=mock_db_session),
    ):
        resp = _post_webhook(client, _BASE_PAYLOAD)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ignored_auto_attention_disabled"

    # DB upsert was called (persistence happened)
    assert len(db_upsert_called) == 1, "DB upsert should be called even when bot is off"
    assert db_upsert_called[0]["message_text"] == "Quiero reservar una cita"

    # Redis publish was NOT called
    mock_stream.assert_not_called()
    mock_pubsub.assert_not_called()


# ---------------------------------------------------------------------------
# SC-10: Global AI off — DB persisted, Redis NOT published
# ---------------------------------------------------------------------------


def test_global_ai_off_persists_db_no_redis_publish(client, mock_redis):
    """SC-10: When ai_agent_enabled=False globally, DB is written but Redis is NOT published."""
    db_upsert_called = []

    async def _fake_upsert(
        session, payload, message_text=None, chatwoot_message_id=None, attachments_payload=None
    ):
        db_upsert_called.append({"message_text": message_text})

    # Settings service reports AI is disabled
    mock_settings_service = MagicMock()
    mock_settings_service.get = AsyncMock(return_value=False)
    mock_db_session = _make_db_session_mock()

    with (
        patch("api.routes.chatwoot.get_settings", return_value=_patch_settings()),
        patch("api.routes.chatwoot.get_redis_client", return_value=mock_redis),
        patch(
            "api.routes.chatwoot.check_and_set_idempotency",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "api.routes.chatwoot.check_conversation_rate_limit",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "api.routes.chatwoot.get_settings_service",
            new_callable=AsyncMock,
            return_value=mock_settings_service,
        ),
        patch("api.routes.chatwoot.upsert_conversation_history", side_effect=_fake_upsert),
        patch("api.routes.chatwoot.add_to_stream", new_callable=AsyncMock) as mock_stream,
        patch("api.routes.chatwoot.publish_to_channel", new_callable=AsyncMock) as mock_pubsub,
        patch("database.connection.get_async_session", return_value=mock_db_session),
    ):
        resp = _post_webhook(client, _PAYLOAD_GLOBAL_AI_OFF)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ignored_ai_disabled"

    # DB upsert was called even though AI is globally disabled (policy change FR-WEBHOOK-4)
    assert len(db_upsert_called) == 1, "DB upsert must happen even when global AI is off"

    # Redis publish was NOT called
    mock_stream.assert_not_called()
    mock_pubsub.assert_not_called()


# ---------------------------------------------------------------------------
# Normal flow: bot on — Redis IS published
# ---------------------------------------------------------------------------


def test_bot_on_inbound_publishes_to_redis(client, mock_redis):
    """Regression: When atencion_automatica=True, message is published to Redis."""
    payload_bot_on = {
        **_BASE_PAYLOAD,
        "conversation": {
            **_BASE_PAYLOAD["conversation"],
            "custom_attributes": {"atencion_automatica": True},
            "messages": [
                {
                    "id": 9002,
                    "content": "Quiero reservar",
                    "message_type": 0,
                    "attachments": [],
                    "created_at": 1715427600,
                    "conversation_id": 42,
                }
            ],
        },
    }

    mock_db_session = _make_db_session_mock()

    with (
        patch("api.routes.chatwoot.get_settings", return_value=_patch_settings()),
        patch("api.routes.chatwoot.get_redis_client", return_value=mock_redis),
        patch(
            "api.routes.chatwoot.check_and_set_idempotency",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "api.routes.chatwoot.check_conversation_rate_limit",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "api.routes.chatwoot.get_settings_service",
            new_callable=AsyncMock,
            return_value=MagicMock(get=AsyncMock(return_value=True)),
        ),
        patch("api.routes.chatwoot.upsert_conversation_history", new_callable=AsyncMock),
        patch(
            "api.routes.chatwoot.add_to_stream",
            new_callable=AsyncMock,
            return_value="1-0",
        ) as mock_stream,
        patch("api.routes.chatwoot.publish_to_channel", new_callable=AsyncMock),
        patch("database.connection.get_async_session", return_value=mock_db_session),
        patch(
            "api.services.resume_injection.maybe_inject_pending_context",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        resp = _post_webhook(client, payload_bot_on)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "received"
    mock_stream.assert_called_once()

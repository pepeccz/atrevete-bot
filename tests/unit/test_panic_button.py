"""
Unit tests for panic button — system-wide AI agent toggle.

Tests the ai_agent_enabled check in api/routes/chatwoot.py:
- AI enabled → message continues processing
- AI disabled → message silently ignored
- Setting missing → fail-closed (message ignored)
- SettingsService error → fail-closed (message ignored)
- Idempotency fires before AI toggle (ordering guarantee)
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app

# =============================================================================
# Helpers
# =============================================================================

WEBHOOK_TOKEN = "test-secret-token"


def _make_webhook_payload(
    conversation_id: int = 1,
    message_id: int = 100,
    phone: str = "+34600000001",
    text: str = "Hola",
    atencion_automatica: bool | None = True,
) -> dict:
    """Build a minimal valid Chatwoot webhook payload."""
    custom_attributes = {}
    if atencion_automatica is not None:
        custom_attributes["atencion_automatica"] = atencion_automatica

    return {
        "event": "message_created",
        "conversation": {
            "id": conversation_id,
            "inbox_id": 1,
            "messages": [
                {
                    "id": message_id,
                    "content": text,
                    "message_type": 0,
                    "content_type": "text",
                    "attachments": [],
                    "sender": {"phone_number": phone, "name": "Test User"},
                    "created_at": int(time.time()),
                    "conversation_id": conversation_id,
                }
            ],
            "custom_attributes": custom_attributes,
        },
        "sender": {"phone_number": phone, "name": "Test User"},
        "attachments": [],
    }


# =============================================================================
# Tests
# =============================================================================


class TestPanicButtonWebhook:
    """Tests for the system-wide AI toggle check in the webhook handler."""

    def test_webhook_continues_when_ai_enabled(self):
        """When ai_agent_enabled=True, message continues to processing.

        After T-04 the gate (Step 9) reads paused_at/resumed_at from DB.
        We supply a mock session returning paused_at=None so the gate passes
        (R8-A: global gate fires BEFORE Step 9; Step 9 only reached when global=True).
        """
        mock_settings_service = AsyncMock()
        mock_settings_service.get = AsyncMock(return_value=True)

        # Mock gate session: paused_at=None → is_paused=False → continue
        gate_row = MagicMock()
        gate_row.paused_at = None
        gate_row.resumed_at = None
        gate_result = MagicMock()
        gate_result.fetchone = MagicMock(return_value=gate_row)
        gate_session = AsyncMock()
        gate_session.__aenter__ = AsyncMock(return_value=gate_session)
        gate_session.__aexit__ = AsyncMock(return_value=False)
        gate_session.execute = AsyncMock(return_value=gate_result)

        with (
            patch(
                "api.routes.chatwoot.get_settings",
                MagicMock(
                    return_value=MagicMock(
                        CHATWOOT_WEBHOOK_TOKEN=WEBHOOK_TOKEN, USE_REDIS_STREAMS=True
                    )
                ),
            ),
            patch(
                "api.routes.chatwoot.check_and_set_idempotency",
                AsyncMock(return_value=False),
            ),
            patch(
                "api.routes.chatwoot.check_conversation_rate_limit",
                AsyncMock(return_value=False),
            ),
            patch("api.routes.chatwoot.upsert_conversation_history", AsyncMock()),
            patch("api.routes.chatwoot.add_to_stream", AsyncMock(return_value="1-0")) as mock_stream,
            patch(
                "api.routes.chatwoot.get_redis_client",
                MagicMock(
                    return_value=MagicMock(
                        setnx=AsyncMock(return_value=True), expire=AsyncMock()
                    )
                ),
            ),
            patch(
                "api.routes.chatwoot.get_settings_service",
                AsyncMock(return_value=mock_settings_service),
            ),
            patch("database.connection.get_async_session", return_value=gate_session),
            patch(
                "api.services.resume_injection.maybe_inject_pending_context",
                AsyncMock(return_value=False),
            ),
        ):
            client = TestClient(app)
            payload = _make_webhook_payload()
            response = client.post(
                f"/webhook/chatwoot/{WEBHOOK_TOKEN}",
                json=payload,
            )

            assert response.status_code == 200
            data = response.json()
            assert data.get("status") != "ignored_ai_disabled"
            # Global gate passed → message was published
            mock_stream.assert_called_once()

    def test_webhook_ignores_when_ai_disabled(self):
        """When ai_agent_enabled=False, message is silently ignored."""
        mock_settings_service = AsyncMock()
        mock_settings_service.get = AsyncMock(return_value=False)

        with (
            patch(
                "api.routes.chatwoot.get_settings",
                MagicMock(
                    return_value=MagicMock(CHATWOOT_WEBHOOK_TOKEN=WEBHOOK_TOKEN, USE_REDIS_STREAMS=True)
                ),
            ),
            patch(
                "api.routes.chatwoot.check_and_set_idempotency", AsyncMock(return_value=False)
            ),
            patch(
                "api.routes.chatwoot.get_settings_service",
                AsyncMock(return_value=mock_settings_service),
            ),
            patch("api.routes.chatwoot.add_to_stream", AsyncMock()) as mock_stream,
        ):
            client = TestClient(app)
            payload = _make_webhook_payload()
            response = client.post(
                f"/webhook/chatwoot/{WEBHOOK_TOKEN}",
                json=payload,
            )

            assert response.status_code == 200
            assert response.json()["status"] == "ignored_ai_disabled"
            mock_stream.assert_not_called()

    def test_webhook_fails_closed_when_setting_missing(self):
        """When ai_agent_enabled setting doesn't exist (None), fail-closed."""
        mock_settings_service = AsyncMock()
        mock_settings_service.get = AsyncMock(return_value=None)

        with (
            patch(
                "api.routes.chatwoot.get_settings",
                MagicMock(
                    return_value=MagicMock(CHATWOOT_WEBHOOK_TOKEN=WEBHOOK_TOKEN, USE_REDIS_STREAMS=True)
                ),
            ),
            patch(
                "api.routes.chatwoot.check_and_set_idempotency", AsyncMock(return_value=False)
            ),
            patch(
                "api.routes.chatwoot.get_settings_service",
                AsyncMock(return_value=mock_settings_service),
            ),
            patch("api.routes.chatwoot.add_to_stream", AsyncMock()) as mock_stream,
        ):
            client = TestClient(app)
            payload = _make_webhook_payload()
            response = client.post(
                f"/webhook/chatwoot/{WEBHOOK_TOKEN}",
                json=payload,
            )

            assert response.status_code == 200
            assert response.json()["status"] == "ignored_ai_disabled"
            mock_stream.assert_not_called()

    def test_webhook_fails_closed_on_settings_service_error(self):
        """When SettingsService raises an exception, fail-closed."""
        with (
            patch(
                "api.routes.chatwoot.get_settings",
                MagicMock(
                    return_value=MagicMock(CHATWOOT_WEBHOOK_TOKEN=WEBHOOK_TOKEN, USE_REDIS_STREAMS=True)
                ),
            ),
            patch(
                "api.routes.chatwoot.check_and_set_idempotency", AsyncMock(return_value=False)
            ),
            patch(
                "api.routes.chatwoot.get_settings_service",
                AsyncMock(side_effect=Exception("db connection refused")),
            ),
            patch("api.routes.chatwoot.add_to_stream", AsyncMock()) as mock_stream,
        ):
            client = TestClient(app)
            payload = _make_webhook_payload()
            response = client.post(
                f"/webhook/chatwoot/{WEBHOOK_TOKEN}",
                json=payload,
            )

            assert response.status_code == 200
            assert response.json()["status"] == "ignored_ai_disabled"
            mock_stream.assert_not_called()

    def test_idempotency_check_fires_before_ai_toggle(self):
        """Duplicate messages are rejected before the AI toggle is checked."""
        mock_get_settings_service = AsyncMock()

        with (
            patch(
                "api.routes.chatwoot.get_settings",
                MagicMock(
                    return_value=MagicMock(CHATWOOT_WEBHOOK_TOKEN=WEBHOOK_TOKEN, USE_REDIS_STREAMS=True)
                ),
            ),
            patch(
                "api.routes.chatwoot.check_and_set_idempotency", AsyncMock(return_value=True)
            ),
            patch(
                "api.routes.chatwoot.get_settings_service", mock_get_settings_service
            ),
        ):
            client = TestClient(app)
            payload = _make_webhook_payload()
            response = client.post(
                f"/webhook/chatwoot/{WEBHOOK_TOKEN}",
                json=payload,
            )

            assert response.status_code == 200
            assert response.json()["status"] == "duplicate"
            # AI toggle should NOT have been checked
            mock_get_settings_service.assert_not_called()

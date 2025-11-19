"""Integration tests for webhook endpoints."""

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from api.main import app


class TestChatwootWebhook:
    """Integration tests for Chatwoot webhook endpoint."""

    def test_valid_chatwoot_webhook_returns_200(self):
        """Test that valid Chatwoot webhook is accepted and returns 200."""
        from shared.config import get_settings

        # Get the actual default token from settings
        settings = get_settings()
        token = settings.CHATWOOT_WEBHOOK_TOKEN

        # Create test payload
        payload = {
            "event": "message_created",
            "conversation": {
                "id": 100,
                "inbox_id": 1,
                "messages": [
                    {
                        "id": 12345,
                        "content": "Hello, I need an appointment",
                        "message_type": 0,
                        "created_at": 1730000000,
                        "conversation_id": 100,
                    }
                ],
                "custom_attributes": {},  # Empty attributes
            },
            "sender": {"phone_number": "612345678", "name": "María García"},
            "created_at": "2025-10-27T10:00:00Z",
        }

        body = json.dumps(payload).encode()

        # Mock Redis publish and ChatwootClient for first message
        with patch("api.routes.chatwoot.publish_to_channel") as mock_publish:
            with patch("api.routes.chatwoot.ChatwootClient") as mock_chatwoot_class:
                mock_chatwoot = AsyncMock()
                mock_chatwoot.update_conversation_attributes = AsyncMock(return_value=True)
                mock_chatwoot_class.return_value = mock_chatwoot
                mock_publish.return_value = AsyncMock()

                client = TestClient(app)
                response = client.post(
                    f"/webhook/chatwoot/{token}",
                    content=body,
                    headers={"Content-Type": "application/json"},
                )

                assert response.status_code == 200
                assert response.json()["status"] == "received"

                # Verify message was published to Redis
                mock_publish.assert_called_once()
                call_args = mock_publish.call_args
                assert call_args[0][0] == "incoming_messages"
                published_data = call_args[0][1]
                assert published_data["conversation_id"] == "100"
                assert published_data["customer_phone"] == "+34612345678"  # Normalized

                # Verify atencion_automatica was set since custom_attributes was empty
                mock_chatwoot.update_conversation_attributes.assert_called_once_with(
                    conversation_id=100,
                    attributes={"atencion_automatica": True}
                )

    def test_invalid_chatwoot_token_returns_401(self):
        """Test that invalid Chatwoot token returns 401."""
        client = TestClient(app)

        payload = {
            "event": "message_created",
            "conversation": {
                "id": 100,
                "inbox_id": 1,
                "messages": [
                    {
                        "id": 12345,
                        "content": "Hello",
                        "message_type": 0,
                        "created_at": 1730000000,
                        "conversation_id": 100,
                    }
                ],
            },
            "sender": {"phone_number": "612345678", "name": "María"},
            "created_at": "2025-10-27T10:00:00Z",
        }

        body = json.dumps(payload).encode()

        response = client.post(
            "/webhook/chatwoot/invalid_token_12345",
            content=body,
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 401

    def test_non_incoming_message_ignored(self):
        """Test that outgoing messages are ignored."""
        client = TestClient(app)

        payload = {
            "event": "message_created",
            "conversation": {
                "id": 100,
                "inbox_id": 1,
                "messages": [
                    {
                        "id": 12345,
                        "content": "Hello",
                        "message_type": 1,  # Outgoing message (1 = outgoing)
                        "created_at": 1730000000,
                        "conversation_id": 100,
                    }
                ],
            },
            "sender": {"phone_number": "612345678", "name": "Bot"},
            "created_at": "2025-10-27T10:00:00Z",
        }

        body = json.dumps(payload).encode()

        from shared.config import get_settings
        settings = get_settings()
        token = settings.CHATWOOT_WEBHOOK_TOKEN

        with patch("api.routes.chatwoot.publish_to_channel") as mock_publish:
            response = client.post(
                f"/webhook/chatwoot/{token}",
                content=body,
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 200
            assert response.json()["status"] == "ignored"
            # Should NOT publish to Redis
            mock_publish.assert_not_called()

    def test_atencion_automatica_true_processes_message(self):
        """Test that message is processed when atencion_automatica=true."""
        client = TestClient(app)

        payload = {
            "event": "message_created",
            "id": 12345,
            "content": "Hello, I need an appointment",
            "conversation": {
                "id": 100,
                "inbox_id": 1,
                "messages": [
                    {
                        "id": 12345,
                        "content": "Hello, I need an appointment",
                        "message_type": 0,
                        "created_at": 1730000000,
                        "conversation_id": 100,
                    }
                ],
                "custom_attributes": {"atencion_automatica": True},
            },
            "sender": {"phone_number": "612345678", "name": "María García"},
            "created_at": "2025-10-27T10:00:00Z",
        }

        body = json.dumps(payload).encode()

        from shared.config import get_settings
        settings = get_settings()
        token = settings.CHATWOOT_WEBHOOK_TOKEN

        with patch("api.routes.chatwoot.publish_to_channel") as mock_publish:
            mock_publish.return_value = AsyncMock()

            response = client.post(
                f"/webhook/chatwoot/{token}",
                content=body,
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 200
            assert response.json()["status"] == "received"
            # Message should be published to Redis
            mock_publish.assert_called_once()

    def test_atencion_automatica_false_ignores_message(self):
        """Test that message is ignored when atencion_automatica=false."""
        client = TestClient(app)

        payload = {
            "event": "message_created",
            "id": 12345,
            "content": "Hello, I need an appointment",
            "conversation": {
                "id": 100,
                "inbox_id": 1,
                "messages": [
                    {
                        "id": 12345,
                        "content": "Hello, I need an appointment",
                        "message_type": 0,
                        "created_at": 1730000000,
                        "conversation_id": 100,
                    }
                ],
                "custom_attributes": {"atencion_automatica": False},
            },
            "sender": {"phone_number": "612345678", "name": "María García"},
            "created_at": "2025-10-27T10:00:00Z",
        }

        body = json.dumps(payload).encode()

        from shared.config import get_settings
        settings = get_settings()
        token = settings.CHATWOOT_WEBHOOK_TOKEN

        with patch("api.routes.chatwoot.publish_to_channel") as mock_publish:
            response = client.post(
                f"/webhook/chatwoot/{token}",
                content=body,
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 200
            assert response.json()["status"] == "ignored_auto_attention_disabled"
            # Message should NOT be published to Redis
            mock_publish.assert_not_called()

    def test_atencion_automatica_undefined_sets_and_processes(self):
        """Test that atencion_automatica is set to true and message is processed when attribute is missing."""
        client = TestClient(app)

        payload = {
            "event": "message_created",
            "id": 12345,
            "content": "Hello, I need an appointment",
            "conversation": {
                "id": 100,
                "inbox_id": 1,
                "messages": [
                    {
                        "id": 12345,
                        "content": "Hello, I need an appointment",
                        "message_type": 0,
                        "created_at": 1730000000,
                        "conversation_id": 100,
                    }
                ],
                "custom_attributes": {},  # Empty - no atencion_automatica
            },
            "sender": {"phone_number": "612345678", "name": "María García"},
            "created_at": "2025-10-27T10:00:00Z",
        }

        body = json.dumps(payload).encode()

        from shared.config import get_settings
        settings = get_settings()
        token = settings.CHATWOOT_WEBHOOK_TOKEN

        with patch("api.routes.chatwoot.publish_to_channel") as mock_publish:
            with patch("api.routes.chatwoot.ChatwootClient") as mock_chatwoot_class:
                mock_chatwoot = AsyncMock()
                mock_chatwoot.update_conversation_attributes = AsyncMock(return_value=True)
                mock_chatwoot_class.return_value = mock_chatwoot
                mock_publish.return_value = AsyncMock()

                response = client.post(
                    f"/webhook/chatwoot/{token}",
                    content=body,
                    headers={"Content-Type": "application/json"},
                )

                assert response.status_code == 200
                assert response.json()["status"] == "received"

                # Should update conversation attributes
                mock_chatwoot.update_conversation_attributes.assert_called_once_with(
                    conversation_id=100,
                    attributes={"atencion_automatica": True}
                )

                # Message should be published to Redis
                mock_publish.assert_called_once()


class TestRateLimiting:
    """Integration tests for rate limiting middleware."""

    def test_rate_limit_allows_10_requests(self):
        """Test that 10 requests per minute are allowed."""
        client = TestClient(app)

        # Mock Redis to track request counts
        request_counts: dict[str, int] = {}

        async def mock_incr(key):
            request_counts[key] = request_counts.get(key, 0) + 1
            return request_counts[key]

        async def mock_expire(key, ttl):
            pass

        with patch("api.middleware.rate_limiting.get_redis_client") as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.incr = mock_incr
            mock_redis.expire = mock_expire
            mock_get_redis.return_value = mock_redis

            # Send 10 requests - all should pass
            for i in range(10):
                response = client.get("/health")
                assert response.status_code in [200, 503]  # Health check may fail but not rate limited
                if i < 10:
                    assert "X-RateLimit-Remaining" in response.headers

    def test_rate_limit_blocks_11th_request(self):
        """Test that the 11th request is blocked with 429."""
        # Mock Redis to simulate rate limit
        request_count = [0]

        async def mock_incr(key):
            request_count[0] += 1
            return request_count[0]

        async def mock_expire(key, ttl):
            pass

        with patch("api.middleware.rate_limiting.get_redis_client") as mock_get_redis:
            with patch("shared.redis_client.get_redis_client") as mock_get_redis_health:
                mock_redis = AsyncMock()
                mock_redis.incr = mock_incr
                mock_redis.expire = mock_expire
                mock_redis.ping = AsyncMock(return_value=True)
                mock_get_redis.return_value = mock_redis
                mock_get_redis_health.return_value = mock_redis

                client = TestClient(app)

                # Send 11 requests
                for i in range(11):
                    response = client.get("/health")

                    if i < 10:
                        assert response.status_code in [200, 503]  # Not rate limited
                    else:
                        assert response.status_code == 429  # 11th request blocked
                        assert response.json()["error"] == "Rate limit exceeded"


class TestHealthCheck:
    """Integration tests for health check endpoint."""

    def test_health_check_returns_status(self):
        """Test that health check endpoint returns status."""
        # Mock Redis and PostgreSQL checks
        with patch("shared.redis_client.get_redis_client") as mock_redis:
            with patch("database.connection.get_async_session") as mock_db:
                with patch("api.middleware.rate_limiting.get_redis_client") as mock_redis_rate:
                    mock_redis_client = AsyncMock()
                    mock_redis_client.ping = AsyncMock()
                    mock_redis_client.incr = AsyncMock(return_value=1)
                    mock_redis_client.expire = AsyncMock()
                    mock_redis.return_value = mock_redis_client
                    mock_redis_rate.return_value = mock_redis_client

                    # Mock async generator for DB session
                    async def mock_session_generator():
                        mock_session = AsyncMock()
                        mock_session.execute = AsyncMock()
                        yield mock_session

                    mock_db.return_value = mock_session_generator()

                    client = TestClient(app)
                    response = client.get("/health")

                    assert response.status_code in [200, 503]
                    data = response.json()
                    assert "status" in data
                    assert "redis" in data
                    assert "postgres" in data

"""Unit tests for Redis client singleton."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from redis import ConnectionError as RedisConnectionError

from shared.redis_client import get_redis_client, publish_to_channel


class TestRedisClient:
    """Tests for Redis client singleton."""

    def test_get_redis_client_returns_instance(self):
        """Test that get_redis_client returns a Redis instance."""
        with patch("shared.redis_client.redis.from_url") as mock_from_url:
            mock_client = MagicMock()
            mock_from_url.return_value = mock_client

            # Clear lru_cache before test
            get_redis_client.cache_clear()

            result = get_redis_client()

            assert result == mock_client
            mock_from_url.assert_called_once()

    def test_get_redis_client_is_singleton(self):
        """Test that get_redis_client returns the same instance (cached)."""
        with patch("shared.redis_client.redis.from_url") as mock_from_url:
            mock_client = MagicMock()
            mock_from_url.return_value = mock_client

            # Clear lru_cache before test
            get_redis_client.cache_clear()

            # Call twice
            result1 = get_redis_client()
            result2 = get_redis_client()

            # Should be the same instance
            assert result1 is result2
            # Should only call from_url once (cached)
            assert mock_from_url.call_count == 1

    def test_redis_client_configured_with_pool(self):
        """Test that Redis client is configured with connection pool."""
        with patch("shared.redis_client.redis.from_url") as mock_from_url:
            with patch("shared.redis_client.get_settings") as mock_settings:
                mock_settings.return_value.REDIS_URL = "redis://test:6379/0"

                get_redis_client.cache_clear()
                get_redis_client()

                mock_from_url.assert_called_once_with(
                    "redis://test:6379/0", max_connections=10, decode_responses=True
                )


class TestPublishToChannel:
    """Tests for publish_to_channel function."""

    @pytest.mark.asyncio
    async def test_publish_message_successfully(self):
        """Test that messages are published to Redis channel successfully."""
        mock_client = AsyncMock()
        mock_client.publish = AsyncMock(return_value=1)  # 1 subscriber received

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            message = {"conversation_id": "123", "text": "Hello"}

            await publish_to_channel("incoming_messages", message)

            mock_client.publish.assert_called_once()
            call_args = mock_client.publish.call_args
            assert call_args[0][0] == "incoming_messages"
            assert json.loads(call_args[0][1]) == message

    @pytest.mark.asyncio
    async def test_message_is_json_serialized(self):
        """Test that message dict is properly JSON serialized."""
        mock_client = AsyncMock()
        mock_client.publish = AsyncMock(return_value=1)

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            message = {
                "conversation_id": "123",
                "customer_phone": "+34612345678",
                "message_text": "Hello",
            }

            await publish_to_channel("incoming_messages", message)

            # Verify JSON serialization
            call_args = mock_client.publish.call_args
            published_message = call_args[0][1]
            assert isinstance(published_message, str)  # JSON string
            assert json.loads(published_message) == message

    @pytest.mark.asyncio
    async def test_redis_connection_error_raises_503(self):
        """Test that Redis connection errors raise HTTPException 503."""
        mock_client = AsyncMock()
        mock_client.publish = AsyncMock(
            side_effect=RedisConnectionError("Connection refused")
        )

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            message = {"conversation_id": "123", "text": "Hello"}

            with pytest.raises(HTTPException) as exc_info:
                await publish_to_channel("incoming_messages", message)

            assert exc_info.value.status_code == 503
            assert "Redis connection failed" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_unexpected_error_raises_503(self):
        """Test that unexpected errors raise HTTPException 503."""
        mock_client = AsyncMock()
        mock_client.publish = AsyncMock(side_effect=Exception("Unexpected error"))

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            message = {"conversation_id": "123", "text": "Hello"}

            with pytest.raises(HTTPException) as exc_info:
                await publish_to_channel("incoming_messages", message)

            assert exc_info.value.status_code == 503
            assert "temporarily unavailable" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_multiple_channels_work(self):
        """Test that publishing to different channels works correctly."""
        mock_client = AsyncMock()
        mock_client.publish = AsyncMock(return_value=1)

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            await publish_to_channel(
                "incoming_messages", {"conversation_id": "123", "text": "Hello"}
            )
            await publish_to_channel(
                "payment_events",
                {"appointment_id": "456", "event_type": "checkout.session.completed"},
            )

            # Should have called publish twice with different channels
            assert mock_client.publish.call_count == 2
            calls = mock_client.publish.call_args_list
            assert calls[0][0][0] == "incoming_messages"
            assert calls[1][0][0] == "payment_events"

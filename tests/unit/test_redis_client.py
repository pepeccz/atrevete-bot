"""Unit tests for Redis client singleton."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from redis import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError as RedisResponseError

from shared.redis_client import (
    get_redis_client,
    publish_to_channel,
    add_to_stream,
    create_consumer_group,
    read_from_stream,
    acknowledge_message,
    move_to_dead_letter,
    INCOMING_STREAM,
    CONSUMER_GROUP,
    DEAD_LETTER_STREAM,
)


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
                    "redis://test:6379/0",
                    max_connections=20,
                    decode_responses=True,
                    retry_on_timeout=True,
                    health_check_interval=30,
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


# =============================================================================
# Redis Streams Tests
# =============================================================================


class TestAddToStream:
    """Tests for add_to_stream function."""

    @pytest.mark.asyncio
    async def test_add_message_successfully(self):
        """Test that messages are added to stream successfully."""
        mock_client = AsyncMock()
        mock_client.xadd = AsyncMock(return_value="1234567890123-0")

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            message = {"conversation_id": "123", "text": "Hello"}

            result = await add_to_stream(INCOMING_STREAM, message)

            assert result == "1234567890123-0"
            mock_client.xadd.assert_called_once()
            call_args = mock_client.xadd.call_args
            assert call_args[0][0] == INCOMING_STREAM
            assert "data" in call_args[0][1]
            assert json.loads(call_args[0][1]["data"]) == message

    @pytest.mark.asyncio
    async def test_add_message_with_maxlen(self):
        """Test that XADD uses approximate maxlen for trimming."""
        mock_client = AsyncMock()
        mock_client.xadd = AsyncMock(return_value="1234567890123-0")

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            message = {"conversation_id": "123"}

            await add_to_stream(INCOMING_STREAM, message, max_len=5000)

            mock_client.xadd.assert_called_once()
            call_kwargs = mock_client.xadd.call_args[1]
            assert call_kwargs["maxlen"] == 5000
            assert call_kwargs["approximate"] is True

    @pytest.mark.asyncio
    async def test_add_message_redis_error_raises_503(self):
        """Test that Redis connection errors raise HTTPException 503."""
        mock_client = AsyncMock()
        mock_client.xadd = AsyncMock(
            side_effect=RedisConnectionError("Connection refused")
        )

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            message = {"conversation_id": "123"}

            with pytest.raises(HTTPException) as exc_info:
                await add_to_stream(INCOMING_STREAM, message)

            assert exc_info.value.status_code == 503
            assert "Redis connection failed" in exc_info.value.detail


class TestCreateConsumerGroup:
    """Tests for create_consumer_group function."""

    @pytest.mark.asyncio
    async def test_create_group_successfully(self):
        """Test that consumer group is created successfully."""
        mock_client = AsyncMock()
        mock_client.xgroup_create = AsyncMock(return_value=True)

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            result = await create_consumer_group(INCOMING_STREAM, CONSUMER_GROUP)

            assert result is True
            mock_client.xgroup_create.assert_called_once_with(
                INCOMING_STREAM, CONSUMER_GROUP, id="0", mkstream=True
            )

    @pytest.mark.asyncio
    async def test_create_group_already_exists(self):
        """Test that existing group returns False without error."""
        mock_client = AsyncMock()
        mock_client.xgroup_create = AsyncMock(
            side_effect=RedisResponseError("BUSYGROUP Consumer Group name already exists")
        )

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            result = await create_consumer_group(INCOMING_STREAM, CONSUMER_GROUP)

            assert result is False

    @pytest.mark.asyncio
    async def test_create_group_connection_error_raises_503(self):
        """Test that connection errors raise HTTPException 503."""
        mock_client = AsyncMock()
        mock_client.xgroup_create = AsyncMock(
            side_effect=RedisConnectionError("Connection refused")
        )

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await create_consumer_group(INCOMING_STREAM, CONSUMER_GROUP)

            assert exc_info.value.status_code == 503


class TestReadFromStream:
    """Tests for read_from_stream function."""

    @pytest.mark.asyncio
    async def test_read_messages_successfully(self):
        """Test that messages are read from stream successfully."""
        mock_client = AsyncMock()
        # Simulate XREADGROUP response format
        mock_client.xreadgroup = AsyncMock(return_value=[
            (INCOMING_STREAM, [
                ("1234567890123-0", {"data": '{"conversation_id": "123", "text": "Hello"}'}),
                ("1234567890123-1", {"data": '{"conversation_id": "456", "text": "World"}'}),
            ])
        ])

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            result = await read_from_stream(
                INCOMING_STREAM, CONSUMER_GROUP, "consumer-1", count=10, block_ms=5000
            )

            assert len(result) == 2
            assert result[0][0] == "1234567890123-0"
            assert result[0][1]["conversation_id"] == "123"
            assert result[1][0] == "1234567890123-1"
            assert result[1][1]["conversation_id"] == "456"

    @pytest.mark.asyncio
    async def test_read_no_messages_returns_empty(self):
        """Test that empty stream returns empty list."""
        mock_client = AsyncMock()
        mock_client.xreadgroup = AsyncMock(return_value=None)

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            result = await read_from_stream(
                INCOMING_STREAM, CONSUMER_GROUP, "consumer-1"
            )

            assert result == []

    @pytest.mark.asyncio
    async def test_read_nogroup_returns_empty(self):
        """Test that NOGROUP error returns empty list (group doesn't exist yet)."""
        mock_client = AsyncMock()
        mock_client.xreadgroup = AsyncMock(
            side_effect=RedisResponseError("NOGROUP No such key or consumer group")
        )

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            result = await read_from_stream(
                INCOMING_STREAM, CONSUMER_GROUP, "consumer-1"
            )

            assert result == []

    @pytest.mark.asyncio
    async def test_read_connection_error_raises_503(self):
        """Test that connection errors raise HTTPException 503."""
        mock_client = AsyncMock()
        mock_client.xreadgroup = AsyncMock(
            side_effect=RedisConnectionError("Connection refused")
        )

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await read_from_stream(INCOMING_STREAM, CONSUMER_GROUP, "consumer-1")

            assert exc_info.value.status_code == 503


class TestAcknowledgeMessage:
    """Tests for acknowledge_message function."""

    @pytest.mark.asyncio
    async def test_acknowledge_successfully(self):
        """Test that message is acknowledged successfully."""
        mock_client = AsyncMock()
        mock_client.xack = AsyncMock(return_value=1)

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            result = await acknowledge_message(
                INCOMING_STREAM, CONSUMER_GROUP, "1234567890123-0"
            )

            assert result == 1
            mock_client.xack.assert_called_once_with(
                INCOMING_STREAM, CONSUMER_GROUP, "1234567890123-0"
            )

    @pytest.mark.asyncio
    async def test_acknowledge_already_acked_returns_0(self):
        """Test that already acknowledged message returns 0."""
        mock_client = AsyncMock()
        mock_client.xack = AsyncMock(return_value=0)

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            result = await acknowledge_message(
                INCOMING_STREAM, CONSUMER_GROUP, "1234567890123-0"
            )

            assert result == 0

    @pytest.mark.asyncio
    async def test_acknowledge_connection_error_raises_503(self):
        """Test that connection errors raise HTTPException 503."""
        mock_client = AsyncMock()
        mock_client.xack = AsyncMock(
            side_effect=RedisConnectionError("Connection refused")
        )

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await acknowledge_message(
                    INCOMING_STREAM, CONSUMER_GROUP, "1234567890123-0"
                )

            assert exc_info.value.status_code == 503


class TestMoveToDeadLetter:
    """Tests for move_to_dead_letter function."""

    @pytest.mark.asyncio
    async def test_move_to_dlq_successfully(self):
        """Test that failed message is moved to DLQ successfully."""
        mock_client = AsyncMock()
        mock_client.xadd = AsyncMock(return_value="dlq-1234567890123-0")
        mock_client.xack = AsyncMock(return_value=1)

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            message_data = {"conversation_id": "123", "text": "Hello"}

            result = await move_to_dead_letter(
                INCOMING_STREAM,
                CONSUMER_GROUP,
                "1234567890123-0",
                message_data,
                "Processing error: timeout"
            )

            assert result == "dlq-1234567890123-0"

            # Verify XADD to DLQ was called
            xadd_call = mock_client.xadd.call_args
            assert xadd_call[0][0] == DEAD_LETTER_STREAM
            dlq_data = xadd_call[0][1]
            assert dlq_data["original_stream"] == INCOMING_STREAM
            assert dlq_data["original_id"] == "1234567890123-0"
            assert "Processing error" in dlq_data["error"]

            # Verify XACK was called to remove from pending
            mock_client.xack.assert_called_once_with(
                INCOMING_STREAM, CONSUMER_GROUP, "1234567890123-0"
            )

    @pytest.mark.asyncio
    async def test_move_to_dlq_truncates_long_errors(self):
        """Test that very long error messages are truncated."""
        mock_client = AsyncMock()
        mock_client.xadd = AsyncMock(return_value="dlq-1234567890123-0")
        mock_client.xack = AsyncMock(return_value=1)

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            long_error = "x" * 2000  # Error longer than 1000 char limit

            await move_to_dead_letter(
                INCOMING_STREAM,
                CONSUMER_GROUP,
                "1234567890123-0",
                {"conversation_id": "123"},
                long_error
            )

            xadd_call = mock_client.xadd.call_args
            dlq_data = xadd_call[0][1]
            assert len(dlq_data["error"]) <= 1000

    @pytest.mark.asyncio
    async def test_move_to_dlq_connection_error_raises_503(self):
        """Test that connection errors raise HTTPException 503."""
        mock_client = AsyncMock()
        mock_client.xadd = AsyncMock(
            side_effect=RedisConnectionError("Connection refused")
        )

        with patch("shared.redis_client.get_redis_client", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await move_to_dead_letter(
                    INCOMING_STREAM,
                    CONSUMER_GROUP,
                    "1234567890123-0",
                    {"conversation_id": "123"},
                    "Error"
                )

            assert exc_info.value.status_code == 503


# =============================================================================
# Webhook Idempotency Tests
# =============================================================================


class TestIdempotency:
    """Tests for webhook idempotency function."""

    @pytest.mark.asyncio
    async def test_new_message_returns_false(self):
        """Test that new messages are not flagged as duplicates."""
        mock_client = AsyncMock()
        mock_client.setnx = AsyncMock(return_value=True)  # Key was set (new)
        mock_client.expire = AsyncMock(return_value=True)

        with patch("api.routes.chatwoot.get_redis_client", return_value=mock_client):
            from api.routes.chatwoot import check_and_set_idempotency

            result = await check_and_set_idempotency(12345)

            assert result is False  # Not a duplicate
            mock_client.setnx.assert_called_once_with("idempotency:chatwoot:12345", "1")
            mock_client.expire.assert_called_once_with("idempotency:chatwoot:12345", 300)

    @pytest.mark.asyncio
    async def test_duplicate_message_returns_true(self):
        """Test that duplicate messages are correctly identified."""
        mock_client = AsyncMock()
        mock_client.setnx = AsyncMock(return_value=False)  # Key already exists (duplicate)

        with patch("api.routes.chatwoot.get_redis_client", return_value=mock_client):
            from api.routes.chatwoot import check_and_set_idempotency

            result = await check_and_set_idempotency(12345)

            assert result is True  # Is a duplicate
            mock_client.setnx.assert_called_once()
            # expire should NOT be called for duplicates
            mock_client.expire.assert_not_called()

    @pytest.mark.asyncio
    async def test_idempotency_key_format(self):
        """Test that idempotency key has correct format."""
        mock_client = AsyncMock()
        mock_client.setnx = AsyncMock(return_value=True)
        mock_client.expire = AsyncMock(return_value=True)

        with patch("api.routes.chatwoot.get_redis_client", return_value=mock_client):
            from api.routes.chatwoot import check_and_set_idempotency

            await check_and_set_idempotency(99999)

            # Verify key format includes prefix and message ID
            call_args = mock_client.setnx.call_args
            assert call_args[0][0] == "idempotency:chatwoot:99999"

    @pytest.mark.asyncio
    async def test_idempotency_ttl_is_5_minutes(self):
        """Test that idempotency TTL is 300 seconds (5 minutes)."""
        mock_client = AsyncMock()
        mock_client.setnx = AsyncMock(return_value=True)
        mock_client.expire = AsyncMock(return_value=True)

        with patch("api.routes.chatwoot.get_redis_client", return_value=mock_client):
            from api.routes.chatwoot import check_and_set_idempotency

            await check_and_set_idempotency(12345)

            # Verify TTL is 300 seconds
            expire_call = mock_client.expire.call_args
            assert expire_call[0][1] == 300

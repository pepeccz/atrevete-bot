"""Unit tests for shared/cache_signals.py — publish_cache_invalidation()."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.cache_signals import CACHE_INVALIDATE_CHANNEL, publish_cache_invalidation


class TestPublishCacheInvalidation:
    """Tests for publish_cache_invalidation()."""

    @pytest.mark.asyncio
    async def test_publishes_to_correct_channel_with_valid_payload(self):
        """publish_cache_invalidation() calls redis.publish on the correct channel
        with a JSON payload containing entity, action, and timestamp."""
        mock_redis = AsyncMock()

        with patch("shared.cache_signals.get_redis_client", return_value=mock_redis):
            await publish_cache_invalidation("stylists", "update")

        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args

        # Verify channel
        channel = call_args[0][0]
        assert channel == CACHE_INVALIDATE_CHANNEL

        # Verify payload is valid JSON with required fields
        raw_payload = call_args[0][1]
        payload = json.loads(raw_payload)
        assert payload["entity"] == "stylists"
        assert payload["action"] == "update"
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_default_action_is_update(self):
        """publish_cache_invalidation() defaults action to 'update' when not provided."""
        mock_redis = AsyncMock()

        with patch("shared.cache_signals.get_redis_client", return_value=mock_redis):
            await publish_cache_invalidation("stylists")

        call_args = mock_redis.publish.call_args
        payload = json.loads(call_args[0][1])
        assert payload["action"] == "update"

    @pytest.mark.asyncio
    async def test_create_action_is_published_correctly(self):
        """publish_cache_invalidation() correctly publishes 'create' action."""
        mock_redis = AsyncMock()

        with patch("shared.cache_signals.get_redis_client", return_value=mock_redis):
            await publish_cache_invalidation("stylists", "create")

        call_args = mock_redis.publish.call_args
        payload = json.loads(call_args[0][1])
        assert payload["entity"] == "stylists"
        assert payload["action"] == "create"

    @pytest.mark.asyncio
    async def test_delete_action_is_published_correctly(self):
        """publish_cache_invalidation() correctly publishes 'delete' action."""
        mock_redis = AsyncMock()

        with patch("shared.cache_signals.get_redis_client", return_value=mock_redis):
            await publish_cache_invalidation("stylists", "delete")

        call_args = mock_redis.publish.call_args
        payload = json.loads(call_args[0][1])
        assert payload["entity"] == "stylists"
        assert payload["action"] == "delete"

    @pytest.mark.asyncio
    async def test_fail_open_when_redis_raises(self):
        """publish_cache_invalidation() does NOT raise when Redis throws — fail-open."""
        mock_redis = AsyncMock()
        mock_redis.publish.side_effect = ConnectionError("Redis unavailable")

        with patch("shared.cache_signals.get_redis_client", return_value=mock_redis):
            # Must NOT raise — fail-open contract
            await publish_cache_invalidation("stylists", "update")

        # Verify publish was attempted
        mock_redis.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_fail_open_when_get_redis_client_raises(self):
        """publish_cache_invalidation() does NOT raise when get_redis_client() fails."""
        with patch(
            "shared.cache_signals.get_redis_client",
            side_effect=RuntimeError("Cannot connect to Redis"),
        ):
            # Must NOT raise — fail-open contract
            await publish_cache_invalidation("stylists", "create")

    @pytest.mark.asyncio
    async def test_fail_open_when_generic_exception_raised(self):
        """publish_cache_invalidation() does NOT raise for any exception type."""
        mock_redis = AsyncMock()
        mock_redis.publish.side_effect = Exception("Unexpected error")

        with patch("shared.cache_signals.get_redis_client", return_value=mock_redis):
            # Must NOT raise — fail-open contract
            await publish_cache_invalidation("stylists", "update")

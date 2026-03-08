"""Unit tests for agent/workers/cache_signal_listener.py."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from agent.workers.cache_signal_listener import (
    CACHE_INVALIDATE_CHANNEL,
    run_cache_signal_listener,
)


def _make_message(data: str, msg_type: str = "message") -> dict:
    """Helper to build a raw pub/sub message dict."""
    return {"type": msg_type, "data": data, "channel": CACHE_INVALIDATE_CHANNEL}


class TestRunCacheSignalListener:
    """Tests for run_cache_signal_listener()."""

    @pytest.mark.asyncio
    async def test_clears_both_caches_on_valid_message(self):
        """On a valid cache:invalidate message, both clear functions are called."""
        payload = json.dumps({"entity": "stylists", "action": "update", "timestamp": "2025-12-09T10:00:00+00:00"})

        # Build a mock pubsub that yields one message then raises CancelledError
        # to break the infinite loop
        async def _listen():
            yield _make_message(payload)
            raise asyncio.CancelledError

        mock_pubsub = AsyncMock()
        mock_pubsub.listen = _listen
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub

        with (
            patch("agent.workers.cache_signal_listener.get_redis_client", return_value=mock_redis),
            patch("agent.workers.cache_signal_listener.clear_stylist_context_cache") as mock_stylist_clear,
            patch("agent.workers.cache_signal_listener.clear_dynamic_context_cache") as mock_dynamic_clear,
        ):
            await run_cache_signal_listener()

        mock_stylist_clear.assert_called_once()
        mock_dynamic_clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_non_message_type(self):
        """Control messages (type != 'message') are silently skipped."""
        payload = json.dumps({"entity": "stylists", "action": "update", "timestamp": "2025-12-09T10:00:00+00:00"})

        async def _listen():
            yield _make_message("1", msg_type="subscribe")  # skip this
            yield _make_message(payload)                     # process this
            raise asyncio.CancelledError

        mock_pubsub = AsyncMock()
        mock_pubsub.listen = _listen
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub

        with (
            patch("agent.workers.cache_signal_listener.get_redis_client", return_value=mock_redis),
            patch("agent.workers.cache_signal_listener.clear_stylist_context_cache") as mock_stylist_clear,
            patch("agent.workers.cache_signal_listener.clear_dynamic_context_cache") as mock_dynamic_clear,
        ):
            await run_cache_signal_listener()

        # Only called once (for the actual message, not the subscribe confirmation)
        mock_stylist_clear.assert_called_once()
        mock_dynamic_clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_malformed_json_is_ignored(self):
        """A message with malformed JSON does not crash the listener."""
        async def _listen():
            yield _make_message("NOT VALID JSON {{{")  # malformed
            raise asyncio.CancelledError

        mock_pubsub = AsyncMock()
        mock_pubsub.listen = _listen
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub

        with (
            patch("agent.workers.cache_signal_listener.get_redis_client", return_value=mock_redis),
            patch("agent.workers.cache_signal_listener.clear_stylist_context_cache") as mock_stylist_clear,
            patch("agent.workers.cache_signal_listener.clear_dynamic_context_cache") as mock_dynamic_clear,
        ):
            # Must NOT raise
            await run_cache_signal_listener()

        # Clear functions must NOT be called for malformed JSON
        mock_stylist_clear.assert_not_called()
        mock_dynamic_clear.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancelled_error_causes_clean_shutdown(self):
        """CancelledError immediately unsubscribes and closes pubsub without re-raising."""
        async def _listen():
            raise asyncio.CancelledError
            yield  # makes this an async generator

        mock_pubsub = AsyncMock()
        mock_pubsub.listen = _listen
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub

        with patch("agent.workers.cache_signal_listener.get_redis_client", return_value=mock_redis):
            # run_cache_signal_listener catches CancelledError and returns cleanly
            await run_cache_signal_listener()

        mock_pubsub.unsubscribe.assert_called_once_with(CACHE_INVALIDATE_CHANNEL)
        mock_pubsub.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscribe_is_called_with_correct_channel(self):
        """The listener subscribes to the CACHE_INVALIDATE_CHANNEL constant."""
        async def _listen():
            raise asyncio.CancelledError
            yield  # makes this an async generator

        mock_pubsub = AsyncMock()
        mock_pubsub.listen = _listen
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub

        with patch("agent.workers.cache_signal_listener.get_redis_client", return_value=mock_redis):
            await run_cache_signal_listener()

        mock_pubsub.subscribe.assert_called_once_with(CACHE_INVALIDATE_CHANNEL)

"""
Unit tests for TASK-3: Store factory and initialization in agent/state/checkpointer.py.

6 tests:
- test_get_redis_store_returns_async_redis_store
- test_get_redis_store_uses_settings_redis_url
- test_get_redis_store_dedicated_client_decode_responses_true
- test_initialize_redis_store_calls_setup
- test_initialize_redis_store_idempotent
- test_initialize_redis_store_raises_on_failure
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGetRedisStore:
    """Tests for get_redis_store() factory function."""

    async def test_get_redis_store_returns_async_redis_store(self):
        """get_redis_store() must return an AsyncRedisStore instance."""
        from langgraph.store.redis import AsyncRedisStore

        mock_settings = MagicMock()
        mock_settings.REDIS_URL = "redis://localhost:6379/0"
        mock_settings.REDIS_PASSWORD = ""

        with (
            patch("agent.state.checkpointer.get_settings", return_value=mock_settings),
            patch("agent.state.checkpointer.Redis") as mock_redis_cls,
        ):
            mock_redis_cls.from_url.return_value = MagicMock()

            from agent.state.checkpointer import get_redis_store

            store = get_redis_store()

        assert isinstance(store, AsyncRedisStore)

    async def test_get_redis_store_uses_settings_redis_url(self):
        """get_redis_store() reads REDIS_URL from settings, NEVER os.getenv()."""
        mock_settings = MagicMock()
        mock_settings.REDIS_URL = "redis://testhost:6380/1"
        mock_settings.REDIS_PASSWORD = ""

        with (
            patch("agent.state.checkpointer.get_settings", return_value=mock_settings),
            patch("agent.state.checkpointer.Redis") as mock_redis_cls,
        ):
            mock_redis_cls.from_url.return_value = MagicMock()

            from agent.state.checkpointer import get_redis_store

            get_redis_store()

        # Verify settings.REDIS_URL was used, not os.getenv
        mock_redis_cls.from_url.assert_called_once()
        call_args = mock_redis_cls.from_url.call_args
        assert call_args[0][0] == "redis://testhost:6380/1"

    async def test_get_redis_store_dedicated_client_decode_responses_true(self):
        """Store client must use decode_responses=True (separate from checkpointer's False)."""
        mock_settings = MagicMock()
        mock_settings.REDIS_URL = "redis://localhost:6379/0"
        mock_settings.REDIS_PASSWORD = ""

        with (
            patch("agent.state.checkpointer.get_settings", return_value=mock_settings),
            patch("agent.state.checkpointer.Redis") as mock_redis_cls,
        ):
            mock_redis_cls.from_url.return_value = MagicMock()

            from agent.state.checkpointer import get_redis_store

            get_redis_store()

        call_kwargs = mock_redis_cls.from_url.call_args[1]
        assert call_kwargs.get("decode_responses") is True


class TestInitializeRedisStore:
    """Tests for initialize_redis_store() async function."""

    async def test_initialize_redis_store_calls_setup(self):
        """initialize_redis_store() must await store.setup() exactly once."""
        # Reset global flag before test
        import agent.state.checkpointer as ckpt_module
        original_flag = ckpt_module._redis_store_initialized
        ckpt_module._redis_store_initialized = False

        try:
            mock_store = AsyncMock()
            mock_store.setup = AsyncMock()

            from agent.state.checkpointer import initialize_redis_store
            await initialize_redis_store(mock_store)

            mock_store.setup.assert_awaited_once()
        finally:
            ckpt_module._redis_store_initialized = original_flag

    async def test_initialize_redis_store_idempotent(self):
        """Calling initialize_redis_store() twice only calls store.setup() once."""
        import agent.state.checkpointer as ckpt_module
        original_flag = ckpt_module._redis_store_initialized
        ckpt_module._redis_store_initialized = False

        try:
            mock_store = AsyncMock()
            mock_store.setup = AsyncMock()

            from agent.state.checkpointer import initialize_redis_store
            await initialize_redis_store(mock_store)
            await initialize_redis_store(mock_store)

            # setup() must be called only ONCE despite 2 invocations
            assert mock_store.setup.await_count == 1
        finally:
            ckpt_module._redis_store_initialized = original_flag

    async def test_initialize_redis_store_raises_on_failure(self):
        """If store.setup() raises, the exception must propagate."""
        import agent.state.checkpointer as ckpt_module
        original_flag = ckpt_module._redis_store_initialized
        ckpt_module._redis_store_initialized = False

        try:
            mock_store = AsyncMock()
            mock_store.setup = AsyncMock(side_effect=RuntimeError("Redis setup failed"))

            from agent.state.checkpointer import initialize_redis_store
            with pytest.raises(RuntimeError, match="Redis setup failed"):
                await initialize_redis_store(mock_store)
        finally:
            ckpt_module._redis_store_initialized = original_flag

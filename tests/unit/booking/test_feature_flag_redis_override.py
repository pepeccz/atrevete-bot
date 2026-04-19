"""
Tests for Redis per-conversation feature flag override.

TDD RED: Tests reference agent.booking.feature_flags.resolve_capability_path
which does NOT exist yet.
Design refs: design §7
Task: T4.4

Acceptance:
- Redis key booking:flag:{conversation_id} = "1" or "on" → override flag ON
- Redis key absent → fall back to global settings flag
- Redis key = "0" or "off" → override flag OFF (emergency per-conv kill)
- source field: "redis-override" when Redis overrides, "global" when from settings
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REDIS_KEY_TEMPLATE = "booking:flag:{}"


def _mock_redis(value: str | None) -> AsyncMock:
    """Return a mock Redis client where get() returns the given value."""
    r = AsyncMock()
    r.get = AsyncMock(return_value=value)
    return r


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestResolveCapabilityPath:
    """Unit tests for resolve_capability_path() Redis override logic."""

    @pytest.mark.asyncio
    async def test_redis_on_value_one_overrides_global_false(self, monkeypatch):
        """Redis key='1' overrides global flag=False → returns (True, 'redis-override')."""
        monkeypatch.setenv("USE_CAPABILITY_BOOKING", "false")
        from shared.config import get_settings
        get_settings.cache_clear()

        redis = _mock_redis("1")
        with patch("agent.booking.feature_flags.get_redis_client", return_value=redis):
            from agent.booking.feature_flags import resolve_capability_path

            use_new, source = await resolve_capability_path("conv-123")

        assert use_new is True, "Redis key='1' should enable new path"
        assert source == "redis-override"

    @pytest.mark.asyncio
    async def test_redis_on_value_overrides_global_false(self, monkeypatch):
        """Redis key='on' overrides global flag=False → returns (True, 'redis-override')."""
        monkeypatch.setenv("USE_CAPABILITY_BOOKING", "false")
        from shared.config import get_settings
        get_settings.cache_clear()

        redis = _mock_redis("on")
        with patch("agent.booking.feature_flags.get_redis_client", return_value=redis):
            from agent.booking.feature_flags import resolve_capability_path

            use_new, source = await resolve_capability_path("conv-456")

        assert use_new is True, "Redis key='on' should enable new path"
        assert source == "redis-override"

    @pytest.mark.asyncio
    async def test_redis_off_value_overrides_global_true(self, monkeypatch):
        """Redis key='0' overrides global flag=True → returns (False, 'redis-override')."""
        monkeypatch.setenv("USE_CAPABILITY_BOOKING", "true")
        from shared.config import get_settings
        get_settings.cache_clear()

        redis = _mock_redis("0")
        with patch("agent.booking.feature_flags.get_redis_client", return_value=redis):
            from agent.booking.feature_flags import resolve_capability_path

            use_new, source = await resolve_capability_path("conv-789")

        assert use_new is False, "Redis key='0' should disable new path even if global=True"
        assert source == "redis-override"

    @pytest.mark.asyncio
    async def test_redis_absent_falls_back_to_global_true(self, monkeypatch):
        """When Redis key absent and global=True → returns (True, 'global')."""
        monkeypatch.setenv("USE_CAPABILITY_BOOKING", "true")
        from shared.config import get_settings
        get_settings.cache_clear()

        redis = _mock_redis(None)  # key not set
        with patch("agent.booking.feature_flags.get_redis_client", return_value=redis):
            from agent.booking.feature_flags import resolve_capability_path

            use_new, source = await resolve_capability_path("conv-000")

        assert use_new is True, "No Redis key + global=True → use new path"
        assert source == "global"

    @pytest.mark.asyncio
    async def test_redis_absent_falls_back_to_global_false(self, monkeypatch):
        """When Redis key absent and global=False → returns (False, 'global')."""
        monkeypatch.setenv("USE_CAPABILITY_BOOKING", "false")
        from shared.config import get_settings
        get_settings.cache_clear()

        redis = _mock_redis(None)  # key not set
        with patch("agent.booking.feature_flags.get_redis_client", return_value=redis):
            from agent.booking.feature_flags import resolve_capability_path

            use_new, source = await resolve_capability_path("conv-111")

        assert use_new is False, "No Redis key + global=False → use legacy path"
        assert source == "global"

    @pytest.mark.asyncio
    async def test_redis_error_falls_back_to_global(self, monkeypatch):
        """When Redis raises an exception, fall back to global flag (fail-open)."""
        monkeypatch.setenv("USE_CAPABILITY_BOOKING", "false")
        from shared.config import get_settings
        get_settings.cache_clear()

        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=Exception("Redis connection refused"))
        with patch("agent.booking.feature_flags.get_redis_client", return_value=redis):
            from agent.booking.feature_flags import resolve_capability_path

            use_new, source = await resolve_capability_path("conv-err")

        assert use_new is False, "Redis error → fall back to global=False"
        assert source == "global"

    @pytest.mark.asyncio
    async def test_redis_key_uses_correct_format(self, monkeypatch):
        """Redis key must be booking:flag:{conversation_id}."""
        monkeypatch.setenv("USE_CAPABILITY_BOOKING", "false")
        from shared.config import get_settings
        get_settings.cache_clear()

        redis = _mock_redis(None)
        with patch("agent.booking.feature_flags.get_redis_client", return_value=redis):
            from agent.booking.feature_flags import resolve_capability_path

            await resolve_capability_path("my-conv-id")

        redis.get.assert_called_once_with("booking:flag:my-conv-id")


class TestRedisKeyFormat:
    """Verify the Redis key constant used by the module."""

    def test_feature_flags_exports_redis_key_prefix(self):
        """Module must export BOOKING_FLAG_KEY_PREFIX for external use (e.g. admin panel)."""
        from agent.booking import feature_flags

        assert hasattr(feature_flags, "BOOKING_FLAG_KEY_PREFIX"), (
            "feature_flags must export BOOKING_FLAG_KEY_PREFIX for admin panel usage"
        )
        assert feature_flags.BOOKING_FLAG_KEY_PREFIX == "booking:flag:"

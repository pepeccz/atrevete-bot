"""Tests for agent.checkpointer — AsyncRedisSaver factory.

NOTE: AsyncRedisSaver.from_conn_string is an @asynccontextmanager.
      get_checkpointer() returns the context manager object itself;
      callers must use `async with get_checkpointer(url) as saver`.
      setup_checkpointer(saver) calls asetup() on an already-entered saver.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

from agent.checkpointer import get_checkpointer, setup_checkpointer

# ---------------------------------------------------------------------------
# Task 2.1 — get_checkpointer
# ---------------------------------------------------------------------------


def test_get_checkpointer_explicit_url():
    """get_checkpointer(url) returns an async context manager (the result of from_conn_string)."""
    url = "redis://localhost:6379/0"
    cm = get_checkpointer(url)
    # from_conn_string is @asynccontextmanager → yields an AsyncGenerator / _AsyncGeneratorContextManager
    # The important thing is it has __aenter__ / __aexit__
    assert hasattr(cm, "__aenter__")
    assert hasattr(cm, "__aexit__")


def test_get_checkpointer_uses_settings_when_no_url():
    """get_checkpointer() with no arg reads REDIS_URL from shared.config.get_settings()."""
    fake_settings = MagicMock()
    fake_settings.REDIS_URL = "redis://redis:6379/0"
    fake_settings.REDIS_PASSWORD = ""

    with patch("shared.checkpointer.get_settings", return_value=fake_settings):
        cm = get_checkpointer()

    # Should have returned a context manager
    assert hasattr(cm, "__aenter__")


def test_get_checkpointer_passes_url_to_from_conn_string():
    """get_checkpointer(url) calls AsyncRedisSaver.from_conn_string with that url (no password configured)."""
    url = "redis://custom:6380/1"
    fake_settings = MagicMock()
    fake_settings.REDIS_PASSWORD = ""
    with (
        patch("shared.checkpointer.get_settings", return_value=fake_settings),
        patch.object(AsyncRedisSaver, "from_conn_string") as mock_fcs,
    ):
        mock_fcs.return_value = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
        get_checkpointer(url)
        mock_fcs.assert_called_once_with(url)


def test_get_checkpointer_injects_password_into_url():
    """When REDIS_PASSWORD is set and URL has no auth, password is injected into netloc."""
    fake_settings = MagicMock()
    fake_settings.REDIS_PASSWORD = "s3cret"
    with (
        patch("shared.checkpointer.get_settings", return_value=fake_settings),
        patch.object(AsyncRedisSaver, "from_conn_string") as mock_fcs,
    ):
        mock_fcs.return_value = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
        get_checkpointer("redis://custom:6380/1")
        mock_fcs.assert_called_once_with("redis://:s3cret@custom:6380/1")


def test_get_checkpointer_passes_settings_url_to_from_conn_string():
    """get_checkpointer() passes settings.REDIS_URL to from_conn_string."""
    fake_settings = MagicMock()
    fake_settings.REDIS_URL = "redis://settings-host:6379/2"
    fake_settings.REDIS_PASSWORD = ""

    with (
        patch("shared.checkpointer.get_settings", return_value=fake_settings),
        patch.object(AsyncRedisSaver, "from_conn_string") as mock_fcs,
    ):
        mock_fcs.return_value = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
        get_checkpointer()
        mock_fcs.assert_called_once_with("redis://settings-host:6379/2")


# ---------------------------------------------------------------------------
# Task 2.2 — setup_checkpointer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_checkpointer_calls_asetup():
    """setup_checkpointer(saver) calls saver.asetup()."""
    mock_saver = AsyncMock(spec=AsyncRedisSaver)
    await setup_checkpointer(mock_saver)
    mock_saver.asetup.assert_called_once()


@pytest.mark.asyncio
async def test_setup_checkpointer_idempotent():
    """Calling setup_checkpointer twice does not raise."""
    mock_saver = AsyncMock(spec=AsyncRedisSaver)
    await setup_checkpointer(mock_saver)
    await setup_checkpointer(mock_saver)
    assert mock_saver.asetup.call_count == 2


@pytest.mark.asyncio
async def test_setup_checkpointer_with_real_redis_if_available():
    """
    Integration smoke: if Redis is up (docker-compose redis), enter the context manager,
    call asetup(), confirm no exception. Skips gracefully if Redis is not available.
    """
    import asyncio

    import redis.asyncio as aioredis

    url = "redis://localhost:6379/0"
    try:
        r = aioredis.from_url(url)
        await asyncio.wait_for(r.ping(), timeout=1.0)
        await r.aclose()
    except Exception:
        pytest.skip("Redis not available — skipping integration smoke")

    async with AsyncRedisSaver.from_conn_string(url) as saver:
        await setup_checkpointer(saver)  # must not raise

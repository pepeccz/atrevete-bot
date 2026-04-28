"""Shared AsyncRedisSaver factory.

Single source of truth for Redis checkpointer construction.
Used by both:
  - agent/main.py   (write path — checkpointing during graph.ainvoke)
  - api/services/checkpointer.py (read-only live endpoint)

Usage (write path — needs async context manager):
    from shared.checkpointer import get_checkpointer

    async with get_checkpointer() as saver:
        await saver.asetup()
        ...

Usage (read-only — single aget_tuple call, no setup needed):
    from shared.checkpointer import get_checkpointer

    async with get_checkpointer() as saver:
        result = await saver.aget_tuple(config)
"""

from contextlib import AbstractAsyncContextManager
from urllib.parse import quote, urlparse, urlunparse

from langgraph.checkpoint.redis.aio import AsyncRedisSaver

from shared.config import get_settings


def _inject_password(url: str, password: str | None) -> str:
    """Rewrite ``redis://host:port/db`` to ``redis://:pass@host:port/db`` when a
    password is configured and the URL does not already carry auth."""
    if not password:
        return url
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        return url
    netloc = f":{quote(password, safe='')}@{parsed.hostname or ''}"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def get_checkpointer(redis_url: str | None = None) -> AbstractAsyncContextManager[AsyncRedisSaver]:
    """Return async context manager that yields AsyncRedisSaver.

    Args:
        redis_url: Override URL. Defaults to ``settings.REDIS_URL``.

    Usage::

        async with get_checkpointer() as saver:
            await saver.asetup()   # only on write path
            result = await saver.aget_tuple(config)
    """
    settings = get_settings()
    url = redis_url or settings.REDIS_URL
    url = _inject_password(url, settings.REDIS_PASSWORD)
    return AsyncRedisSaver.from_conn_string(url)

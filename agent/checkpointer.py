"""AsyncRedisSaver factory — MVP v7. AsyncRedisStore deferred post-MVP.

IMPORTANT: AsyncRedisSaver.from_conn_string is an @asynccontextmanager.
Callers must use it as:

    async with get_checkpointer(url) as saver:
        await setup_checkpointer(saver)
        graph = create_graph(checkpointer=saver)
        ...

setup_checkpointer() expects an already-entered saver instance.
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

    Usage:
        async with get_checkpointer() as saver:
            await setup_checkpointer(saver)
    """
    settings = get_settings()
    url = redis_url or settings.REDIS_URL
    url = _inject_password(url, settings.REDIS_PASSWORD)
    return AsyncRedisSaver.from_conn_string(url)


async def setup_checkpointer(saver: AsyncRedisSaver) -> None:
    """Idempotent index setup — safe to call on every boot.

    Must be called after entering the context manager returned by get_checkpointer().
    """
    await saver.asetup()

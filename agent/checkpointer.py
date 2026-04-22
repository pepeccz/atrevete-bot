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

from langgraph.checkpoint.redis.aio import AsyncRedisSaver

from shared.config import get_settings


def get_checkpointer(redis_url: str | None = None) -> AbstractAsyncContextManager[AsyncRedisSaver]:
    """Return async context manager that yields AsyncRedisSaver.

    Usage:
        async with get_checkpointer() as saver:
            await setup_checkpointer(saver)
    """
    url = redis_url or get_settings().REDIS_URL
    return AsyncRedisSaver.from_conn_string(url)


async def setup_checkpointer(saver: AsyncRedisSaver) -> None:
    """Idempotent index setup — safe to call on every boot.

    Must be called after entering the context manager returned by get_checkpointer().
    """
    await saver.asetup()

"""Read-only checkpointer accessor for the API process.

Thin wrapper over shared.checkpointer.get_checkpointer.
Used by the live conversation endpoint to read Redis checkpoints without
performing any write or index-setup operations.

Usage::

    from api.services.checkpointer import get_checkpointer

    async with get_checkpointer() as saver:
        tpl = await saver.aget_tuple({"configurable": {"thread_id": f"v2:{conv_id}"}})
"""

from contextlib import AbstractAsyncContextManager

from langgraph.checkpoint.redis.aio import AsyncRedisSaver

from shared.checkpointer import get_checkpointer as _shared_get_checkpointer


def get_checkpointer(redis_url: str | None = None) -> AbstractAsyncContextManager[AsyncRedisSaver]:
    """Return async context manager yielding AsyncRedisSaver (read-only usage).

    Args:
        redis_url: Override Redis URL. Defaults to settings.REDIS_URL.
    """
    return _shared_get_checkpointer(redis_url)

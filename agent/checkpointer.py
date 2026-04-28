"""AsyncRedisSaver factory — thin re-export from shared/checkpointer.py.

This module keeps backward compatibility for existing imports inside agent/.
New code should import directly from shared.checkpointer.

IMPORTANT: AsyncRedisSaver.from_conn_string is an @asynccontextmanager.
Callers must use it as:

    async with get_checkpointer(url) as saver:
        await setup_checkpointer(saver)
        graph = create_graph(checkpointer=saver)
        ...

setup_checkpointer() expects an already-entered saver instance.
"""

from langgraph.checkpoint.redis.aio import AsyncRedisSaver

# Re-export the shared factory so agent/main.py and agent/ tests continue to work unchanged.
from shared.checkpointer import get_checkpointer as get_checkpointer  # noqa: F401


async def setup_checkpointer(saver: AsyncRedisSaver) -> None:
    """Idempotent index setup — safe to call on every boot.

    Must be called after entering the context manager returned by get_checkpointer().
    """
    await saver.asetup()

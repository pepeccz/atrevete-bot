"""
Redis checkpointer for LangGraph state persistence.

This module provides a singleton Redis checkpointer for LangGraph StateGraph.
The checkpointer enables crash recovery by persisting conversation state to Redis
after each node execution.
"""

import asyncio
import logging
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from redis.asyncio import Redis

from shared.config import get_settings

# Configure logger
logger = logging.getLogger(__name__)

# Global flag to track if Redis indexes have been initialized
_redis_indexes_initialized = False


async def initialize_redis_indexes(checkpointer: AsyncRedisSaver) -> None:
    """
    Initialize Redis indexes for LangGraph checkpointer.

    This function calls setup() on the AsyncRedisSaver to create necessary
    RedisSearch indexes (checkpoint_writes, etc.) that are required for
    checkpoint persistence and retrieval.

    Args:
        checkpointer: AsyncRedisSaver instance to initialize

    Raises:
        Exception: If index creation fails
    """
    global _redis_indexes_initialized

    if _redis_indexes_initialized:
        logger.debug("Redis indexes already initialized, skipping")
        return

    try:
        logger.info("Initializing Redis indexes for LangGraph checkpointer...")
        await checkpointer.setup()
        _redis_indexes_initialized = True
        logger.info("✓ Redis indexes initialized successfully")
    except Exception as e:
        logger.error(f"✗ Failed to initialize Redis indexes: {e}", exc_info=True)
        raise


def get_redis_checkpointer() -> BaseCheckpointSaver[Any]:
    """
    Get Redis checkpointer instance with 24-hour TTL.

    This function creates an AsyncRedisSaver instance for LangGraph state persistence.
    Checkpoints are automatically expired after 24 hours (86400 seconds) to prevent
    unbounded memory growth in Redis.

    The checkpointer stores conversation state in Redis with keys following
    the pattern: langgraph:checkpoint:{thread_id}:{checkpoint_ns}

    Returns:
        AsyncRedisSaver instance configured with REDIS_URL and 24-hour TTL

    Example:
        >>> checkpointer = get_redis_checkpointer()
        >>> # Initialize indexes (must be called before using checkpointer)
        >>> await initialize_redis_indexes(checkpointer)
        >>> graph = create_conversation_graph(checkpointer=checkpointer)
        >>> config = {"configurable": {"thread_id": "wa-msg-123"}}
        >>> result = await graph.ainvoke(state, config=config)

    Note:
        - Checkpoints are automatically saved after each node execution
        - Crash recovery: Invoke graph with same thread_id to resume
        - Redis key pattern: langgraph:checkpoint:{thread_id}:{checkpoint_ns}
        - TTL: 24 hours (86400 seconds) for automatic cleanup
        - Older conversations (>24h) should be archived to PostgreSQL (Story 2.5c)
        - Not cached with @lru_cache to avoid issues with event loops
        - IMPORTANT: Call initialize_redis_indexes() before first use
    """
    settings = get_settings()
    redis_url = settings.REDIS_URL

    logger.info(f"Creating Redis checkpointer with URL: {redis_url}")

    # Create Redis async client (decode_responses=False for binary checkpoint data)
    redis_client = Redis.from_url(redis_url, decode_responses=False)

    # Create AsyncRedisSaver with TTL configuration
    # TTL of 86400 seconds (24 hours) for automatic checkpoint expiration
    checkpointer = AsyncRedisSaver(
        redis_client=redis_client,
        ttl={"default": 86400}  # 24 hours in seconds
    )

    logger.info("Redis checkpointer created with 24-hour TTL")

    return checkpointer

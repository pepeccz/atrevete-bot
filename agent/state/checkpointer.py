"""
Redis checkpointer for LangGraph state persistence.

This module provides a singleton Redis checkpointer for LangGraph StateGraph.
The checkpointer enables crash recovery by persisting conversation state to Redis
after each node execution.
"""

import logging
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from redis.asyncio import Redis

from shared.config import get_settings

# Configure logger
logger = logging.getLogger(__name__)


def get_redis_checkpointer() -> BaseCheckpointSaver[Any]:
    """
    Get Redis checkpointer instance.

    This function creates an AsyncRedisSaver instance for LangGraph state persistence.

    The checkpointer stores conversation state in Redis with keys following
    the pattern: checkpoint:{thread_id}:state

    Returns:
        AsyncRedisSaver instance configured with REDIS_URL from settings

    Example:
        >>> checkpointer = get_redis_checkpointer()
        >>> graph = create_conversation_graph(checkpointer=checkpointer)
        >>> config = {"configurable": {"thread_id": "wa-msg-123"}}
        >>> result = await graph.ainvoke(state, config=config)

    Note:
        - Checkpoints are automatically saved after each node execution
        - Crash recovery: Invoke graph with same thread_id to resume
        - Redis key pattern: checkpoint:{thread_id}:state
        - Not cached with @lru_cache to avoid issues with event loops
    """
    settings = get_settings()
    redis_url = settings.REDIS_URL

    logger.info(f"Creating Redis checkpointer with URL: {redis_url}")

    # Create Redis async client
    redis_client = Redis.from_url(redis_url, decode_responses=False)

    # Create AsyncRedisSaver with the Redis client
    checkpointer = AsyncRedisSaver(redis_client)

    logger.info("Redis checkpointer created successfully")

    return checkpointer

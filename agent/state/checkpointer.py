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
from langgraph.store.redis import AsyncRedisStore
from redis.asyncio import Redis

from shared.config import get_settings

# Configure logger
logger = logging.getLogger(__name__)

# Global flag to track if Redis indexes have been initialized
_redis_indexes_initialized = False

# Global flag to track if Redis Store has been initialized
_redis_store_initialized = False


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

    # Build connection kwargs (decode_responses=False for binary checkpoint data)
    conn_kwargs: dict[str, Any] = {"decode_responses": False}
    if settings.REDIS_PASSWORD:
        conn_kwargs["password"] = settings.REDIS_PASSWORD
        logger.info("Redis checkpointer: using password authentication")

    # Create Redis async client
    redis_client = Redis.from_url(redis_url, **conn_kwargs)

    # Create AsyncRedisSaver with TTL configuration
    # TTL of 86400 seconds (24 hours) for automatic checkpoint expiration
    checkpointer = AsyncRedisSaver(
        redis_client=redis_client,
        ttl={"default": 86400}  # 24 hours in seconds
    )

    logger.info("Redis checkpointer created with 24-hour TTL")

    return checkpointer


def get_redis_store() -> AsyncRedisStore:
    """Create an AsyncRedisStore for cross-conversation customer memory.

    Uses the same Redis instance as the checkpointer but a different key prefix
    ('store:*' vs 'langgraph:checkpoint:*') — no key collision.

    TTL: None (no automatic expiry). refresh_on_read=True so active customers
    stay warm. Cold customers are naturally evicted by Redis memory pressure.

    Returns:
        AsyncRedisStore configured for customer memory persistence.

    Note:
        IMPORTANT: Cannot reuse the checkpointer's Redis client because the
        checkpointer uses decode_responses=False (binary checkpoint data) while
        AsyncRedisStore requires decode_responses=True (JSON string values).
        A dedicated client is created here to avoid this incompatibility.
    """
    settings = get_settings()
    redis_url = settings.REDIS_URL

    logger.info("Creating AsyncRedisStore for customer memory")

    # Connection kwargs — Store needs decode_responses=True (JSON values)
    # NOTE: Cannot reuse the checkpointer's client which uses decode_responses=False
    conn_kwargs: dict[str, Any] = {"decode_responses": True}
    if settings.REDIS_PASSWORD:
        conn_kwargs["password"] = settings.REDIS_PASSWORD
        logger.info("Redis Store: using password authentication")

    # Create a dedicated Redis client for the Store
    store_redis_client = Redis.from_url(redis_url, **conn_kwargs)

    store = AsyncRedisStore(
        redis_client=store_redis_client,
        ttl={
            "refresh_on_read": True,
            "default_ttl": None,
        },
        # Default prefix 'store' → keys like store:customers:+34...:preferences
        # Does NOT collide with checkpointer's 'langgraph:checkpoint:' prefix
    )

    logger.info("AsyncRedisStore created (prefix='store', TTL=None, refresh_on_read=True)")
    return store


async def initialize_redis_store(store: AsyncRedisStore) -> None:
    """Initialize Redis indexes for the Store (call once at startup).

    Similar to initialize_redis_indexes() for the checkpointer.
    Guards with a global flag to ensure setup() is called at most once.

    Args:
        store: AsyncRedisStore instance to initialize

    Raises:
        Exception: If setup() fails (caller in main.py handles graceful degradation)
    """
    global _redis_store_initialized

    if _redis_store_initialized:
        logger.debug("Redis Store already initialized, skipping")
        return

    try:
        logger.info("Initializing Redis Store indexes...")
        await store.setup()
        _redis_store_initialized = True
        logger.info("Redis Store initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize Redis Store: %s", e, exc_info=True)
        raise

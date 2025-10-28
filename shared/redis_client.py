"""
Redis client singleton for pub/sub messaging and state persistence.

This module provides a singleton Redis client configured for production reliability
with connection pooling, retry logic, and health checks.
"""

import json
import logging
from functools import lru_cache
from typing import Any

import redis.asyncio as redis
from fastapi import HTTPException
from redis import ConnectionError as RedisConnectionError

from shared.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_redis_client() -> redis.Redis:
    """
    Get cached Redis client instance with production-ready configuration.

    This function creates a singleton Redis client with:
    - Connection pooling (max 20 connections for api, agent, workers)
    - Automatic retry on timeout for transient failures
    - Health check pings every 30 seconds
    - Graceful error handling with logging

    Redis Key Patterns:
        - Checkpoints: langgraph:checkpoint:{conversation_id}:{checkpoint_ns}
        - Human mode flags: conversation:{conversation_id}:human_mode
        - TTL: 24 hours (86400 seconds) for all conversation-related keys

    Returns:
        Redis async client configured with connection pool and retry logic

    Note:
        Uses @lru_cache to ensure only one Redis connection is created.
        If Redis connection fails, logs error and raises exception for
        graceful degradation (checkpointing unavailable, but app continues).
    """
    settings = get_settings()

    try:
        client = redis.from_url(
            settings.REDIS_URL,
            max_connections=20,  # Sufficient for 3 containers (api, agent, workers)
            decode_responses=True,  # Automatically decode bytes to strings
            retry_on_timeout=True,  # Retry on transient network timeouts
            health_check_interval=30,  # Ping Redis every 30s to detect failures
        )

        logger.info(
            f"Redis client initialized: {settings.REDIS_URL} "
            f"(max_connections=20, retry_on_timeout=True, health_check_interval=30s)"
        )
        return client

    except RedisConnectionError as e:
        logger.error(
            f"Redis connection failed: {e}. Checkpointing unavailable, "
            f"conversations will not persist across restarts.",
            exc_info=True
        )
        raise

    except Exception as e:
        logger.error(
            f"Unexpected error creating Redis client: {e}",
            exc_info=True
        )
        raise


async def publish_to_channel(channel: str, message: dict[str, Any]) -> None:
    """
    Publish a message to a Redis pub/sub channel.

    Args:
        channel: Redis channel name (e.g., 'incoming_messages', 'payment_events')
        message: Message dict to publish (will be JSON-serialized)

    Raises:
        HTTPException: 503 if Redis connection fails
    """
    client = get_redis_client()

    try:
        # Serialize message to JSON
        json_message = json.dumps(message)

        # Publish to channel
        await client.publish(channel, json_message)

        logger.debug(f"Message published to channel '{channel}': {json_message[:100]}")

    except RedisConnectionError as e:
        logger.error(f"Redis connection error while publishing to '{channel}': {e}")
        raise HTTPException(
            status_code=503, detail="Service temporarily unavailable (Redis connection failed)"
        ) from e

    except Exception as e:
        logger.error(f"Unexpected error publishing to Redis channel '{channel}': {e}")
        raise HTTPException(
            status_code=503, detail="Service temporarily unavailable"
        ) from e


async def close_redis_client() -> None:
    """
    Close Redis connection gracefully.

    Note:
        Should be called during application shutdown.
    """
    try:
        client = get_redis_client()
        await client.close()
        logger.info("Redis client closed")
    except Exception as e:
        logger.warning(f"Error closing Redis client: {e}")

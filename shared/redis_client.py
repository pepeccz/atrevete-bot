"""Redis client singleton for pub/sub messaging."""

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
    Get cached Redis client instance (singleton pattern).

    Returns:
        Redis async client configured with connection pool

    Note:
        Uses @lru_cache to ensure only one Redis connection is created.
    """
    settings = get_settings()

    client = redis.from_url(
        settings.REDIS_URL,
        max_connections=10,
        decode_responses=True,  # Automatically decode bytes to strings
    )

    logger.info(f"Redis client initialized: {settings.REDIS_URL}")
    return client


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

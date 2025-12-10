"""
Redis client singleton for pub/sub messaging and state persistence.

This module provides a singleton Redis client configured for production reliability
with connection pooling, retry logic, and health checks.

Supports two messaging modes:
- Redis Streams (default): Persistent messages with consumer groups and acknowledgment
- Redis Pub/Sub (legacy): Fire-and-forget messaging for backward compatibility
"""

import json
import logging
from datetime import datetime, UTC
from functools import lru_cache
from typing import Any

import redis.asyncio as redis
from fastapi import HTTPException
from redis import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError as RedisResponseError

from shared.config import get_settings

# Redis Streams constants
INCOMING_STREAM = "incoming_messages_stream"
OUTGOING_STREAM = "outgoing_messages_stream"
CONSUMER_GROUP = "agent_workers"
DEAD_LETTER_STREAM = "dead_letter_stream"
STREAM_MAX_LEN = 10000  # Approximate trim to keep stream bounded

logger = logging.getLogger(__name__)


@lru_cache
def get_redis_client() -> "redis.Redis[str]":
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


# =============================================================================
# Redis Streams Functions (Persistent Message Delivery)
# =============================================================================


async def add_to_stream(
    stream: str,
    message: dict[str, Any],
    max_len: int = STREAM_MAX_LEN,
) -> str:
    """
    Add a message to a Redis Stream with automatic trimming.

    Unlike pub/sub, Stream messages persist until explicitly acknowledged.
    This ensures no message loss even if consumers are temporarily offline.

    Args:
        stream: Name of the Redis Stream
        message: Message dict to add (will be JSON-serialized)
        max_len: Maximum stream length (approximate trimming for performance)

    Returns:
        Stream message ID (e.g., "1234567890123-0")

    Raises:
        HTTPException: 503 if Redis connection fails
    """
    client = get_redis_client()

    try:
        json_message = json.dumps(message)

        # XADD with MAXLEN ~ (approximate) for performance
        # The ~ means Redis may keep slightly more entries for efficiency
        message_id = await client.xadd(
            stream,
            {"data": json_message},
            maxlen=max_len,
            approximate=True,
        )

        logger.debug(
            f"Message added to stream '{stream}': id={message_id}, "
            f"data={json_message[:100]}..."
        )
        return message_id

    except RedisConnectionError as e:
        logger.error(f"Redis connection error adding to stream '{stream}': {e}")
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable (Redis connection failed)",
        ) from e

    except Exception as e:
        logger.error(f"Unexpected error adding to stream '{stream}': {e}")
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable",
        ) from e


async def create_consumer_group(
    stream: str,
    group: str,
    start_id: str = "0",
) -> bool:
    """
    Create a consumer group for a Redis Stream.

    Consumer groups allow multiple workers to process messages cooperatively.
    Each message is delivered to exactly one consumer in the group.

    Args:
        stream: Name of the Redis Stream
        group: Name of the consumer group
        start_id: Starting message ID ("0" for all messages, "$" for new only)

    Returns:
        True if group was created, False if it already exists

    Raises:
        HTTPException: 503 if Redis connection fails (except for BUSYGROUP)
    """
    client = get_redis_client()

    try:
        # XGROUP CREATE with MKSTREAM creates the stream if it doesn't exist
        await client.xgroup_create(
            stream,
            group,
            id=start_id,
            mkstream=True,
        )
        logger.info(f"Consumer group '{group}' created for stream '{stream}'")
        return True

    except RedisResponseError as e:
        if "BUSYGROUP" in str(e):
            # Group already exists - this is fine
            logger.debug(f"Consumer group '{group}' already exists for stream '{stream}'")
            return False
        logger.error(f"Error creating consumer group '{group}': {e}")
        raise HTTPException(
            status_code=503,
            detail="Failed to create consumer group",
        ) from e

    except RedisConnectionError as e:
        logger.error(f"Redis connection error creating consumer group: {e}")
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable (Redis connection failed)",
        ) from e


async def read_from_stream(
    stream: str,
    group: str,
    consumer: str,
    count: int = 1,
    block_ms: int = 5000,
) -> list[tuple[str, dict[str, Any]]]:
    """
    Read messages from a Redis Stream using consumer group.

    Messages are claimed by this consumer until acknowledged (XACK).
    If the consumer crashes, messages can be reclaimed by other consumers.

    Args:
        stream: Name of the Redis Stream
        group: Name of the consumer group
        consumer: Unique consumer identifier (e.g., "agent-{pid}")
        count: Maximum number of messages to read
        block_ms: Milliseconds to block waiting for messages (0 = no block)

    Returns:
        List of tuples: [(message_id, message_data), ...]
        Empty list if no messages available

    Raises:
        HTTPException: 503 if Redis connection fails
    """
    client = get_redis_client()

    try:
        # XREADGROUP: Read new messages (">") for this consumer
        messages = await client.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=count,
            block=block_ms,
        )

        result: list[tuple[str, dict[str, Any]]] = []

        if messages:
            for stream_name, stream_messages in messages:
                for msg_id, msg_data in stream_messages:
                    # Handle both bytes and string responses
                    data_key = b"data" if b"data" in msg_data else "data"
                    raw_data = msg_data.get(data_key, "{}")

                    # Decode if bytes
                    if isinstance(raw_data, bytes):
                        raw_data = raw_data.decode("utf-8")

                    try:
                        parsed_data = json.loads(raw_data)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in message {msg_id}: {raw_data[:100]}")
                        parsed_data = {"_raw": raw_data, "_parse_error": True}

                    result.append((msg_id, parsed_data))

        if result:
            logger.debug(
                f"Read {len(result)} messages from stream '{stream}' "
                f"(consumer={consumer})"
            )

        return result

    except RedisConnectionError as e:
        logger.error(f"Redis connection error reading from stream '{stream}': {e}")
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable (Redis connection failed)",
        ) from e

    except RedisResponseError as e:
        # Handle case where group doesn't exist yet
        if "NOGROUP" in str(e):
            logger.warning(f"Consumer group '{group}' doesn't exist for stream '{stream}'")
            return []
        raise

    except Exception as e:
        logger.error(f"Unexpected error reading from stream '{stream}': {e}")
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable",
        ) from e


async def acknowledge_message(
    stream: str,
    group: str,
    message_id: str,
) -> int:
    """
    Acknowledge successful message processing (XACK).

    Once acknowledged, the message is removed from the consumer's pending list.
    This confirms the message was processed successfully and shouldn't be redelivered.

    Args:
        stream: Name of the Redis Stream
        group: Name of the consumer group
        message_id: ID of the message to acknowledge

    Returns:
        Number of messages acknowledged (usually 1, 0 if already acked)

    Raises:
        HTTPException: 503 if Redis connection fails
    """
    client = get_redis_client()

    try:
        ack_count = await client.xack(stream, group, message_id)

        if ack_count > 0:
            logger.debug(f"Acknowledged message {message_id} in stream '{stream}'")
        else:
            logger.warning(
                f"Message {message_id} was already acknowledged or doesn't exist"
            )

        return ack_count

    except RedisConnectionError as e:
        logger.error(f"Redis connection error acknowledging message: {e}")
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable (Redis connection failed)",
        ) from e

    except Exception as e:
        logger.error(f"Unexpected error acknowledging message {message_id}: {e}")
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable",
        ) from e


async def move_to_dead_letter(
    source_stream: str,
    group: str,
    message_id: str,
    message_data: dict[str, Any],
    error: str,
) -> str:
    """
    Move a failed message to the dead letter stream for later inspection/retry.

    This preserves failed messages instead of losing them, allowing:
    - Manual inspection of failures
    - Automated retry processing
    - Error pattern analysis

    Args:
        source_stream: Original stream the message came from
        group: Consumer group name
        message_id: Original message ID
        message_data: Original message data
        error: Error description explaining why processing failed

    Returns:
        Dead letter message ID

    Raises:
        HTTPException: 503 if Redis connection fails
    """
    client = get_redis_client()

    try:
        # Add to dead letter stream with metadata
        dlq_message = {
            "original_stream": source_stream,
            "original_id": message_id,
            "data": json.dumps(message_data),
            "error": str(error)[:1000],  # Truncate long errors
            "failed_at": datetime.now(UTC).isoformat(),
            "consumer_group": group,
        }

        dlq_id = await client.xadd(
            DEAD_LETTER_STREAM,
            {k: v for k, v in dlq_message.items()},
            maxlen=STREAM_MAX_LEN,
            approximate=True,
        )

        # Acknowledge the original message (remove from pending)
        await client.xack(source_stream, group, message_id)

        logger.warning(
            f"Message {message_id} moved to dead letter queue: {error[:100]}... "
            f"(dlq_id={dlq_id})"
        )

        return dlq_id

    except RedisConnectionError as e:
        logger.error(f"Redis connection error moving to DLQ: {e}")
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable (Redis connection failed)",
        ) from e

    except Exception as e:
        logger.error(f"Unexpected error moving message {message_id} to DLQ: {e}")
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable",
        ) from e


async def get_pending_messages(
    stream: str,
    group: str,
    count: int = 10,
) -> list[dict[str, Any]]:
    """
    Get pending (unacknowledged) messages for monitoring/debugging.

    Useful for checking if messages are stuck or need reprocessing.

    Args:
        stream: Name of the Redis Stream
        group: Name of the consumer group
        count: Maximum number of pending messages to return

    Returns:
        List of pending message info dicts
    """
    client = get_redis_client()

    try:
        # XPENDING with IDLE option to find stuck messages
        pending = await client.xpending_range(
            stream,
            group,
            min="-",
            max="+",
            count=count,
        )

        result = []
        for p in pending:
            result.append({
                "message_id": p.get("message_id"),
                "consumer": p.get("consumer"),
                "idle_time_ms": p.get("time_since_delivered"),
                "delivery_count": p.get("times_delivered"),
            })

        return result

    except Exception as e:
        logger.error(f"Error getting pending messages: {e}")
        return []

"""
Conversation archiver worker - Archives expired Redis checkpoints to PostgreSQL.

This module implements an hourly background worker that archives conversation
state from Redis to PostgreSQL before the 24-hour TTL expires. The archival
process preserves customer interaction history for long-term storage and analysis.

Architecture:
    - Runs hourly via cron schedule
    - Archives checkpoints older than 23 hours (1-hour buffer before expiration)
    - Stores messages in conversation_history table
    - Deletes archived checkpoints from Redis
    - Implements retry logic for database failures
    - Provides health check monitoring

Key Pattern:
    Redis Checkpoint (TTL=24h) → Archive Worker (>23h) → PostgreSQL → Delete from Redis
"""

import asyncio
import json
import logging
import pickle
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import schedule
import redis
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_async_session
from database.models import ConversationHistory, MessageRole
from shared.config import get_settings

# Configure logger
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_requested = False

# Timezone for all datetime operations
TIMEZONE = ZoneInfo("Europe/Madrid")

# Archival configuration
CUTOFF_HOURS = 23  # Archive checkpoints older than this (before 24h TTL expiration)
RETRY_DELAY_SECONDS = 5
MAX_RETRY_ATTEMPTS = 2


def get_sync_redis_client() -> Redis:
    """
    Get synchronous Redis client for worker operations.

    Returns:
        Redis: Synchronous Redis client instance
    """
    settings = get_settings()
    return redis.from_url(
        settings.REDIS_URL,
        decode_responses=False,  # Keep binary for checkpoint data
        retry_on_timeout=True,
    )


def signal_handler(signum: int, frame: Any) -> None:
    """
    Handle SIGTERM/SIGINT for graceful shutdown.

    Sets global shutdown flag to complete current archival run before exiting.
    """
    global shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_requested = True


# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


async def find_expired_checkpoints(redis_client: Redis) -> list[tuple[str, str, datetime]]:
    """
    Query Redis for checkpoint keys older than CUTOFF_HOURS.

    Args:
        redis_client: Redis client instance

    Returns:
        List of tuples: (key, conversation_id, checkpoint_time)
        Sorted by checkpoint_time (oldest first)

    Note:
        Checkpoint key pattern: langgraph:checkpoint:{thread_id}:{checkpoint_ns}
        The checkpoint_ns contains Unix timestamp (seconds since epoch)
    """
    cutoff_time = datetime.now(TIMEZONE) - timedelta(hours=CUTOFF_HOURS)
    logger.info(f"Searching for checkpoints older than {cutoff_time.isoformat()}")

    try:
        # Query all checkpoint keys
        # Note: keys() is synchronous in redis-py, but should be fast for checkpoint patterns
        keys = redis_client.keys("langgraph:checkpoint:*")
        logger.debug(f"Found {len(keys)} total checkpoint keys")

        expired_keys = []

        for key in keys:
            try:
                # Parse key pattern: langgraph:checkpoint:{thread_id}:{checkpoint_ns}
                # checkpoint_ns format may vary, but typically contains timestamp
                key_str = key.decode('utf-8') if isinstance(key, bytes) else key
                parts = key_str.split(":")

                if len(parts) < 3:
                    logger.warning(f"Unexpected key format: {key_str}, skipping")
                    continue

                # Extract thread_id (conversation_id) - may be multi-part
                # Format: langgraph:checkpoint:{thread_id}:{checkpoint_ns}
                # thread_id could contain colons, so we need to parse carefully
                # We assume checkpoint_ns is the last part and is numeric
                thread_id_parts = parts[2:-1]  # Everything between 'checkpoint:' and last part
                conversation_id = ":".join(thread_id_parts) if thread_id_parts else parts[2]
                checkpoint_ns = parts[-1]

                # Try to parse checkpoint_ns as Unix timestamp
                # LangGraph AsyncRedisSaver uses format: {thread_id}:{checkpoint_ns}
                # where checkpoint_ns may contain timestamp
                try:
                    # If checkpoint_ns is numeric, treat as Unix timestamp
                    if checkpoint_ns.isdigit():
                        timestamp = int(checkpoint_ns)
                        checkpoint_time = datetime.fromtimestamp(timestamp, tz=TIMEZONE)
                    else:
                        # checkpoint_ns may have other format, try to get TTL instead
                        ttl = redis_client.ttl(key)
                        if ttl <= 0:
                            # Key expired or no TTL, skip
                            continue
                        # Calculate checkpoint time from TTL (24h total TTL)
                        checkpoint_time = datetime.now(TIMEZONE) - timedelta(seconds=(86400 - ttl))

                    # Check if checkpoint is older than cutoff
                    if checkpoint_time < cutoff_time:
                        expired_keys.append((key_str, conversation_id, checkpoint_time))
                        logger.debug(
                            f"Expired checkpoint found: {conversation_id}, "
                            f"age: {checkpoint_time.isoformat()}"
                        )

                except (ValueError, TypeError) as e:
                    logger.debug(f"Could not parse timestamp from checkpoint_ns '{checkpoint_ns}': {e}")
                    continue

            except Exception as e:
                logger.warning(f"Error parsing checkpoint key {key}: {e}", exc_info=True)
                continue

        # Sort by checkpoint_time (oldest first)
        expired_keys.sort(key=lambda x: x[2])

        logger.info(f"Found {len(expired_keys)} expired checkpoints to archive")
        return expired_keys

    except RedisConnectionError as e:
        logger.critical(f"Redis connection failed during key query: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error querying Redis keys: {e}", exc_info=True)
        raise


async def retrieve_and_parse_checkpoint(redis_client: Redis, key: str) -> dict[str, Any] | None:
    """
    Retrieve and deserialize checkpoint data from Redis.

    Args:
        redis_client: Redis client instance
        key: Checkpoint key to retrieve

    Returns:
        Parsed checkpoint state dict, or None if checkpoint is missing/malformed

    Note:
        LangGraph AsyncRedisSaver may use JSON or pickle serialization.
        This function attempts both formats.
    """
    try:
        # Retrieve checkpoint data (binary)
        checkpoint_data = redis_client.get(key)

        if checkpoint_data is None:
            logger.warning(f"Checkpoint {key} not found (already deleted?)")
            return None

        # Try to deserialize (JSON first, then pickle)
        try:
            # Attempt JSON deserialization
            if isinstance(checkpoint_data, bytes):
                checkpoint_data = checkpoint_data.decode('utf-8')
            state = json.loads(checkpoint_data)
            logger.debug(f"Checkpoint {key} deserialized as JSON")
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Attempt pickle deserialization
            try:
                state = pickle.loads(checkpoint_data)
                logger.debug(f"Checkpoint {key} deserialized as pickle")
            except Exception as e:
                logger.error(
                    f"Failed to deserialize checkpoint {key} (tried JSON and pickle): {e}",
                    exc_info=True
                )
                return None

        # Validate state structure
        if not isinstance(state, dict):
            logger.error(f"Checkpoint {key} deserialized to non-dict type: {type(state)}")
            return None

        # LangGraph checkpoint structure: {"v": 1, "ts": timestamp, "data": state_dict, ...}
        # Extract actual state from 'data' field if present
        if 'data' in state and isinstance(state['data'], dict):
            state = state['data']

        # Validate required fields for archival
        if 'conversation_id' not in state:
            logger.warning(f"Checkpoint {key} missing 'conversation_id' field, skipping")
            return None

        if 'messages' not in state or not isinstance(state['messages'], list):
            logger.warning(f"Checkpoint {key} missing or invalid 'messages' field, skipping")
            return None

        logger.debug(
            f"Checkpoint {key} parsed successfully: "
            f"conversation_id={state['conversation_id']}, "
            f"messages={len(state['messages'])}"
        )

        return state

    except RedisConnectionError as e:
        logger.error(f"Redis connection error retrieving checkpoint {key}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error retrieving checkpoint {key}: {e}", exc_info=True)
        return None


async def insert_messages_to_db(
    session: AsyncSession,
    state: dict[str, Any],
) -> int:
    """
    Insert conversation messages into conversation_history table.

    Args:
        session: SQLAlchemy async session
        state: Parsed checkpoint state dict

    Returns:
        Number of messages inserted

    Raises:
        Exception: If database insertion fails
    """
    conversation_id = state['conversation_id']
    customer_id = state.get('customer_id')  # May be None for unidentified customers
    messages = state.get('messages', [])
    conversation_summary = state.get('conversation_summary')

    if not messages and not conversation_summary:
        logger.warning(f"No messages or summary to archive for conversation {conversation_id}")
        return 0

    inserted_count = 0

    # Insert conversation messages
    for message in messages:
        try:
            # Parse message dict
            role = message.get('role')
            content = message.get('content')
            timestamp_str = message.get('timestamp')
            metadata = message.get('metadata', {})

            # Validate required fields
            if not role or not content:
                logger.warning(
                    f"Skipping message with missing role or content: {message}"
                )
                continue

            # Parse timestamp
            if timestamp_str:
                try:
                    if isinstance(timestamp_str, str):
                        timestamp = datetime.fromisoformat(timestamp_str)
                        # Ensure timezone-aware
                        if timestamp.tzinfo is None:
                            timestamp = timestamp.replace(tzinfo=TIMEZONE)
                    elif isinstance(timestamp_str, datetime):
                        timestamp = timestamp_str
                        if timestamp.tzinfo is None:
                            timestamp = timestamp.replace(tzinfo=TIMEZONE)
                    else:
                        timestamp = datetime.now(TIMEZONE)
                except Exception as e:
                    logger.warning(f"Could not parse timestamp '{timestamp_str}': {e}")
                    timestamp = datetime.now(TIMEZONE)
            else:
                timestamp = datetime.now(TIMEZONE)

            # Map role to MessageRole enum
            try:
                message_role = MessageRole[role.upper()]
            except (KeyError, AttributeError):
                logger.warning(f"Invalid message role '{role}', defaulting to USER")
                message_role = MessageRole.USER

            # Create ConversationHistory record
            history_record = ConversationHistory(
                customer_id=customer_id,
                conversation_id=conversation_id,
                timestamp=timestamp,
                message_role=message_role,
                message_content=content,
                metadata_=metadata,
            )

            session.add(history_record)
            inserted_count += 1

        except Exception as e:
            logger.error(
                f"Error creating history record for message in {conversation_id}: {e}",
                exc_info=True
            )
            # Continue to next message (don't fail entire archival for one message)
            continue

    # Insert conversation summary as system message (if present)
    if conversation_summary:
        try:
            summary_record = ConversationHistory(
                customer_id=customer_id,
                conversation_id=conversation_id,
                timestamp=datetime.now(TIMEZONE),
                message_role=MessageRole.SYSTEM,
                message_content=conversation_summary,
                metadata_={'type': 'conversation_summary'},
            )
            session.add(summary_record)
            inserted_count += 1
            logger.debug(f"Archived conversation summary for {conversation_id}")
        except Exception as e:
            logger.error(
                f"Error creating summary record for {conversation_id}: {e}",
                exc_info=True
            )

    # Commit transaction
    await session.commit()

    logger.info(
        f"Archived {inserted_count} messages for conversation {conversation_id}"
    )

    return inserted_count


async def archive_checkpoint(
    redis_client: Redis,
    key: str,
    conversation_id: str,
) -> dict[str, Any]:
    """
    Archive a single checkpoint: retrieve, insert to DB, delete from Redis.

    Args:
        redis_client: Redis client instance
        key: Checkpoint key to archive
        conversation_id: Conversation ID (for logging)

    Returns:
        Dict with archival statistics: {
            'success': bool,
            'messages_archived': int,
            'error': str | None
        }
    """
    result = {
        'success': False,
        'messages_archived': 0,
        'error': None,
    }

    # Step 1: Retrieve and parse checkpoint
    state = await retrieve_and_parse_checkpoint(redis_client, key)

    if state is None:
        result['error'] = 'Failed to retrieve or parse checkpoint'
        return result

    # Step 2: Insert messages to database (with retry)
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            async with get_async_session() as session:
                messages_archived = await insert_messages_to_db(session, state)
                result['messages_archived'] = messages_archived
                result['success'] = True

            if result['success']:
                break  # Success, exit retry loop

        except Exception as e:
            if attempt < MAX_RETRY_ATTEMPTS - 1:
                logger.warning(
                    f"Database insert failed for {conversation_id} (attempt {attempt + 1}/{MAX_RETRY_ATTEMPTS}), retrying: {e}"
                )
                await asyncio.sleep(RETRY_DELAY_SECONDS)
            else:
                logger.error(
                    f"Failed to archive {conversation_id} after {MAX_RETRY_ATTEMPTS} attempts, skipping: {e}",
                    exc_info=True
                )
                result['error'] = f'Database insert failed after {MAX_RETRY_ATTEMPTS} attempts'
                return result  # Skip deletion from Redis

    # Step 3: Delete checkpoint from Redis (only if DB insert succeeded)
    if result['success']:
        try:
            deleted_count = redis_client.delete(key)
            if deleted_count == 0:
                logger.warning(
                    f"Checkpoint {key} already deleted by another process"
                )
            else:
                logger.info(f"Deleted checkpoint {key} from Redis")
        except Exception as e:
            logger.error(
                f"Error deleting checkpoint {key} from Redis: {e}",
                exc_info=True
            )
            # Don't mark as failure - messages are archived, Redis cleanup is secondary

    return result


async def update_health_check(
    last_run: datetime,
    status: str,
    checkpoints_archived: int,
    messages_archived: int,
    errors: int,
) -> None:
    """
    Update health check file with archival run statistics.

    Args:
        last_run: Timestamp of archival run completion
        status: Health status ('healthy' or 'unhealthy')
        checkpoints_archived: Number of checkpoints archived
        messages_archived: Total messages archived
        errors: Number of errors encountered
    """
    health_data = {
        'last_run': last_run.isoformat(),
        'status': status,
        'checkpoints_archived': checkpoints_archived,
        'messages_archived': messages_archived,
        'errors': errors,
    }

    # Write health check file atomically (temp file + rename)
    health_file = Path('/var/health/archiver_health.json')  # Shared volume for Docker
    temp_file = Path(f'/var/health/archiver_health.{int(time.time())}.tmp')

    try:
        temp_file.write_text(json.dumps(health_data, indent=2))
        temp_file.rename(health_file)
        logger.debug(f"Health check file updated: {health_file}")
    except Exception as e:
        logger.error(f"Failed to write health check file: {e}", exc_info=True)


async def archive_expired_conversations() -> None:
    """
    Main archival function - archives expired Redis checkpoints to PostgreSQL.

    This function:
        1. Queries Redis for checkpoints older than CUTOFF_HOURS
        2. For each expired checkpoint:
           - Retrieves and deserializes state
           - Inserts messages into conversation_history table
           - Deletes checkpoint from Redis
        3. Implements retry logic for database failures
        4. Updates health check file with run statistics

    Logs comprehensive statistics and errors for monitoring.
    """
    start_time = datetime.now(TIMEZONE)
    logger.info(f"Starting conversation archival run at {start_time.isoformat()}")

    checkpoints_found = 0
    checkpoints_archived = 0
    messages_archived = 0
    errors = 0

    try:
        # Connect to Redis (synchronous client)
        redis_client = get_sync_redis_client()

        # Step 1: Find expired checkpoints
        expired_keys = await find_expired_checkpoints(redis_client)
        checkpoints_found = len(expired_keys)

        if checkpoints_found == 0:
            logger.info("No expired checkpoints to archive")
            await update_health_check(
                last_run=datetime.now(TIMEZONE),
                status='healthy',
                checkpoints_archived=0,
                messages_archived=0,
                errors=0,
            )
            return

        # Step 2: Archive each checkpoint
        for key, conversation_id, checkpoint_time in expired_keys:
            logger.info(
                f"Archiving conversation {conversation_id} "
                f"(checkpoint age: {checkpoint_time.isoformat()})"
            )

            result = await archive_checkpoint(redis_client, key, conversation_id)

            if result['success']:
                checkpoints_archived += 1
                messages_archived += result['messages_archived']
            else:
                errors += 1
                logger.error(
                    f"Failed to archive {conversation_id}: {result['error']}"
                )

        # Step 3: Log summary statistics
        end_time = datetime.now(TIMEZONE)
        duration = (end_time - start_time).total_seconds()

        logger.info(
            f"Completed archival run in {duration:.2f}s",
            extra={
                'checkpoints_found': checkpoints_found,
                'checkpoints_archived': checkpoints_archived,
                'messages_archived': messages_archived,
                'errors': errors,
                'duration_seconds': duration,
            }
        )

        # Step 4: Update health check file
        status = 'healthy' if errors == 0 else 'unhealthy'
        await update_health_check(
            last_run=end_time,
            status=status,
            checkpoints_archived=checkpoints_archived,
            messages_archived=messages_archived,
            errors=errors,
        )

    except RedisConnectionError as e:
        logger.critical(
            f"Redis connection failed, archival worker cannot proceed: {e}",
            exc_info=True
        )
        await update_health_check(
            last_run=datetime.now(TIMEZONE),
            status='unhealthy',
            checkpoints_archived=checkpoints_archived,
            messages_archived=messages_archived,
            errors=errors + 1,
        )
        raise

    except Exception as e:
        logger.exception(f"Unexpected error in archival worker: {e}")
        await update_health_check(
            last_run=datetime.now(TIMEZONE),
            status='unhealthy',
            checkpoints_archived=checkpoints_archived,
            messages_archived=messages_archived,
            errors=errors + 1,
        )
        raise


def run_archival_worker() -> None:
    """
    Main worker entry point - runs archival on hourly schedule.

    Schedules archive_expired_conversations() to run every hour at :00.
    Handles graceful shutdown on SIGTERM/SIGINT.
    """
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
        ]
    )

    logger.info("Conversation archiver worker starting...")
    logger.info(f"Configuration: CUTOFF_HOURS={CUTOFF_HOURS}, TIMEZONE={TIMEZONE}")

    # Write initial health check file
    asyncio.run(
        update_health_check(
            last_run=datetime.now(TIMEZONE),
            status="healthy",
            checkpoints_archived=0,
            messages_archived=0,
            errors=0,
        )
    )
    logger.info("Initial health check file written")

    # Schedule hourly execution at :00
    schedule.every().hour.at(":00").do(
        lambda: asyncio.run(archive_expired_conversations())
    )

    logger.info("Archival worker scheduled (hourly at :00)")

    # Run scheduler loop
    while not shutdown_requested:
        schedule.run_pending()
        time.sleep(60)  # Check every minute

    logger.info("Archival worker shutting down gracefully")


if __name__ == "__main__":
    run_archival_worker()

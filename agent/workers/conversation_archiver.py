"""
Conversation archiver worker - Archives expired Redis checkpoints to PostgreSQL.

This module implements an hourly background worker that archives conversation
state from Redis to PostgreSQL before the 24-hour TTL expires. The archival
process preserves customer interaction history for long-term storage and analysis.

Architecture:
    - Runs hourly via cron schedule
    - Archives checkpoints older than 23 hours (1-hour buffer before expiration)
    - Two-table write path (v2):
        * ConversationHistory — one parent row per conversation (upserted by conversation_id)
        * ConversationMessage — one child row per message (idempotent via timestamp+role+content)
    - Deletes archived checkpoints from Redis after successful write
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

import redis
import schedule
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_async_session
from database.models import ConversationHistory, ConversationMessage
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
        Checkpoint key pattern: checkpoint:{thread_id}:{checkpoint_ns}:{uuid}
        The checkpoint_ns is typically "__empty__" and the uuid contains timestamp info.
        AsyncRedisSaver uses NO "langgraph:" prefix.
    """
    cutoff_time = datetime.now(TIMEZONE) - timedelta(hours=CUTOFF_HOURS)
    logger.info(f"Searching for checkpoints older than {cutoff_time.isoformat()}")

    try:
        # Query all checkpoint keys using SCAN (non-blocking)
        # Note: scan_iter() is non-blocking and processes keys in batches,
        # allowing other Redis commands to execute between iterations.
        # This prevents Redis from being blocked when there are many keys.
        # AsyncRedisSaver uses "checkpoint:*" pattern (NO "langgraph:" prefix)
        keys = list(redis_client.scan_iter(match="checkpoint:*", count=1000))
        logger.debug(f"Found {len(keys)} total checkpoint keys")

        expired_keys = []

        for key in keys:
            try:
                # Real key format (verified against live Redis):
                #   checkpoint:{thread_id}:__empty__:{uuid}
                # where thread_id is the Chatwoot conversation_id (e.g. "1")
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key

                # Key format: checkpoint:{thread_id}:{checkpoint_ns}:{checkpoint_id}
                # thread_id may itself contain ":" (e.g. "v2:1"), so strip the
                # "checkpoint:" prefix and the trailing ":ns:id" suffix.
                if not key_str.startswith("checkpoint:"):
                    logger.warning(f"Unexpected key format: {key_str}, skipping")
                    continue
                inner = key_str[len("checkpoint:") :]
                inner_parts = inner.rsplit(":", 2)
                if len(inner_parts) < 3 or not inner_parts[0]:
                    logger.warning(f"Unexpected key format: {key_str}, skipping")
                    continue
                thread_id = inner_parts[0]
                # Strip v2: prefix so logs and expired_keys carry the bare
                # Chatwoot conversation_id consistent with state["conversation_id"].
                conversation_id = thread_id.removeprefix("v2:")

                # Age estimation via TTL (24h total TTL set by AsyncRedisSaver)
                try:
                    ttl = redis_client.ttl(key)
                    if ttl < 0:
                        # Key has no TTL or already expired — skip
                        continue
                    # checkpoint_time = now - (24h - remaining_ttl)
                    checkpoint_time = datetime.now(TIMEZONE) - timedelta(seconds=(86400 - ttl))

                    # Check if checkpoint is older than cutoff
                    if checkpoint_time < cutoff_time:
                        expired_keys.append((key_str, conversation_id, checkpoint_time))
                        logger.debug(
                            f"Expired checkpoint found: {conversation_id}, "
                            f"age: {checkpoint_time.isoformat()}"
                        )

                except (ValueError, TypeError) as e:
                    logger.debug(f"Could not estimate age for key '{key_str}': {e}")
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
        state: dict[str, Any] | None = None
        try:
            # Attempt JSON deserialization
            raw = (
                checkpoint_data.decode("utf-8")
                if isinstance(checkpoint_data, bytes)
                else checkpoint_data
            )
            state = json.loads(raw)
            logger.debug(f"Checkpoint {key} deserialized as JSON")
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Attempt pickle deserialization
            try:
                state = pickle.loads(checkpoint_data)  # type: ignore[arg-type]
                logger.debug(f"Checkpoint {key} deserialized as pickle")
            except Exception as e:
                logger.error(
                    f"Failed to deserialize checkpoint {key} (tried JSON and pickle): {e}",
                    exc_info=True,
                )
                return None

        # Validate state structure
        if not isinstance(state, dict):
            logger.error(f"Checkpoint {key} deserialized to non-dict type: {type(state)}")
            return None

        # LangGraph checkpoint structure: {"v": 1, "ts": timestamp, "data": state_dict, ...}
        # Extract actual state from 'data' field if present
        if "data" in state and isinstance(state["data"], dict):
            state = state["data"]

        # Validate required fields for archival
        if "conversation_id" not in state:
            logger.warning(f"Checkpoint {key} missing 'conversation_id' field, skipping")
            return None

        if "messages" not in state or not isinstance(state["messages"], list):
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


def _parse_message_timestamp(timestamp_str: Any) -> datetime:
    """Parse a message timestamp from various formats, defaulting to now."""
    if timestamp_str is None:
        return datetime.now(TIMEZONE)

    if isinstance(timestamp_str, datetime):
        return timestamp_str if timestamp_str.tzinfo else timestamp_str.replace(tzinfo=TIMEZONE)

    if isinstance(timestamp_str, str):
        try:
            ts = datetime.fromisoformat(timestamp_str)
            return ts if ts.tzinfo else ts.replace(tzinfo=TIMEZONE)
        except (ValueError, TypeError):
            pass

    return datetime.now(TIMEZONE)


async def upsert_conversation_to_db(
    session: AsyncSession,
    state: dict[str, Any],
) -> int:
    """
    Upsert a conversation into the two-table schema (ConversationHistory + ConversationMessage).

    Strategy:
        1. Get-or-create ConversationHistory parent by conversation_id (unique constraint).
        2. Insert ConversationMessage children, skipping duplicates via
           (conversation_history_id, role, content, created_at) comparison.
        3. Update parent aggregate fields: started_at, ended_at, message_count, summary.

    Args:
        session: SQLAlchemy async session
        state: Parsed checkpoint state dict containing:
            - conversation_id (str)
            - customer_id (UUID | None)
            - messages (list[dict])
            - conversation_summary (str | None)

    Returns:
        Number of new ConversationMessage rows inserted.

    Raises:
        Exception: If database operations fail (caller handles retries).
    """
    conversation_id: str = state["conversation_id"]
    customer_id = state.get("customer_id")
    messages: list[dict[str, Any]] = state.get("messages", [])
    conversation_summary: str | None = state.get("conversation_summary")

    if not messages and not conversation_summary:
        logger.warning(f"No messages or summary to archive for conversation {conversation_id}")
        return 0

    # -------------------------------------------------------------------------
    # Step 1: Get-or-create ConversationHistory parent
    # -------------------------------------------------------------------------
    result = await session.execute(
        select(ConversationHistory).where(ConversationHistory.conversation_id == conversation_id)
    )
    parent: ConversationHistory | None = result.scalar_one_or_none()

    if parent is None:
        parent = ConversationHistory(
            customer_id=customer_id,
            conversation_id=conversation_id,
            message_count=0,
            metadata_={},
        )
        session.add(parent)
        await session.flush()  # populate parent.id without committing
        logger.debug(f"Created ConversationHistory parent for {conversation_id}")
    else:
        # Update customer_id if we now know it (was None on first insert)
        if parent.customer_id is None and customer_id is not None:
            parent.customer_id = customer_id

    # -------------------------------------------------------------------------
    # Step 2: Load existing message fingerprints to enable idempotent inserts
    # -------------------------------------------------------------------------
    existing_result = await session.execute(
        select(
            ConversationMessage.role,
            ConversationMessage.content,
            ConversationMessage.created_at,
        ).where(ConversationMessage.conversation_history_id == parent.id)
    )
    existing_fingerprints: set[tuple[str, str, str]] = {
        (row.role, row.content, row.created_at.isoformat()) for row in existing_result.all()
    }

    # -------------------------------------------------------------------------
    # Step 3: Insert new ConversationMessage children (dedup by fingerprint)
    # -------------------------------------------------------------------------
    inserted_count = 0
    all_timestamps: list[datetime] = []

    for message in messages:
        role = message.get("role", "")
        content = message.get("content", "")
        timestamp = _parse_message_timestamp(message.get("timestamp"))

        if not role or not content:
            logger.warning(f"Skipping message with missing role or content: {message}")
            continue

        # Normalise role to lowercase for storage consistency
        role = role.lower()

        fingerprint = (role, content, timestamp.isoformat())
        if fingerprint in existing_fingerprints:
            logger.debug(
                f"Skipping duplicate message for {conversation_id} at {timestamp.isoformat()}"
            )
            all_timestamps.append(timestamp)
            continue

        msg_record = ConversationMessage(
            conversation_history_id=parent.id,
            role=role,
            content=content,
            created_at=timestamp,
        )
        session.add(msg_record)
        existing_fingerprints.add(fingerprint)
        all_timestamps.append(timestamp)
        inserted_count += 1

    # Store summary in parent (overwrite if archiver runs again with updated summary)
    if conversation_summary:
        parent.summary = conversation_summary
        logger.debug(f"Set conversation summary for {conversation_id}")

    # -------------------------------------------------------------------------
    # Step 4: Update parent aggregate metadata
    # -------------------------------------------------------------------------
    if all_timestamps:
        parent.started_at = min(all_timestamps)
        parent.ended_at = max(all_timestamps)

    # Update message_count to reflect the full count (existing + newly inserted)
    total_count_result = await session.execute(
        select(func.count())
        .select_from(ConversationMessage)
        .where(ConversationMessage.conversation_history_id == parent.id)
    )
    current_db_count = total_count_result.scalar() or 0
    parent.message_count = current_db_count + inserted_count

    await session.commit()

    logger.info(
        f"Archived {inserted_count} new messages for conversation {conversation_id} "
        f"(total in DB: {parent.message_count})"
    )

    return inserted_count


async def archive_checkpoint(
    redis_client: Redis,
    key: str,
    conversation_id: str,
) -> dict[str, Any]:
    """
    Archive a single checkpoint: retrieve, upsert to DB, delete from Redis.

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
    result: dict[str, Any] = {
        "success": False,
        "messages_archived": 0,
        "error": None,
    }

    # Step 1: Retrieve and parse checkpoint
    state = await retrieve_and_parse_checkpoint(redis_client, key)

    if state is None:
        result["error"] = "Failed to retrieve or parse checkpoint"
        return result

    # Step 2: Upsert to database (with retry)
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            async with get_async_session() as session:
                messages_archived = await upsert_conversation_to_db(session, state)
                result["messages_archived"] = messages_archived
                result["success"] = True
            break  # Success, exit retry loop

        except Exception as e:
            if attempt < MAX_RETRY_ATTEMPTS - 1:
                logger.warning(
                    f"Database upsert failed for {conversation_id} (attempt {attempt + 1}/{MAX_RETRY_ATTEMPTS}), retrying: {e}"
                )
                await asyncio.sleep(RETRY_DELAY_SECONDS)
            else:
                logger.error(
                    f"Failed to archive {conversation_id} after {MAX_RETRY_ATTEMPTS} attempts, skipping: {e}",
                    exc_info=True,
                )
                result["error"] = f"Database upsert failed after {MAX_RETRY_ATTEMPTS} attempts"
                return result  # Skip deletion from Redis

    # Step 3: Delete ALL Redis checkpoint key families for this conversation_id.
    # Uses the shared async helper for dual-scan (v2: + bare) including checkpoint_latest:.
    # Does NOT delete batcher:pending — that belongs to the delete endpoint, not the archiver.
    if result["success"]:
        try:
            from shared.redis_client import get_redis_client
            from shared.redis_conversation_cleanup import cleanup_conversation_redis_keys

            async_redis = get_redis_client()
            cleanup = await cleanup_conversation_redis_keys(
                async_redis,
                conversation_id,
                include_batcher=False,
            )
            if cleanup.total_deleted > 0:
                logger.info(
                    f"Deleted {cleanup.total_deleted} Redis keys for conversation {conversation_id}",
                    extra={"by_family": cleanup.by_family},
                )
            else:
                logger.warning(f"No Redis keys found for conversation {conversation_id}")
            if cleanup.errors:
                logger.error(f"Redis cleanup errors for {conversation_id}: {cleanup.errors}")
        except Exception as e:
            logger.error(
                f"Error deleting Redis keys for conversation {conversation_id}: {e}", exc_info=True
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
        "last_heartbeat": time.time(),
        "last_run": last_run.isoformat(),
        "status": status,
        "checkpoints_archived": checkpoints_archived,
        "messages_archived": messages_archived,
        "errors": errors,
    }

    # Write health check file atomically (temp file + rename)
    health_dir = Path("/tmp/health")
    health_dir.mkdir(parents=True, exist_ok=True)
    health_file = health_dir / "archiver_health.json"
    temp_file = health_dir / f"archiver_health.{int(time.time())}.tmp"

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
           - Upserts ConversationHistory parent + ConversationMessage children
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
                status="healthy",
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

            if result["success"]:
                checkpoints_archived += 1
                messages_archived += result["messages_archived"]
            else:
                errors += 1
                logger.error(f"Failed to archive {conversation_id}: {result['error']}")

        # Step 3: Log summary statistics
        end_time = datetime.now(TIMEZONE)
        duration = (end_time - start_time).total_seconds()

        logger.info(
            f"Completed archival run in {duration:.2f}s",
            extra={
                "checkpoints_found": checkpoints_found,
                "checkpoints_archived": checkpoints_archived,
                "messages_archived": messages_archived,
                "errors": errors,
                "duration_seconds": duration,
            },
        )

        # Step 4: Update health check file
        status = "healthy" if errors == 0 else "unhealthy"
        await update_health_check(
            last_run=end_time,
            status=status,
            checkpoints_archived=checkpoints_archived,
            messages_archived=messages_archived,
            errors=errors,
        )

    except RedisConnectionError as e:
        logger.critical(
            f"Redis connection failed, archival worker cannot proceed: {e}", exc_info=True
        )
        await update_health_check(
            last_run=datetime.now(TIMEZONE),
            status="unhealthy",
            checkpoints_archived=checkpoints_archived,
            messages_archived=messages_archived,
            errors=errors + 1,
        )
        raise

    except Exception as e:
        logger.exception(f"Unexpected error in archival worker: {e}")
        await update_health_check(
            last_run=datetime.now(TIMEZONE),
            status="unhealthy",
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
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
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
    schedule.every().hour.at(":00").do(lambda: asyncio.run(archive_expired_conversations()))

    logger.info("Archival worker scheduled (hourly at :00)")

    # Run scheduler loop
    while not shutdown_requested:
        # Refresh heartbeat every iteration (every 60s) to keep health check fresh during idle
        asyncio.run(
            update_health_check(
                last_run=datetime.now(TIMEZONE),
                status="healthy",
                checkpoints_archived=0,
                messages_archived=0,
                errors=0,
            )
        )
        schedule.run_pending()
        time.sleep(60)  # Check every minute

    logger.info("Archival worker shutting down gracefully")


if __name__ == "__main__":
    run_archival_worker()

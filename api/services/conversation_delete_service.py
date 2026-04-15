"""
Delete service for conversations — Phase 2 of conversation-management change.

Handles atomic deletion of a conversation from both PostgreSQL (parent + child
messages via CASCADE) and Redis (all checkpoint key families for the thread).

Architecture:
    1. Load ConversationHistory parent by UUID PK
    2. DELETE parent (CASCADE removes all ConversationMessage children)
    3. SCAN Redis for all LangGraph checkpoint key families matching thread_id
    4. Pipeline-delete all found Redis keys
    5. Return DeleteResult with per-step outcomes

Error Strategy:
    - DB failure → early return (db_deleted=False, redis_status="skipped")
    - Redis failure → partial success (db_deleted=True, redis_status="error")
    - Redis no keys → acceptable (db_deleted=True, redis_status="no_keys_found")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import ConversationHistory

logger = logging.getLogger(__name__)

# LangGraph AsyncRedisSaver key families — NO "langgraph:" prefix.
# Verified against running Redis instance: actual key patterns are:
#   checkpoint_latest:{thread_id}:__empty__          (latest checkpoint pointer)
#   checkpoint:{thread_id}:__empty__:{uuid}          (checkpoint states)
#   checkpoint_write:{thread_id}:__empty__:{uuid}:{uuid}:{step}  (write records)
#   write_keys_zset:{thread_id}:__empty__:{uuid}     (sorted set index)
_REDIS_KEY_FAMILIES = [
    "checkpoint_latest:{thread_id}:*",
    "checkpoint:{thread_id}:*",
    "checkpoint_write:{thread_id}:*",
    "write_keys_zset:{thread_id}:*",
]

# Number of keys to request per SCAN cursor iteration
_SCAN_COUNT = 200


@dataclass
class DeleteResult:
    """
    Outcome of a single delete_conversation() call.

    Fields:
        conversation_uuid: The UUID PK of the deleted ConversationHistory row.
        thread_id:         The conversation_id string (LangGraph thread_id) used for Redis cleanup.
        db_deleted:        True if the DB row was successfully deleted.
        redis_keys_deleted: Total number of Redis keys removed.
        redis_status:      One of "cleaned", "no_keys_found", "skipped", "error".
        error:             Human-readable error description (None on full success).
    """

    conversation_uuid: UUID
    thread_id: str
    db_deleted: bool
    redis_keys_deleted: int
    redis_status: str  # "cleaned" | "no_keys_found" | "skipped" | "error"
    error: str | None = field(default=None)


async def delete_conversation(
    conversation_uuid: UUID,
    session: AsyncSession,
    redis_client,  # redis.asyncio.Redis (decode_responses=True or False — both work)
) -> DeleteResult:
    """
    Delete a conversation from PostgreSQL and clean up all Redis checkpoint keys.

    The DB deletion is done within the provided session (caller controls the
    transaction boundary). Redis cleanup is best-effort: a Redis failure does NOT
    roll back the DB deletion.

    Args:
        conversation_uuid: UUID primary key of the ConversationHistory parent row.
        session:           Active async SQLAlchemy session.
        redis_client:      Async Redis client (from shared.redis_client.get_redis_client()).

    Returns:
        DeleteResult describing what happened in each step.

    Raises:
        Does NOT raise. All errors are captured into DeleteResult.error.
    """
    # -------------------------------------------------------------------------
    # Step 1: Load the parent ConversationHistory by UUID PK
    # -------------------------------------------------------------------------
    try:
        record = await session.get(ConversationHistory, conversation_uuid)
    except Exception as exc:
        logger.error(
            "conversation_delete_service: DB lookup failed",
            extra={"conversation_uuid": str(conversation_uuid), "error": str(exc)},
            exc_info=True,
        )
        return DeleteResult(
            conversation_uuid=conversation_uuid,
            thread_id="<unknown>",
            db_deleted=False,
            redis_keys_deleted=0,
            redis_status="skipped",
            error=f"DB lookup failed: {exc}",
        )

    if record is None:
        logger.warning(
            "conversation_delete_service: record not found",
            extra={"conversation_uuid": str(conversation_uuid)},
        )
        return DeleteResult(
            conversation_uuid=conversation_uuid,
            thread_id="<not_found>",
            db_deleted=False,
            redis_keys_deleted=0,
            redis_status="skipped",
            error="ConversationHistory not found",
        )

    thread_id: str = record.conversation_id  # the LangGraph thread_id string

    # -------------------------------------------------------------------------
    # Step 2: DELETE the parent — CASCADE removes ConversationMessage children
    # -------------------------------------------------------------------------
    try:
        await session.delete(record)
        await session.commit()
        logger.info(
            "conversation_delete_service: DB deleted",
            extra={"conversation_uuid": str(conversation_uuid), "thread_id": thread_id},
        )
    except Exception as exc:
        await session.rollback()
        logger.error(
            "conversation_delete_service: DB delete failed",
            extra={"conversation_uuid": str(conversation_uuid), "thread_id": thread_id, "error": str(exc)},
            exc_info=True,
        )
        return DeleteResult(
            conversation_uuid=conversation_uuid,
            thread_id=thread_id,
            db_deleted=False,
            redis_keys_deleted=0,
            redis_status="skipped",
            error=f"DB delete failed: {exc}",
        )

    # -------------------------------------------------------------------------
    # Step 3: SCAN + DELETE all Redis checkpoint key families for this thread_id
    # -------------------------------------------------------------------------
    redis_keys_deleted = 0

    try:
        all_keys: list[bytes | str] = []

        for family_template in _REDIS_KEY_FAMILIES:
            pattern = family_template.replace("{thread_id}", thread_id)
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(cursor, match=pattern, count=_SCAN_COUNT)
                if keys:
                    all_keys.extend(keys)
                if cursor == 0:
                    break

        if all_keys:
            # Pipeline batch delete for efficiency
            pipe = redis_client.pipeline(transaction=False)
            for key in all_keys:
                pipe.delete(key)
            results = await pipe.execute()
            redis_keys_deleted = sum(int(r) for r in results if r)
            redis_status = "cleaned"
            logger.info(
                "conversation_delete_service: Redis keys deleted",
                extra={
                    "thread_id": thread_id,
                    "keys_found": len(all_keys),
                    "keys_deleted": redis_keys_deleted,
                },
            )
        else:
            redis_status = "no_keys_found"
            logger.debug(
                "conversation_delete_service: no Redis keys found",
                extra={"thread_id": thread_id},
            )

    except Exception as exc:
        logger.error(
            "conversation_delete_service: Redis cleanup failed (DB already deleted)",
            extra={"thread_id": thread_id, "error": str(exc)},
            exc_info=True,
        )
        return DeleteResult(
            conversation_uuid=conversation_uuid,
            thread_id=thread_id,
            db_deleted=True,
            redis_keys_deleted=0,
            redis_status="error",
            error=f"Redis cleanup failed: {exc}",
        )

    return DeleteResult(
        conversation_uuid=conversation_uuid,
        thread_id=thread_id,
        db_deleted=True,
        redis_keys_deleted=redis_keys_deleted,
        redis_status=redis_status,
    )

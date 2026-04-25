"""
Redis conversation cleanup helper.

Provides a single async helper that knows the canonical LangGraph checkpoint
key families and deletes all Redis state for a given conversation ID.

Supports both v2:{cid} and bare {cid} thread-id forms via dual SCAN so that
both active (v2-prefixed) and legacy (bare) checkpoints are cleaned up.

Usage:
    from shared.redis_conversation_cleanup import cleanup_conversation_redis_keys

    result = await cleanup_conversation_redis_keys(redis_client, conversation_id)
    print(f"Deleted {result.total_deleted} keys")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# LangGraph AsyncRedisSaver checkpoint key families (no leading prefix).
# Each family is scanned under both "v2:{cid}" and bare "{cid}" forms.
_CHECKPOINT_FAMILIES = (
    "checkpoint_latest",
    "checkpoint",
    "checkpoint_write",
    "write_keys_zset",
)

_SCAN_COUNT = 200


@dataclass
class CleanupResult:
    """
    Outcome of a cleanup_conversation_redis_keys() call.

    Fields:
        total_deleted: Total number of Redis keys removed.
        by_family:     Per-family deletion counts.
                       Key format: "{family}:{prefix}" e.g. "checkpoint:v2" or "checkpoint".
        errors:        List of error descriptions captured during cleanup.
                       Empty on full success. Never raises — errors go here instead.
    """

    total_deleted: int
    by_family: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


async def cleanup_conversation_redis_keys(
    redis_client: Redis,
    conversation_id: str,
    *,
    include_batcher: bool = True,
) -> CleanupResult:
    """
    Delete all Redis state for a conversation.

    Scans both ``v2:{conversation_id}`` and bare ``{conversation_id}`` forms
    for each of the 4 LangGraph checkpoint key families, then optionally deletes
    ``batcher:pending:{conversation_id}``.

    The DELETE is pipelined (non-transactional) for efficiency.

    Args:
        redis_client:    Async Redis client (``redis.asyncio.Redis``).
        conversation_id: Bare conversation ID — no ``v2:`` prefix.
        include_batcher: When True (default), also delete ``batcher:pending:{cid}``.
                         Set to False for archiver cleanup (archiver is not
                         responsible for live batching state).

    Returns:
        CleanupResult with counts and any captured errors.

    Guarantees:
        - Idempotent: zero matching keys is a valid result (total_deleted=0).
        - Never raises: all exceptions are captured into CleanupResult.errors.
    """
    all_keys: list[str | bytes] = []
    by_family: dict[str, int] = {}
    errors: list[str] = []

    # --- Scan 4 checkpoint families under both v2: and bare prefixes ---
    for family in _CHECKPOINT_FAMILIES:
        for prefix, label in [
            (f"v2:{conversation_id}", f"{family}:v2"),
            (conversation_id, family),
        ]:
            pattern = f"{family}:{prefix}:*"
            family_keys: list[str | bytes] = []
            try:
                async for key in redis_client.scan_iter(match=pattern, count=_SCAN_COUNT):
                    family_keys.append(key)
            except Exception as exc:
                msg = f"scan_iter failed for pattern '{pattern}': {exc}"
                logger.warning(msg)
                errors.append(msg)
                continue

            if family_keys:
                all_keys.extend(family_keys)
                by_family[label] = by_family.get(label, 0) + len(family_keys)

    # --- Optionally add batcher:pending:{cid} (bare only, no v2 prefix) ---
    if include_batcher:
        batcher_key = f"batcher:pending:{conversation_id}"
        try:
            if await redis_client.exists(batcher_key):
                all_keys.append(batcher_key)
                by_family["batcher:pending"] = 1
        except Exception as exc:
            msg = f"exists check failed for batcher key: {exc}"
            logger.warning(msg)
            errors.append(msg)

    if not all_keys:
        logger.debug(
            "redis_conversation_cleanup: no keys found",
            extra={"conversation_id": conversation_id},
        )
        return CleanupResult(total_deleted=0, by_family=by_family, errors=errors)

    # --- Pipelined DELETE ---
    try:
        pipe = redis_client.pipeline(transaction=False)
        for key in all_keys:
            pipe.delete(key)
        results = await pipe.execute()
        total_deleted = sum(int(r) for r in results if r)
    except Exception as exc:
        msg = f"pipeline DELETE failed: {exc}"
        logger.error(msg)
        errors.append(msg)
        return CleanupResult(total_deleted=0, by_family=by_family, errors=errors)

    logger.info(
        "redis_conversation_cleanup: deleted keys",
        extra={
            "conversation_id": conversation_id,
            "total_deleted": total_deleted,
            "by_family": by_family,
        },
    )
    return CleanupResult(total_deleted=total_deleted, by_family=by_family, errors=errors)

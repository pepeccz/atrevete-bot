"""
Unit tests for cleanup_conversation_redis_keys — pending_injection key cleanup.

Task 1.2: Verify that cleanup_conversation_redis_keys deletes the
``pending_injection:v2:{conversation_id}`` Redis key when it exists.

RED phase: this test FAILS until the key is added to the cleanup helper (Task 1.3).
"""

import pytest
import fakeredis.aioredis as fakeredis_async

from shared.redis_conversation_cleanup import cleanup_conversation_redis_keys


@pytest.mark.asyncio
async def test_cleanup_deletes_pending_injection_key():
    """
    GIVEN a Redis instance with a pending_injection:v2:{cid} key set
    WHEN cleanup_conversation_redis_keys is called with that conversation_id
    THEN the pending_injection:v2:{cid} key must be deleted.
    """
    redis = fakeredis_async.FakeRedis()
    cid = "conv-cleanup-test"

    # Set the pending_injection key (mimics /resume endpoint)
    pending_key = f"pending_injection:v2:{cid}"
    await redis.set(pending_key, "1", ex=600)

    result = await cleanup_conversation_redis_keys(redis, cid, include_batcher=True)

    # The key must be gone
    remaining = await redis.keys("*")
    assert pending_key not in [
        k.decode() if isinstance(k, bytes) else k for k in remaining
    ], f"pending_injection key was NOT deleted. Remaining: {remaining}"

    # Cleanup result must account for the deleted key
    assert result.total_deleted >= 1, (
        f"Expected at least 1 key deleted, got {result.total_deleted}"
    )
    assert not result.errors, f"Unexpected errors: {result.errors}"


@pytest.mark.asyncio
async def test_cleanup_pending_injection_absent_is_noop():
    """
    GIVEN a Redis instance with NO pending_injection key
    WHEN cleanup_conversation_redis_keys is called
    THEN no error is raised and total_deleted remains 0 (nothing to delete).
    """
    redis = fakeredis_async.FakeRedis()
    cid = "conv-no-injection"

    result = await cleanup_conversation_redis_keys(redis, cid, include_batcher=True)

    assert result.total_deleted == 0
    assert not result.errors


@pytest.mark.asyncio
async def test_cleanup_pending_injection_alongside_checkpoint_keys():
    """
    GIVEN a Redis instance with checkpoint keys AND a pending_injection key
    WHEN cleanup_conversation_redis_keys is called
    THEN ALL keys are deleted (checkpoints + pending_injection).
    """
    redis = fakeredis_async.FakeRedis()
    cid = "conv-full-cleanup"

    # Seed checkpoint keys
    await redis.set(f"checkpoint_latest:v2:{cid}:__empty__", "1")
    await redis.set(f"checkpoint:v2:{cid}:__empty__:uuid1", "1")
    # Seed pending_injection
    await redis.set(f"pending_injection:v2:{cid}", "1", ex=600)

    result = await cleanup_conversation_redis_keys(redis, cid, include_batcher=True)

    remaining = await redis.keys("*")
    assert len(remaining) == 0, f"Keys still present after cleanup: {remaining}"
    assert result.total_deleted >= 3
    assert not result.errors

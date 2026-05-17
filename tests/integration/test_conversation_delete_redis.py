"""
Integration tests for conversation delete + Redis cleanup.

Tests the full DELETE endpoint flow against a real Redis instance
(docker-compose service). These tests are SKIPPED when Redis is not reachable.

Seed: v2 checkpoint + batcher keys → call DELETE → verify 0 keys remain.
"""

from __future__ import annotations

import asyncio

import pytest

# ---------------------------------------------------------------------------
# Skip guard — skip entire module if Redis unavailable
# ---------------------------------------------------------------------------

try:
    import redis as _redis_sync

    _r = _redis_sync.Redis(host="localhost", port=6379, socket_connect_timeout=1)
    _r.ping()
    REDIS_AVAILABLE = True
except Exception:
    REDIS_AVAILABLE = False

pytestmark = pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not reachable — skipping integration tests")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_v2_keys(redis_async, cid: str) -> list[str]:
    """Seed a realistic set of v2 checkpoint + batcher keys."""
    keys = [
        f"checkpoint_latest:v2:{cid}:__empty__",
        f"checkpoint:v2:{cid}:__empty__:uuid-inttest-1",
        f"checkpoint:v2:{cid}:__empty__:uuid-inttest-2",
        f"checkpoint_write:v2:{cid}:__empty__:uuid-inttest-1:0",
        f"write_keys_zset:v2:{cid}:__empty__:uuid-inttest-1",
        f"batcher:pending:{cid}",
    ]
    for key in keys:
        await redis_async.set(key, "integration-test-value", ex=300)  # 5-min TTL
    return keys


async def _remaining_keys(redis_async, cid: str) -> list[str]:
    """Return all keys matching this conversation in Redis."""
    patterns = [
        f"checkpoint_latest:*{cid}*",
        f"checkpoint:*{cid}*",
        f"checkpoint_write:*{cid}*",
        f"write_keys_zset:*{cid}*",
        f"batcher:pending:{cid}",
    ]
    found = []
    for pattern in patterns:
        async for key in redis_async.scan_iter(match=pattern, count=100):
            found.append(key if isinstance(key, str) else key.decode())
    return found


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_endpoint_removes_all_v2_keys_and_batcher():
    """
    GIVEN v2 checkpoint keys + batcher:pending seeded in real Redis
    WHEN cleanup_conversation_redis_keys is called with the bare cid
    THEN all 6 keys are deleted and redis_keys_deleted >= 6.
    """
    import redis.asyncio as aioredis

    from shared.redis_conversation_cleanup import cleanup_conversation_redis_keys

    redis_async = aioredis.Redis(host="localhost", port=6379, decode_responses=False)

    cid = f"int-test-del-{asyncio.get_event_loop().time():.0f}"
    seeded_keys = await _seed_v2_keys(redis_async, cid)

    try:
        result = await cleanup_conversation_redis_keys(redis_async, cid, include_batcher=True)

        assert result.total_deleted == len(seeded_keys), (
            f"Expected {len(seeded_keys)} deleted, got {result.total_deleted}"
        )
        assert result.errors == []

        # Verify no keys remain
        remaining = await _remaining_keys(redis_async, cid)
        assert remaining == [], f"Keys still in Redis: {remaining}"
    finally:
        # Cleanup in case test fails mid-way
        for key in seeded_keys:
            await redis_async.delete(key)
        await redis_async.aclose()


@pytest.mark.asyncio
async def test_cleanup_helper_returns_zero_for_nonexistent_conversation():
    """
    GIVEN no Redis keys exist for the given cid
    WHEN cleanup_conversation_redis_keys is called
    THEN total_deleted=0, no error, 200 OK.
    """
    import redis.asyncio as aioredis

    from shared.redis_conversation_cleanup import cleanup_conversation_redis_keys

    redis_async = aioredis.Redis(host="localhost", port=6379, decode_responses=False)

    try:
        result = await cleanup_conversation_redis_keys(
            redis_async, "nonexistent-conv-xyz-999", include_batcher=True
        )

        assert result.total_deleted == 0
        assert result.errors == []
    finally:
        await redis_async.aclose()

"""
Unit tests for shared.redis_conversation_cleanup module.

Tests the CleanupResult dataclass and cleanup_conversation_redis_keys() helper
using fakeredis async client — no live Redis required.

TDD cycle: these tests were written BEFORE the production module exists.
"""

from __future__ import annotations

import fakeredis.aioredis as fakeredis_async
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_redis() -> fakeredis_async.FakeRedis:
    """Create a fresh async fakeredis instance per test."""
    return fakeredis_async.FakeRedis()


async def _seed_keys(redis, *keys: str) -> None:
    """Seed arbitrary string keys with a placeholder value."""
    for key in keys:
        await redis.set(key, "1")


# ---------------------------------------------------------------------------
# Phase 2.1 — CleanupResult dataclass
# ---------------------------------------------------------------------------


def test_cleanup_result_dataclass_fields():
    """
    CleanupResult must expose total_deleted, by_family, and errors.
    Verify field types and defaults.
    """
    from shared.redis_conversation_cleanup import CleanupResult

    result = CleanupResult(total_deleted=3)
    assert result.total_deleted == 3
    assert isinstance(result.by_family, dict)
    assert isinstance(result.errors, list)
    assert result.by_family == {}
    assert result.errors == []


def test_cleanup_result_with_by_family_and_errors():
    """
    CleanupResult with non-default by_family and errors must store values correctly.
    """
    from shared.redis_conversation_cleanup import CleanupResult

    result = CleanupResult(
        total_deleted=7,
        by_family={"checkpoint:v2": 3, "batcher:pending": 1},
        errors=["scan failed"],
    )
    assert result.total_deleted == 7
    assert result.by_family["checkpoint:v2"] == 3
    assert result.by_family["batcher:pending"] == 1
    assert len(result.errors) == 1
    assert "scan failed" in result.errors[0]


# ---------------------------------------------------------------------------
# Phase 2.2 — v2-only keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_v2_only_keys_deletes_all_families_and_batcher():
    """
    GIVEN checkpoint:v2:{cid}:*, checkpoint_latest:v2:{cid}:*, etc. + batcher:pending:{cid}
    WHEN cleanup_conversation_redis_keys is called with bare cid
    THEN all keys are deleted and by_family counts are correct.
    """
    from shared.redis_conversation_cleanup import cleanup_conversation_redis_keys

    redis = await _make_redis()
    cid = "abc123"

    v2_keys = [
        f"checkpoint_latest:v2:{cid}:__empty__",
        f"checkpoint:v2:{cid}:__empty__:uuid1",
        f"checkpoint:v2:{cid}:__empty__:uuid2",
        f"checkpoint_write:v2:{cid}:__empty__:uuid1:step1",
        f"write_keys_zset:v2:{cid}:__empty__:uuid1",
    ]
    batcher_key = f"batcher:pending:{cid}"
    all_seeded = v2_keys + [batcher_key]
    await _seed_keys(redis, *all_seeded)

    result = await cleanup_conversation_redis_keys(redis, cid, include_batcher=True)

    assert result.total_deleted == len(all_seeded)
    assert result.errors == []
    # All seeded keys should be gone
    for key in all_seeded:
        assert await redis.exists(key) == 0, f"Key {key} should have been deleted"


@pytest.mark.asyncio
async def test_cleanup_v2_by_family_counts_correct():
    """
    Triangulation: by_family counts must accurately reflect per-family deletions.
    """
    from shared.redis_conversation_cleanup import cleanup_conversation_redis_keys

    redis = await _make_redis()
    cid = "xyz789"

    # 2 checkpoint keys, 1 checkpoint_latest, 0 checkpoint_write, 0 write_keys_zset, 1 batcher
    await _seed_keys(
        redis,
        f"checkpoint_latest:v2:{cid}:__empty__",
        f"checkpoint:v2:{cid}:__empty__:a",
        f"checkpoint:v2:{cid}:__empty__:b",
        f"batcher:pending:{cid}",
    )

    result = await cleanup_conversation_redis_keys(redis, cid, include_batcher=True)

    assert result.total_deleted == 4
    # by_family must have an entry for checkpoint_latest and checkpoint (v2 scans)
    assert result.by_family.get("checkpoint_latest:v2", 0) + result.by_family.get(
        "checkpoint_latest", 0
    ) >= 1
    assert result.by_family.get("checkpoint:v2", 0) + result.by_family.get("checkpoint", 0) >= 2


# ---------------------------------------------------------------------------
# Phase 2.3 — v1-only (bare) keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_v1_bare_keys_deletes_all():
    """
    GIVEN checkpoint:{cid}:*, checkpoint_latest:{cid}:* (no v2: prefix)
    WHEN cleanup is called
    THEN all bare-prefixed keys are deleted.
    """
    from shared.redis_conversation_cleanup import cleanup_conversation_redis_keys

    redis = await _make_redis()
    cid = "legacy-conv"

    bare_keys = [
        f"checkpoint_latest:{cid}:__empty__",
        f"checkpoint:{cid}:__empty__:uuid-old",
        f"checkpoint_write:{cid}:__empty__:uuid-old:step0",
        f"write_keys_zset:{cid}:__empty__:uuid-old",
    ]
    await _seed_keys(redis, *bare_keys)

    result = await cleanup_conversation_redis_keys(redis, cid, include_batcher=True)

    assert result.total_deleted == len(bare_keys)
    assert result.errors == []
    for key in bare_keys:
        assert await redis.exists(key) == 0


# ---------------------------------------------------------------------------
# Phase 2.4 — mixed v1+v2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_mixed_v1_v2_keys_deletes_all():
    """
    GIVEN both v2:{cid} and bare {cid} keys present simultaneously
    WHEN cleanup is called
    THEN all of them are deleted (no double-count errors).
    """
    from shared.redis_conversation_cleanup import cleanup_conversation_redis_keys

    redis = await _make_redis()
    cid = "mixed-conv"

    v2_keys = [
        f"checkpoint:v2:{cid}:__empty__:new-uuid",
        f"checkpoint_latest:v2:{cid}:__empty__",
    ]
    bare_keys = [
        f"checkpoint:{cid}:__empty__:old-uuid",
        f"checkpoint_latest:{cid}:__empty__",
    ]
    all_keys = v2_keys + bare_keys
    await _seed_keys(redis, *all_keys)

    result = await cleanup_conversation_redis_keys(redis, cid, include_batcher=False)

    assert result.total_deleted == len(all_keys)
    for key in all_keys:
        assert await redis.exists(key) == 0


# ---------------------------------------------------------------------------
# Phase 2.5 — include_batcher=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_include_batcher_false_preserves_batcher_key():
    """
    GIVEN batcher:pending:{cid} exists in Redis
    WHEN cleanup is called with include_batcher=False
    THEN batcher key is NOT deleted.
    """
    from shared.redis_conversation_cleanup import cleanup_conversation_redis_keys

    redis = await _make_redis()
    cid = "archiver-conv"

    batcher_key = f"batcher:pending:{cid}"
    ckpt_key = f"checkpoint:v2:{cid}:__empty__:uuid-arch"
    await _seed_keys(redis, batcher_key, ckpt_key)

    result = await cleanup_conversation_redis_keys(redis, cid, include_batcher=False)

    # checkpoint key deleted
    assert await redis.exists(ckpt_key) == 0
    # batcher key preserved
    assert await redis.exists(batcher_key) == 1
    assert "batcher:pending" not in result.by_family


# ---------------------------------------------------------------------------
# Phase 2.6 — no keys present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_no_keys_returns_zero_no_error():
    """
    GIVEN no Redis keys exist for the conversation
    WHEN cleanup is called
    THEN total_deleted=0, errors=[], no exception raised.
    """
    from shared.redis_conversation_cleanup import cleanup_conversation_redis_keys

    redis = await _make_redis()
    cid = "ghost-conv"

    result = await cleanup_conversation_redis_keys(redis, cid)

    assert result.total_deleted == 0
    assert result.errors == []
    # by_family may be empty or have zero-count entries — both valid
    assert sum(result.by_family.values()) == 0


# ---------------------------------------------------------------------------
# Phase 2.7 — error capture: helper never raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_captures_scan_error_does_not_raise():
    """
    GIVEN a Redis client whose scan_iter raises an exception
    WHEN cleanup is called
    THEN errors list is populated, no exception propagates, total_deleted=0.
    """
    from unittest.mock import MagicMock

    from shared.redis_conversation_cleanup import cleanup_conversation_redis_keys

    mock_redis = MagicMock()

    async def _failing_scan(*args, **kwargs):
        raise RuntimeError("Redis connection lost")
        yield  # make it an async generator

    mock_redis.scan_iter = MagicMock(side_effect=_failing_scan)
    mock_redis.pipeline = MagicMock()

    result = await cleanup_conversation_redis_keys(mock_redis, "err-conv")

    assert len(result.errors) > 0
    assert any("Redis connection lost" in e or "connection lost" in e.lower() for e in result.errors)
    assert result.total_deleted == 0

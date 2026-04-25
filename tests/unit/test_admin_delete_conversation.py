"""
Unit tests for DELETE /api/admin/conversations/{conversation_uuid} endpoint.

Tests cover the three main scenarios for the redis: prefix (active conversation) path:

1. Redis keys found → successful Redis-only delete (happy path)
2. Redis keys NOT found, DB record found → DB fallback delete, returns db_deleted=True
3. Redis keys NOT found, DB record NOT found → HTTPException 404

All tests use mocks — no live Redis or PostgreSQL required.

Patching strategy:
- `shared.redis_client.get_redis_client` — patched at source because the
  endpoint imports it lazily inside the function body.
- `api.services.conversation_delete_service.delete_conversation` — same reason.
- `api.routes.admin.get_async_session` — top-level import, so patched normally.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_async_generator(items: list):
    """Return an async generator that yields items from a list."""
    async def _gen():
        for item in items:
            yield item
    return _gen()


def _build_redis_mock(keys_per_pattern: list | None = None, all_keys: list | None = None):
    """
    Build a MagicMock Redis client whose scan_iter yields keys per call.

    The endpoint calls scan_iter once per Redis key pattern (3 patterns total).
    Use `all_keys` to provide a flat list that is split evenly across 3 calls,
    or `keys_per_pattern` to supply a list of lists (one per scan_iter call).
    When both are None, scan_iter yields nothing (simulates empty Redis).
    """
    mock_redis = MagicMock()

    if all_keys is not None:
        # Split the flat list across the 3 scan_iter calls (one per pattern).
        # Each call gets 1 key so total_collected == len(all_keys).
        per_call = [all_keys[i:i+1] for i in range(len(all_keys))]
        # Pad with empty lists if fewer than len(all_keys) calls happen
        call_index = {"n": 0}

        def _scan_iter_factory(match, count):
            idx = call_index["n"]
            call_index["n"] += 1
            return _make_async_generator(per_call[idx] if idx < len(per_call) else [])

        mock_redis.scan_iter = MagicMock(side_effect=_scan_iter_factory)
        mock_redis.delete = AsyncMock(return_value=len(all_keys))
    elif keys_per_pattern is not None:
        call_index = {"n": 0}

        def _scan_iter_factory(match, count):
            idx = call_index["n"]
            call_index["n"] += 1
            return _make_async_generator(keys_per_pattern[idx] if idx < len(keys_per_pattern) else [])

        mock_redis.scan_iter = MagicMock(side_effect=_scan_iter_factory)
        total = sum(len(kl) for kl in keys_per_pattern)
        mock_redis.delete = AsyncMock(return_value=total)
    else:
        # No keys in Redis
        mock_redis.scan_iter = MagicMock(
            side_effect=lambda match, count: _make_async_generator([])
        )
        mock_redis.delete = AsyncMock(return_value=0)

    return mock_redis


def _build_session_ctx(record):
    """
    Build an async context manager mock for get_async_session().
    The session's execute() returns a result whose scalar_one_or_none() returns `record`.
    """
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = record

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


def _make_db_record(thread_id: str):
    """Build a minimal ConversationHistory-like mock."""
    record = MagicMock()
    record.id = uuid4()
    record.conversation_id = thread_id
    return record


def _make_delete_result(
    db_deleted: bool,
    thread_id: str = "test-thread",
    redis_keys_deleted: int = 0,
    error=None,
):
    """Build a real DeleteResult instance."""
    from api.services.conversation_delete_service import DeleteResult

    return DeleteResult(
        conversation_uuid=uuid4(),
        thread_id=thread_id,
        db_deleted=db_deleted,
        redis_keys_deleted=redis_keys_deleted,
        redis_status="cleaned" if db_deleted else "skipped",
        error=error,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_redis_conversation_keys_found():
    """
    GIVEN a redis:{thread_id} conversation with checkpoint keys in Redis
    WHEN the endpoint is called
    THEN it deletes all keys and returns db_deleted=False, redis_status='cleaned', error=None.

    Updated to use fakeredis (route now delegates to cleanup_conversation_redis_keys
    which does dual-scan v2+bare; the old MagicMock scan_iter approach is insufficient).
    """
    import fakeredis.aioredis as fakeredis_async
    from api.routes.admin import delete_conversation_endpoint

    thread_id = "conv-abc-123"
    conversation_uuid = f"redis:{thread_id}"
    mock_user = {"sub": "admin"}

    redis = fakeredis_async.FakeRedis()
    await redis.set(f"checkpoint:{thread_id}:__empty__:aaa", "1")
    await redis.set(f"checkpoint_write:{thread_id}:__empty__:bbb", "1")
    await redis.set(f"write_keys_zset:{thread_id}:__empty__:ccc", "1")

    with patch("shared.redis_client.get_redis_client", return_value=redis):
        result = await delete_conversation_endpoint(
            conversation_uuid=conversation_uuid,
            current_user=mock_user,
        )

    assert result["db_deleted"] is False
    assert result["redis_status"] == "cleaned"
    assert result["thread_id"] == thread_id
    assert result["error"] is None
    assert result["redis_keys_deleted"] == 3

    remaining = await redis.keys("*")
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_delete_redis_conversation_fallback_to_db_success():
    """
    GIVEN a redis:{thread_id} conversation with NO Redis keys but an existing DB record
    WHEN the endpoint is called
    THEN it falls back to DB delete and returns db_deleted=True, redis_status='already_archived'.
    """
    from api.routes.admin import delete_conversation_endpoint

    thread_id = "conv-archived-456"
    conversation_uuid = f"redis:{thread_id}"
    mock_user = {"sub": "admin"}

    # Redis returns no keys for any pattern
    mock_redis = _build_redis_mock()

    # DB record found during the lookup session
    db_record = _make_db_record(thread_id)
    session_ctx_lookup = _build_session_ctx(db_record)

    # Session context for the actual delete call (just needs to be a valid ctx)
    delete_session = AsyncMock()
    session_ctx_delete = AsyncMock()
    session_ctx_delete.__aenter__ = AsyncMock(return_value=delete_session)
    session_ctx_delete.__aexit__ = AsyncMock(return_value=False)

    # Service returns success
    service_result = _make_delete_result(
        db_deleted=True,
        thread_id=thread_id,
        redis_keys_deleted=0,
    )

    # get_async_session is called twice inside the if-not-all_keys branch:
    # first for the lookup, second for the delete call
    call_count = {"n": 0}

    def _session_factory():
        call_count["n"] += 1
        return session_ctx_lookup if call_count["n"] == 1 else session_ctx_delete

    with (
        patch("shared.redis_client.get_redis_client", return_value=mock_redis),
        patch("api.routes.admin.get_async_session", side_effect=_session_factory),
        # delete_conversation is lazily imported inside the endpoint — patch at source
        patch(
            "api.services.conversation_delete_service.delete_conversation",
            new=AsyncMock(return_value=service_result),
        ),
    ):
        result = await delete_conversation_endpoint(
            conversation_uuid=conversation_uuid,
            current_user=mock_user,
        )

    assert result["db_deleted"] is True
    assert result["redis_status"] == "already_archived"
    assert result["thread_id"] == thread_id
    assert "conversation_uuid" in result
    assert result["error"] is None


@pytest.mark.asyncio
async def test_delete_redis_conversation_not_in_redis_or_db_raises_404():
    """
    GIVEN a redis:{thread_id} conversation with NO Redis keys and NO DB record
    WHEN the endpoint is called
    THEN HTTPException 404 is raised with a "not found" detail.
    """
    from api.routes.admin import delete_conversation_endpoint

    thread_id = "conv-ghost-789"
    conversation_uuid = f"redis:{thread_id}"
    mock_user = {"sub": "admin"}

    # Redis returns no keys
    mock_redis = _build_redis_mock()

    # DB returns None — record doesn't exist
    session_ctx = _build_session_ctx(record=None)

    with (
        patch("shared.redis_client.get_redis_client", return_value=mock_redis),
        patch("api.routes.admin.get_async_session", return_value=session_ctx),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation_endpoint(
                conversation_uuid=conversation_uuid,
                current_user=mock_user,
            )

    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# Phase 4: delete_conversation service — uses cleanup helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_service_uuid_path_v2_keys_deleted():
    """
    GIVEN a ConversationHistory record with conversation_id="testconv"
    AND fakeredis seeded with v2 checkpoint keys + batcher
    WHEN delete_conversation() is called
    THEN all v2 keys and batcher are deleted, redis_keys_deleted >= 5.
    """
    import fakeredis.aioredis as fakeredis_async
    from unittest.mock import AsyncMock
    from uuid import uuid4
    from api.services.conversation_delete_service import delete_conversation

    redis = fakeredis_async.FakeRedis()
    cid = "testconv"

    # Seed v2 keys + batcher
    await redis.set(f"checkpoint_latest:v2:{cid}:__empty__", "1")
    await redis.set(f"checkpoint:v2:{cid}:__empty__:uuid1", "1")
    await redis.set(f"checkpoint:v2:{cid}:__empty__:uuid2", "1")
    await redis.set(f"checkpoint_write:v2:{cid}:__empty__:uuid1:0", "1")
    await redis.set(f"write_keys_zset:v2:{cid}:__empty__:uuid1", "1")
    await redis.set(f"batcher:pending:{cid}", "1")

    conv_uuid = uuid4()

    # Build SQLAlchemy session mock
    mock_record = MagicMock()
    mock_record.conversation_id = cid
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_record)
    mock_session.delete = AsyncMock()
    mock_session.commit = AsyncMock()

    result = await delete_conversation(conv_uuid, mock_session, redis)

    assert result.db_deleted is True
    assert result.redis_keys_deleted >= 5
    assert result.redis_status == "cleaned"
    assert result.error is None

    # All seeded keys must be gone
    remaining = await redis.keys("*")
    assert len(remaining) == 0, f"Keys still present: {remaining}"


@pytest.mark.asyncio
async def test_delete_service_v1_compat_bare_keys():
    """
    GIVEN a ConversationHistory with conversation_id="legacyconv"
    AND fakeredis seeded with bare (v1) checkpoint keys only
    WHEN delete_conversation() is called
    THEN bare keys are deleted, no error raised.
    """
    import fakeredis.aioredis as fakeredis_async
    from unittest.mock import AsyncMock
    from uuid import uuid4
    from api.services.conversation_delete_service import delete_conversation

    redis = fakeredis_async.FakeRedis()
    cid = "legacyconv"

    await redis.set(f"checkpoint:{cid}:__empty__:old-uuid", "1")
    await redis.set(f"checkpoint_write:{cid}:__empty__:old-uuid:0", "1")
    await redis.set(f"write_keys_zset:{cid}:__empty__:old-uuid", "1")
    await redis.set(f"checkpoint_latest:{cid}:__empty__", "1")

    conv_uuid = uuid4()
    mock_record = MagicMock()
    mock_record.conversation_id = cid
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_record)
    mock_session.delete = AsyncMock()
    mock_session.commit = AsyncMock()

    result = await delete_conversation(conv_uuid, mock_session, redis)

    assert result.db_deleted is True
    assert result.redis_keys_deleted == 4
    assert result.error is None

    remaining = await redis.keys("*")
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_delete_service_helper_error_maps_to_redis_status_error():
    """
    GIVEN the cleanup helper returns errors (e.g. Redis failure during scan)
    WHEN delete_conversation() is called
    THEN redis_status="error" is returned and db_deleted remains True.
    """
    from unittest.mock import AsyncMock, MagicMock, patch
    from uuid import uuid4
    from api.services.conversation_delete_service import delete_conversation
    from shared.redis_conversation_cleanup import CleanupResult

    cid = "err-conv"
    conv_uuid = uuid4()
    mock_record = MagicMock()
    mock_record.conversation_id = cid
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_record)
    mock_session.delete = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_redis = MagicMock()

    bad_cleanup = CleanupResult(total_deleted=0, errors=["scan error"])

    with patch(
        "api.services.conversation_delete_service.cleanup_conversation_redis_keys",
        new=AsyncMock(return_value=bad_cleanup),
    ):
        result = await delete_conversation(conv_uuid, mock_session, mock_redis)

    assert result.db_deleted is True
    assert result.redis_status == "error"
    assert result.redis_keys_deleted == 0


# ---------------------------------------------------------------------------
# Phase 5: Admin route — redis:v2:{cid} and redis:{cid} strip prefix correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_redis_v2_prefix_stripped_and_helper_called_with_bare_cid():
    """
    GIVEN conversation_uuid="redis:v2:myconv"
    WHEN the endpoint is called
    THEN the helper is called with bare cid "myconv" (not "v2:myconv").
    AND redis_status='cleaned' is returned.
    """
    import fakeredis.aioredis as fakeredis_async
    from api.routes.admin import delete_conversation_endpoint

    redis = fakeredis_async.FakeRedis()
    cid = "myconv"

    # Seed keys under v2: prefix
    await redis.set(f"checkpoint:v2:{cid}:__empty__:uuid1", "1")
    await redis.set(f"checkpoint_latest:v2:{cid}:__empty__", "1")
    await redis.set(f"batcher:pending:{cid}", "1")

    mock_user = {"sub": "admin"}

    with patch("shared.redis_client.get_redis_client", return_value=redis):
        result = await delete_conversation_endpoint(
            conversation_uuid=f"redis:v2:{cid}",
            current_user=mock_user,
        )

    assert result["redis_status"] == "cleaned"
    assert result["redis_keys_deleted"] >= 3
    assert result["db_deleted"] is False

    remaining = await redis.keys("*")
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_route_redis_bare_cid_still_works():
    """
    GIVEN conversation_uuid="redis:bareconv" (no v2: prefix)
    WHEN the endpoint is called
    THEN the helper is called with bare cid "bareconv".
    AND redis_status='cleaned' is returned.
    """
    import fakeredis.aioredis as fakeredis_async
    from api.routes.admin import delete_conversation_endpoint

    redis = fakeredis_async.FakeRedis()
    cid = "bareconv"

    await redis.set(f"checkpoint:{cid}:__empty__:uuid-bare", "1")
    await redis.set(f"batcher:pending:{cid}", "1")

    mock_user = {"sub": "admin"}

    with patch("shared.redis_client.get_redis_client", return_value=redis):
        result = await delete_conversation_endpoint(
            conversation_uuid=f"redis:{cid}",
            current_user=mock_user,
        )

    assert result["redis_status"] == "cleaned"
    assert result["redis_keys_deleted"] >= 2

    remaining = await redis.keys("*")
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_route_redis_zero_keys_still_returns_200():
    """
    GIVEN conversation_uuid="redis:ghostconv" with NO Redis keys
    AND no DB record found
    WHEN the endpoint is called
    THEN 404 is raised (conversation not found anywhere).
    """
    import fakeredis.aioredis as fakeredis_async
    from fastapi import HTTPException
    from api.routes.admin import delete_conversation_endpoint

    redis = fakeredis_async.FakeRedis()

    # DB returns nothing either
    session_ctx = _build_session_ctx(record=None)
    mock_user = {"sub": "admin"}

    with (
        patch("shared.redis_client.get_redis_client", return_value=redis),
        patch("api.routes.admin.get_async_session", return_value=session_ctx),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation_endpoint(
                conversation_uuid="redis:ghostconv",
                current_user=mock_user,
            )

    assert exc_info.value.status_code == 404

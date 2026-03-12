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
    GIVEN a redis:{thread_id} conversation with 3 Redis keys
    WHEN the endpoint is called
    THEN it deletes all keys and returns db_deleted=False, redis_status='cleaned', error=None.
    """
    from api.routes.admin import delete_conversation_endpoint

    thread_id = "conv-abc-123"
    conversation_uuid = f"redis:{thread_id}"
    mock_user = {"sub": "admin"}

    # One key per pattern (3 patterns × 1 key each = 3 total)
    key_ckpt = f"checkpoint:{thread_id}:__empty__:aaa".encode()
    key_write = f"checkpoint_write:{thread_id}:__empty__:bbb".encode()
    key_zset = f"write_keys_zset:{thread_id}:__empty__:ccc".encode()
    redis_keys = [key_ckpt, key_write, key_zset]

    # keys_per_pattern: one list per scan_iter call (3 patterns in the endpoint)
    mock_redis = _build_redis_mock(keys_per_pattern=[[key_ckpt], [key_write], [key_zset]])

    # get_redis_client is lazily imported inside the endpoint body — patch at source
    with patch("shared.redis_client.get_redis_client", return_value=mock_redis):
        result = await delete_conversation_endpoint(
            conversation_uuid=conversation_uuid,
            current_user=mock_user,
        )

    assert result["db_deleted"] is False
    assert result["redis_status"] == "cleaned"
    assert result["thread_id"] == thread_id
    assert result["error"] is None
    assert result["redis_keys_deleted"] == 3
    # Verify delete was called once with all 3 accumulated keys
    mock_redis.delete.assert_awaited_once_with(*redis_keys)


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

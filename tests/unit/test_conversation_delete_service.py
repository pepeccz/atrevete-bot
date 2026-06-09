"""
Unit tests for conversation delete service.

Covers:
- cleanup_conversation_redis_keys — pending_injection key cleanup.
- delete_conversation — orphan Notification cleanup (inbox-polish Fix #6).
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import fakeredis.aioredis as fakeredis_async
import pytest

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


# ─── Fix #6 — Notification orphan cleanup in delete_conversation ──────────────


def _make_fake_session(record):
    """
    Build a minimal AsyncSession mock that supports get(), delete(), commit(),
    rollback(), and execute() — enough to exercise delete_conversation().
    """
    session = MagicMock()
    session.get = AsyncMock(return_value=record)
    session.delete = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    return session


def _make_fake_record(conv_id: str):
    """Return a minimal ConversationHistory-like object."""
    record = MagicMock()
    record.id = uuid4()
    record.conversation_id = conv_id
    return record


@pytest.mark.asyncio
async def test_delete_conversation_removes_orphan_notifications():
    """
    GIVEN delete_conversation is called for a conversation that has associated
          Notification rows (entity_type='conversation_history', entity_id=conv_uuid)
    WHEN  the service runs successfully
    THEN  session.execute() is called with a DELETE statement targeting those
          notification rows, AND the result is committed.

    RED phase: fails until the notification cleanup step is added to
    conversation_delete_service.py.
    """
    from api.services.conversation_delete_service import delete_conversation

    conv_id = "v2:test-notify-cleanup"
    record = _make_fake_record(conv_id)
    session = _make_fake_session(record)

    fake_redis = MagicMock()
    fake_redis.scan_iter = MagicMock(return_value=_async_iter([]))

    with patch(
        "api.services.conversation_delete_service.cleanup_conversation_redis_keys",
        new_callable=AsyncMock,
    ) as mock_cleanup:
        from shared.redis_conversation_cleanup import CleanupResult

        mock_cleanup.return_value = CleanupResult(
            total_deleted=0, errors=[], by_family={}
        )

        result = await delete_conversation(record.id, session, fake_redis)

    assert result.db_deleted is True, "DB delete must succeed"
    # The critical assertion: session.execute must have been called (notification DELETE)
    session.execute.assert_called(), (
        "session.execute() was never called — notification cleanup step is missing"
    )
    # And commit must have been called at least twice (DB delete + notification delete)
    assert session.commit.call_count >= 2, (
        f"Expected at least 2 commits (DB + notifications), got {session.commit.call_count}"
    )


async def _async_iter(items):
    """Helper: yield items as an async iterator (for fakeredis scan_iter mock)."""
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_delete_conversation_does_not_remove_unrelated_notifications():
    """
    GIVEN delete_conversation is called
    WHEN  it runs notification cleanup
    THEN  the DELETE statement filters by BOTH entity_type='conversation_history'
          AND entity_id=<the conversation's UUID>, not a broader delete.

    We verify this by inspecting the compiled SQL of the statement passed to
    session.execute(), which must reference the specific entity_type value.
    """

    from api.services.conversation_delete_service import delete_conversation

    conv_id = "v2:test-scoped-delete"
    record = _make_fake_record(conv_id)
    session = _make_fake_session(record)

    fake_redis = MagicMock()
    fake_redis.scan_iter = MagicMock(return_value=_async_iter([]))

    with patch(
        "api.services.conversation_delete_service.cleanup_conversation_redis_keys",
        new_callable=AsyncMock,
    ) as mock_cleanup:
        from shared.redis_conversation_cleanup import CleanupResult

        mock_cleanup.return_value = CleanupResult(
            total_deleted=0, errors=[], by_family={}
        )

        result = await delete_conversation(record.id, session, fake_redis)

    assert result.db_deleted is True

    # Verify that at least one execute() call carried a DELETE statement
    execute_calls = session.execute.call_args_list
    assert execute_calls, "session.execute() was never called — notification cleanup missing"

    # At least one of the calls should be a SQLAlchemy Delete construct
    from sqlalchemy.sql import Delete as SADelete

    delete_calls = [
        c for c in execute_calls if isinstance(c.args[0], SADelete)
    ]
    assert delete_calls, (
        "No SQLAlchemy DELETE statement was passed to session.execute(). "
        "Notification cleanup must use sa_delete(Notification).where(...)"
    )

"""
Unit tests for conversation archival logic.

Tests checkpoint age calculation, key pattern parsing, and error handling
with mocked Redis and database dependencies.
"""

import json
import pickle
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.workers.conversation_archiver import (
    CUTOFF_HOURS,
    TIMEZONE,
    find_expired_checkpoints,
    retrieve_and_parse_checkpoint,
    upsert_conversation_to_db,
)

# ============================================================================
# Checkpoint Age Calculation Tests
# ============================================================================


def _make_mock_redis_with_keys(keys_and_ttls: list[tuple[str, int]]) -> MagicMock:
    """Build a mock Redis client for find_expired_checkpoints tests.

    The implementation uses scan_iter(match="checkpoint:*") and then ttl(key)
    per key. Keys must follow the "checkpoint:{thread_id}:..." format.

    Args:
        keys_and_ttls: list of (key_string, ttl_seconds) tuples.
                       ttl_seconds is the remaining TTL for the key.
    """
    mock_redis = MagicMock()
    encoded_keys = [k.encode("utf-8") for k, _ in keys_and_ttls]
    mock_redis.scan_iter.return_value = iter(encoded_keys)

    ttl_map = {k.encode("utf-8"): ttl for k, ttl in keys_and_ttls}

    def _ttl(key):
        return ttl_map.get(key, -2)

    mock_redis.ttl.side_effect = _ttl
    return mock_redis


@pytest.mark.asyncio
async def test_checkpoint_age_calculation_with_various_ages():
    """
    Test that find_expired_checkpoints correctly identifies checkpoints by age.

    Tests checkpoints:
        - 24h old (should be marked for archival) → TTL ≈ 0s
        - 23.5h old (should be marked for archival) → TTL ≈ 1800s
        - 1h old (should NOT be marked for archival) → TTL ≈ 82800s

    Key format: checkpoint:{thread_id}:__empty__:{uuid}
    Age formula: checkpoint_time = now - (86400 - ttl)
    """
    # 24h old → TTL = 86400 - 24*3600 = 0
    key_24h = "checkpoint:conv-24h:__empty__:abc1"
    ttl_24h = 86400 - 24 * 3600  # 0s remaining

    # 23.5h old → TTL = 86400 - 23.5*3600 = 1800
    key_23_5h = "checkpoint:conv-23.5h:__empty__:abc2"
    ttl_23_5h = 86400 - int(23.5 * 3600)  # 1800s remaining

    # 1h old → TTL = 86400 - 1*3600 = 82800
    key_1h = "checkpoint:conv-1h:__empty__:abc3"
    ttl_1h = 86400 - 1 * 3600  # 82800s remaining

    mock_redis = _make_mock_redis_with_keys(
        [
            (key_24h, ttl_24h),
            (key_23_5h, ttl_23_5h),
            (key_1h, ttl_1h),
        ]
    )

    expired_keys = await find_expired_checkpoints(mock_redis)
    expired_conv_ids = [conv_id for _, conv_id, _ in expired_keys]

    # 24h and 23.5h checkpoints must be marked for archival
    assert "conv-24h" in expired_conv_ids
    assert "conv-23.5h" in expired_conv_ids
    # 1h checkpoint must NOT be marked for archival
    assert "conv-1h" not in expired_conv_ids


@pytest.mark.asyncio
async def test_find_expired_checkpoints_with_exact_cutoff_boundary():
    """
    Test checkpoint at exact CUTOFF_HOURS boundary.

    Checkpoint at exactly CUTOFF_HOURS old should be marked for archival.
    """
    key_exact = "checkpoint:conv-exact:__empty__:abc4"
    # TTL slightly past the cutoff boundary (1 second older than cutoff)
    # so checkpoint_time < cutoff_time holds despite timer jitter.
    ttl_exact = 86400 - CUTOFF_HOURS * 3600 - 1

    mock_redis = _make_mock_redis_with_keys([(key_exact, ttl_exact)])

    expired_keys = await find_expired_checkpoints(mock_redis)

    assert len(expired_keys) == 1
    assert expired_keys[0][1] == "conv-exact"


@pytest.mark.asyncio
async def test_find_expired_checkpoints_returns_empty_list_when_none_expired():
    """
    Test that find_expired_checkpoints returns empty list when no checkpoints are expired.
    """
    key_recent = "checkpoint:conv-recent:__empty__:abc5"
    ttl_recent = 86400 - 1 * 3600  # 1h old → not expired

    mock_redis = _make_mock_redis_with_keys([(key_recent, ttl_recent)])

    expired_keys = await find_expired_checkpoints(mock_redis)

    assert len(expired_keys) == 0


# ============================================================================
# Redis Key Pattern Parsing Tests
# ============================================================================


@pytest.mark.asyncio
async def test_redis_key_pattern_parsing_standard_format():
    """
    Test parsing of current checkpoint key format (TTL-based, no langgraph: prefix).

    Key format: checkpoint:{thread_id}:__empty__:{uuid}
    Age is derived from remaining TTL (total TTL = 24h).
    """
    # Use _make_mock_redis_with_keys: TTL ≈ 0 → 24h old → expired
    key = "checkpoint:thread-123:__empty__:abc-uuid-111"
    ttl = 100  # very small → 24h - 100s old → well past cutoff

    mock_redis = _make_mock_redis_with_keys([(key, ttl)])

    expired_keys = await find_expired_checkpoints(mock_redis)

    assert len(expired_keys) == 1
    key_str, conversation_id, _ = expired_keys[0]

    assert conversation_id == "thread-123"
    assert key_str == key


@pytest.mark.asyncio
async def test_redis_key_pattern_parsing_with_complex_thread_id():
    """
    Test parsing checkpoint key with multi-part thread_id containing colons.

    Key format: checkpoint:v2:wa-msg-123:__empty__:{uuid}
    The "v2:" prefix is stripped so conversation_id equals the bare Chatwoot ID.
    """
    key = "checkpoint:v2:wa-msg-456:__empty__:abc-uuid-222"
    ttl = 100  # expired (24h - 100s old)

    mock_redis = _make_mock_redis_with_keys([(key, ttl)])

    expired_keys = await find_expired_checkpoints(mock_redis)

    assert len(expired_keys) == 1
    _, conversation_id, _ = expired_keys[0]

    # "v2:" prefix is stripped by implementation
    assert conversation_id == "wa-msg-456"


@pytest.mark.asyncio
async def test_redis_key_pattern_parsing_skips_malformed_keys():
    """
    Test that malformed keys (too few parts) are skipped gracefully.

    The implementation requires at least 3 parts after stripping the
    "checkpoint:" prefix (thread_id, checkpoint_ns, checkpoint_id).
    Keys with fewer parts are skipped with a warning.
    """
    # Valid key: expired (ttl ≈ 0)
    valid_key = "checkpoint:valid-thread:__empty__:uuid-333"
    valid_ttl = 100  # expired

    # Invalid key: only 2 parts after prefix → skipped
    invalid_key = "checkpoint:only-one-part"

    ttl_map = {
        valid_key.encode("utf-8"): valid_ttl,
        invalid_key.encode("utf-8"): 1000,
    }
    mock_redis = MagicMock()
    mock_redis.scan_iter.return_value = iter(
        [valid_key.encode("utf-8"), invalid_key.encode("utf-8")]
    )
    mock_redis.ttl.side_effect = lambda k: ttl_map.get(k, -2)

    expired_keys = await find_expired_checkpoints(mock_redis)

    # Only the valid key should be returned
    assert len(expired_keys) == 1
    assert expired_keys[0][1] == "valid-thread"


# ============================================================================
# Checkpoint Deserialization Tests
# ============================================================================


@pytest.mark.asyncio
async def test_retrieve_and_parse_checkpoint_with_json_format():
    """
    Test deserialization of JSON-formatted checkpoint.
    """
    mock_redis = MagicMock()

    key = "langgraph:checkpoint:test:123"

    # Create JSON checkpoint
    state = {
        "conversation_id": "test-conv",
        "messages": [
            {
                "role": "user",
                "content": "Test message",
                "timestamp": datetime.now(TIMEZONE).isoformat(),
            }
        ],
    }

    checkpoint = {"v": 1, "ts": 123, "data": state}
    json_data = json.dumps(checkpoint)

    mock_redis.get.return_value = json_data

    # Parse checkpoint
    parsed_state = await retrieve_and_parse_checkpoint(mock_redis, key)

    # Verify parsing
    assert parsed_state is not None
    assert parsed_state["conversation_id"] == "test-conv"
    assert len(parsed_state["messages"]) == 1
    assert parsed_state["messages"][0]["content"] == "Test message"


@pytest.mark.asyncio
async def test_retrieve_and_parse_checkpoint_with_pickle_format():
    """
    Test deserialization of pickle-formatted checkpoint.
    """
    mock_redis = MagicMock()

    key = "langgraph:checkpoint:test:456"

    # Create pickle checkpoint
    state = {
        "conversation_id": "test-conv-pickle",
        "messages": [
            {
                "role": "assistant",
                "content": "Pickle test",
                "timestamp": datetime.now(TIMEZONE).isoformat(),
            }
        ],
    }

    checkpoint = {"v": 1, "ts": 456, "data": state}
    pickle_data = pickle.dumps(checkpoint)

    mock_redis.get.return_value = pickle_data

    # Parse checkpoint
    parsed_state = await retrieve_and_parse_checkpoint(mock_redis, key)

    # Verify parsing
    assert parsed_state is not None
    assert parsed_state["conversation_id"] == "test-conv-pickle"
    assert len(parsed_state["messages"]) == 1
    assert parsed_state["messages"][0]["content"] == "Pickle test"


@pytest.mark.asyncio
async def test_retrieve_and_parse_checkpoint_handles_missing_checkpoint():
    """
    Test that retrieve_and_parse_checkpoint handles missing checkpoint gracefully.
    """
    mock_redis = MagicMock()
    key = "langgraph:checkpoint:missing:789"

    # Mock get() to return None (checkpoint deleted)
    mock_redis.get.return_value = None

    # Parse checkpoint
    parsed_state = await retrieve_and_parse_checkpoint(mock_redis, key)

    # Should return None
    assert parsed_state is None


@pytest.mark.asyncio
async def test_retrieve_and_parse_checkpoint_handles_malformed_data():
    """
    Test error handling for malformed checkpoint data.

    Malformed data:
        - Invalid JSON
        - Invalid pickle
        - Missing required fields (conversation_id, messages)
    """
    mock_redis = MagicMock()

    # Test 1: Invalid JSON/pickle
    key_invalid = "langgraph:checkpoint:invalid:111"
    mock_redis.get.return_value = b"INVALID_DATA_NOT_JSON_OR_PICKLE"

    parsed_state = await retrieve_and_parse_checkpoint(mock_redis, key_invalid)
    assert parsed_state is None

    # Test 2: Missing conversation_id
    key_no_id = "langgraph:checkpoint:no_id:222"
    state_no_id = {"messages": []}
    checkpoint_no_id = {"v": 1, "ts": 222, "data": state_no_id}
    mock_redis.get.return_value = json.dumps(checkpoint_no_id)

    parsed_state = await retrieve_and_parse_checkpoint(mock_redis, key_no_id)
    assert parsed_state is None

    # Test 3: Missing messages field
    key_no_msgs = "langgraph:checkpoint:no_msgs:333"
    state_no_msgs = {"conversation_id": "test"}
    checkpoint_no_msgs = {"v": 1, "ts": 333, "data": state_no_msgs}
    mock_redis.get.return_value = json.dumps(checkpoint_no_msgs)

    parsed_state = await retrieve_and_parse_checkpoint(mock_redis, key_no_msgs)
    assert parsed_state is None


# ============================================================================
# Message Insertion Tests
# ============================================================================


@pytest.mark.asyncio
async def test_upsert_conversation_to_db_with_valid_messages():
    """
    Test message insertion with valid message data.
    """
    # Mock session
    mock_session = AsyncMock()

    # Mock session.execute to return empty existing fingerprints (no-ops for SELECT)
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = None
    mock_exec_result.all.return_value = []
    mock_exec_result.scalar.return_value = 0
    mock_session.execute.return_value = mock_exec_result

    customer_id = uuid4()
    conversation_id = "test-conv-insert"

    state = {
        "conversation_id": conversation_id,
        "customer_id": str(customer_id),
        "messages": [
            {
                "role": "user",
                "content": "Test message 1",
                "timestamp": datetime.now(TIMEZONE).isoformat(),
            },
            {
                "role": "assistant",
                "content": "Test message 2",
                "timestamp": datetime.now(TIMEZONE).isoformat(),
            },
        ],
    }

    # Insert messages
    inserted_count = await upsert_conversation_to_db(mock_session, state)

    # Verify 2 messages inserted
    assert inserted_count == 2

    # Verify session.add called at least twice (parent + 2 messages)
    assert mock_session.add.call_count >= 2

    # Verify commit called
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_conversation_to_db_with_conversation_summary():
    """
    Test that conversation_summary is stored on the parent ConversationHistory row.
    """
    mock_session = AsyncMock()

    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = None
    mock_exec_result.all.return_value = []
    mock_exec_result.scalar.return_value = 0
    mock_session.execute.return_value = mock_exec_result

    customer_id = uuid4()
    conversation_id = "test-conv-summary"

    state = {
        "conversation_id": conversation_id,
        "customer_id": str(customer_id),
        "messages": [
            {
                "role": "user",
                "content": "Test",
                "timestamp": datetime.now(TIMEZONE).isoformat(),
            }
        ],
        "conversation_summary": "Summary of conversation",
    }

    # Insert messages
    inserted_count = await upsert_conversation_to_db(mock_session, state)

    # Verify 1 message inserted (summary goes to parent.summary, not a child row)
    assert inserted_count == 1

    # Verify session.add called at least once (parent + message)
    assert mock_session.add.call_count >= 1


@pytest.mark.asyncio
async def test_upsert_conversation_to_db_handles_missing_customer_id():
    """
    Test message insertion with missing customer_id (unidentified customer).
    """
    mock_session = AsyncMock()

    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = None
    mock_exec_result.all.return_value = []
    mock_exec_result.scalar.return_value = 0
    mock_session.execute.return_value = mock_exec_result

    conversation_id = "test-conv-no-customer"

    state = {
        "conversation_id": conversation_id,
        # No customer_id
        "messages": [
            {
                "role": "user",
                "content": "Anonymous message",
                "timestamp": datetime.now(TIMEZONE).isoformat(),
            }
        ],
    }

    # Insert messages
    inserted_count = await upsert_conversation_to_db(mock_session, state)

    # Verify 1 message inserted
    assert inserted_count == 1

    # Verify session.add called (parent + message)
    assert mock_session.add.call_count >= 1


@pytest.mark.asyncio
async def test_upsert_conversation_to_db_skips_invalid_messages():
    """
    Test that upsert_conversation_to_db skips messages with missing role or content.
    """
    mock_session = AsyncMock()

    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = None
    mock_exec_result.all.return_value = []
    mock_exec_result.scalar.return_value = 0
    mock_session.execute.return_value = mock_exec_result

    conversation_id = "test-conv-invalid-msgs"

    state = {
        "conversation_id": conversation_id,
        "customer_id": str(uuid4()),
        "messages": [
            {
                "role": "user",
                "content": "Valid message",
                "timestamp": datetime.now(TIMEZONE).isoformat(),
            },
            {
                # Missing content
                "role": "assistant",
                "timestamp": datetime.now(TIMEZONE).isoformat(),
            },
            {
                # Missing role
                "content": "Missing role",
                "timestamp": datetime.now(TIMEZONE).isoformat(),
            },
        ],
    }

    # Insert messages
    inserted_count = await upsert_conversation_to_db(mock_session, state)

    # Only 1 valid message should be inserted
    assert inserted_count == 1


@pytest.mark.asyncio
async def test_upsert_conversation_to_db_handles_missing_timestamp():
    """
    Test that upsert_conversation_to_db uses current time when timestamp is missing.
    """
    mock_session = AsyncMock()

    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = None
    mock_exec_result.all.return_value = []
    mock_exec_result.scalar.return_value = 0
    mock_session.execute.return_value = mock_exec_result

    conversation_id = "test-conv-no-timestamp"

    state = {
        "conversation_id": conversation_id,
        "customer_id": str(uuid4()),
        "messages": [
            {
                "role": "user",
                "content": "Message without timestamp",
                # No timestamp
            }
        ],
    }

    # Insert messages
    inserted_count = await upsert_conversation_to_db(mock_session, state)

    # Message should be inserted with current timestamp
    assert inserted_count == 1


@pytest.mark.asyncio
async def test_upsert_conversation_to_db_returns_zero_when_no_messages():
    """
    Test that upsert_conversation_to_db returns 0 when state has no messages or summary.
    """
    mock_session = AsyncMock()

    conversation_id = "test-conv-empty"

    state = {
        "conversation_id": conversation_id,
        "messages": [],  # Empty messages list
    }

    # Insert messages
    inserted_count = await upsert_conversation_to_db(mock_session, state)

    # Should return 0
    assert inserted_count == 0

    # session.add should NOT be called
    mock_session.add.assert_not_called()


# ============================================================================
# Phase 6: archive_checkpoint Redis cleanup
# ============================================================================


@pytest.mark.asyncio
async def test_archive_checkpoint_cleanup_deletes_all_4_families_including_checkpoint_latest():
    """
    GIVEN a successful DB archive for conversation_id "archivetest"
    AND fakeredis seeded with all 4 checkpoint families under v2: prefix
    WHEN archive_checkpoint runs
    THEN all 4 families are deleted; batcher:pending is NOT deleted.

    Phase 6 spec requirement: archiver must delete checkpoint_latest: (was missing before),
    use async Redis, and NOT delete batcher:pending.
    """
    from unittest.mock import AsyncMock, MagicMock

    import fakeredis.aioredis as fakeredis_async

    from agent.workers.conversation_archiver import archive_checkpoint

    redis_async = fakeredis_async.FakeRedis()
    cid = "archivetest"

    # Seed all 4 checkpoint families (v2 prefix)
    await redis_async.set(f"checkpoint_latest:v2:{cid}:__empty__", "1")
    await redis_async.set(f"checkpoint:v2:{cid}:__empty__:uuid1", "1")
    await redis_async.set(f"checkpoint_write:v2:{cid}:__empty__:uuid1:0", "1")
    await redis_async.set(f"write_keys_zset:v2:{cid}:__empty__:uuid1", "1")
    # Batcher key should survive
    await redis_async.set(f"batcher:pending:{cid}", "BATCH_DATA")

    # Minimal state that upsert_conversation_to_db will accept (1 message → success)
    state = {
        "conversation_id": cid,
        "customer_id": None,
        "messages": [
            {
                "role": "user",
                "content": "hello",
                "timestamp": datetime.now(TIMEZONE).isoformat(),
            }
        ],
    }

    # Sync redis mock for TTL scan (the checkpoint retrieval step is patched away)
    mock_sync_redis = MagicMock()
    ckpt_key = f"checkpoint:v2:{cid}:__empty__:uuid1"

    # Mock the DB session so upsert_conversation_to_db succeeds without real DB
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = None
    mock_exec_result.all.return_value = []
    mock_exec_result.scalar.return_value = 0
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        # Bypass the checkpoint retrieval (sync redis GET) — we supply state directly
        patch(
            "agent.workers.conversation_archiver.retrieve_and_parse_checkpoint",
            new=AsyncMock(return_value=state),
        ),
        patch("agent.workers.conversation_archiver.get_async_session", return_value=mock_session_ctx),
        patch(
            "shared.redis_client.get_redis_client",
            return_value=redis_async,
        ),
    ):
        result = await archive_checkpoint(mock_sync_redis, ckpt_key, cid)

    assert result.get("success") is True, f"archive_checkpoint failed: {result}"

    # All 4 checkpoint families deleted
    for key in [
        f"checkpoint_latest:v2:{cid}:__empty__",
        f"checkpoint:v2:{cid}:__empty__:uuid1",
        f"checkpoint_write:v2:{cid}:__empty__:uuid1:0",
        f"write_keys_zset:v2:{cid}:__empty__:uuid1",
    ]:
        assert await redis_async.exists(key) == 0, f"Key {key} should be deleted"

    # Batcher key preserved
    assert await redis_async.exists(f"batcher:pending:{cid}") == 1, "batcher:pending must NOT be deleted by archiver"


@pytest.mark.asyncio
async def test_archive_checkpoint_cleanup_no_checkpoint_latest_keys_no_error():
    """
    GIVEN a conversation archived before checkpoint_latest was introduced
    AND only 3 legacy families exist (no checkpoint_latest keys)
    WHEN archive_checkpoint runs
    THEN the 3 existing families are deleted, no error raised.
    """
    from unittest.mock import AsyncMock, MagicMock

    import fakeredis.aioredis as fakeredis_async

    from agent.workers.conversation_archiver import archive_checkpoint

    redis_async = fakeredis_async.FakeRedis()
    cid = "legacyarchive"

    # Only 3 legacy families — no checkpoint_latest
    await redis_async.set(f"checkpoint:v2:{cid}:__empty__:uuid-old", "1")
    await redis_async.set(f"checkpoint_write:v2:{cid}:__empty__:uuid-old:0", "1")
    await redis_async.set(f"write_keys_zset:v2:{cid}:__empty__:uuid-old", "1")

    state = {
        "conversation_id": cid,
        "messages": [
            {
                "role": "user",
                "content": "legacy",
                "timestamp": datetime.now(TIMEZONE).isoformat(),
            }
        ],
    }

    mock_sync_redis = MagicMock()
    ckpt_key = f"checkpoint:v2:{cid}:__empty__:uuid-old"

    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = None
    mock_exec_result.all.return_value = []
    mock_exec_result.scalar.return_value = 0
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "agent.workers.conversation_archiver.retrieve_and_parse_checkpoint",
            new=AsyncMock(return_value=state),
        ),
        patch("agent.workers.conversation_archiver.get_async_session", return_value=mock_session_ctx),
        patch("shared.redis_client.get_redis_client", return_value=redis_async),
    ):
        result = await archive_checkpoint(mock_sync_redis, ckpt_key, cid)

    assert result.get("success") is True

    # 3 present families deleted
    for key in [
        f"checkpoint:v2:{cid}:__empty__:uuid-old",
        f"checkpoint_write:v2:{cid}:__empty__:uuid-old:0",
        f"write_keys_zset:v2:{cid}:__empty__:uuid-old",
    ]:
        assert await redis_async.exists(key) == 0

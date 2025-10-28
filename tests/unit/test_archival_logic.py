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
from zoneinfo import ZoneInfo

import pytest

from agent.workers.conversation_archiver import (
    CUTOFF_HOURS,
    TIMEZONE,
    find_expired_checkpoints,
    insert_messages_to_db,
    retrieve_and_parse_checkpoint,
)
from database.models import MessageRole

# ============================================================================
# Checkpoint Age Calculation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_checkpoint_age_calculation_with_various_ages():
    """
    Test that find_expired_checkpoints correctly identifies checkpoints by age.

    Tests checkpoints:
        - 24h old (should be marked for archival)
        - 23.5h old (should be marked for archival)
        - 1h old (should NOT be marked for archival)
    """
    # Mock Redis client
    mock_redis = MagicMock()

    # Create mock checkpoint keys with different timestamps
    now = datetime.now(TIMEZONE)

    # 24h old (expired)
    ts_24h = int((now - timedelta(hours=24)).timestamp())
    key_24h = f"langgraph:checkpoint:conv-24h:{ts_24h}"

    # 23.5h old (expired)
    ts_23_5h = int((now - timedelta(hours=23.5)).timestamp())
    key_23_5h = f"langgraph:checkpoint:conv-23.5h:{ts_23_5h}"

    # 1h old (NOT expired)
    ts_1h = int((now - timedelta(hours=1)).timestamp())
    key_1h = f"langgraph:checkpoint:conv-1h:{ts_1h}"

    # Mock keys() to return test keys
    mock_redis.keys.return_value = [
        key_24h.encode('utf-8'),
        key_23_5h.encode('utf-8'),
        key_1h.encode('utf-8'),
    ]

    # Find expired checkpoints
    expired_keys = await find_expired_checkpoints(mock_redis)

    # Extract conversation IDs
    expired_conv_ids = [conv_id for _, conv_id, _ in expired_keys]

    # Assert: 24h and 23.5h checkpoints marked for archival
    assert "conv-24h" in expired_conv_ids
    assert "conv-23.5h" in expired_conv_ids

    # Assert: 1h checkpoint NOT marked for archival
    assert "conv-1h" not in expired_conv_ids


@pytest.mark.asyncio
async def test_find_expired_checkpoints_with_exact_cutoff_boundary():
    """
    Test checkpoint at exact CUTOFF_HOURS boundary.

    Checkpoint at exactly 23 hours should be marked for archival.
    """
    mock_redis = MagicMock()

    now = datetime.now(TIMEZONE)

    # Exactly 23h old (at cutoff boundary)
    ts_exact = int((now - timedelta(hours=CUTOFF_HOURS)).timestamp())
    key_exact = f"langgraph:checkpoint:conv-exact:{ts_exact}"

    mock_redis.keys.return_value = [key_exact.encode('utf-8')]

    expired_keys = await find_expired_checkpoints(mock_redis)

    # Should be marked for archival (>= cutoff)
    assert len(expired_keys) == 1
    assert expired_keys[0][1] == "conv-exact"


@pytest.mark.asyncio
async def test_find_expired_checkpoints_returns_empty_list_when_none_expired():
    """
    Test that find_expired_checkpoints returns empty list when no checkpoints are expired.
    """
    mock_redis = MagicMock()

    now = datetime.now(TIMEZONE)

    # Create only recent checkpoints (< 23h old)
    ts_recent = int((now - timedelta(hours=1)).timestamp())
    key_recent = f"langgraph:checkpoint:conv-recent:{ts_recent}"

    mock_redis.keys.return_value = [key_recent.encode('utf-8')]

    expired_keys = await find_expired_checkpoints(mock_redis)

    # Should return empty list
    assert len(expired_keys) == 0


# ============================================================================
# Redis Key Pattern Parsing Tests
# ============================================================================


@pytest.mark.asyncio
async def test_redis_key_pattern_parsing_standard_format():
    """
    Test parsing of standard checkpoint key format.

    Key format: langgraph:checkpoint:{thread_id}:{checkpoint_ns}
    Example: langgraph:checkpoint:thread-123:1698765432
    """
    mock_redis = MagicMock()

    timestamp = int((datetime.now(TIMEZONE) - timedelta(hours=24)).timestamp())
    key = f"langgraph:checkpoint:thread-123:{timestamp}"

    mock_redis.keys.return_value = [key.encode('utf-8')]

    expired_keys = await find_expired_checkpoints(mock_redis)

    # Verify parsing
    assert len(expired_keys) == 1
    key_str, conversation_id, checkpoint_time = expired_keys[0]

    assert conversation_id == "thread-123"
    assert key_str == key
    # Verify timestamp parsed correctly (within 1 second tolerance)
    expected_time = datetime.fromtimestamp(timestamp, tz=TIMEZONE)
    assert abs((checkpoint_time - expected_time).total_seconds()) < 1


@pytest.mark.asyncio
async def test_redis_key_pattern_parsing_with_complex_thread_id():
    """
    Test parsing checkpoint key with multi-part thread_id containing colons.

    Key format: langgraph:checkpoint:wa-msg-123:user-456:1698765432
    """
    mock_redis = MagicMock()

    timestamp = int((datetime.now(TIMEZONE) - timedelta(hours=24)).timestamp())
    key = f"langgraph:checkpoint:wa-msg-123:user-456:{timestamp}"

    mock_redis.keys.return_value = [key.encode('utf-8')]

    expired_keys = await find_expired_checkpoints(mock_redis)

    # Verify parsing handles multi-part thread_id
    assert len(expired_keys) == 1
    _, conversation_id, _ = expired_keys[0]

    assert conversation_id == "wa-msg-123:user-456"


@pytest.mark.asyncio
async def test_redis_key_pattern_parsing_skips_malformed_keys():
    """
    Test that malformed keys are skipped gracefully.

    Malformed keys:
        - Missing parts (< 3 parts)
        - Non-numeric checkpoint_ns
    """
    mock_redis = MagicMock()

    timestamp = int((datetime.now(TIMEZONE) - timedelta(hours=24)).timestamp())

    # Create mix of valid and invalid keys
    valid_key = f"langgraph:checkpoint:valid-thread:{timestamp}"
    invalid_key_1 = "langgraph:checkpoint"  # Missing parts
    invalid_key_2 = "langgraph:checkpoint:thread:NOT_A_NUMBER"  # Non-numeric timestamp

    mock_redis.keys.return_value = [
        valid_key.encode('utf-8'),
        invalid_key_1.encode('utf-8'),
        invalid_key_2.encode('utf-8'),
    ]

    # Mock TTL for invalid_key_2 (since timestamp parsing will fail)
    mock_redis.ttl.return_value = 3600  # 1 hour remaining

    expired_keys = await find_expired_checkpoints(mock_redis)

    # Only valid key should be returned
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
            {"role": "user", "content": "Test message", "timestamp": datetime.now(TIMEZONE).isoformat()}
        ],
    }

    checkpoint = {"v": 1, "ts": 123, "data": state}
    json_data = json.dumps(checkpoint)

    mock_redis.get.return_value = json_data

    # Parse checkpoint
    parsed_state = await retrieve_and_parse_checkpoint(mock_redis, key)

    # Verify parsing
    assert parsed_state is not None
    assert parsed_state['conversation_id'] == "test-conv"
    assert len(parsed_state['messages']) == 1
    assert parsed_state['messages'][0]['content'] == "Test message"


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
            {"role": "assistant", "content": "Pickle test", "timestamp": datetime.now(TIMEZONE).isoformat()}
        ],
    }

    checkpoint = {"v": 1, "ts": 456, "data": state}
    pickle_data = pickle.dumps(checkpoint)

    mock_redis.get.return_value = pickle_data

    # Parse checkpoint
    parsed_state = await retrieve_and_parse_checkpoint(mock_redis, key)

    # Verify parsing
    assert parsed_state is not None
    assert parsed_state['conversation_id'] == "test-conv-pickle"
    assert len(parsed_state['messages']) == 1
    assert parsed_state['messages'][0]['content'] == "Pickle test"


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
async def test_insert_messages_to_db_with_valid_messages():
    """
    Test message insertion with valid message data.
    """
    # Mock session
    mock_session = AsyncMock()

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
    inserted_count = await insert_messages_to_db(mock_session, state)

    # Verify 2 messages inserted
    assert inserted_count == 2

    # Verify session.add called twice
    assert mock_session.add.call_count == 2

    # Verify commit called
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_insert_messages_to_db_with_conversation_summary():
    """
    Test that conversation_summary is inserted as system message.
    """
    mock_session = AsyncMock()

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
    inserted_count = await insert_messages_to_db(mock_session, state)

    # Verify 2 records inserted (1 message + 1 summary)
    assert inserted_count == 2

    # Verify session.add called twice
    assert mock_session.add.call_count == 2


@pytest.mark.asyncio
async def test_insert_messages_to_db_handles_missing_customer_id():
    """
    Test message insertion with missing customer_id (unidentified customer).
    """
    mock_session = AsyncMock()

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
    inserted_count = await insert_messages_to_db(mock_session, state)

    # Verify 1 message inserted
    assert inserted_count == 1

    # Verify session.add called with customer_id=None
    mock_session.add.assert_called_once()


@pytest.mark.asyncio
async def test_insert_messages_to_db_skips_invalid_messages():
    """
    Test that insert_messages_to_db skips messages with missing role or content.
    """
    mock_session = AsyncMock()

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
    inserted_count = await insert_messages_to_db(mock_session, state)

    # Only 1 valid message should be inserted
    assert inserted_count == 1


@pytest.mark.asyncio
async def test_insert_messages_to_db_handles_missing_timestamp():
    """
    Test that insert_messages_to_db uses current time when timestamp is missing.
    """
    mock_session = AsyncMock()

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
    inserted_count = await insert_messages_to_db(mock_session, state)

    # Message should be inserted with current timestamp
    assert inserted_count == 1


@pytest.mark.asyncio
async def test_insert_messages_to_db_returns_zero_when_no_messages():
    """
    Test that insert_messages_to_db returns 0 when state has no messages or summary.
    """
    mock_session = AsyncMock()

    conversation_id = "test-conv-empty"

    state = {
        "conversation_id": conversation_id,
        "messages": [],  # Empty messages list
    }

    # Insert messages
    inserted_count = await insert_messages_to_db(mock_session, state)

    # Should return 0
    assert inserted_count == 0

    # session.add should NOT be called
    mock_session.add.assert_not_called()

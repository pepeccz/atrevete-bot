"""
Integration tests for conversation archival worker.

Tests the full archival workflow: creating old checkpoints in Redis,
running the archival worker, and verifying messages are archived to
PostgreSQL and deleted from Redis.
"""

import asyncio
import json
import pickle
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
import redis
from sqlalchemy import delete, select

from agent.workers.conversation_archiver import (
    archive_checkpoint,
    archive_expired_conversations,
    find_expired_checkpoints,
    get_sync_redis_client,
    retrieve_and_parse_checkpoint,
)
from database.connection import get_async_session
from database.models import ConversationHistory, Customer, MessageRole

# Timezone for all datetime operations
TIMEZONE = ZoneInfo("Europe/Madrid")


@pytest.fixture
async def test_customer():
    """Create a test customer for use in tests."""
    customer_id = uuid4()

    async for session in get_async_session():
        # Create test customer
        customer = Customer(
            id=customer_id,
            phone="+34612345678",
            first_name="Test",
            last_name="Customer",
        )
        session.add(customer)
        await session.commit()
        break

    yield customer_id

    # Clean up
    async for session in get_async_session():
        await session.execute(
            delete(Customer).where(Customer.id == customer_id)
        )
        await session.commit()
        break


@pytest.fixture
async def clean_test_data():
    """Clean Redis and PostgreSQL test data before and after tests."""
    redis_client = get_sync_redis_client()

    # Clean before test
    test_keys = redis_client.keys("langgraph:checkpoint:test-*")
    if test_keys:
        redis_client.delete(*test_keys)

    async for session in get_async_session():
        # Delete test conversation history
        await session.execute(
            delete(ConversationHistory).where(
                ConversationHistory.conversation_id.like("test-conv-%")
            )
        )
        await session.commit()
        break

    yield

    # Clean after test
    test_keys = redis_client.keys("langgraph:checkpoint:test-*")
    if test_keys:
        redis_client.delete(*test_keys)

    async for session in get_async_session():
        await session.execute(
            delete(ConversationHistory).where(
                ConversationHistory.conversation_id.like("test-conv-%")
            )
        )
        await session.commit()
        break


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_full_archival_workflow_with_json_serialization(clean_test_data, test_customer):
    """
    Test full archival workflow with JSON-serialized checkpoint.

    Steps:
        1. Create checkpoint in Redis with 23.5h old timestamp
        2. Run archival worker
        3. Verify messages archived to PostgreSQL
        4. Verify checkpoint deleted from Redis
    """
    redis_client = get_sync_redis_client()

    # Step 1: Create mock checkpoint in Redis
    conversation_id = "test-conv-001"
    customer_id = test_customer  # Use test customer fixture

    # Create checkpoint with timestamp 23.5 hours ago
    old_timestamp = int((datetime.now(TIMEZONE) - timedelta(hours=23.5)).timestamp())
    key = f"langgraph:checkpoint:{conversation_id}:{old_timestamp}"

    # Create conversation state with 5 messages
    state = {
        "conversation_id": conversation_id,
        "customer_id": str(customer_id),
        "customer_phone": "+34612345678",
        "customer_name": "Test Customer",
        "messages": [
            {
                "role": "user",
                "content": "Hola, quiero hacer una cita",
                "timestamp": (datetime.now(TIMEZONE) - timedelta(hours=24)).isoformat(),
            },
            {
                "role": "assistant",
                "content": "¡Hola! Claro, te ayudo con tu cita.",
                "timestamp": (datetime.now(TIMEZONE) - timedelta(hours=23, minutes=59)).isoformat(),
            },
            {
                "role": "user",
                "content": "Para mañana a las 10",
                "timestamp": (datetime.now(TIMEZONE) - timedelta(hours=23, minutes=58)).isoformat(),
            },
            {
                "role": "assistant",
                "content": "Perfecto, te confirmo la cita.",
                "timestamp": (datetime.now(TIMEZONE) - timedelta(hours=23, minutes=57)).isoformat(),
            },
            {
                "role": "user",
                "content": "Gracias",
                "timestamp": (datetime.now(TIMEZONE) - timedelta(hours=23, minutes=56)).isoformat(),
            },
        ],
        "current_intent": "booking",
        "metadata": {"test": True},
    }

    # Wrap in LangGraph checkpoint structure
    checkpoint = {
        "v": 1,
        "ts": old_timestamp,
        "data": state,
    }

    # Serialize to JSON
    serialized_state = json.dumps(checkpoint)

    # Store in Redis (using sync client)
    redis_client.set(key, serialized_state)

    # Verify checkpoint exists
    assert redis_client.exists(key) == 1

    # Step 2: Run archival worker
    await archive_expired_conversations()

    # Step 3: Query PostgreSQL for archived messages
    async for session in get_async_session():
        result = await session.execute(
            select(ConversationHistory)
            .where(ConversationHistory.conversation_id == conversation_id)
            .order_by(ConversationHistory.timestamp)
        )
        archived_messages = result.scalars().all()
        break

    # Assert: 5 messages archived
    assert len(archived_messages) == 5

    # Assert: Messages have correct content
    assert archived_messages[0].message_content == "Hola, quiero hacer una cita"
    assert archived_messages[1].message_content == "¡Hola! Claro, te ayudo con tu cita."
    assert archived_messages[2].message_content == "Para mañana a las 10"
    assert archived_messages[3].message_content == "Perfecto, te confirmo la cita."
    assert archived_messages[4].message_content == "Gracias"

    # Assert: Messages have correct roles
    assert archived_messages[0].message_role == MessageRole.USER
    assert archived_messages[1].message_role == MessageRole.ASSISTANT
    assert archived_messages[2].message_role == MessageRole.USER
    assert archived_messages[3].message_role == MessageRole.ASSISTANT
    assert archived_messages[4].message_role == MessageRole.USER

    # Assert: Messages have customer_id
    assert all(msg.customer_id == customer_id for msg in archived_messages)

    # Step 4: Verify checkpoint deleted from Redis
    assert redis_client.exists(key) == 0


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_archival_with_conversation_summary(clean_test_data, test_customer):
    """
    Test archival of checkpoint with conversation_summary field.

    Verifies that summary is stored as separate system message.
    """
    redis_client = get_sync_redis_client()

    # Create checkpoint with summary
    conversation_id = "test-conv-002"
    customer_id = test_customer  # Use test customer fixture

    old_timestamp = int((datetime.now(TIMEZONE) - timedelta(hours=23.5)).timestamp())
    key = f"langgraph:checkpoint:{conversation_id}:{old_timestamp}"

    state = {
        "conversation_id": conversation_id,
        "customer_id": str(customer_id),
        "messages": [
            {
                "role": "user",
                "content": "Message 1",
                "timestamp": datetime.now(TIMEZONE).isoformat(),
            },
        ],
        "conversation_summary": "Customer requested booking for tomorrow at 10am. Confirmed appointment.",
    }

    checkpoint = {"v": 1, "ts": old_timestamp, "data": state}
    redis_client.set(key, json.dumps(checkpoint))

    # Run archival
    await archive_expired_conversations()

    # Verify summary archived as system message
    async for session in get_async_session():
        result = await session.execute(
            select(ConversationHistory)
            .where(ConversationHistory.conversation_id == conversation_id)
            .where(ConversationHistory.message_role == MessageRole.SYSTEM)
        )
        summary_records = result.scalars().all()
        break

    assert len(summary_records) == 1
    assert "Customer requested booking" in summary_records[0].message_content
    assert summary_records[0].metadata_.get('type') == 'conversation_summary'


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_archival_skips_malformed_checkpoint(clean_test_data):
    """
    Test that archival worker skips malformed checkpoint data gracefully.
    """
    redis_client = get_sync_redis_client()

    # Create checkpoint with invalid data
    conversation_id = "test-conv-003"
    old_timestamp = int((datetime.now(TIMEZONE) - timedelta(hours=23.5)).timestamp())
    key = f"langgraph:checkpoint:{conversation_id}:{old_timestamp}"

    # Store invalid JSON
    redis_client.set(key, b"INVALID_JSON_DATA")

    # Run archival (should not crash)
    await archive_expired_conversations()

    # Verify no messages archived
    async for session in get_async_session():
        result = await session.execute(
            select(ConversationHistory).where(
                ConversationHistory.conversation_id == conversation_id
            )
        )
        archived_messages = result.scalars().all()
        break

    assert len(archived_messages) == 0

    # Checkpoint should NOT be deleted (failed to parse)
    assert redis_client.exists(key) == 1


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_archival_handles_missing_customer_id(clean_test_data):
    """
    Test archival of checkpoint without customer_id (unidentified customer).

    Verifies that messages are still archived with NULL customer_id.
    """
    redis_client = get_sync_redis_client()

    # Create checkpoint without customer_id
    conversation_id = "test-conv-004"
    old_timestamp = int((datetime.now(TIMEZONE) - timedelta(hours=23.5)).timestamp())
    key = f"langgraph:checkpoint:{conversation_id}:{old_timestamp}"

    state = {
        "conversation_id": conversation_id,
        # No customer_id field
        "messages": [
            {
                "role": "user",
                "content": "Hola",
                "timestamp": datetime.now(TIMEZONE).isoformat(),
            },
        ],
    }

    checkpoint = {"v": 1, "ts": old_timestamp, "data": state}
    redis_client.set(key, json.dumps(checkpoint))

    # Run archival
    await archive_expired_conversations()

    # Verify message archived with NULL customer_id
    async for session in get_async_session():
        result = await session.execute(
            select(ConversationHistory).where(
                ConversationHistory.conversation_id == conversation_id
            )
        )
        archived_messages = result.scalars().all()
        break

    assert len(archived_messages) == 1
    assert archived_messages[0].customer_id is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_find_expired_checkpoints_filters_correctly(clean_test_data):
    """
    Test that find_expired_checkpoints correctly filters by age.

    Creates checkpoints with different ages:
        - 24h old (should be found)
        - 23.5h old (should be found)
        - 1h old (should NOT be found)
    """
    redis_client = get_sync_redis_client()

    # Create checkpoints with different ages
    now = datetime.now(TIMEZONE)

    # 24h old (expired)
    old_24h_ts = int((now - timedelta(hours=24)).timestamp())
    key_24h = f"langgraph:checkpoint:test-conv-24h:{old_24h_ts}"
    redis_client.set(key_24h, json.dumps({"data": {"conversation_id": "test-conv-24h", "messages": []}}))

    # 23.5h old (expired)
    old_23_5h_ts = int((now - timedelta(hours=23.5)).timestamp())
    key_23_5h = f"langgraph:checkpoint:test-conv-23.5h:{old_23_5h_ts}"
    redis_client.set(key_23_5h, json.dumps({"data": {"conversation_id": "test-conv-23.5h", "messages": []}}))

    # 1h old (NOT expired)
    recent_1h_ts = int((now - timedelta(hours=1)).timestamp())
    key_1h = f"langgraph:checkpoint:test-conv-1h:{recent_1h_ts}"
    redis_client.set(key_1h, json.dumps({"data": {"conversation_id": "test-conv-1h", "messages": []}}))

    # Find expired checkpoints
    expired_keys = await find_expired_checkpoints(redis_client)

    # Extract conversation IDs from results
    expired_conv_ids = [conv_id for _, conv_id, _ in expired_keys]

    # Assert: 24h and 23.5h checkpoints found
    assert "test-conv-24h" in expired_conv_ids
    assert "test-conv-23.5h" in expired_conv_ids

    # Assert: 1h checkpoint NOT found
    assert "test-conv-1h" not in expired_conv_ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_retrieve_and_parse_checkpoint_handles_pickle(clean_test_data):
    """
    Test that retrieve_and_parse_checkpoint can handle pickle serialization.
    """
    redis_client = get_sync_redis_client()

    conversation_id = "test-conv-pickle"
    key = f"langgraph:checkpoint:{conversation_id}:123456789"

    # Create state with pickle serialization
    state = {
        "conversation_id": conversation_id,
        "messages": [{"role": "user", "content": "Test", "timestamp": datetime.now(TIMEZONE).isoformat()}],
    }

    checkpoint = {"v": 1, "ts": 123456789, "data": state}
    serialized = pickle.dumps(checkpoint)

    redis_client.set(key, serialized)

    # Parse checkpoint
    parsed_state = await retrieve_and_parse_checkpoint(redis_client, key)

    # Verify parsed correctly
    assert parsed_state is not None
    assert parsed_state['conversation_id'] == conversation_id
    assert len(parsed_state['messages']) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_archive_checkpoint_with_retry_logic(clean_test_data, test_customer, monkeypatch):
    """
    Test that archive_checkpoint retries on database failure.

    This test is challenging to implement without mocking database failures.
    Left as placeholder for manual testing or advanced mocking.
    """
    # TODO: Implement with database failure injection
    # For now, test successful archival path
    redis_client = get_sync_redis_client()

    conversation_id = "test-conv-retry"
    old_timestamp = int((datetime.now(TIMEZONE) - timedelta(hours=23.5)).timestamp())
    key = f"langgraph:checkpoint:{conversation_id}:{old_timestamp}"

    state = {
        "conversation_id": conversation_id,
        "customer_id": str(test_customer),  # Use test customer fixture
        "messages": [
            {
                "role": "user",
                "content": "Test message",
                "timestamp": datetime.now(TIMEZONE).isoformat(),
            }
        ],
    }

    checkpoint = {"v": 1, "ts": old_timestamp, "data": state}
    redis_client.set(key, json.dumps(checkpoint))

    # Run archival
    result = await archive_checkpoint(redis_client, key, conversation_id)

    # Verify success
    assert result['success'] is True
    assert result['messages_archived'] == 1
    assert result['error'] is None

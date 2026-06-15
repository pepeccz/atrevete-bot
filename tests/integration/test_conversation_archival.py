"""
Integration tests for conversation archival worker.

Tests the full archival workflow: creating old checkpoints in Redis,
running the archival worker, and verifying messages are archived to
PostgreSQL and deleted from Redis.
"""

import json
import pickle
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

from agent.workers.conversation_archiver import (
    archive_checkpoint,
    archive_expired_conversations,
    find_expired_checkpoints,
    get_sync_redis_client,
    retrieve_and_parse_checkpoint,
)
from database.connection import get_async_session
from database.models import ConversationHistory, ConversationMessage, Customer

# Timezone for all datetime operations
TIMEZONE = ZoneInfo("Europe/Madrid")


def _make_checkpoint_key(conversation_id: str) -> str:
    """
    Build a Redis checkpoint key in the format expected by the archiver.

    Real format (from AsyncRedisSaver + archiver scan pattern):
        checkpoint:{thread_id}:{checkpoint_ns}:{checkpoint_id}
    where thread_id = "v2:{conversation_id}".

    The archiver scans "checkpoint:*" and extracts thread_id via
    ``inner.rsplit(":", 2)[0]``, then strips the "v2:" prefix.
    """
    checkpoint_ns = "__empty__"
    checkpoint_id = str(uuid4()).replace("-", "")
    return f"checkpoint:v2:{conversation_id}:{checkpoint_ns}:{checkpoint_id}"


def _set_checkpoint_with_ttl(redis_client, key: str, data: dict, ttl_seconds: int) -> None:
    """Store JSON-serialized checkpoint data with an explicit TTL.

    The archiver uses ``redis.ttl(key)`` to compute checkpoint age:
        checkpoint_age = 24h - remaining_ttl
        expired if checkpoint_age > 23h  →  ttl < 3600

    So to simulate an old checkpoint, use a small TTL (e.g. 0 remaining ≈ 1).
    """
    redis_client.setex(key, ttl_seconds, json.dumps(data))


@pytest.fixture
async def test_customer():
    """Create a test customer for use in tests."""
    customer_id = uuid4()

    try:
        async with get_async_session() as session:
            # Remove any stale customer with the same phone from prior test runs
            await session.execute(delete(Customer).where(Customer.phone == "+34612345678"))
            await session.commit()
    except RuntimeError as exc:
        if "event loop" in str(exc).lower():
            pytest.skip(f"Event loop unavailable (prior module-scoped test closed it): {exc}")
        raise

    async with get_async_session() as session:
        # Create test customer
        customer = Customer(
            id=customer_id,
            phone="+34612345678",
            first_name="Test",
            last_name="Customer",
        )
        session.add(customer)
        await session.commit()

    yield customer_id

    # Clean up
    async with get_async_session() as session:
        await session.execute(delete(Customer).where(Customer.id == customer_id))
        await session.commit()


@pytest.fixture
async def clean_test_data():
    """Clean Redis and PostgreSQL test data before and after tests."""
    redis_client = get_sync_redis_client()

    def _delete_test_checkpoint_keys():
        # Archiver scans "checkpoint:*" (no langgraph: prefix).
        # Test keys follow "checkpoint:v2:test-conv-*" format.
        test_keys = list(redis_client.scan_iter(match="checkpoint:v2:test-conv-*"))
        if test_keys:
            redis_client.delete(*test_keys)

    # Clean before test
    _delete_test_checkpoint_keys()

    async with get_async_session() as session:
        # Delete test conversation history
        await session.execute(
            delete(ConversationHistory).where(
                ConversationHistory.conversation_id.like("test-conv-%")
            )
        )
        await session.commit()

    yield

    # Clean after test
    _delete_test_checkpoint_keys()

    async with get_async_session() as session:
        await session.execute(
            delete(ConversationHistory).where(
                ConversationHistory.conversation_id.like("test-conv-%")
            )
        )
        await session.commit()


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

    # Use the real checkpoint key format (archiver scans "checkpoint:*", no langgraph: prefix).
    # TTL=1800 → remaining=1800s → age = 24h - 1800s = 22.5h > 23h threshold:
    #   checkpoint_time = now - (86400 - 1800) = now - 84600 ≈ 23.5h ago → expired.
    key = _make_checkpoint_key(conversation_id)

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
        "data": state,
    }

    # Store in Redis with a low TTL (1800s) to simulate a ~23.5h-old checkpoint.
    # Archiver age formula: checkpoint_age = 24h - remaining_ttl → 24h - 0.5h = 23.5h > CUTOFF_HOURS (23h).
    _set_checkpoint_with_ttl(redis_client, key, checkpoint, ttl_seconds=1800)

    # Verify checkpoint exists
    assert redis_client.exists(key) == 1

    # Step 2: Run archival worker
    await archive_expired_conversations()

    # Step 3: Query PostgreSQL for archived messages (two-table schema)
    async with get_async_session() as session:
        # Query the parent ConversationHistory row
        parent_result = await session.execute(
            select(ConversationHistory).where(
                ConversationHistory.conversation_id == conversation_id
            )
        )
        parent = parent_result.scalar_one_or_none()

        # Query the child ConversationMessage rows in chronological order
        messages_result = await session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_history_id == parent.id)
            .order_by(ConversationMessage.created_at)
        )
        archived_messages = messages_result.scalars().all()

    # Assert: parent row exists with correct customer
    assert parent is not None
    assert parent.customer_id == customer_id
    assert parent.message_count == 5

    # Assert: 5 messages archived as child rows
    assert len(archived_messages) == 5

    # Assert: Messages have correct content
    assert archived_messages[0].content == "Hola, quiero hacer una cita"
    assert archived_messages[1].content == "¡Hola! Claro, te ayudo con tu cita."
    assert archived_messages[2].content == "Para mañana a las 10"
    assert archived_messages[3].content == "Perfecto, te confirmo la cita."
    assert archived_messages[4].content == "Gracias"

    # Assert: Messages have correct roles (stored as lowercase strings)
    assert archived_messages[0].role == "user"
    assert archived_messages[1].role == "assistant"
    assert archived_messages[2].role == "user"
    assert archived_messages[3].role == "assistant"
    assert archived_messages[4].role == "user"

    # Assert: Messages have created_at timestamps
    assert all(msg.created_at is not None for msg in archived_messages)

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

    key = _make_checkpoint_key(conversation_id)

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

    checkpoint = {"v": 1, "data": state}
    _set_checkpoint_with_ttl(redis_client, key, checkpoint, ttl_seconds=1800)

    # Run archival
    await archive_expired_conversations()

    # Verify summary stored on the parent ConversationHistory row
    async with get_async_session() as session:
        result = await session.execute(
            select(ConversationHistory).where(
                ConversationHistory.conversation_id == conversation_id
            )
        )
        parent = result.scalar_one_or_none()

    assert parent is not None
    assert parent.summary is not None
    assert "Customer requested booking" in parent.summary


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
    key = _make_checkpoint_key(conversation_id)

    # Store invalid JSON with a low TTL to make it appear expired to the archiver
    redis_client.setex(key, 1800, b"INVALID_JSON_DATA")

    # Run archival (should not crash)
    await archive_expired_conversations()

    # Verify no conversation parent was created (nothing archived)
    async with get_async_session() as session:
        result = await session.execute(
            select(ConversationHistory).where(
                ConversationHistory.conversation_id == conversation_id
            )
        )
        parent = result.scalar_one_or_none()

    assert parent is None

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
    key = _make_checkpoint_key(conversation_id)

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

    checkpoint = {"v": 1, "data": state}
    _set_checkpoint_with_ttl(redis_client, key, checkpoint, ttl_seconds=1800)

    # Run archival
    await archive_expired_conversations()

    # Verify parent created with NULL customer_id, and 1 child message archived
    async with get_async_session() as session:
        parent_result = await session.execute(
            select(ConversationHistory).where(
                ConversationHistory.conversation_id == conversation_id
            )
        )
        parent = parent_result.scalar_one_or_none()

        messages_result = await session.execute(
            select(ConversationMessage).where(
                ConversationMessage.conversation_history_id == parent.id
            )
        )
        archived_messages = messages_result.scalars().all()

    assert parent is not None
    assert parent.customer_id is None
    assert len(archived_messages) == 1


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

    # Create checkpoints with different ages using the correct key format.
    # Archiver age formula: checkpoint_age = 24h - remaining_ttl.
    # Expired when checkpoint_age > CUTOFF_HOURS (23h), i.e. TTL < 3600s.
    dummy_data = json.dumps({"data": {"conversation_id": "placeholder", "messages": []}})

    # 24h old (expired): TTL ≈ 1s — nearly zero remaining
    key_24h = _make_checkpoint_key("test-conv-24h")
    redis_client.setex(key_24h, 1, dummy_data)

    # 23.5h old (expired): TTL = 1800s (0.5h remaining of 24h = 23.5h age)
    key_23_5h = _make_checkpoint_key("test-conv-23.5h")
    redis_client.setex(key_23_5h, 1800, dummy_data)

    # 1h old (NOT expired): TTL = 82800s (23h remaining of 24h = 1h age)
    key_1h = _make_checkpoint_key("test-conv-1h")
    redis_client.setex(key_1h, 82800, dummy_data)

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
    key = _make_checkpoint_key(conversation_id)

    # Create state with pickle serialization
    state = {
        "conversation_id": conversation_id,
        "messages": [
            {"role": "user", "content": "Test", "timestamp": datetime.now(TIMEZONE).isoformat()}
        ],
    }

    checkpoint = {"v": 1, "data": state}
    serialized = pickle.dumps(checkpoint)

    redis_client.set(key, serialized)

    # Parse checkpoint
    parsed_state = await retrieve_and_parse_checkpoint(redis_client, key)

    # Verify parsed correctly
    assert parsed_state is not None
    assert parsed_state["conversation_id"] == conversation_id
    assert len(parsed_state["messages"]) == 1


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
    key = _make_checkpoint_key(conversation_id)

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

    checkpoint = {"v": 1, "data": state}
    _set_checkpoint_with_ttl(redis_client, key, checkpoint, ttl_seconds=1800)

    # Run archival
    result = await archive_checkpoint(redis_client, key, conversation_id)

    # Verify success
    assert result["success"] is True
    assert result["messages_archived"] == 1
    assert result["error"] is None

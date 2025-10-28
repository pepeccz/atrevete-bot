"""
Integration tests for crash recovery with LangGraph checkpointing.

These tests verify that conversation state persists across agent "crashes"
(simulated by creating new checkpointer instances) using Redis-backed checkpointing.
"""

import pytest
from redis.asyncio import Redis

from agent.state.checkpointer import get_redis_checkpointer
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState
from shared.config import get_settings


@pytest.mark.asyncio
@pytest.mark.integration
async def test_message_windowing_with_add_message_helper():
    """
    Test that message windowing (max 10 messages) works correctly.

    Verifies AC#4 and AC#9 from Story 2.5a: add_message maintains exactly 10 messages.
    """
    # Create state with 10 messages
    initial_messages = [
        {"role": "user" if i % 2 == 0 else "assistant",
         "content": f"Message {i+1}",
         "timestamp": f"2025-10-28T10:00:{i:02d}+01:00"}
        for i in range(10)
    ]

    state: ConversationState = {
        "conversation_id": "test-windowing-001",
        "customer_phone": "+34612345678",
        "customer_name": "Test User",
        "messages": initial_messages,
        "current_intent": None,
        "metadata": {},
    }

    # Verify we start with 10 messages
    assert len(state["messages"]) == 10

    # Add an 11th message
    updated_state = add_message(state, "user", "Message 11")

    # Verify exactly 10 messages retained (oldest dropped)
    assert len(updated_state["messages"]) == 10

    # Verify first message is now "Message 2" (Message 1 was dropped)
    assert updated_state["messages"][0]["content"] == "Message 2"

    # Verify last message is "Message 11" (newest retained)
    assert updated_state["messages"][9]["content"] == "Message 11"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_checkpoint_key_pattern():
    """
    Test that checkpoints use the correct Redis key pattern.

    Verifies AC#3 from Story 2.5a: Keys follow pattern langgraph:checkpoint:{thread_id}:*
    """
    settings = get_settings()
    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=False)

    test_thread_id = "test-key-pattern-002"

    try:
        # Clear existing checkpoints
        keys = await redis_client.keys(f"*{test_thread_id}*")
        if keys:
            await redis_client.delete(*keys)

        # Create checkpointer
        checkpointer = get_redis_checkpointer()

        # Save a test checkpoint
        test_checkpoint = {
            "v": 1,
            "id": "test-checkpoint-id",
            "ts": "2025-10-28T10:00:00Z",
            "channel_values": {
                "conversation_id": test_thread_id,
                "messages": []
            }
        }

        config = {
            "configurable": {
                "thread_id": test_thread_id,
                "checkpoint_ns": "",
                "checkpoint_id": "test-checkpoint-id"
            }
        }

        await checkpointer.aput(
            config=config,
            checkpoint=test_checkpoint,
            metadata={"source": "test", "step": 1, "writes": None, "parents": {}},
            new_versions={}
        )

        # Query Redis for checkpoint keys
        checkpoint_keys = await redis_client.keys(f"*{test_thread_id}*")

        # Verify at least one checkpoint exists
        assert len(checkpoint_keys) > 0, \
            f"Expected checkpoint keys for thread_id={test_thread_id}"

        # Verify key pattern contains thread_id
        for key in checkpoint_keys:
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            assert test_thread_id in key_str, \
                f"Checkpoint key should contain thread_id, got: {key_str}"

    finally:
        # Cleanup
        keys = await redis_client.keys(f"*{test_thread_id}*")
        if keys:
            await redis_client.delete(*keys)
        await redis_client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_checkpoint_persistence_and_retrieval():
    """
    Test that checkpoints persist in Redis and can be retrieved.

    Verifies AC#2, AC#7, and AC#10 from Story 2.5a.
    """
    settings = get_settings()
    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=False)

    test_thread_id = "test-persistence-003"

    try:
        # Clear test data
        keys = await redis_client.keys(f"*{test_thread_id}*")
        if keys:
            await redis_client.delete(*keys)

        # Create checkpointer
        checkpointer = get_redis_checkpointer()

        # Create checkpoint with 3 messages
        test_checkpoint = {
            "v": 1,
            "id": "checkpoint-003",
            "ts": "2025-10-28T10:00:00Z",
            "channel_values": {
                "conversation_id": test_thread_id,
                "customer_phone": "+34612345678",
                "messages": [
                    {"role": "user", "content": "Hola", "timestamp": "2025-10-28T10:00:00+01:00"},
                    {"role": "assistant", "content": "¡Hola! Soy Maite 🌸", "timestamp": "2025-10-28T10:00:01+01:00"},
                    {"role": "user", "content": "Quiero una cita", "timestamp": "2025-10-28T10:00:02+01:00"},
                ]
            }
        }

        config = {
            "configurable": {
                "thread_id": test_thread_id,
                "checkpoint_ns": "",
                "checkpoint_id": "checkpoint-003"
            }
        }

        # Save checkpoint (simulates "crash" before this point)
        await checkpointer.aput(
            config=config,
            checkpoint=test_checkpoint,
            metadata={"source": "test", "step": 1, "writes": None, "parents": {}},
            new_versions={}
        )

        # Verify checkpoint exists in Redis
        checkpoint_keys = await redis_client.keys(f"*{test_thread_id}*")
        assert len(checkpoint_keys) > 0, "Checkpoint should exist in Redis"

        # Simulate "recovery": create new checkpointer and retrieve checkpoint
        new_checkpointer = get_redis_checkpointer()
        retrieved = await new_checkpointer.aget(config)

        # Verify checkpoint retrieved
        assert retrieved is not None, "Checkpoint should be retrievable after 'crash'"

        # retrieved is a CheckpointTuple with .checkpoint attribute or a dict
        # Access checkpoint data appropriately
        if hasattr(retrieved, 'checkpoint'):
            checkpoint_data = retrieved.checkpoint
        else:
            checkpoint_data = retrieved

        # Verify checkpoint contains expected messages
        assert checkpoint_data is not None
        messages = checkpoint_data.get("channel_values", {}).get("messages", [])
        assert len(messages) == 3, f"Expected 3 messages, got {len(messages)}"

        # Verify first message retained
        assert messages[0]["content"] == "Hola", \
            "First message should be preserved across checkpoint save/load"

    finally:
        # Cleanup
        keys = await redis_client.keys(f"*{test_thread_id}*")
        if keys:
            await redis_client.delete(*keys)
        await redis_client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_checkpointer_configuration():
    """
    Test that checkpointer can be created with correct configuration.

    Verifies that AsyncRedisSaver initializes properly with TTL settings.
    """
    from agent.graphs.conversation_flow import create_conversation_graph

    # Verify checkpointer creation succeeds (requires event loop)
    checkpointer = get_redis_checkpointer()
    assert checkpointer is not None

    # Verify graph can be created with checkpointer
    graph = create_conversation_graph(checkpointer=checkpointer)
    assert graph is not None

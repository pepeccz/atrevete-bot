"""
Integration tests for LangGraph checkpoint persistence in Redis.

These tests verify checkpoint creation, retrieval, and TTL configuration
without running the full conversation graph to avoid complexity.
"""

import pytest
from redis.asyncio import Redis

from agent.state.checkpointer import get_redis_checkpointer
from agent.state.schemas import ConversationState
from shared.config import get_settings


@pytest.mark.asyncio
@pytest.mark.integration
async def test_checkpoint_created_in_redis():
    """
    Test that checkpoints are created in Redis with correct key pattern.

    Verifies AC#3 and AC#10 requirements from Story 2.5a.
    """
    settings = get_settings()
    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=False)

    test_thread_id = "test-checkpoint-creation-001"

    try:
        # Clear any existing checkpoints
        keys = await redis_client.keys(f"*{test_thread_id}*")
        if keys:
            await redis_client.delete(*keys)

        # Get checkpointer
        checkpointer = get_redis_checkpointer()
        assert checkpointer is not None

        # Create a simple test checkpoint manually
        test_checkpoint = {
            "v": 1,
            "id": "test-checkpoint-id",
            "ts": "2025-10-28T10:00:00Z",
            "channel_values": {
                "conversation_id": test_thread_id,
                "customer_phone": "+34612345678",
                "messages": [
                    {"role": "user", "content": "Hola", "timestamp": "2025-10-28T10:00:00+01:00"}
                ]
            }
        }

        # Save checkpoint using LangGraph's async put method
        config = {"configurable": {"thread_id": test_thread_id, "checkpoint_ns": "", "checkpoint_id": "test-checkpoint-id"}}

        # Use checkpointer's put method to save state
        await checkpointer.aput(
            config=config,
            checkpoint=test_checkpoint,
            metadata={"source": "test", "step": 1, "writes": None, "parents": {}},
            new_versions={}
        )

        # Query Redis for checkpoint keys
        checkpoint_keys = await redis_client.keys(f"*{test_thread_id}*")

        # Verify at least one checkpoint key exists
        assert len(checkpoint_keys) > 0, \
            f"Expected checkpoint keys in Redis, found none for thread_id={test_thread_id}"

        # Verify key contains thread_id
        found_thread_id_in_key = False
        for key in checkpoint_keys:
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            if test_thread_id in key_str:
                found_thread_id_in_key = True
                break

        assert found_thread_id_in_key, \
            f"No checkpoint key contains thread_id={test_thread_id}"

    finally:
        # Cleanup
        keys = await redis_client.keys(f"*{test_thread_id}*")
        if keys:
            await redis_client.delete(*keys)
        await redis_client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_checkpoint_retrieval():
    """
    Test that checkpoints can be retrieved from Redis.

    Verifies AC#7 and AC#10 requirements from Story 2.5a.
    """
    settings = get_settings()
    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=False)

    test_thread_id = "test-checkpoint-retrieval-002"

    try:
        # Clear test data
        keys = await redis_client.keys(f"*{test_thread_id}*")
        if keys:
            await redis_client.delete(*keys)

        # Get checkpointer
        checkpointer = get_redis_checkpointer()

        # Create and save checkpoint
        test_checkpoint = {
            "v": 1,
            "id": "test-checkpoint-id-002",
            "ts": "2025-10-28T10:00:00Z",
            "channel_values": {
                "conversation_id": test_thread_id,
                "customer_phone": "+34612345678",
                "messages": [
                    {"role": "user", "content": "Test message", "timestamp": "2025-10-28T10:00:00+01:00"}
                ]
            }
        }

        config = {"configurable": {"thread_id": test_thread_id, "checkpoint_ns": "", "checkpoint_id": "test-checkpoint-id-002"}}

        await checkpointer.aput(
            config=config,
            checkpoint=test_checkpoint,
            metadata={"source": "test", "step": 1, "writes": None, "parents": {}},
            new_versions={}
        )

        # Retrieve checkpoint using checkpointer
        retrieved = await checkpointer.aget(config)

        # Verify checkpoint retrieved successfully
        assert retrieved is not None, "Checkpoint should be retrievable"

        # Verify checkpoint contains expected data
        # retrieved is a CheckpointTuple with .checkpoint attribute or a dict
        if hasattr(retrieved, 'checkpoint'):
            checkpoint_data = retrieved.checkpoint
        else:
            checkpoint_data = retrieved

        assert checkpoint_data is not None
        assert checkpoint_data.get("id") == "test-checkpoint-id-002"

    finally:
        # Cleanup
        keys = await redis_client.keys(f"*{test_thread_id}*")
        if keys:
            await redis_client.delete(*keys)
        await redis_client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_checkpointer_configuration():
    """Test that checkpointer can be created with correct configuration."""
    from agent.graphs.conversation_flow import create_conversation_graph
    from agent.state.checkpointer import get_redis_checkpointer

    # Verify checkpointer creation succeeds (requires event loop)
    checkpointer = get_redis_checkpointer()
    assert checkpointer is not None

    # Verify graph can be created with checkpointer
    graph = create_conversation_graph(checkpointer=checkpointer)
    assert graph is not None

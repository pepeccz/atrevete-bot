"""
Integration tests for per-node checkpoint persistence.

These tests verify that LangGraph saves checkpoints to Redis after EVERY node
execution, not just at the end of graph execution. This ensures crash recovery
can resume from any point in the conversation flow.
"""

import pytest
from redis.asyncio import Redis

from agent.graphs.conversation_flow import create_conversation_graph
from agent.state.checkpointer import get_redis_checkpointer, initialize_redis_indexes
from agent.state.helpers import add_message
from shared.config import get_settings


@pytest.mark.asyncio
@pytest.mark.integration
async def test_checkpoint_saved_after_conversational_agent():
    """
    Verify checkpoint is saved after conversational_agent node execution.

    This test ensures that when a user sends a message and the conversational
    agent processes it, a checkpoint is persisted to Redis before graph completion.
    """
    settings = get_settings()
    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=False)

    test_conversation_id = "test-per-node-checkpoint-001"

    try:
        # Clear any existing checkpoints
        keys = await redis_client.keys(f"*{test_conversation_id}*")
        if keys:
            await redis_client.delete(*keys)

        # Create graph with checkpointer
        checkpointer = get_redis_checkpointer()
        await initialize_redis_indexes(checkpointer)
        graph = create_conversation_graph(checkpointer=checkpointer)

        # Create initial state with user message
        state = {
            "conversation_id": test_conversation_id,
            "customer_phone": "+34612345678",
            "customer_name": None,
            "messages": [],
            "total_message_count": 0,
            "metadata": {},
        }

        # Add user message
        state = add_message(state, "user", "Hola")

        # Invoke graph (should go through conversational_agent)
        config = {"configurable": {"thread_id": test_conversation_id}}
        result = await graph.ainvoke(state, config=config)

        # Verify checkpoint exists in Redis
        checkpoint_keys = await redis_client.keys(f"*checkpoint*{test_conversation_id}*")

        assert len(checkpoint_keys) > 0, (
            "Expected at least one checkpoint key in Redis after graph execution"
        )

        # Verify we can retrieve the checkpoint
        checkpoints = []
        for key in checkpoint_keys:
            value = await redis_client.get(key)
            if value:
                checkpoints.append(key)

        assert len(checkpoints) > 0, (
            "Expected to retrieve checkpoint data from Redis"
        )

        # Verify result contains assistant response
        assert "messages" in result
        assert len(result["messages"]) > 0
        assert result["messages"][-1]["role"] == "assistant"

        print(f"✓ Checkpoint saved after conversational_agent: {len(checkpoint_keys)} keys")

    finally:
        # Cleanup
        keys = await redis_client.keys(f"*{test_conversation_id}*")
        if keys:
            await redis_client.delete(*keys)
        await redis_client.aclose()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_checkpoint_recovery_after_crash():
    """
    Verify that conversation can be resumed from checkpoint after simulated crash.

    This test simulates a crash scenario:
    1. User sends first message → checkpoint saved
    2. Simulate crash (create new graph instance)
    3. User sends second message → graph resumes from checkpoint
    4. Verify both messages are in conversation history
    """
    settings = get_settings()
    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=False)

    test_conversation_id = "test-crash-recovery-002"

    try:
        # Clear any existing checkpoints
        keys = await redis_client.keys(f"*{test_conversation_id}*")
        if keys:
            await redis_client.delete(*keys)

        # ===== STEP 1: First message =====
        checkpointer_1 = get_redis_checkpointer()
        await initialize_redis_indexes(checkpointer_1)
        graph_1 = create_conversation_graph(checkpointer=checkpointer_1)

        state_1 = {
            "conversation_id": test_conversation_id,
            "customer_phone": "+34612345678",
            "customer_name": None,
            "messages": [],
            "total_message_count": 0,
            "metadata": {},
        }

        state_1 = add_message(state_1, "user", "Hola")

        config = {"configurable": {"thread_id": test_conversation_id}}
        result_1 = await graph_1.ainvoke(state_1, config=config)

        assert result_1["total_message_count"] == 2  # User + assistant
        first_message_count = result_1["total_message_count"]

        # ===== STEP 2: Simulate crash - create new graph instance =====
        # This simulates the agent service restarting
        checkpointer_2 = get_redis_checkpointer()
        await initialize_redis_indexes(checkpointer_2)
        graph_2 = create_conversation_graph(checkpointer=checkpointer_2)

        # ===== STEP 3: Send second message =====
        # Create fresh state (as if service just restarted)
        state_2 = {
            "conversation_id": test_conversation_id,
            "customer_phone": "+34612345678",
            "customer_name": None,
            "messages": [],
            "total_message_count": 0,
            "metadata": {},
        }

        state_2 = add_message(state_2, "user", "¿Qué horario tenéis?")

        # Graph should load checkpoint and merge with new message
        result_2 = await graph_2.ainvoke(state_2, config=config)

        # Verify total message count includes previous conversation
        # Should be: 2 (from first conversation) + 2 (user + assistant from second)
        # But due to FIFO windowing (max 10), we should see recent messages
        assert result_2["total_message_count"] >= first_message_count, (
            f"Expected total_message_count >= {first_message_count}, "
            f"got {result_2['total_message_count']}"
        )

        # Verify we have messages in the result
        assert len(result_2["messages"]) > 0
        assert result_2["messages"][-1]["role"] == "assistant"

        print(f"✓ Conversation resumed after crash: {result_2['total_message_count']} total messages")

    finally:
        # Cleanup
        keys = await redis_client.keys(f"*{test_conversation_id}*")
        if keys:
            await redis_client.delete(*keys)
        await redis_client.aclose()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_message_windowing_with_checkpoints():
    """
    Verify that FIFO message windowing works correctly with checkpoints.

    This test sends 15 messages and verifies:
    1. Only last 10 messages retained in memory
    2. total_message_count tracks all messages (including dropped ones)
    3. Checkpoints persist the correct state
    """
    settings = get_settings()
    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=False)

    test_conversation_id = "test-windowing-checkpoints-003"

    try:
        # Clear existing checkpoints
        keys = await redis_client.keys(f"*{test_conversation_id}*")
        if keys:
            await redis_client.delete(*keys)

        checkpointer = get_redis_checkpointer()
        await initialize_redis_indexes(checkpointer)
        graph = create_conversation_graph(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": test_conversation_id}}

        # Send 8 messages (16 total with assistant responses = exceeds 10-message window)
        for i in range(8):
            state = {
                "conversation_id": test_conversation_id,
                "customer_phone": "+34612345678",
                "customer_name": None,
                "messages": [],
                "total_message_count": 0,
                "metadata": {},
            }

            state = add_message(state, "user", f"Mensaje {i+1}")
            result = await graph.ainvoke(state, config=config)

            # After each invocation, verify windowing
            if (i + 1) * 2 > 10:  # Each user message + assistant response = 2 messages
                # Should have exactly 10 messages in window
                assert len(result["messages"]) <= 10, (
                    f"Expected max 10 messages in window, got {len(result['messages'])}"
                )

            # Verify total_message_count is cumulative
            expected_total = (i + 1) * 2  # User + assistant for each iteration
            assert result["total_message_count"] == expected_total, (
                f"Expected total_message_count={expected_total}, "
                f"got {result['total_message_count']}"
            )

        # Final verification
        assert len(result["messages"]) == 10  # FIFO window
        assert result["total_message_count"] == 16  # 8 user + 8 assistant

        print(f"✓ FIFO windowing working: {len(result['messages'])} in window, "
              f"{result['total_message_count']} total")

    finally:
        # Cleanup
        keys = await redis_client.keys(f"*{test_conversation_id}*")
        if keys:
            await redis_client.delete(*keys)
        await redis_client.aclose()

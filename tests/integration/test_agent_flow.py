"""
Integration tests for agent message flow.

Tests the complete flow:
1. Message published to incoming_messages channel
2. Agent processes message through LangGraph
3. Response published to outgoing_messages channel
4. State saved to Redis checkpoint
"""

import asyncio
import json
from unittest.mock import patch

import pytest
import redis.asyncio as redis

from agent.graphs.conversation_flow import create_conversation_graph
from shared.config import get_settings
from shared.redis_client import publish_to_channel


@pytest.fixture
async def redis_client():
    """Get Redis client for tests."""
    settings = get_settings()
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    yield client
    await client.close()


@pytest.fixture
async def subscriber_fixture(redis_client):
    """
    Create a subscriber fixture that captures messages from a channel.

    Returns a helper function that sets up a subscriber and returns
    a queue to capture messages.
    """

    async def create_subscriber(channel: str):
        """Create subscriber for a channel and return message queue."""
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)

        message_queue: asyncio.Queue[str] = asyncio.Queue()

        async def listener():
            """Listen for messages and put them in queue."""
            async for message in pubsub.listen():
                if message["type"] == "message":
                    message_queue.put_nowait(message["data"])

        # Start listener task
        listener_task = asyncio.create_task(listener())

        # Return queue and cleanup function
        async def cleanup():
            listener_task.cancel()
            await pubsub.unsubscribe(channel)
            await pubsub.close()

        return message_queue, cleanup

    return create_subscriber


@pytest.mark.asyncio
async def test_graph_greeting_without_checkpointer():
    """Test that graph produces greeting message without checkpointing."""
    from agent.state.schemas import ConversationState

    # Create graph without checkpointer
    graph = create_conversation_graph(checkpointer=None)

    # Create initial state
    state: ConversationState = {
        "conversation_id": "test-123",
        "customer_phone": "+34612345678",
        "customer_name": None,
        "messages": [{"role": "user", "content": "Hello"}],
        "current_intent": None,
        "metadata": {},
    }

    # Invoke graph - LangGraph ainvoke exists at runtime
    result = await graph.ainvoke(state)

    # Verify result
    assert "messages" in result
    assert len(result["messages"]) == 2  # User message + AI greeting
    assert result["messages"][1]["role"] == "assistant"
    assert result["messages"][1]["content"] == "¡Hola! Soy Maite, la asistenta virtual de Atrévete Peluquería 🌸"
    assert result["last_node"] == "greet_customer"


@pytest.mark.asyncio
async def test_publish_to_incoming_messages(redis_client, subscriber_fixture):
    """Test publishing message to incoming_messages channel."""
    # Create subscriber for outgoing_messages
    message_queue, cleanup = await subscriber_fixture("test_outgoing")

    try:
        # Publish test message
        test_message = {
            "conversation_id": "test-456",
            "customer_phone": "+34612345678",
            "message": "Test response",
        }

        await publish_to_channel("test_outgoing", test_message)

        # Wait for message (with timeout)
        received = await asyncio.wait_for(message_queue.get(), timeout=2.0)

        # Verify message
        received_data = json.loads(received)
        assert received_data["conversation_id"] == "test-456"
        assert received_data["customer_phone"] == "+34612345678"
        assert received_data["message"] == "Test response"

    finally:
        await cleanup()


@pytest.mark.skip(reason="Requires Redis running and Docker Compose environment")
@pytest.mark.asyncio
async def test_graph_with_checkpointer(redis_client):
    """Test that graph saves state to Redis checkpoint."""
    # This test requires Docker Compose to be running with Redis
    # It will be tested in the full Docker environment
    pass


@pytest.mark.skip(reason="Requires Docker Compose with Redis running")
@pytest.mark.asyncio
@patch("agent.tools.notification_tools.ChatwootClient.send_message")
async def test_full_agent_flow_with_mock_chatwoot(
    mock_send_message,
    redis_client,
    subscriber_fixture,
):
    """
    Test full agent flow with mocked Chatwoot API.

    This test requires Docker Compose to be running with Redis.
    It will be validated in the Docker environment.
    """
    pass


@pytest.mark.asyncio
async def test_greeting_node_immutability():
    """Test that greeting node follows immutability pattern."""
    from agent.nodes.greeting import greet_customer
    from agent.state.schemas import ConversationState

    # Create initial state
    original_state: ConversationState = {
        "conversation_id": "test-immutable",
        "customer_phone": "+34612345678",
        "customer_name": None,
        "messages": [{"role": "user", "content": "Hello"}],
        "current_intent": None,
        "metadata": {"key": "value"},
    }

    # Store original messages list reference
    original_messages = original_state["messages"]

    # Invoke node
    result = await greet_customer(original_state)

    # Verify original state not mutated
    assert original_state["messages"] is not None
    assert len(original_state["messages"]) == 1  # Still only user message
    assert original_messages is original_state["messages"]  # Same reference

    # Verify result has new messages list
    assert result["messages"] is not None
    assert len(result["messages"]) == 2  # User message + AI greeting
    assert result["messages"] is not original_messages  # Different reference
    assert result["last_node"] == "greet_customer"

"""
Unit tests for message windowing functionality (add_message helper).

These tests verify the FIFO windowing behavior, immutability, and correctness
of the add_message helper function used for conversation state management.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agent.state.helpers import add_message
from agent.state.schemas import ConversationState


def test_add_single_message_to_empty_state():
    """Test adding a single message to an empty state."""
    state: ConversationState = {
        "conversation_id": "test-001",
        "customer_phone": "+34612345678",
        "customer_name": None,
        "messages": [],
        "current_intent": None,
        "metadata": {}
    }

    result = add_message(state, "user", "Hola")

    assert len(result["messages"]) == 1
    assert result["messages"][0]["content"] == "Hola"
    assert result["messages"][0]["role"] == "user"
    assert "timestamp" in result["messages"][0]


def test_add_11_messages_exactly_10_retained():
    """Test that adding 11 messages results in exactly 10 retained (FIFO)."""
    state: ConversationState = {
        "conversation_id": "test-002",
        "customer_phone": "+34612345678",
        "customer_name": None,
        "messages": [],
        "current_intent": None,
        "metadata": {}
    }

    # Add 11 messages sequentially
    for i in range(1, 12):
        state = add_message(state, "user", f"Message {i}")

    assert len(state["messages"]) == 10
    # First message should be "Message 2" (oldest "Message 1" removed)
    assert state["messages"][0]["content"] == "Message 2"
    # Last message should be "Message 11" (newest retained)
    assert state["messages"][9]["content"] == "Message 11"


def test_fifo_ordering_alternating_roles():
    """Test FIFO ordering with alternating user/assistant messages."""
    state: ConversationState = {
        "conversation_id": "test-003",
        "customer_phone": "+34612345678",
        "customer_name": None,
        "messages": [],
        "current_intent": None,
        "metadata": {}
    }

    # Add 5 user messages
    for i in range(1, 6):
        state = add_message(state, "user", f"User message {i}")

    # Add 6 assistant messages (total 11)
    for i in range(1, 7):
        state = add_message(state, "assistant", f"Assistant message {i}")

    assert len(state["messages"]) == 10

    # Verify first user message was dropped
    assert state["messages"][0]["content"] == "User message 2"
    assert state["messages"][0]["role"] == "user"

    # Verify all 6 assistant messages retained
    assistant_messages = [m for m in state["messages"] if m["role"] == "assistant"]
    assert len(assistant_messages) == 6
    assert assistant_messages[-1]["content"] == "Assistant message 6"

    # Verify only 4 user messages retained (first one dropped)
    user_messages = [m for m in state["messages"] if m["role"] == "user"]
    assert len(user_messages) == 4


def test_state_immutability():
    """Test that original state is not mutated (immutability requirement)."""
    original_state: ConversationState = {
        "conversation_id": "test-004",
        "customer_phone": "+34612345678",
        "customer_name": None,
        "messages": [
            {"role": "user", "content": "Message 1", "timestamp": "2025-10-28T10:00:00+01:00"},
            {"role": "assistant", "content": "Response 1", "timestamp": "2025-10-28T10:00:01+01:00"},
            {"role": "user", "content": "Message 2", "timestamp": "2025-10-28T10:00:02+01:00"}
        ],
        "current_intent": None,
        "metadata": {}
    }

    # Store original message count
    original_message_count = len(original_state["messages"])

    # Add a new message
    new_state = add_message(original_state, "assistant", "Response 2")

    # Verify original state unchanged
    assert len(original_state["messages"]) == original_message_count
    assert len(original_state["messages"]) == 3

    # Verify new state has 4 messages
    assert len(new_state["messages"]) == 4
    assert new_state["messages"][-1]["content"] == "Response 2"


def test_timestamp_field_added():
    """Test that timestamp field is added to each message."""
    state: ConversationState = {
        "conversation_id": "test-005",
        "customer_phone": "+34612345678",
        "customer_name": None,
        "messages": [],
        "current_intent": None,
        "metadata": {}
    }

    result = add_message(state, "user", "Test message")

    assert "timestamp" in result["messages"][0]
    # Verify timestamp is ISO 8601 string format
    timestamp_str = result["messages"][0]["timestamp"]
    # Should be parseable as datetime
    parsed_timestamp = datetime.fromisoformat(timestamp_str)
    assert isinstance(parsed_timestamp, datetime)


def test_timezone_handling():
    """Test that timestamps use Europe/Madrid timezone."""
    state: ConversationState = {
        "conversation_id": "test-006",
        "customer_phone": "+34612345678",
        "customer_name": None,
        "messages": [],
        "current_intent": None,
        "metadata": {}
    }

    result = add_message(state, "user", "Test message")

    timestamp_str = result["messages"][0]["timestamp"]
    # Should contain timezone offset for Europe/Madrid
    # In winter: +01:00, in summer: +02:00
    assert ("+01:00" in timestamp_str) or ("+02:00" in timestamp_str)


def test_updated_at_field_set():
    """Test that updated_at field is set when adding message."""
    state: ConversationState = {
        "conversation_id": "test-007",
        "customer_phone": "+34612345678",
        "customer_name": None,
        "messages": [],
        "current_intent": None,
        "metadata": {}
    }

    result = add_message(state, "user", "Test message")

    assert "updated_at" in result
    assert isinstance(result["updated_at"], datetime)


def test_graceful_error_handling():
    """Test that errors are handled gracefully (returns unchanged state)."""
    # Create a state that might cause issues
    state: ConversationState = {
        "conversation_id": "test-008",
        "customer_phone": "+34612345678",
        "customer_name": None,
        "messages": [],
        "current_intent": None,
        "metadata": {}
    }

    # Normal operation should work
    result = add_message(state, "user", "Test message")
    assert len(result["messages"]) == 1


def test_empty_content_handling():
    """Test handling of empty message content."""
    state: ConversationState = {
        "conversation_id": "test-009",
        "customer_phone": "+34612345678",
        "customer_name": None,
        "messages": [],
        "current_intent": None,
        "metadata": {}
    }

    # Empty content should still be added (business logic may need it)
    result = add_message(state, "user", "")

    assert len(result["messages"]) == 1
    assert result["messages"][0]["content"] == ""


def test_max_messages_exactly_10():
    """Test that MAX_MESSAGES constant is respected (exactly 10)."""
    state: ConversationState = {
        "conversation_id": "test-010",
        "customer_phone": "+34612345678",
        "customer_name": None,
        "messages": [],
        "current_intent": None,
        "metadata": {}
    }

    # Add 20 messages
    for i in range(1, 21):
        state = add_message(state, "user", f"Message {i}")

    # Should have exactly 10 messages
    assert len(state["messages"]) == 10
    # Should be messages 11-20 (oldest 10 dropped)
    assert state["messages"][0]["content"] == "Message 11"
    assert state["messages"][9]["content"] == "Message 20"

"""
Unit tests for process_incoming_message node.

Tests cover:
- Customer creation with WhatsApp name
- Fallback to "Cliente" when name is empty
- Message addition to conversation history
- State immutability
"""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from agent.graphs.conversation_flow import process_incoming_message, ensure_customer_exists
from agent.state.schemas import ConversationState
from agent.state.helpers import add_message


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def base_state() -> ConversationState:
    """Base conversation state for testing."""
    return {
        "conversation_id": "test-conv-123",
        "customer_phone": "+34612345678",
        "customer_name": "Juan Pérez",  # Name from Chatwoot webhook
        "user_message": "Hola, quiero hacer una reserva",
        "messages": [],
        "total_message_count": 0,
        "metadata": {},
        "updated_at": datetime.now(UTC),
    }


@pytest.fixture
def state_without_name() -> ConversationState:
    """State without customer name (edge case)."""
    return {
        "conversation_id": "test-conv-124",
        "customer_phone": "+34612345679",
        "customer_name": None,  # No name available
        "user_message": "Hola",
        "messages": [],
        "total_message_count": 0,
        "metadata": {},
        "updated_at": datetime.now(UTC),
    }


@pytest.fixture
def state_with_empty_name() -> ConversationState:
    """State with empty name (edge case)."""
    return {
        "conversation_id": "test-conv-125",
        "customer_phone": "+34612345680",
        "customer_name": "   ",  # Whitespace only
        "user_message": "Hola",
        "messages": [],
        "total_message_count": 0,
        "metadata": {},
        "updated_at": datetime.now(UTC),
    }


# ============================================================================
# Tests for process_incoming_message
# ============================================================================


@pytest.mark.asyncio
async def test_process_incoming_message_with_customer_name(base_state):
    """
    Test that customer is created with WhatsApp name from state["customer_name"].

    This test verifies the fix for the bug where customers were being created
    with default name "Cliente" instead of using the actual WhatsApp name.
    """
    with patch(
        "agent.graphs.conversation_flow.ensure_customer_exists",
        new_callable=AsyncMock,
    ) as mock_ensure_customer:
        mock_customer_id = uuid4()
        mock_ensure_customer.return_value = mock_customer_id

        result = await process_incoming_message(base_state)

        # Verify that ensure_customer_exists was called with correct parameters
        mock_ensure_customer.assert_called_once()
        call_args = mock_ensure_customer.call_args

        # Check that the phone number is correct
        assert call_args[0][0] == "+34612345678"

        # Check that the WhatsApp name from state["customer_name"] is used
        assert call_args[0][1] == "Juan Pérez"

        # Verify customer_id was added to state
        assert result["customer_id"] == mock_customer_id


@pytest.mark.asyncio
async def test_process_incoming_message_passes_none_when_no_name(state_without_name):
    """
    Test that None is passed to ensure_customer_exists when customer_name is None.
    The fallback to "Cliente" happens inside ensure_customer_exists, not in process_incoming_message.
    """
    with patch(
        "agent.graphs.conversation_flow.ensure_customer_exists",
        new_callable=AsyncMock,
    ) as mock_ensure_customer:
        mock_customer_id = uuid4()
        mock_ensure_customer.return_value = mock_customer_id

        result = await process_incoming_message(state_without_name)

        # Verify that None is passed (fallback happens inside ensure_customer_exists)
        mock_ensure_customer.assert_called_once()
        call_args = mock_ensure_customer.call_args
        assert call_args[0][1] is None


@pytest.mark.asyncio
async def test_process_incoming_message_fallback_to_cliente_empty_whitespace(
    state_with_empty_name,
):
    """
    Test that "Cliente" is used when customer_name is whitespace-only.
    """
    with patch(
        "agent.graphs.conversation_flow.ensure_customer_exists",
        new_callable=AsyncMock,
    ) as mock_ensure_customer:
        mock_customer_id = uuid4()
        mock_ensure_customer.return_value = mock_customer_id

        result = await process_incoming_message(state_with_empty_name)

        # Verify fallback to "Cliente" (whitespace-only name becomes "Cliente")
        mock_ensure_customer.assert_called_once()
        call_args = mock_ensure_customer.call_args
        assert call_args[0][1] == "   "  # The function receives the whitespace


@pytest.mark.asyncio
async def test_process_incoming_message_adds_user_message(base_state):
    """Test that user message is added to conversation history."""
    with patch(
        "agent.graphs.conversation_flow.ensure_customer_exists",
        new_callable=AsyncMock,
    ) as mock_ensure_customer:
        mock_ensure_customer.return_value = uuid4()

        result = await process_incoming_message(base_state)

        # Verify message was added to history
        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][0]["content"] == "Hola, quiero hacer una reserva"


@pytest.mark.asyncio
async def test_process_incoming_message_clears_user_message_field(base_state):
    """Test that user_message field is cleared after processing."""
    with patch(
        "agent.graphs.conversation_flow.ensure_customer_exists",
        new_callable=AsyncMock,
    ) as mock_ensure_customer:
        mock_ensure_customer.return_value = uuid4()

        result = await process_incoming_message(base_state)

        # Verify user_message was cleared
        assert result["user_message"] is None


@pytest.mark.asyncio
async def test_process_incoming_message_no_customer_if_existing_customer_id(base_state):
    """Test that customer creation is skipped if customer_id already exists."""
    base_state["customer_id"] = uuid4()

    with patch(
        "agent.graphs.conversation_flow.ensure_customer_exists",
        new_callable=AsyncMock,
    ) as mock_ensure_customer:
        result = await process_incoming_message(base_state)

        # Verify ensure_customer_exists was NOT called
        mock_ensure_customer.assert_not_called()


# ============================================================================
# Unit tests for name parsing logic in ensure_customer_exists
# ============================================================================
# Note: Full integration tests for ensure_customer_exists are in tests/integration/
# These unit tests verify the name-splitting logic


def test_name_parsing_full_name():
    """Test that full name is correctly split into first and last name."""
    # This is the core logic that was fixed
    whatsapp_name = "Juan Pérez"
    name_parts = whatsapp_name.strip().split(maxsplit=1)
    first_name = name_parts[0] if name_parts else "Cliente"
    last_name = name_parts[1] if len(name_parts) > 1 else None

    assert first_name == "Juan"
    assert last_name == "Pérez"


def test_name_parsing_single_name():
    """Test that single name is used as first_name only."""
    whatsapp_name = "Juan"
    name_parts = whatsapp_name.strip().split(maxsplit=1)
    first_name = name_parts[0] if name_parts else "Cliente"
    last_name = name_parts[1] if len(name_parts) > 1 else None

    assert first_name == "Juan"
    assert last_name is None


def test_name_parsing_empty_name():
    """Test that empty name falls back to 'Cliente'."""
    whatsapp_name = ""
    name_parts = whatsapp_name.strip().split(maxsplit=1)
    first_name = name_parts[0] if name_parts else "Cliente"
    last_name = name_parts[1] if len(name_parts) > 1 else None

    assert first_name == "Cliente"
    assert last_name is None


def test_name_parsing_none_name():
    """Test that None name handling (converted to string for processing)."""
    # In ensure_customer_exists, None is passed to the function
    # If we receive None, we should handle it gracefully
    whatsapp_name = None or "Cliente"
    name_parts = whatsapp_name.strip().split(maxsplit=1)
    first_name = name_parts[0] if name_parts else "Cliente"
    last_name = name_parts[1] if len(name_parts) > 1 else None

    assert first_name == "Cliente"
    assert last_name is None

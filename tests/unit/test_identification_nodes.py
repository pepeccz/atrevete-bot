"""
Unit tests for customer identification nodes.

Tests cover:
- identify_customer node (customer found vs not found)
- greet_new_customer node (with/without metadata name)
- confirm_name node (all three classification paths)
- State immutability
- Error handling
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage

from agent.nodes.identification import confirm_name, greet_new_customer, identify_customer
from agent.state.schemas import ConversationState


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def base_state() -> ConversationState:
    """Base conversation state for testing."""
    return {
        "conversation_id": "test-conv-123",
        "customer_phone": "+34612345678",
        "messages": [],
        "metadata": {},
    }


@pytest.fixture
def mock_customer_data():
    """Mock customer data returned from database."""
    return {
        "id": str(uuid4()),
        "phone": "+34612345678",
        "first_name": "María",
        "last_name": "García",
        "total_spent": 150.00,
        "last_service_date": None,
        "preferred_stylist_id": None,
        "created_at": "2025-10-28T10:00:00",
    }


# ============================================================================
# Tests for identify_customer
# ============================================================================


@pytest.mark.asyncio
async def test_identify_customer_found(base_state, mock_customer_data):
    """Test identify_customer when customer exists in database."""
    with patch("agent.nodes.identification.get_customer_by_phone") as mock_get:
        mock_get.ainvoke = AsyncMock(return_value=mock_customer_data)

        result = await identify_customer(base_state)

        # Verify state updates
        assert result["customer_id"] == mock_customer_data["id"]
        assert result["customer_name"] == "María García"
        assert result["is_returning_customer"] is True

        # Verify original state not mutated
        assert "customer_id" not in base_state


@pytest.mark.asyncio
async def test_identify_customer_not_found(base_state):
    """Test identify_customer when customer does not exist."""
    with patch("agent.nodes.identification.get_customer_by_phone") as mock_get:
        mock_get.ainvoke = AsyncMock(return_value=None)

        result = await identify_customer(base_state)

        # Verify state updates
        assert result["is_returning_customer"] is False
        assert "customer_id" not in result

        # Verify original state not mutated
        assert "is_returning_customer" not in base_state


@pytest.mark.asyncio
async def test_identify_customer_database_error(base_state):
    """Test identify_customer handles database errors gracefully."""
    with patch("agent.nodes.identification.get_customer_by_phone") as mock_get:
        mock_get.ainvoke = AsyncMock(side_effect=Exception("Database connection failed"))

        result = await identify_customer(base_state)

        # Verify error handling
        assert result["error_count"] == 1
        assert result["is_returning_customer"] is False


@pytest.mark.asyncio
async def test_identify_customer_error_in_result(base_state):
    """Test identify_customer when get_customer_by_phone returns error dict."""
    with patch("agent.nodes.identification.get_customer_by_phone") as mock_get:
        mock_get.ainvoke = AsyncMock(return_value={"error": "Invalid phone number format"})

        result = await identify_customer(base_state)

        # Verify state updates - treat as not found
        assert result["is_returning_customer"] is False


# ============================================================================
# Tests for greet_new_customer
# ============================================================================


@pytest.mark.asyncio
async def test_greet_new_customer_with_reliable_name(base_state):
    """Test greet_new_customer with reliable WhatsApp metadata name."""
    state_with_name = {
        **base_state,
        "metadata": {"whatsapp_name": "Carlos"},
    }

    result = await greet_new_customer(state_with_name)

    # Verify greeting message
    assert len(result["messages"]) == 1
    message = result["messages"][0]
    assert isinstance(message, AIMessage)
    assert "Maite" in message.content
    assert "🌸" in message.content
    assert "Carlos" in message.content
    assert "¿Me confirmas si tu nombre es Carlos?" in message.content

    # Verify state updates
    assert result["awaiting_name_confirmation"] is True

    # Verify original state not mutated
    assert "awaiting_name_confirmation" not in state_with_name


@pytest.mark.asyncio
async def test_greet_new_customer_without_metadata_name(base_state):
    """Test greet_new_customer without WhatsApp metadata name."""
    result = await greet_new_customer(base_state)

    # Verify greeting message
    assert len(result["messages"]) == 1
    message = result["messages"][0]
    assert isinstance(message, AIMessage)
    assert "Maite" in message.content
    assert "🌸" in message.content
    assert "¿Me confirmas tu nombre para dirigirme a ti correctamente?" in message.content

    # Verify state updates
    assert result["awaiting_name_confirmation"] is True


@pytest.mark.asyncio
async def test_greet_new_customer_unreliable_name_numeric(base_state):
    """Test greet_new_customer with unreliable numeric metadata name."""
    state_with_numeric = {
        **base_state,
        "metadata": {"whatsapp_name": "123456"},
    }

    result = await greet_new_customer(state_with_numeric)

    # Verify it treats as unreliable and asks for name
    message = result["messages"][0]
    assert "¿Me confirmas tu nombre para dirigirme a ti correctamente?" in message.content


@pytest.mark.asyncio
async def test_greet_new_customer_unreliable_name_too_short(base_state):
    """Test greet_new_customer with unreliable short metadata name."""
    state_with_short = {
        **base_state,
        "metadata": {"whatsapp_name": "AB"},
    }

    result = await greet_new_customer(state_with_short)

    # Verify it treats as unreliable
    message = result["messages"][0]
    assert "¿Me confirmas tu nombre para dirigirme a ti correctamente?" in message.content


@pytest.mark.asyncio
async def test_greet_new_customer_emoji_present(base_state):
    """Test that greeting message contains 🌸 emoji."""
    result = await greet_new_customer(base_state)
    message = result["messages"][0]
    assert "🌸" in message.content


@pytest.mark.asyncio
async def test_greet_new_customer_preserves_existing_messages(base_state):
    """Test that greet_new_customer preserves existing messages."""
    state_with_messages = {
        **base_state,
        "messages": [HumanMessage(content="Hola")],
    }

    result = await greet_new_customer(state_with_messages)

    # Verify existing message preserved and new one added
    assert len(result["messages"]) == 2
    assert isinstance(result["messages"][0], HumanMessage)
    assert isinstance(result["messages"][1], AIMessage)


# ============================================================================
# Tests for confirm_name
# ============================================================================


@pytest.mark.asyncio
async def test_confirm_name_confirmed_path(base_state):
    """Test confirm_name when user confirms the name."""
    state_with_response = {
        **base_state,
        "metadata": {"whatsapp_name": "Ana Martín"},
        "messages": [HumanMessage(content="Sí, correcto")],
    }

    mock_customer = {
        "id": str(uuid4()),
        "phone": "+34612345678",
        "first_name": "Ana",
        "last_name": "Martín",
        "total_spent": 0.0,
        "created_at": "2025-10-28T10:00:00",
    }

    with patch("agent.nodes.identification.llm") as mock_llm, \
         patch("agent.nodes.identification.create_customer") as mock_create:
        mock_llm_response = MagicMock()
        mock_llm_response.content = "confirmed"
        mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response)
        mock_create.ainvoke = AsyncMock(return_value=mock_customer)

        result = await confirm_name(state_with_response)

        # Verify customer created
        mock_create.ainvoke.assert_called_once_with({
            "phone": "+34612345678",
            "first_name": "Ana",
            "last_name": "Martín"
        })

        # Verify state updates
        assert result["customer_id"] == mock_customer["id"]
        assert result["customer_name"] == "Ana Martín"
        assert result["customer_identified"] is True
        assert result["awaiting_name_confirmation"] is False


@pytest.mark.asyncio
async def test_confirm_name_different_name_path(base_state):
    """Test confirm_name when user provides a different name."""
    state_with_response = {
        **base_state,
        "metadata": {"whatsapp_name": "Juan"},
        "messages": [HumanMessage(content="No, mi nombre es Pedro López")],
    }

    mock_customer = {
        "id": str(uuid4()),
        "phone": "+34612345678",
        "first_name": "Pedro",
        "last_name": "López",
        "total_spent": 0.0,
        "created_at": "2025-10-28T10:00:00",
    }

    with patch("agent.nodes.identification.llm") as mock_llm, \
         patch("agent.nodes.identification.create_customer") as mock_create:
        mock_llm_response = MagicMock()
        mock_llm_response.content = "different_name:Pedro López"
        mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response)
        mock_create.ainvoke = AsyncMock(return_value=mock_customer)

        result = await confirm_name(state_with_response)

        # Verify customer created with corrected name
        mock_create.ainvoke.assert_called_once_with({
            "phone": "+34612345678",
            "first_name": "Pedro",
            "last_name": "López"
        })

        # Verify state updates
        assert result["customer_id"] == mock_customer["id"]
        assert result["customer_name"] == "Pedro López"
        assert result["customer_identified"] is True


@pytest.mark.asyncio
async def test_confirm_name_ambiguous_first_attempt(base_state):
    """Test confirm_name with ambiguous response on first attempt."""
    state_with_response = {
        **base_state,
        "clarification_attempts": 0,
        "messages": [HumanMessage(content="mmm... no sé")],
    }

    with patch("agent.nodes.identification.llm") as mock_llm:
        mock_llm_response = MagicMock()
        mock_llm_response.content = "ambiguous"
        mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response)

        result = await confirm_name(state_with_response)

        # Verify clarification request
        assert result["clarification_attempts"] == 1
        assert len(result["messages"]) == 2  # Original + clarification
        clarification_msg = result["messages"][1]
        assert isinstance(clarification_msg, AIMessage)
        assert "nombre completo" in clarification_msg.content.lower()

        # Verify NOT escalated yet
        assert "escalated" not in result or not result.get("escalated")


@pytest.mark.asyncio
async def test_confirm_name_ambiguous_second_attempt_escalates(base_state):
    """Test confirm_name escalates after 2 ambiguous responses."""
    state_with_response = {
        **base_state,
        "clarification_attempts": 1,  # Already had one attempt
        "messages": [HumanMessage(content="no entiendo")],
    }

    with patch("agent.nodes.identification.llm") as mock_llm:
        mock_llm_response = MagicMock()
        mock_llm_response.content = "ambiguous"
        mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response)

        result = await confirm_name(state_with_response)

        # Verify escalation
        assert result["escalated"] is True
        assert result["escalation_reason"] == "ambiguity"
        assert result["clarification_attempts"] == 2

        # Verify escalation message
        escalation_msg = result["messages"][1]
        assert isinstance(escalation_msg, AIMessage)
        assert "equipo" in escalation_msg.content.lower()


@pytest.mark.asyncio
async def test_confirm_name_no_user_messages_error(base_state):
    """Test confirm_name handles missing user messages."""
    state_no_messages = {
        **base_state,
        "messages": [],  # No messages
    }

    result = await confirm_name(state_no_messages)

    # Verify error handling
    assert result["error_count"] == 1


@pytest.mark.asyncio
async def test_confirm_name_create_customer_failure(base_state):
    """Test confirm_name handles customer creation failures."""
    state_with_response = {
        **base_state,
        "metadata": {"whatsapp_name": "Test User"},
        "messages": [HumanMessage(content="Sí")],
    }

    with patch("agent.nodes.identification.llm") as mock_llm, \
         patch("agent.nodes.identification.create_customer") as mock_create:
        mock_llm_response = MagicMock()
        mock_llm_response.content = "confirmed"
        mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response)
        mock_create.ainvoke = AsyncMock(return_value={"error": "Database error"})

        result = await confirm_name(state_with_response)

        # Verify error handling
        assert result["error_count"] == 1
        assert "customer_identified" not in result or not result.get("customer_identified")


@pytest.mark.asyncio
async def test_confirm_name_state_immutability(base_state):
    """Test that confirm_name does not mutate original state."""
    state_with_response = {
        **base_state,
        "metadata": {"whatsapp_name": "Test"},
        "messages": [HumanMessage(content="Sí")],
    }

    mock_customer = {
        "id": str(uuid4()),
        "phone": "+34612345678",
        "first_name": "Test",
        "last_name": "",
        "total_spent": 0.0,
        "created_at": "2025-10-28T10:00:00",
    }

    with patch("agent.nodes.identification.llm") as mock_llm, \
         patch("agent.nodes.identification.create_customer") as mock_create:
        mock_llm_response = MagicMock()
        mock_llm_response.content = "confirmed"
        mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response)
        mock_create.ainvoke = AsyncMock(return_value=mock_customer)

        result = await confirm_name(state_with_response)

        # Verify original state not mutated
        assert "customer_identified" not in state_with_response
        assert "customer_id" not in state_with_response


@pytest.mark.asyncio
async def test_confirm_name_single_word_name(base_state):
    """Test confirm_name with single-word name (no last name)."""
    state_with_response = {
        **base_state,
        "metadata": {"whatsapp_name": "María"},
        "messages": [HumanMessage(content="Sí")],
    }

    mock_customer = {
        "id": str(uuid4()),
        "phone": "+34612345678",
        "first_name": "María",
        "last_name": "",
        "total_spent": 0.0,
        "created_at": "2025-10-28T10:00:00",
    }

    with patch("agent.nodes.identification.llm") as mock_llm, \
         patch("agent.nodes.identification.create_customer") as mock_create:
        mock_llm_response = MagicMock()
        mock_llm_response.content = "confirmed"
        mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response)
        mock_create.ainvoke = AsyncMock(return_value=mock_customer)

        result = await confirm_name(state_with_response)

        # Verify customer created with empty last name
        mock_create.ainvoke.assert_called_once_with({
            "phone": "+34612345678",
            "first_name": "María",
            "last_name": ""
        })
        assert result["customer_name"] == "María"

"""
Unit tests for conversational agent node.

Tests cover:
- Basic conversational flow
- Booking intent detection
- Tool calling (customer identification, creation)
- Error handling
- State immutability
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, HumanMessage

from agent.nodes.conversational_agent import (
    conversational_agent,
    detect_booking_intent,
    format_llm_messages_with_summary,
)
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
        "messages": [
            {
                "role": "human",
                "content": "Hola, quiero información sobre mechas",
                "timestamp": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(),
            }
        ],
        "metadata": {},
    }


@pytest.fixture
def mock_llm_response_inquiry():
    """Mock LLM response for service inquiry (no booking intent)."""
    return AIMessage(
        content="¡Hola! 🌸 Las mechas cuestan 60€ y duran aproximadamente 120 minutos. ¿Te gustaría conocer más detalles?"
    )


@pytest.fixture
def mock_llm_response_booking():
    """Mock LLM response with booking intent."""
    return AIMessage(
        content="Perfecto, quiero reservar mechas para el viernes. ¿Qué horarios tienes disponibles?"
    )


# ============================================================================
# Tests for detect_booking_intent
# ============================================================================


def test_detect_booking_intent_positive():
    """Test booking intent detection with positive signals."""
    # Test various booking keywords
    test_cases = [
        "Quiero reservar mechas para el viernes",
        "Dame cita para mañana",
        "Perfecto, reserva la cita",
        "Sí, confirmo la cita",
        "Quiero el pack",
    ]

    for content in test_cases:
        response = AIMessage(content=content)
        assert detect_booking_intent(response) is True, f"Failed to detect booking intent in: {content}"


def test_detect_booking_intent_negative():
    """Test booking intent detection with negative signals (inquiry only)."""
    # Test inquiry-only messages (NOT booking intent)
    test_cases = [
        "¿Cuánto cuesta el corte?",
        "¿Tenéis libre para mañana?",
        "¿Qué diferencia hay entre mechas y balayage?",
        "Hola, quiero información",
        "¿Dónde estáis ubicados?",
    ]

    for content in test_cases:
        response = AIMessage(content=content)
        assert detect_booking_intent(response) is False, f"False positive booking intent in: {content}"


def test_detect_booking_intent_empty():
    """Test booking intent detection with empty response."""
    response = AIMessage(content="")
    assert detect_booking_intent(response) is False

    # Test with whitespace-only content
    response = AIMessage(content="   ")
    assert detect_booking_intent(response) is False


# ============================================================================
# Tests for format_llm_messages_with_summary
# ============================================================================


def test_format_llm_messages_basic(base_state):
    """Test basic message formatting without summary."""
    system_prompt = "You are Maite, a helpful assistant."

    messages = format_llm_messages_with_summary(base_state, system_prompt)

    # Should have system message + 1 human message
    assert len(messages) == 2
    assert messages[0].content == system_prompt
    assert isinstance(messages[1], HumanMessage)
    assert messages[1].content == "Hola, quiero información sobre mechas"


def test_format_llm_messages_with_summary(base_state):
    """Test message formatting with conversation summary."""
    system_prompt = "You are Maite."
    base_state["conversation_summary"] = "Customer previously asked about prices for corte."

    messages = format_llm_messages_with_summary(base_state, system_prompt)

    # Should have system message + summary message + 1 human message
    assert len(messages) == 3
    assert "Previous conversation summary" in messages[1].content
    assert "Customer previously asked about prices for corte" in messages[1].content


def test_format_llm_messages_multiple_turns(base_state):
    """Test message formatting with multiple conversation turns."""
    base_state["messages"] = [
        {"role": "human", "content": "Hola", "timestamp": "2025-01-01T10:00:00"},
        {"role": "ai", "content": "¡Hola! 🌸 ¿En qué puedo ayudarte?", "timestamp": "2025-01-01T10:00:01"},
        {"role": "human", "content": "Quiero mechas", "timestamp": "2025-01-01T10:01:00"},
    ]

    system_prompt = "You are Maite."
    messages = format_llm_messages_with_summary(base_state, system_prompt)

    # Should have system message + 3 messages (human, ai, human)
    assert len(messages) == 4
    assert isinstance(messages[1], HumanMessage)
    assert isinstance(messages[2], AIMessage)
    assert isinstance(messages[3], HumanMessage)


# ============================================================================
# Tests for conversational_agent node
# ============================================================================


@pytest.mark.asyncio
async def test_conversational_agent_inquiry_flow(base_state, mock_llm_response_inquiry):
    """Test conversational agent with inquiry (no booking intent)."""
    with patch("agent.nodes.conversational_agent.get_llm_with_tools") as mock_get_llm, \
         patch("agent.nodes.conversational_agent.load_maite_system_prompt") as mock_prompt:

        mock_prompt.return_value = "System prompt"

        # Mock LLM
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response_inquiry)
        mock_get_llm.return_value = mock_llm

        result = await conversational_agent(base_state)

        # Verify state updates
        assert "messages" in result
        assert len(result["messages"]) == 2  # Original + AI response
        assert result["messages"][1]["role"] == "ai"
        assert "mechas" in result["messages"][1]["content"].lower()

        # Verify booking intent NOT detected
        assert result["booking_intent_confirmed"] is False

        # Verify timestamps
        assert "updated_at" in result
        assert result["last_node"] == "conversational_agent"

        # Verify original state not mutated
        assert len(base_state["messages"]) == 1


@pytest.mark.asyncio
async def test_conversational_agent_booking_intent_detected(base_state, mock_llm_response_booking):
    """Test conversational agent with booking intent detection."""
    with patch("agent.nodes.conversational_agent.get_llm_with_tools") as mock_get_llm, \
         patch("agent.nodes.conversational_agent.load_maite_system_prompt") as mock_prompt:

        mock_prompt.return_value = "System prompt"

        # Mock LLM with booking intent response
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response_booking)
        mock_get_llm.return_value = mock_llm

        result = await conversational_agent(base_state)

        # Verify booking intent detected
        assert result["booking_intent_confirmed"] is True

        # Verify message added
        assert len(result["messages"]) == 2


@pytest.mark.asyncio
async def test_conversational_agent_tool_calling(base_state):
    """Test conversational agent with tool calls."""
    with patch("agent.nodes.conversational_agent.get_llm_with_tools") as mock_get_llm, \
         patch("agent.nodes.conversational_agent.load_maite_system_prompt") as mock_prompt:

        mock_prompt.return_value = "System prompt"

        # Mock LLM response with tool calls
        mock_response = AIMessage(
            content="Déjame buscar tu información...",
        )
        mock_response.tool_calls = [
            {"name": "get_customer_by_phone", "args": {"phone": "+34612345678"}}
        ]

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm

        result = await conversational_agent(base_state)

        # Verify tool calls were logged (implicit in the mock)
        assert "messages" in result
        assert result["booking_intent_confirmed"] is False


@pytest.mark.asyncio
async def test_conversational_agent_error_handling(base_state):
    """Test conversational agent error handling."""
    with patch("agent.nodes.conversational_agent.get_llm_with_tools") as mock_get_llm, \
         patch("agent.nodes.conversational_agent.load_maite_system_prompt") as mock_prompt:

        mock_prompt.return_value = "System prompt"

        # Mock LLM to raise exception
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("API error"))
        mock_get_llm.return_value = mock_llm

        result = await conversational_agent(base_state)

        # Verify error handling
        assert result["error_count"] == 1
        assert result["last_node"] == "conversational_agent"

        # Verify error message added
        assert len(result["messages"]) == 2
        assert "Lo siento" in result["messages"][1]["content"]


@pytest.mark.asyncio
async def test_conversational_agent_state_immutability(base_state):
    """Test that conversational agent does not mutate input state."""
    original_messages_count = len(base_state["messages"])
    original_keys = set(base_state.keys())

    with patch("agent.nodes.conversational_agent.get_llm_with_tools") as mock_get_llm, \
         patch("agent.nodes.conversational_agent.load_maite_system_prompt") as mock_prompt:

        mock_prompt.return_value = "System prompt"

        mock_response = AIMessage(content="Test response")
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm

        result = await conversational_agent(base_state)

        # Verify original state unchanged
        assert len(base_state["messages"]) == original_messages_count
        assert set(base_state.keys()) == original_keys
        assert "booking_intent_confirmed" not in base_state


@pytest.mark.asyncio
async def test_conversational_agent_with_summary(base_state):
    """Test conversational agent with existing conversation summary."""
    base_state["conversation_summary"] = "Customer asked about haircut prices earlier."

    with patch("agent.nodes.conversational_agent.get_llm_with_tools") as mock_get_llm, \
         patch("agent.nodes.conversational_agent.load_maite_system_prompt") as mock_prompt:

        mock_prompt.return_value = "System prompt"

        mock_response = AIMessage(content="Based on our earlier conversation...")
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm

        result = await conversational_agent(base_state)

        # Verify summary was used (implicit in message formatting)
        assert "messages" in result
        assert result["booking_intent_confirmed"] is False

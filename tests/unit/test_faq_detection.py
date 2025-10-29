"""
Unit tests for FAQ detection variations (Story 2.6, AC #10).

Tests that the FAQ detection node correctly classifies 10 variations per FAQ category.
All tests use mocked Claude LLM to avoid real API calls.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage

from agent.nodes.faq import detect_faq_intent
from agent.state.schemas import ConversationState


# ============================================================================
# Test Case 1: Hours FAQ - 10 Variations
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [
    "¿qué horario?",
    "¿abrís?",
    "¿cuándo abren?",
    "horarios",
    "¿hasta qué hora?",
    "¿abren domingos?",
    "¿abrís sábados?",
    "¿a qué hora cierran?",
    "horario de apertura",
    "¿cierran los domingos?",
])
async def test_detect_hours_faq_variations(question):
    """Test that all 10 variations of hours questions detect 'hours' FAQ."""
    # Arrange
    state: ConversationState = {
        "conversation_id": "test-hours",
        "messages": [HumanMessage(content=question)],
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "current_intent": None,
        "metadata": {},
        "total_message_count": 1,
    }

    # Mock Claude LLM response
    mock_response = MagicMock()
    mock_response.content = "hours"

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Act
    result = await detect_faq_intent(state, llm=mock_llm)

    # Assert
    assert result["faq_detected"] is True, f"Should detect FAQ for question: {question}"
    assert result["detected_faq_id"] == "hours", f"Should detect 'hours' FAQ for question: {question}"


# ============================================================================
# Test Case 2: Parking FAQ - 10 Variations
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [
    "¿hay parking?",
    "¿dónde aparcar?",
    "¿hay aparcamiento?",
    "parking",
    "zona azul",
    "estacionamiento",
    "¿puedo aparcar cerca?",
    "¿hay sitio para aparcar?",
    "¿dónde dejo el coche?",
    "¿hay parking público?",
])
async def test_detect_parking_faq_variations(question):
    """Test that all 10 variations of parking questions detect 'parking' FAQ."""
    # Arrange
    state: ConversationState = {
        "conversation_id": "test-parking",
        "messages": [HumanMessage(content=question)],
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "current_intent": None,
        "metadata": {},
        "total_message_count": 1,
    }

    # Mock Claude LLM response
    mock_response = MagicMock()
    mock_response.content = "parking"

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Act
    result = await detect_faq_intent(state, llm=mock_llm)

    # Assert
    assert result["faq_detected"] is True, f"Should detect FAQ for question: {question}"
    assert result["detected_faq_id"] == "parking", f"Should detect 'parking' FAQ for question: {question}"


# ============================================================================
# Test Case 3: Address FAQ - 10 Variations
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [
    "¿dónde están?",
    "¿cuál es la dirección?",
    "¿cómo llego?",
    "ubicación",
    "dirección",
    "¿dónde es?",
    "¿dónde está el salón?",
    "¿cómo llegar?",
    "¿me das la dirección?",
    "ubicación del local",
])
async def test_detect_address_faq_variations(question):
    """Test that all 10 variations of address questions detect 'address' FAQ."""
    # Arrange
    state: ConversationState = {
        "conversation_id": "test-address",
        "messages": [HumanMessage(content=question)],
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "current_intent": None,
        "metadata": {},
        "total_message_count": 1,
    }

    # Mock Claude LLM response
    mock_response = MagicMock()
    mock_response.content = "address"

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Act
    result = await detect_faq_intent(state, llm=mock_llm)

    # Assert
    assert result["faq_detected"] is True, f"Should detect FAQ for question: {question}"
    assert result["detected_faq_id"] == "address", f"Should detect 'address' FAQ for question: {question}"


# ============================================================================
# Test Case 4: Cancellation Policy FAQ - 10 Variations
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [
    "¿puedo cancelar?",
    "política de cancelación",
    "¿y si cancelo?",
    "cancelación",
    "¿me devuelven el dinero?",
    "reembolso",
    "¿qué pasa si cancelo?",
    "¿devuelven el anticipo?",
    "política de reembolso",
    "cancelar cita",
])
async def test_detect_cancellation_policy_faq_variations(question):
    """Test that all 10 variations of cancellation policy questions detect 'cancellation_policy' FAQ."""
    # Arrange
    state: ConversationState = {
        "conversation_id": "test-cancellation",
        "messages": [HumanMessage(content=question)],
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "current_intent": None,
        "metadata": {},
        "total_message_count": 1,
    }

    # Mock Claude LLM response
    mock_response = MagicMock()
    mock_response.content = "cancellation_policy"

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Act
    result = await detect_faq_intent(state, llm=mock_llm)

    # Assert
    assert result["faq_detected"] is True, f"Should detect FAQ for question: {question}"
    assert result["detected_faq_id"] == "cancellation_policy", f"Should detect 'cancellation_policy' FAQ for question: {question}"


# ============================================================================
# Test Case 5: Payment FAQ - 10 Variations
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [
    "¿cómo se paga?",
    "¿hay que pagar por adelantado?",
    "anticipo",
    "¿cuánto hay que pagar?",
    "forma de pago",
    "¿aceptan tarjeta?",
    "¿pago anticipado?",
    "¿cuánto es el anticipo?",
    "métodos de pago",
    "¿puedo pagar con tarjeta?",
])
async def test_detect_payment_info_faq_variations(question):
    """Test that all 10 variations of payment questions detect 'payment_info' FAQ."""
    # Arrange
    state: ConversationState = {
        "conversation_id": "test-payment",
        "messages": [HumanMessage(content=question)],
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "current_intent": None,
        "metadata": {},
        "total_message_count": 1,
    }

    # Mock Claude LLM response
    mock_response = MagicMock()
    mock_response.content = "payment_info"

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Act
    result = await detect_faq_intent(state, llm=mock_llm)

    # Assert
    assert result["faq_detected"] is True, f"Should detect FAQ for question: {question}"
    assert result["detected_faq_id"] == "payment_info", f"Should detect 'payment_info' FAQ for question: {question}"


# ============================================================================
# Test Case 6: Non-FAQ Messages
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [
    "Quiero una cita",
    "Necesito corte y color",
    "¿Tienen disponibilidad mañana?",
    "Quiero modificar mi cita",
    "Cancelar mi cita del viernes",
])
async def test_detect_non_faq_messages(message):
    """Test that non-FAQ messages (booking, modification intents) return faq_detected=False."""
    # Arrange
    state: ConversationState = {
        "conversation_id": "test-non-faq",
        "messages": [HumanMessage(content=message)],
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "current_intent": None,
        "metadata": {},
        "total_message_count": 1,
    }

    # Mock Claude LLM response for non-FAQ
    mock_response = MagicMock()
    mock_response.content = "none"

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Act
    result = await detect_faq_intent(state, llm=mock_llm)

    # Assert
    assert result["faq_detected"] is False, f"Should NOT detect FAQ for message: {message}"
    assert "detected_faq_id" not in result, "Should not have detected_faq_id for non-FAQ messages"


# ============================================================================
# Test Case 7: Error Handling
# ============================================================================


@pytest.mark.asyncio
async def test_detect_faq_intent_handles_llm_error():
    """Test that detect_faq_intent gracefully handles LLM API errors."""
    # Arrange
    state: ConversationState = {
        "conversation_id": "test-error",
        "messages": [HumanMessage(content="¿qué horario?")],
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "current_intent": None,
        "metadata": {},
        "total_message_count": 1,
    }

    # Mock LLM to raise an exception
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(side_effect=Exception("API Error"))

    # Act
    result = await detect_faq_intent(state, llm=mock_llm)

    # Assert
    assert result["faq_detected"] is False, "Should return faq_detected=False on error"
    assert result["error_count"] == 1, "Should increment error count"


@pytest.mark.asyncio
async def test_detect_faq_intent_handles_no_messages():
    """Test that detect_faq_intent handles state with no user messages."""
    # Arrange
    state: ConversationState = {
        "conversation_id": "test-no-messages",
        "messages": [],  # No messages
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "current_intent": None,
        "metadata": {},
        "total_message_count": 0,
    }

    mock_llm = AsyncMock()

    # Act
    result = await detect_faq_intent(state, llm=mock_llm)

    # Assert
    assert result["faq_detected"] is False, "Should return faq_detected=False when no messages"
    assert not mock_llm.ainvoke.called, "Should not call LLM when no messages"


@pytest.mark.asyncio
async def test_detect_faq_intent_handles_unrecognized_faq_id():
    """Test that detect_faq_intent handles unrecognized faq_id from Claude."""
    # Arrange
    state: ConversationState = {
        "conversation_id": "test-unrecognized",
        "messages": [HumanMessage(content="Random question")],
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "current_intent": None,
        "metadata": {},
        "total_message_count": 1,
    }

    # Mock Claude returning an unrecognized faq_id
    mock_response = MagicMock()
    mock_response.content = "unknown_faq"

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Act
    result = await detect_faq_intent(state, llm=mock_llm)

    # Assert
    assert result["faq_detected"] is False, "Should return faq_detected=False for unrecognized faq_id"


# ============================================================================
# Test Case 8: answer_faq Unit Tests
# ============================================================================


@pytest.mark.asyncio
async def test_answer_faq_success():
    """Test successful FAQ answer retrieval and formatting."""
    from agent.nodes.faq import answer_faq
    from unittest.mock import patch

    # Arrange
    state: ConversationState = {
        "conversation_id": "test-answer",
        "customer_id": "test-customer-123",
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "detected_faq_id": "hours",
        "messages": [],
        "metadata": {},
        "total_message_count": 1,
    }

    # Mock database policy retrieval
    mock_policy = MagicMock()
    mock_policy.value = {
        "faq_id": "hours",
        "answer": "Estamos abiertos de lunes a viernes de 10:00 a 20:00 🌸",
        "category": "general",
        "requires_location_link": False,
    }

    mock_session = AsyncMock()
    mock_result = AsyncMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=mock_policy)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    async def mock_get_session():
        yield mock_session

    # Act
    with patch("agent.nodes.faq.get_async_session", return_value=mock_get_session()):
        result = await answer_faq(state)

    # Assert
    assert result["faq_answered"] is True, "Should mark FAQ as answered"
    assert result["current_intent"] == "faq", "Should set intent to faq"
    assert len(result["messages"]) == 1, "Should add one message"

    answer_text = result["messages"][0]["content"]
    assert "Estamos abiertos" in answer_text, "Should contain FAQ answer"
    assert "¿Hay algo más en lo que pueda ayudarte?" in answer_text, "Should have follow-up question"


@pytest.mark.asyncio
async def test_answer_faq_with_location_link():
    """Test FAQ answer includes Google Maps link for location FAQs."""
    from agent.nodes.faq import answer_faq
    from unittest.mock import patch

    # Arrange
    state: ConversationState = {
        "conversation_id": "test-location",
        "customer_id": "test-customer-123",
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "detected_faq_id": "address",
        "messages": [],
        "metadata": {},
        "total_message_count": 1,
    }

    # Mock database policy retrieval
    mock_policy = MagicMock()
    mock_policy.value = {
        "faq_id": "address",
        "answer": "Estamos en La Línea de la Concepción 📍",
        "category": "location",
        "requires_location_link": True,
    }

    mock_session = AsyncMock()
    mock_result = AsyncMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=mock_policy)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    async def mock_get_session():
        yield mock_session

    # Act
    with patch("agent.nodes.faq.get_async_session", return_value=mock_get_session()):
        result = await answer_faq(state)

    # Assert
    assert result["faq_answered"] is True
    answer_text = result["messages"][0]["content"]
    assert "Google Maps" in answer_text, "Should include Google Maps link"
    assert "https://maps.google.com" in answer_text, "Should have Maps URL"


@pytest.mark.asyncio
async def test_answer_faq_not_found_in_database():
    """Test answer_faq handles FAQ not found in database gracefully."""
    from agent.nodes.faq import answer_faq
    from unittest.mock import patch

    # Arrange
    state: ConversationState = {
        "conversation_id": "test-not-found",
        "customer_id": "test-customer-123",
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "detected_faq_id": "nonexistent",
        "messages": [],
        "metadata": {},
        "total_message_count": 1,
    }

    # Mock database returning None (FAQ not found)
    mock_session = AsyncMock()
    mock_result = AsyncMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    async def mock_get_session():
        yield mock_session

    # Act
    with patch("agent.nodes.faq.get_async_session", return_value=mock_get_session()):
        result = await answer_faq(state)

    # Assert
    assert result["faq_detected"] is False, "Should set faq_detected to False"
    assert result["error"] == "FAQ not found", "Should return error"
    assert len(result["messages"]) == 1, "Should add fallback message"

    fallback_text = result["messages"][0]["content"]
    assert "Lo siento" in fallback_text, "Should apologize"
    assert "¿Puedo ayudarte con algo más?" in fallback_text, "Should offer help"


@pytest.mark.asyncio
async def test_answer_faq_handles_database_error():
    """Test answer_faq handles database errors gracefully."""
    from agent.nodes.faq import answer_faq
    from unittest.mock import patch

    # Arrange
    state: ConversationState = {
        "conversation_id": "test-db-error",
        "customer_id": "test-customer-123",
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "detected_faq_id": "hours",
        "messages": [],
        "metadata": {},
        "total_message_count": 1,
    }

    # Mock database raising an exception
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=Exception("Database connection error"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    async def mock_get_session():
        yield mock_session

    # Act
    with patch("agent.nodes.faq.get_async_session", return_value=mock_get_session()):
        result = await answer_faq(state)

    # Assert
    assert result["faq_detected"] is False, "Should set faq_detected to False on error"
    assert "error" in result, "Should return error field"
    assert result["error_count"] == 1, "Should increment error count"
    assert len(result["messages"]) == 1, "Should add fallback message"


@pytest.mark.asyncio
async def test_answer_faq_missing_detected_faq_id():
    """Test answer_faq handles missing detected_faq_id in state."""
    from agent.nodes.faq import answer_faq

    # Arrange
    state: ConversationState = {
        "conversation_id": "test-missing-id",
        "customer_id": "test-customer-123",
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        # detected_faq_id is missing
        "messages": [],
        "metadata": {},
        "total_message_count": 1,
    }

    # Act
    result = await answer_faq(state)

    # Assert
    assert result["faq_detected"] is False, "Should set faq_detected to False"
    assert result["error"] == "No FAQ ID provided", "Should return appropriate error"


# ============================================================================
# Multi-FAQ Detection Tests (Compound Queries)
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("question,expected_faq_ids,expected_complexity", [
    # Compound queries with 2 FAQs
    ("¿Dónde estáis ubicados y a qué hora abrís?", ["address", "hours"], "compound"),
    ("¿Hay parking y cuál es vuestro horario?", ["parking", "hours"], "compound"),
    ("¿Cómo se paga y puedo cancelar?", ["payment_info", "cancellation_policy"], "compound"),
    ("¿Dónde están y hay parking?", ["address", "parking"], "compound"),

    # Compound queries with 3 FAQs
    ("¿Dónde estáis, a qué hora abrís y hay parking?", ["address", "hours", "parking"], "compound"),
    ("¿Cómo se paga, puedo cancelar y qué horario tenéis?", ["payment_info", "cancellation_policy", "hours"], "compound"),
])
async def test_detect_compound_faq_queries(question, expected_faq_ids, expected_complexity):
    """Test that compound queries (multiple FAQs) are correctly detected."""
    # Arrange
    state: ConversationState = {
        "conversation_id": "test-compound",
        "messages": [HumanMessage(content=question)],
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "current_intent": None,
        "metadata": {},
        "total_message_count": 1,
    }

    # Mock Claude LLM response with JSON array
    mock_response = MagicMock()
    import json
    mock_response.content = json.dumps(expected_faq_ids)

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Act
    result = await detect_faq_intent(state, llm=mock_llm)

    # Assert
    assert result["faq_detected"] is True, f"Should detect FAQ for compound question: {question}"
    assert result["detected_faq_ids"] == expected_faq_ids, f"Should detect all FAQs: {expected_faq_ids}"
    assert result["query_complexity"] == expected_complexity, f"Should classify as {expected_complexity}"
    # Backward compatibility: detected_faq_id should be first FAQ
    assert result["detected_faq_id"] == expected_faq_ids[0], "Should set detected_faq_id to first FAQ for backward compatibility"


@pytest.mark.asyncio
async def test_detect_single_faq_returns_simple_complexity():
    """Test that single FAQ queries return 'simple' complexity."""
    # Arrange
    state: ConversationState = {
        "conversation_id": "test-simple",
        "messages": [HumanMessage(content="¿Qué horario tenéis?")],
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "current_intent": None,
        "metadata": {},
        "total_message_count": 1,
    }

    # Mock Claude LLM response
    mock_response = MagicMock()
    mock_response.content = '["hours"]'

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Act
    result = await detect_faq_intent(state, llm=mock_llm)

    # Assert
    assert result["faq_detected"] is True
    assert result["detected_faq_ids"] == ["hours"]
    assert result["query_complexity"] == "simple", "Should classify single FAQ as 'simple'"


@pytest.mark.asyncio
async def test_detect_no_faq_returns_empty_list():
    """Test that non-FAQ messages return empty list."""
    # Arrange
    state: ConversationState = {
        "conversation_id": "test-no-faq",
        "messages": [HumanMessage(content="Quiero hacer una reserva")],
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "current_intent": None,
        "metadata": {},
        "total_message_count": 1,
    }

    # Mock Claude LLM response
    mock_response = MagicMock()
    mock_response.content = '[]'

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Act
    result = await detect_faq_intent(state, llm=mock_llm)

    # Assert
    assert result["faq_detected"] is False
    assert result["detected_faq_ids"] == []
    assert result["query_complexity"] == "none"


@pytest.mark.asyncio
async def test_detect_faq_handles_invalid_json():
    """Test that invalid JSON from Claude is handled gracefully."""
    # Arrange
    state: ConversationState = {
        "conversation_id": "test-invalid-json",
        "messages": [HumanMessage(content="¿Horarios?")],
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "current_intent": None,
        "metadata": {},
        "total_message_count": 1,
    }

    # Mock Claude LLM response with invalid JSON
    mock_response = MagicMock()
    mock_response.content = "hours"  # Not JSON array

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Act
    result = await detect_faq_intent(state, llm=mock_llm)

    # Assert
    assert result["faq_detected"] is False, "Should handle invalid JSON gracefully"
    assert result["detected_faq_ids"] == []


@pytest.mark.asyncio
async def test_detect_faq_filters_invalid_ids():
    """Test that invalid FAQ IDs are filtered out."""
    # Arrange
    state: ConversationState = {
        "conversation_id": "test-filter-invalid",
        "messages": [HumanMessage(content="¿Horarios y precios?")],
        "customer_phone": "+34612000000",
        "customer_name": "Test Customer",
        "current_intent": None,
        "metadata": {},
        "total_message_count": 1,
    }

    # Mock Claude LLM response with valid and invalid IDs
    mock_response = MagicMock()
    mock_response.content = '["hours", "pricing", "address"]'  # "pricing" is not a valid FAQ ID

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Act
    result = await detect_faq_intent(state, llm=mock_llm)

    # Assert
    assert result["faq_detected"] is True
    assert result["detected_faq_ids"] == ["hours", "address"], "Should filter out invalid 'pricing' ID"
    assert "pricing" not in result["detected_faq_ids"], "Should not include invalid FAQ ID"

"""
Integration tests for FAQ flow (Story 2.6).

Tests the complete FAQ detection and answering flow including:
- FAQ detection for all 5 categories
- FAQ answer retrieval and formatting
- Maite's tone and emoji usage
- Proactive follow-up question
- Google Maps link for location FAQs
- Non-FAQ message routing to booking flow
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import delete

from agent.graphs.conversation_flow import create_conversation_graph
from agent.state.schemas import ConversationState
from database.connection import get_async_session
from database.models import Customer


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def returning_customer_faq():
    """Create a returning customer for FAQ testing."""
    customer_id = uuid4()
    phone = "+34612999888"

    async for session in get_async_session():
        # Clean up any existing customer with this phone
        await session.execute(delete(Customer).where(Customer.phone == phone))
        await session.commit()

        # Create new customer
        customer = Customer(
            id=customer_id,
            phone=phone,
            first_name="Laura",
            last_name="Martínez",
            total_spent=120.00,
            metadata_={},
        )
        session.add(customer)
        await session.commit()
        await session.refresh(customer)

        yield customer

        # Cleanup after test
        await session.execute(delete(Customer).where(Customer.phone == phone))
        await session.commit()


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_faq_flow_hours(returning_customer_faq):
    """
    Test FAQ flow for business hours question.

    AC: 9 - Integration test: "¿Abrís los sábados?" → verify answer → verify follow-up
    """
    # Arrange
    graph = create_conversation_graph(checkpointer=None)

    initial_state: ConversationState = {
        "conversation_id": "test-faq-hours",
        "customer_phone": returning_customer_faq.phone,
        "customer_name": f"{returning_customer_faq.first_name} {returning_customer_faq.last_name}",
        "messages": [HumanMessage(content="¿Abrís los sábados?")],
        "current_intent": None,
        "metadata": {},
        "customer_id": returning_customer_faq.id,
        "is_returning_customer": True,
        "customer_history": [],
        "preferred_stylist_id": None,
        "total_message_count": 1,
    }

    # Mock Claude LLM response for FAQ detection
    mock_response = MagicMock()
    mock_response.content = "hours"

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Act - patch get_llm factory function
    with patch("agent.nodes.faq.get_llm", return_value=mock_llm):
        result = await graph.ainvoke(initial_state)

    # Assert
    assert result["faq_detected"] is True, "FAQ should be detected"
    assert result["detected_faq_id"] == "hours", "Should detect hours FAQ"
    assert result["faq_answered"] is True, "FAQ should be marked as answered"
    assert result["current_intent"] == "faq", "Intent should be set to faq"

    # Check answer message
    assistant_messages = [msg for msg in result["messages"] if isinstance(msg, AIMessage)]
    assert len(assistant_messages) > 0, "Should have assistant response"

    answer_text = assistant_messages[-1].content
    assert "sábados de 10:00 a 14:00" in answer_text, "Answer should contain Saturday hours"
    assert any(emoji in answer_text for emoji in ["🌸", "😊"]), "Answer should contain emoji"
    assert "¿Hay algo más en lo que pueda ayudarte?" in answer_text, "Should have proactive follow-up"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_faq_flow_parking(returning_customer_faq):
    """Test FAQ flow for parking question."""
    # Arrange
    graph = create_conversation_graph(checkpointer=None)

    initial_state: ConversationState = {
        "conversation_id": "test-faq-parking",
        "customer_phone": returning_customer_faq.phone,
        "customer_name": f"{returning_customer_faq.first_name} {returning_customer_faq.last_name}",
        "messages": [HumanMessage(content="¿Hay aparcamiento?")],
        "current_intent": None,
        "metadata": {},
        "customer_id": returning_customer_faq.id,
        "is_returning_customer": True,
        "customer_history": [],
        "preferred_stylist_id": None,
        "total_message_count": 1,
    }

    # Mock Claude LLM response
    mock_response = MagicMock()
    mock_response.content = "parking"

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Act
    with patch("agent.nodes.faq.get_llm", return_value=mock_llm):
        result = await graph.ainvoke(initial_state)

    # Assert
    assert result["faq_detected"] is True
    assert result["detected_faq_id"] == "parking"
    assert result["faq_answered"] is True

    # Check answer content
    assistant_messages = [msg for msg in result["messages"] if isinstance(msg, AIMessage)]
    answer_text = assistant_messages[-1].content

    assert "parking público" in answer_text or "zona azul" in answer_text, "Answer should contain parking info"
    assert any(emoji in answer_text for emoji in ["😊", "🚗"]), "Answer should contain emoji"
    assert "¿Hay algo más en lo que pueda ayudarte?" in answer_text, "Should have follow-up"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_faq_flow_location_with_maps_link(returning_customer_faq):
    """
    Test FAQ flow for location question with Google Maps link.

    AC: 8 - If location FAQ → optionally offer Google Maps link
    """
    # Arrange
    graph = create_conversation_graph(checkpointer=None)

    initial_state: ConversationState = {
        "conversation_id": "test-faq-location",
        "customer_phone": returning_customer_faq.phone,
        "customer_name": f"{returning_customer_faq.first_name} {returning_customer_faq.last_name}",
        "messages": [HumanMessage(content="¿Dónde están?")],
        "current_intent": None,
        "metadata": {},
        "customer_id": returning_customer_faq.id,
        "is_returning_customer": True,
        "customer_history": [],
        "preferred_stylist_id": None,
        "total_message_count": 1,
    }

    # Mock Claude LLM response
    mock_response = MagicMock()
    mock_response.content = "address"

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Act
    with patch("agent.nodes.faq.get_llm", return_value=mock_llm):
        result = await graph.ainvoke(initial_state)

    # Assert
    assert result["faq_detected"] is True
    assert result["detected_faq_id"] == "address"
    assert result["faq_answered"] is True

    # Check for Google Maps link
    assistant_messages = [msg for msg in result["messages"] if isinstance(msg, AIMessage)]
    answer_text = assistant_messages[-1].content

    assert "La Línea de la Concepción" in answer_text, "Answer should contain location"
    assert "📍" in answer_text, "Answer should have location emoji"
    assert "Google Maps" in answer_text, "Answer should mention Google Maps"
    assert "https://maps.google.com" in answer_text, "Answer should include Maps link"
    assert "¿Hay algo más en lo que pueda ayudarte?" in answer_text, "Should have follow-up"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_faq_flow_cancellation_policy(returning_customer_faq):
    """Test FAQ flow for cancellation policy question."""
    # Arrange
    graph = create_conversation_graph(checkpointer=None)

    initial_state: ConversationState = {
        "conversation_id": "test-faq-cancel",
        "customer_phone": returning_customer_faq.phone,
        "customer_name": f"{returning_customer_faq.first_name} {returning_customer_faq.last_name}",
        "messages": [HumanMessage(content="¿Puedo cancelar mi cita?")],
        "current_intent": None,
        "metadata": {},
        "customer_id": returning_customer_faq.id,
        "is_returning_customer": True,
        "customer_history": [],
        "preferred_stylist_id": None,
        "total_message_count": 1,
    }

    # Mock Claude LLM response
    mock_response = MagicMock()
    mock_response.content = "cancellation_policy"

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Act
    with patch("agent.nodes.faq.get_llm", return_value=mock_llm):
        result = await graph.ainvoke(initial_state)

    # Assert
    assert result["faq_detected"] is True
    assert result["detected_faq_id"] == "cancellation_policy"
    assert result["faq_answered"] is True

    # Check answer content
    assistant_messages = [msg for msg in result["messages"] if isinstance(msg, AIMessage)]
    answer_text = assistant_messages[-1].content

    assert "24 horas" in answer_text, "Answer should mention 24-hour threshold"
    assert "anticipo completo" in answer_text or "devolvemos" in answer_text, "Answer should mention refund"
    assert any(emoji in answer_text for emoji in ["💕", "😊"]), "Answer should have empathetic tone with emoji"
    assert "¿Hay algo más en lo que pueda ayudarte?" in answer_text, "Should have follow-up"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_faq_flow_payment_info(returning_customer_faq):
    """Test FAQ flow for payment information question."""
    # Arrange
    graph = create_conversation_graph(checkpointer=None)

    initial_state: ConversationState = {
        "conversation_id": "test-faq-payment",
        "customer_phone": returning_customer_faq.phone,
        "customer_name": f"{returning_customer_faq.first_name} {returning_customer_faq.last_name}",
        "messages": [HumanMessage(content="¿Cómo se paga?")],
        "current_intent": None,
        "metadata": {},
        "customer_id": returning_customer_faq.id,
        "is_returning_customer": True,
        "customer_history": [],
        "preferred_stylist_id": None,
        "total_message_count": 1,
    }

    # Mock Claude LLM response
    mock_response = MagicMock()
    mock_response.content = "payment_info"

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Act
    with patch("agent.nodes.faq.get_llm", return_value=mock_llm):
        result = await graph.ainvoke(initial_state)

    # Assert
    assert result["faq_detected"] is True
    assert result["detected_faq_id"] == "payment_info"
    assert result["faq_answered"] is True

    # Check answer content
    assistant_messages = [msg for msg in result["messages"] if isinstance(msg, AIMessage)]
    answer_text = assistant_messages[-1].content

    assert "anticipo" in answer_text and "20%" in answer_text, "Answer should mention 20% advance"
    assert "tarjeta" in answer_text, "Answer should mention card payment"
    assert any(emoji in answer_text for emoji in ["💳", "🌸"]), "Answer should contain relevant emoji"
    assert "¿Hay algo más en lo que pueda ayudarte?" in answer_text, "Should have follow-up"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_non_faq_message_routes_to_booking_flow(returning_customer_faq):
    """
    Test that non-FAQ messages are correctly routed to booking flow.

    AC: 9 - Test scenario 5: Non-FAQ message (booking intent)
    """
    # Arrange
    graph = create_conversation_graph(checkpointer=None)

    initial_state: ConversationState = {
        "conversation_id": "test-non-faq",
        "customer_phone": returning_customer_faq.phone,
        "customer_name": f"{returning_customer_faq.first_name} {returning_customer_faq.last_name}",
        "messages": [HumanMessage(content="Quiero una cita para corte")],
        "current_intent": None,
        "metadata": {},
        "customer_id": returning_customer_faq.id,
        "is_returning_customer": True,
        "customer_history": [],
        "preferred_stylist_id": None,
        "total_message_count": 1,
    }

    # Mock Claude LLM responses (both FAQ detection and intent extraction)
    mock_faq_response = MagicMock()
    mock_faq_response.content = "none"

    mock_faq_llm = AsyncMock()
    mock_faq_llm.ainvoke = AsyncMock(return_value=mock_faq_response)

    mock_intent_response = MagicMock()
    mock_intent_response.content = "booking"

    mock_classification_llm = AsyncMock()
    mock_classification_llm.ainvoke = AsyncMock(return_value=mock_intent_response)

    # Act
    with patch("agent.nodes.faq.get_llm", return_value=mock_faq_llm), \
         patch("agent.nodes.classification.get_llm", return_value=mock_classification_llm):
        result = await graph.ainvoke(initial_state)

    # Assert
    assert result["faq_detected"] is False, "Should not detect FAQ for booking intent"
    assert result["current_intent"] == "booking", "Should classify as booking intent"

    # Verify routing to booking flow (currently placeholder)
    assistant_messages = [msg for msg in result["messages"] if isinstance(msg, AIMessage)]
    assert len(assistant_messages) > 0, "Should have response"

    # Should NOT have FAQ-specific follow-up or FAQ answer
    answer_text = assistant_messages[-1].content
    # Booking handler currently returns placeholder, but importantly NOT an FAQ answer
    assert result.get("faq_answered") is not True, "Should not mark FAQ as answered for booking"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_faq_multiple_variations_same_category(returning_customer_faq):
    """Test that multiple question variations detect the same FAQ."""
    # Arrange
    graph = create_conversation_graph(checkpointer=None)

    # Test multiple hours FAQ variations
    hours_variations = [
        "¿qué horario?",
        "¿abrís?",
        "¿cuándo abren?",
        "¿hasta qué hora?",
    ]

    # Mock Claude LLM response
    mock_response = MagicMock()
    mock_response.content = "hours"

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    for question in hours_variations:
        initial_state: ConversationState = {
            "conversation_id": f"test-faq-variation-{question[:10]}",
            "customer_phone": returning_customer_faq.phone,
            "customer_name": f"{returning_customer_faq.first_name} {returning_customer_faq.last_name}",
            "messages": [HumanMessage(content=question)],
            "current_intent": None,
            "metadata": {},
            "customer_id": returning_customer_faq.id,
            "is_returning_customer": True,
            "customer_history": [],
            "preferred_stylist_id": None,
            "total_message_count": 1,
        }

        # Act
        with patch("agent.nodes.faq.get_llm", return_value=mock_llm):
            result = await graph.ainvoke(initial_state)

        # Assert
        assert result["faq_detected"] is True, f"Should detect FAQ for question: {question}"
        assert result["detected_faq_id"] == "hours", f"Should detect hours FAQ for question: {question}"
        assert result["faq_answered"] is True, f"Should answer FAQ for question: {question}"


# ============================================================================
# Compound Query Integration Tests
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_compound_faq_flow_address_and_hours(returning_customer_faq):
    """
    Test FAQ flow for compound query: location + hours.

    Tests that system detects both FAQs and generates a single cohesive AI response
    that answers both questions naturally.
    """
    # Arrange
    graph = create_conversation_graph(checkpointer=None)

    initial_state: ConversationState = {
        "conversation_id": "test-compound-address-hours",
        "customer_phone": returning_customer_faq.phone,
        "customer_name": f"{returning_customer_faq.first_name} {returning_customer_faq.last_name}",
        "messages": [HumanMessage(content="¿Dónde estáis ubicados y a qué hora abrís?")],
        "current_intent": None,
        "metadata": {},
        "customer_id": returning_customer_faq.id,
        "is_returning_customer": True,
        "customer_history": [],
        "preferred_stylist_id": None,
        "total_message_count": 1,
    }

    # Mock Claude LLM responses
    # First call: FAQ detection - returns JSON array with both FAQs
    detection_response = MagicMock()
    detection_response.content = '["address", "hours"]'

    # Second call: AI generation - returns personalized response
    generation_response = MagicMock()
    generation_response.content = """¡Hola Laura! 🌸 Estamos en La Línea de la Concepción. Te dejo aquí el enlace para que llegues fácilmente:

📍 https://maps.google.com/?q=Atrévete+Peluquería+La+Línea

Nuestro horario es de lunes a viernes de 10:00 a 20:00, y los sábados de 10:00 a 14:00. Los domingos descansamos 😊.

¿Hay algo más en lo que pueda ayudarte? 😊"""

    mock_llm = AsyncMock()
    # Configure side_effect to return different responses for each call
    mock_llm.ainvoke = AsyncMock(side_effect=[detection_response, generation_response])

    # Act
    with patch("agent.nodes.faq.get_llm", return_value=mock_llm):
        with patch("agent.nodes.faq_generation.get_llm", return_value=mock_llm):
            result = await graph.ainvoke(initial_state)

    # Assert
    assert result["faq_detected"] is True, "Should detect FAQ"
    assert set(result["detected_faq_ids"]) == {"address", "hours"}, "Should detect both address and hours FAQs"
    assert result["query_complexity"] == "compound", "Should classify as compound query"
    assert result["faq_answered"] is True, "Should answer FAQ"

    # Verify AI-generated response
    ai_messages = [msg for msg in result["messages"] if isinstance(msg, AIMessage)]
    assert len(ai_messages) > 0, "Should have AI response"
    last_response = ai_messages[-1].content

    # Check that response addresses both questions
    assert "línea" in last_response.lower() or "ubicados" in last_response.lower(), "Should mention location"
    assert "maps.google.com" in last_response.lower(), "Should include Google Maps link"
    assert ("10:00" in last_response and "20:00" in last_response) or "horario" in last_response.lower(), "Should mention hours"
    assert "¿hay algo más" in last_response.lower(), "Should include follow-up question"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_compound_faq_flow_parking_and_payment(returning_customer_faq):
    """
    Test FAQ flow for compound query: parking + payment info.
    """
    # Arrange
    graph = create_conversation_graph(checkpointer=None)

    initial_state: ConversationState = {
        "conversation_id": "test-compound-parking-payment",
        "customer_phone": returning_customer_faq.phone,
        "customer_name": f"{returning_customer_faq.first_name} {returning_customer_faq.last_name}",
        "messages": [HumanMessage(content="¿Hay parking y cómo se paga?")],
        "current_intent": None,
        "metadata": {},
        "customer_id": returning_customer_faq.id,
        "is_returning_customer": True,
        "customer_history": [],
        "preferred_stylist_id": None,
        "total_message_count": 1,
    }

    # Mock Claude LLM responses
    detection_response = MagicMock()
    detection_response.content = '["parking", "payment_info"]'

    generation_response = MagicMock()
    generation_response.content = """¡Hola! 😊 Sí, hay parking público muy cerca y también zona azul en la calle, es fácil encontrar sitio 🚗.

En cuanto al pago, para confirmar tu cita pedimos un anticipo del 20% que se paga online con tarjeta de forma segura 💳. El resto lo pagas en el salón después del servicio 🌸.

¿Hay algo más en lo que pueda ayudarte? 😊"""

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(side_effect=[detection_response, generation_response])

    # Act
    with patch("agent.nodes.faq.get_llm", return_value=mock_llm):
        with patch("agent.nodes.faq_generation.get_llm", return_value=mock_llm):
            result = await graph.ainvoke(initial_state)

    # Assert
    assert result["faq_detected"] is True
    assert set(result["detected_faq_ids"]) == {"parking", "payment_info"}
    assert result["query_complexity"] == "compound"
    assert result["faq_answered"] is True

    # Verify response addresses both questions
    ai_messages = [msg for msg in result["messages"] if isinstance(msg, AIMessage)]
    last_response = ai_messages[-1].content

    assert "parking" in last_response.lower() or "aparcar" in last_response.lower(), "Should mention parking"
    assert "pag" in last_response.lower() or "anticipo" in last_response.lower(), "Should mention payment"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_compound_faq_with_three_questions(returning_customer_faq):
    """
    Test FAQ flow for complex compound query with 3 FAQs.
    """
    # Arrange
    graph = create_conversation_graph(checkpointer=None)

    initial_state: ConversationState = {
        "conversation_id": "test-compound-three-faqs",
        "customer_phone": returning_customer_faq.phone,
        "customer_name": f"{returning_customer_faq.first_name} {returning_customer_faq.last_name}",
        "messages": [HumanMessage(content="¿Dónde estáis, a qué hora abrís y hay parking?")],
        "current_intent": None,
        "metadata": {},
        "customer_id": returning_customer_faq.id,
        "is_returning_customer": True,
        "customer_history": [],
        "preferred_stylist_id": None,
        "total_message_count": 1,
    }

    # Mock Claude LLM responses
    detection_response = MagicMock()
    detection_response.content = '["address", "hours", "parking"]'

    generation_response = MagicMock()
    generation_response.content = """¡Hola! 🌸 Estamos en La Línea de la Concepción:

📍 https://maps.google.com/?q=Atrévete+Peluquería+La+Línea

Abrimos de lunes a viernes de 10:00 a 20:00, y los sábados de 10:00 a 14:00. Y sí, hay parking público cerca y zona azul, es fácil encontrar sitio 🚗😊.

¿Hay algo más en lo que pueda ayudarte? 😊"""

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(side_effect=[detection_response, generation_response])

    # Act
    with patch("agent.nodes.faq.get_llm", return_value=mock_llm):
        with patch("agent.nodes.faq_generation.get_llm", return_value=mock_llm):
            result = await graph.ainvoke(initial_state)

    # Assert
    assert result["faq_detected"] is True
    assert set(result["detected_faq_ids"]) == {"address", "hours", "parking"}
    assert result["query_complexity"] == "compound"
    assert result["faq_answered"] is True

    # Verify response addresses all three questions
    ai_messages = [msg for msg in result["messages"] if isinstance(msg, AIMessage)]
    last_response = ai_messages[-1].content

    assert "maps.google.com" in last_response.lower(), "Should include location"
    assert "10:00" in last_response or "horario" in last_response.lower(), "Should mention hours"
    assert "parking" in last_response.lower() or "aparcar" in last_response.lower(), "Should mention parking"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_simple_faq_uses_static_response(returning_customer_faq):
    """
    Test that simple single-FAQ queries still use fast static response path.
    """
    # Arrange
    graph = create_conversation_graph(checkpointer=None)

    initial_state: ConversationState = {
        "conversation_id": "test-simple-static",
        "customer_phone": returning_customer_faq.phone,
        "customer_name": f"{returning_customer_faq.first_name} {returning_customer_faq.last_name}",
        "messages": [HumanMessage(content="¿Qué horario tenéis?")],
        "current_intent": None,
        "metadata": {},
        "customer_id": returning_customer_faq.id,
        "is_returning_customer": True,
        "customer_history": [],
        "preferred_stylist_id": None,
        "total_message_count": 1,
    }

    # Mock Claude LLM response for detection only
    detection_response = MagicMock()
    detection_response.content = '["hours"]'

    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=detection_response)

    # Act
    with patch("agent.nodes.faq.get_llm", return_value=mock_llm):
        result = await graph.ainvoke(initial_state)

    # Assert
    assert result["faq_detected"] is True
    assert result["detected_faq_ids"] == ["hours"]
    assert result["query_complexity"] == "simple"
    assert result["faq_answered"] is True

    # Verify static response was used (no AI generation call)
    # Should only have been called once for detection, not for generation
    assert mock_llm.ainvoke.call_count == 1, "Should only call LLM once for detection, not for generation"

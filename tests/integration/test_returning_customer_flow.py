"""
Integration tests for returning customer flow (Story 2.3).

Tests the complete flow from customer identification through intent extraction
and routing for returning customers.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from langchain_core.messages import HumanMessage
from sqlalchemy import delete

from agent.graphs.conversation_flow import create_conversation_graph
from agent.state.schemas import ConversationState
from database.connection import get_async_session


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def returning_customer():
    """Create a returning customer in the database."""
    customer_id = uuid4()
    phone = "+34612345678"

    async for session in get_async_session():
        # Clean up any existing customer with this phone
        await session.execute(delete(Customer).where(Customer.phone == phone))
        await session.commit()

        # Create new customer
        customer = Customer(
            id=customer_id,
            phone=phone,
            first_name="María",
            last_name="García",
            total_spent=150.00,
            metadata_={},
        )
        session.add(customer)
        await session.commit()
        await session.refresh(customer)

        yield customer

        # Cleanup after test
        await session.execute(delete(Customer).where(Customer.phone == phone))
        await session.commit()


@pytest.fixture
async def returning_customer_incomplete_profile():
    """Create a returning customer with incomplete profile (missing last_name)."""
    customer_id = uuid4()
    phone = "+34698765432"

    async for session in get_async_session():
        # Clean up any existing customer
        await session.execute(delete(Customer).where(Customer.phone == phone))
        await session.commit()

        # Create customer with incomplete profile
        customer = Customer(
            id=customer_id,
            phone=phone,
            first_name="Pedro",
            last_name=None,  # Incomplete profile
            total_spent=75.00,
            metadata_={},
        )
        session.add(customer)
        await session.commit()
        await session.refresh(customer)

        yield customer

        # Cleanup
        await session.execute(delete(Customer).where(Customer.phone == phone))
        await session.commit()


@pytest.fixture
async def returning_customer_with_history():
    """Create a returning customer with appointment history."""
    customer_id = uuid4()
    phone = "+34611223344"

    async for session in get_async_session():
        # Clean up any existing data
        await session.execute(delete(Customer).where(Customer.phone == phone))
        await session.commit()

        # Create customer with some service history indicated by total_spent
        customer = Customer(
            id=customer_id,
            phone=phone,
            first_name="Carlos",
            last_name="López",
            total_spent=300.00,  # Indicates 3 past services
            last_service_date=datetime(2024, 10, 15, 10, 0, tzinfo=timezone.utc),
            metadata_={},
        )
        session.add(customer)
        await session.commit()
        await session.refresh(customer)

        yield customer

        # Cleanup
        await session.execute(delete(Customer).where(Customer.phone == phone))
        await session.commit()


@pytest.fixture
def mock_claude_llm():
    """Mock Claude LLM for intent classification."""
    with patch("agent.nodes.classification.llm") as mock_llm, \
         patch("agent.nodes.identification.llm") as mock_identification_llm:
        yield mock_llm


# ============================================================================
# Integration Test: Greeting Only Flow
# ============================================================================


@pytest.mark.asyncio
async def test_returning_customer_greeting_only_flow(returning_customer, mock_claude_llm):
    """
    Test complete flow: returning customer → greeting_only intent → personalized greeting.

    Verifies:
    - Customer identified correctly
    - is_returning_customer = True
    - customer_identified = True (skip name confirmation)
    - Intent extracted as greeting_only
    - Personalized greeting with customer name and emoji
    """
    # Mock LLM response for greeting_only intent
    mock_response = AsyncMock()
    mock_response.content = "greeting_only"
    mock_claude_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Create graph without checkpointer (testing mode)
    graph = create_conversation_graph(checkpointer=None)

    # Initial state with returning customer phone
    initial_state: ConversationState = {
        "conversation_id": "test-conv-greeting",
        "customer_phone": "+34612345678",
        "messages": [HumanMessage(content="Hola")],
        "metadata": {},
    }

    # Execute graph
    result = await graph.ainvoke(initial_state)

    # Verify customer identification
    assert result["is_returning_customer"] is True
    assert result["customer_identified"] is True
    assert result["customer_id"] == str(returning_customer.id)
    assert result["customer_name"] == "María García"

    # Verify intent extraction
    assert result["current_intent"] == "greeting_only"

    # Verify personalized greeting
    messages = result["messages"]
    assert len(messages) > 1  # Initial message + greeting

    # Find the greeting message from Maite
    greeting_found = False
    for msg in messages:
        if hasattr(msg, "content") and "Maite" in msg.content:
            assert "¡Hola, María!" in msg.content
            assert "🌸" in msg.content
            assert "¿En qué puedo ayudarte hoy?" in msg.content
            greeting_found = True
            break

    assert greeting_found, "Personalized greeting not found in messages"

    # Verify no name confirmation was triggered
    assert result.get("awaiting_name_confirmation") is not True


@pytest.mark.asyncio
async def test_returning_customer_booking_intent_flow(returning_customer, mock_claude_llm):
    """
    Test complete flow: returning customer → booking intent → routed to booking handler.

    Verifies:
    - Customer identified
    - Intent extracted as booking
    - Routed to booking_handler placeholder
    - Acknowledgment message generated
    """
    # Mock LLM response for booking intent
    mock_response = AsyncMock()
    mock_response.content = "booking"
    mock_claude_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Create graph
    graph = create_conversation_graph(checkpointer=None)

    # Initial state with booking request
    initial_state: ConversationState = {
        "conversation_id": "test-conv-booking",
        "customer_phone": "+34612345678",
        "messages": [HumanMessage(content="Quiero hacer una cita para mañana")],
        "metadata": {},
    }

    # Execute graph
    result = await graph.ainvoke(initial_state)

    # Verify customer identification
    assert result["is_returning_customer"] is True
    assert result["customer_identified"] is True

    # Verify intent extraction
    assert result["current_intent"] == "booking"

    # Verify acknowledgment message
    messages = result["messages"]
    acknowledgment_found = False
    placeholder_found = False

    for msg in messages:
        if hasattr(msg, "content"):
            if "¡Hola de nuevo, María!" in msg.content:
                acknowledgment_found = True
            if "Entiendo que quieres hacer una reserva" in msg.content:
                placeholder_found = True

    assert acknowledgment_found, "Acknowledgment message not found"
    assert placeholder_found, "Placeholder booking handler message not found"


@pytest.mark.asyncio
async def test_returning_customer_modification_intent(returning_customer, mock_claude_llm):
    """Test returning customer with modification intent routes correctly."""
    mock_response = AsyncMock()
    mock_response.content = "modification"
    mock_claude_llm.ainvoke = AsyncMock(return_value=mock_response)

    graph = create_conversation_graph(checkpointer=None)

    initial_state: ConversationState = {
        "conversation_id": "test-conv-modification",
        "customer_phone": "+34612345678",
        "messages": [HumanMessage(content="Necesito cambiar mi cita")],
        "metadata": {},
    }

    result = await graph.ainvoke(initial_state)

    assert result["current_intent"] == "modification"

    # Verify modification handler was called
    modification_found = False
    for msg in result["messages"]:
        if hasattr(msg, "content") and "modificar una cita" in msg.content:
            modification_found = True
            break
    assert modification_found


@pytest.mark.asyncio
async def test_returning_customer_cancellation_intent(returning_customer, mock_claude_llm):
    """Test returning customer with cancellation intent routes correctly."""
    mock_response = AsyncMock()
    mock_response.content = "cancellation"
    mock_claude_llm.ainvoke = AsyncMock(return_value=mock_response)

    graph = create_conversation_graph(checkpointer=None)

    initial_state: ConversationState = {
        "conversation_id": "test-conv-cancellation",
        "customer_phone": "+34612345678",
        "messages": [HumanMessage(content="Quiero cancelar mi cita")],
        "metadata": {},
    }

    result = await graph.ainvoke(initial_state)

    assert result["current_intent"] == "cancellation"

    # Verify cancellation handler was called
    cancellation_found = False
    for msg in result["messages"]:
        if hasattr(msg, "content") and "cancelar una cita" in msg.content:
            cancellation_found = True
            break
    assert cancellation_found


# ============================================================================
# Integration Test: Incomplete Profile
# ============================================================================


@pytest.mark.asyncio
async def test_returning_customer_incomplete_profile(returning_customer_incomplete_profile, mock_claude_llm):
    """
    Test returning customer with incomplete profile (missing last_name) still recognized.

    Verifies:
    - Customer identified despite missing last_name
    - is_returning_customer = True
    - Flow proceeds normally
    """
    mock_response = AsyncMock()
    mock_response.content = "greeting_only"
    mock_claude_llm.ainvoke = AsyncMock(return_value=mock_response)

    graph = create_conversation_graph(checkpointer=None)

    initial_state: ConversationState = {
        "conversation_id": "test-conv-incomplete",
        "customer_phone": "+34698765432",
        "messages": [HumanMessage(content="Hola")],
        "metadata": {},
    }

    result = await graph.ainvoke(initial_state)

    # Verify customer identified despite incomplete profile
    assert result["is_returning_customer"] is True
    assert result["customer_identified"] is True
    assert result["customer_id"] == str(returning_customer_incomplete_profile.id)
    assert result["customer_name"] == "Pedro"  # Only first name

    # Verify flow proceeds normally
    assert result["current_intent"] == "greeting_only"


# ============================================================================
# Integration Test: Customer History
# ============================================================================


@pytest.mark.asyncio
async def test_returning_customer_with_history(returning_customer_with_history, mock_claude_llm):
    """
    Test returning customer with service history (indicated by total_spent).

    Verifies:
    - Customer recognized with last_service_date
    - customer_history field exists in state
    - Flow proceeds normally for customer with history
    """
    mock_response = AsyncMock()
    mock_response.content = "greeting_only"
    mock_claude_llm.ainvoke = AsyncMock(return_value=mock_response)

    graph = create_conversation_graph(checkpointer=None)

    initial_state: ConversationState = {
        "conversation_id": "test-conv-history",
        "customer_phone": "+34611223344",
        "messages": [HumanMessage(content="Hola")],
        "metadata": {},
    }

    result = await graph.ainvoke(initial_state)

    # Verify customer identified
    assert result["is_returning_customer"] is True
    assert result["customer_id"] == str(returning_customer_with_history.id)
    assert result["customer_name"] == "Carlos López"

    # Verify customer_history field exists in state (may be empty list if no appointments)
    assert "customer_history" in result
    assert isinstance(result["customer_history"], list)

    # Verify flow completes successfully
    assert result["current_intent"] == "greeting_only"


# ============================================================================
# Integration Test: Intent Routing All Types
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("intent,expected_keyword", [
    ("inquiry", "consulta"),
    ("faq", "consulta"),
    ("usual_service", "servicio habitual"),
])
async def test_all_intent_types_routing(returning_customer, mock_claude_llm, intent, expected_keyword):
    """Test all intent types route to correct handlers."""
    mock_response = AsyncMock()
    mock_response.content = intent
    mock_claude_llm.ainvoke = AsyncMock(return_value=mock_response)

    graph = create_conversation_graph(checkpointer=None)

    initial_state: ConversationState = {
        "conversation_id": f"test-conv-{intent}",
        "customer_phone": "+34612345678",
        "messages": [HumanMessage(content="Test message")],
        "metadata": {},
    }

    result = await graph.ainvoke(initial_state)

    assert result["current_intent"] == intent

    # Verify appropriate handler was called
    handler_found = False
    for msg in result["messages"]:
        if hasattr(msg, "content") and expected_keyword in msg.content.lower():
            handler_found = True
            break
    assert handler_found, f"Handler for intent '{intent}' not called correctly"

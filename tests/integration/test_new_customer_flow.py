"""
Integration tests for new customer identification flow.

This module tests the complete flow:
1. Customer identification by phone
2. Greeting new customers
3. Name confirmation
4. Customer creation in database

Uses real async PostgreSQL connection with test database.
External APIs (Chatwoot) are mocked.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage
from sqlalchemy import delete, select

from agent.nodes.identification import confirm_name, greet_new_customer, identify_customer
from agent.state.schemas import ConversationState
from database.connection import get_async_session
from database.models import Customer


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def cleanup_test_customer():
    """Cleanup fixture to remove test customer after each test."""
    test_phone = "+34600000001"
    yield test_phone

    # Cleanup after test
    async for session in get_async_session():
        await session.execute(delete(Customer).where(Customer.phone == test_phone))
        await session.commit()


@pytest.fixture
def initial_state(cleanup_test_customer) -> ConversationState:
    """Initial conversation state for integration tests."""
    return {
        "conversation_id": "integration-test-123",
        "customer_phone": cleanup_test_customer,
        "messages": [],
        "metadata": {"whatsapp_name": "Test Customer"},
    }


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_full_new_customer_flow_with_confirmation(initial_state, cleanup_test_customer):
    """
    Test complete new customer flow:
    1. Identify customer (not found)
    2. Greet new customer
    3. User confirms name
    4. Customer created in database
    """
    # Step 1: Identify customer (should not be found)
    identify_result = await identify_customer(initial_state)

    assert identify_result["is_returning_customer"] is False

    # Update state
    state_after_identify = {**initial_state, **identify_result}

    # Step 2: Greet new customer
    greet_result = await greet_new_customer(state_after_identify)

    assert greet_result["awaiting_name_confirmation"] is True
    assert len(greet_result["messages"]) == 1
    greeting_message = greet_result["messages"][0].content
    assert "Maite" in greeting_message
    assert "🌸" in greeting_message

    # Update state
    state_after_greet = {**state_after_identify, **greet_result}

    # Step 3: User confirms name
    user_confirmation = HumanMessage(content="Sí, correcto")
    state_after_greet["messages"].append(user_confirmation)

    # Mock LLM response for classification
    with patch("agent.nodes.identification.llm") as mock_llm:
        mock_llm_response = MagicMock()
        mock_llm_response.content = "confirmed"
        mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response)

        confirm_result = await confirm_name(state_after_greet)

    assert confirm_result["customer_identified"] is True
    assert confirm_result["customer_id"] is not None
    assert "customer_name" in confirm_result

    # Step 4: Verify customer exists in database
    async for session in get_async_session():
        result = await session.execute(
            select(Customer).where(Customer.phone == cleanup_test_customer)
        )
        customer = result.scalar_one_or_none()

        assert customer is not None
        assert customer.phone == cleanup_test_customer
        assert customer.first_name == "Test"
        assert customer.last_name == "Customer"
        assert str(customer.id) == confirm_result["customer_id"]


@pytest.mark.asyncio
async def test_new_customer_flow_different_name_provided(initial_state, cleanup_test_customer):
    """
    Test new customer flow when user provides a different name:
    1. Identify customer (not found)
    2. Greet new customer
    3. User provides different name
    4. Customer created with corrected name
    """
    # Step 1: Identify customer
    identify_result = await identify_customer(initial_state)
    state_after_identify = {**initial_state, **identify_result}

    # Step 2: Greet new customer
    greet_result = await greet_new_customer(state_after_identify)
    state_after_greet = {**state_after_identify, **greet_result}

    # Step 3: User provides different name
    user_response = HumanMessage(content="No, mi nombre es Carmen Ruiz")
    state_after_greet["messages"].append(user_response)

    # Mock LLM response for different name
    with patch("agent.nodes.identification.llm") as mock_llm:
        mock_llm_response = MagicMock()
        mock_llm_response.content = "different_name:Carmen Ruiz"
        mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response)

        confirm_result = await confirm_name(state_after_greet)

    assert confirm_result["customer_identified"] is True
    assert confirm_result["customer_name"] == "Carmen Ruiz"

    # Verify database has corrected name
    async for session in get_async_session():
        result = await session.execute(
            select(Customer).where(Customer.phone == cleanup_test_customer)
        )
        customer = result.scalar_one_or_none()

        assert customer is not None
        assert customer.first_name == "Carmen"
        assert customer.last_name == "Ruiz"


@pytest.mark.asyncio
async def test_new_customer_flow_escalation_after_two_ambiguous_responses(initial_state):
    """
    Test new customer flow with escalation:
    1. Identify customer (not found)
    2. Greet new customer
    3. First ambiguous response → clarification
    4. Second ambiguous response → escalation
    """
    # Step 1: Identify customer
    identify_result = await identify_customer(initial_state)
    state_after_identify = {**initial_state, **identify_result}

    # Step 2: Greet new customer
    greet_result = await greet_new_customer(state_after_identify)
    state_after_greet = {**state_after_identify, **greet_result}

    # Step 3: First ambiguous response
    user_response_1 = HumanMessage(content="ehh... no sé")
    state_after_greet["messages"].append(user_response_1)
    state_after_greet["clarification_attempts"] = 0

    with patch("agent.nodes.identification.llm") as mock_llm:
        mock_llm_response_1 = MagicMock()
        mock_llm_response_1.content = "ambiguous"
        mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response_1)

        confirm_result_1 = await confirm_name(state_after_greet)

    assert confirm_result_1["clarification_attempts"] == 1
    assert "escalated" not in confirm_result_1 or not confirm_result_1.get("escalated")

    # Update state after first attempt
    state_after_first_clarification = {**state_after_greet, **confirm_result_1}

    # Step 4: Second ambiguous response
    user_response_2 = HumanMessage(content="no entiendo la pregunta")
    state_after_first_clarification["messages"].append(user_response_2)

    with patch("agent.nodes.identification.llm") as mock_llm:
        mock_llm_response_2 = MagicMock()
        mock_llm_response_2.content = "ambiguous"
        mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response_2)

        confirm_result_2 = await confirm_name(state_after_first_clarification)

    assert confirm_result_2["escalated"] is True
    assert confirm_result_2["escalation_reason"] == "ambiguity"
    assert confirm_result_2["clarification_attempts"] == 2


@pytest.mark.asyncio
async def test_new_customer_without_whatsapp_metadata_name(cleanup_test_customer):
    """
    Test new customer flow without WhatsApp metadata name.
    Should ask for name directly without suggesting one.
    """
    state_no_metadata = {
        "conversation_id": "integration-test-no-metadata",
        "customer_phone": cleanup_test_customer,
        "messages": [],
        "metadata": {},  # No whatsapp_name
    }

    # Identify customer
    identify_result = await identify_customer(state_no_metadata)
    state_after_identify = {**state_no_metadata, **identify_result}

    # Greet new customer
    greet_result = await greet_new_customer(state_after_identify)

    greeting_message = greet_result["messages"][0].content
    assert "Maite" in greeting_message
    assert "🌸" in greeting_message
    assert "¿Me confirmas tu nombre para dirigirme a ti correctamente?" in greeting_message

    # User provides name
    state_after_greet = {**state_after_identify, **greet_result}
    user_response = HumanMessage(content="Soy Laura Fernández")
    state_after_greet["messages"].append(user_response)

    # Mock LLM to extract name from response
    with patch("agent.nodes.identification.llm") as mock_llm:
        mock_llm_response = MagicMock()
        mock_llm_response.content = "different_name:Laura Fernández"
        mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response)

        confirm_result = await confirm_name(state_after_greet)

    assert confirm_result["customer_identified"] is True
    assert confirm_result["customer_name"] == "Laura Fernández"

    # Verify in database
    async for session in get_async_session():
        result = await session.execute(
            select(Customer).where(Customer.phone == cleanup_test_customer)
        )
        customer = result.scalar_one_or_none()

        assert customer is not None
        assert customer.first_name == "Laura"
        assert customer.last_name == "Fernández"


@pytest.mark.asyncio
async def test_emoji_present_in_greeting(initial_state):
    """Test that the 🌸 emoji is present in the greeting message."""
    # Identify customer
    identify_result = await identify_customer(initial_state)
    state_after_identify = {**initial_state, **identify_result}

    # Greet new customer
    greet_result = await greet_new_customer(state_after_identify)

    greeting_message = greet_result["messages"][0].content
    assert "🌸" in greeting_message


@pytest.mark.asyncio
async def test_returning_customer_identified(cleanup_test_customer):
    """
    Test that returning customers are correctly identified.
    This is the alternate path where is_returning_customer=True.
    """
    # First, create a customer in the database
    async for session in get_async_session():
        new_customer = Customer(
            phone=cleanup_test_customer,
            first_name="Existing",
            last_name="Customer",
            metadata_={},
        )
        session.add(new_customer)
        await session.commit()
        await session.refresh(new_customer)
        customer_id = str(new_customer.id)

    # Now try to identify this customer
    state_with_existing_customer = {
        "conversation_id": "integration-test-returning",
        "customer_phone": cleanup_test_customer,
        "messages": [],
        "metadata": {},
    }

    identify_result = await identify_customer(state_with_existing_customer)

    assert identify_result["is_returning_customer"] is True
    assert identify_result["customer_id"] == customer_id
    assert identify_result["customer_name"] == "Existing Customer"

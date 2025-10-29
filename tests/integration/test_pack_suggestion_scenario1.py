"""
Integration test for Story 3.4 - Pack suggestion Scenario 1.

Tests the complete conversation flow from initial service request
through pack suggestion and acceptance.

Scenario 1 (from docs/specs/scenarios.md):
1. Customer: "Quiero hacerme mechas el viernes"
2. Bot: Greets, confirms identity (Laura)
3. Customer: "Sí, soy Laura"
4. Bot: Suggests "Mechas + Corte" pack with transparent pricing
5. Customer: "Sí, el pack"
6. Verify: pack_id set, requested_services updated to pack services
"""

import pytest
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from agent.graphs.conversation_flow import create_conversation_graph
from agent.state.schemas import ConversationState
from database.connection import get_async_session
from database.models import Customer, Pack, Service
from langchain_core.messages import HumanMessage


@pytest.mark.asyncio
async def test_scenario1_pack_suggestion_full_flow():
    """
    Test Scenario 1: Customer requests mechas, bot suggests pack, customer accepts.

    This integration test verifies:
    - Service extraction (simulated via state)
    - Pack query and suggestion
    - Transparent pricing format
    - Pack acceptance handling
    - State updates (pack_id, requested_services)
    """
    # Setup: Query actual services and packs from database
    async for session in get_async_session():
        # Find MECHAS service
        from sqlalchemy import select
        stmt = select(Service).where(Service.name == "MECHAS")
        result = await session.execute(stmt)
        mechas_service = result.scalar_one_or_none()

        if not mechas_service:
            pytest.skip("MECHAS service not found in database. Run seeds first.")

        # Find Mechas + Corte pack
        stmt = select(Pack).where(Pack.name.like("%Mechas%Corte%"))
        result = await session.execute(stmt)
        mechas_corte_pack = result.scalar_one_or_none()

        if not mechas_corte_pack:
            pytest.skip("Mechas + Corte pack not found in database. Run seeds first.")

        # Find or create test customer Laura
        stmt = select(Customer).where(Customer.phone == "+34612000001")
        result = await session.execute(stmt)
        laura = result.scalar_one_or_none()

        if not laura:
            pytest.skip("Test customer Laura not found. Run seeds first.")

    # Create conversation graph (no checkpointer for test)
    graph = create_conversation_graph(checkpointer=None)

    # Initial state simulating customer after identification
    # For Story 3.4, we simulate that service extraction has occurred
    # (Full service extraction will be implemented in a future story)
    conversation_id = f"test-scenario1-{uuid4()}"
    initial_state = ConversationState(
        conversation_id=conversation_id,
        customer_phone=laura.phone,
        customer_name=laura.first_name,  # Customer model uses first_name/last_name
        customer_id=laura.id,
        is_returning_customer=True,
        customer_identified=True,
        messages=[
            HumanMessage(content="Quiero hacerme mechas el viernes"),
        ],
        current_intent="booking",
        # Simulate service extraction result (future story will do this automatically)
        requested_services=[mechas_service.id],
        metadata={},
    )

    # Invoke graph starting from booking_handler
    # This will trigger: booking_handler → suggest_pack → (pack suggestion shown)
    config = {"configurable": {"thread_id": conversation_id}}

    try:
        result_state = await graph.ainvoke(initial_state, config=config)

        # Verify pack was suggested
        assert result_state.get("matching_packs") is not None
        assert len(result_state["matching_packs"]) > 0

        assert result_state.get("suggested_pack") is not None
        suggested_pack = result_state["suggested_pack"]

        # Verify pack details
        assert suggested_pack["pack"].id == mechas_corte_pack.id
        assert suggested_pack["savings_amount"] > 0

        # Verify bot response contains transparent pricing
        bot_response = result_state.get("bot_response")
        assert bot_response is not None
        assert "€" in bot_response  # Shows pricing
        assert "ahorras" in bot_response.lower()  # Shows savings
        assert "pack" in bot_response.lower()

        # Verify state has individual total calculated
        assert result_state.get("individual_service_total") is not None

        # Step 2: Customer accepts pack
        # Add customer's acceptance message to state
        acceptance_state = ConversationState(
            **result_state,
            messages=[
                *result_state["messages"],
                HumanMessage(content="Sí, el pack"),
            ]
        )

        # Invoke graph again - should trigger handle_pack_response
        result_state_2 = await graph.ainvoke(acceptance_state, config=config)

        # Verify pack was accepted
        assert result_state_2.get("pack_id") == mechas_corte_pack.id

        # Verify requested_services updated to pack's services
        assert result_state_2.get("requested_services") == mechas_corte_pack.included_service_ids

        # Verify total_price and total_duration updated
        assert result_state_2.get("total_price") == mechas_corte_pack.price_euros
        assert result_state_2.get("total_duration") == mechas_corte_pack.duration_minutes

        # Verify confirmation message
        final_bot_response = result_state_2.get("bot_response")
        assert final_bot_response is not None
        assert "laura" in final_bot_response.lower()
        assert "pack" in final_bot_response.lower()

        print("✓ Scenario 1 test passed: Pack suggestion and acceptance flow works correctly")

    except Exception as e:
        pytest.fail(f"Scenario 1 test failed: {e}")


@pytest.mark.asyncio
async def test_scenario1_pack_decline():
    """
    Test Scenario 1 variant: Customer declines pack, proceeds with individual service.
    """
    # Setup: Query services from database
    async for session in get_async_session():
        from sqlalchemy import select

        # Find MECHAS service
        stmt = select(Service).where(Service.name == "MECHAS")
        result = await session.execute(stmt)
        mechas_service = result.scalar_one_or_none()

        if not mechas_service:
            pytest.skip("MECHAS service not found in database. Run seeds first.")

        # Find test customer Laura
        stmt = select(Customer).where(Customer.phone == "+34612000001")
        result = await session.execute(stmt)
        laura = result.scalar_one_or_none()

        if not laura:
            pytest.skip("Test customer Laura not found. Run seeds first.")

    # Create conversation graph
    graph = create_conversation_graph(checkpointer=None)

    # Initial state with service extraction
    conversation_id = f"test-scenario1-decline-{uuid4()}"
    initial_state = ConversationState(
        conversation_id=conversation_id,
        customer_phone=laura.phone,
        customer_name=laura.first_name,
        customer_id=laura.id,
        is_returning_customer=True,
        customer_identified=True,
        messages=[
            HumanMessage(content="Quiero hacerme mechas el viernes"),
        ],
        current_intent="booking",
        requested_services=[mechas_service.id],
        metadata={},
    )

    config = {"configurable": {"thread_id": conversation_id}}

    try:
        # Step 1: Get pack suggestion
        result_state = await graph.ainvoke(initial_state, config=config)

        assert result_state.get("suggested_pack") is not None

        # Step 2: Customer declines pack
        decline_state = ConversationState(
            **result_state,
            messages=[
                *result_state["messages"],
                HumanMessage(content="No, solo las mechas"),
            ]
        )

        result_state_2 = await graph.ainvoke(decline_state, config=config)

        # Verify pack was declined
        assert result_state_2.get("pack_declined") is True

        # Verify requested_services unchanged (still individual service)
        assert result_state_2.get("requested_services") == [mechas_service.id]

        # Verify no pack_id set
        assert result_state_2.get("pack_id") is None

        # Verify acknowledgment message
        final_bot_response = result_state_2.get("bot_response")
        assert final_bot_response is not None
        assert "entendido" in final_bot_response.lower()

        print("✓ Scenario 1 decline test passed: Customer can decline pack and proceed with individual service")

    except Exception as e:
        pytest.fail(f"Scenario 1 decline test failed: {e}")


@pytest.mark.asyncio
async def test_scenario1_no_pack_available():
    """
    Test Scenario 1 variant: Service has no packs available, skip suggestion.
    """
    # Setup: Find a service without packs (or use a mock scenario)
    async for session in get_async_session():
        from sqlalchemy import select

        # Find test customer Laura
        stmt = select(Customer).where(Customer.phone == "+34612000001")
        result = await session.execute(stmt)
        laura = result.scalar_one_or_none()

        if not laura:
            pytest.skip("Test customer Laura not found. Run seeds first.")

        # For this test, we'll use a service ID that has no packs
        # In practice, you'd query for such a service from the database
        # For now, we'll create a dummy UUID
        no_pack_service_id = uuid4()

    # Create conversation graph
    graph = create_conversation_graph(checkpointer=None)

    conversation_id = f"test-scenario1-no-pack-{uuid4()}"
    initial_state = ConversationState(
        conversation_id=conversation_id,
        customer_phone=laura.phone,
        customer_name=laura.first_name,
        customer_id=laura.id,
        is_returning_customer=True,
        customer_identified=True,
        messages=[
            HumanMessage(content="Quiero un servicio sin pack"),
        ],
        current_intent="booking",
        requested_services=[no_pack_service_id],  # Service with no packs
        metadata={},
    )

    config = {"configurable": {"thread_id": conversation_id}}

    try:
        result_state = await graph.ainvoke(initial_state, config=config)

        # Verify no pack was suggested
        assert result_state.get("matching_packs") == [] or result_state.get("matching_packs") is None
        assert result_state.get("suggested_pack") is None

        # Verify no pack suggestion message
        bot_response = result_state.get("bot_response")
        # Bot response might be None or not contain pack suggestion
        if bot_response:
            assert "pack" not in bot_response.lower() or result_state.get("bot_response") is None

        print("✓ Scenario 1 no pack test passed: Services without packs skip suggestion correctly")

    except Exception as e:
        pytest.fail(f"Scenario 1 no pack test failed: {e}")


@pytest.mark.asyncio
async def test_scenario1_unclear_response_clarification():
    """
    Test Scenario 1 variant: Customer gives unclear response, bot asks for clarification.
    """
    # Setup
    async for session in get_async_session():
        from sqlalchemy import select

        # Find MECHAS service
        stmt = select(Service).where(Service.name == "MECHAS")
        result = await session.execute(stmt)
        mechas_service = result.scalar_one_or_none()

        if not mechas_service:
            pytest.skip("MECHAS service not found in database. Run seeds first.")

        # Find test customer Laura
        stmt = select(Customer).where(Customer.phone == "+34612000001")
        result = await session.execute(stmt)
        laura = result.scalar_one_or_none()

        if not laura:
            pytest.skip("Test customer Laura not found. Run seeds first.")

    # Create conversation graph
    graph = create_conversation_graph(checkpointer=None)

    conversation_id = f"test-scenario1-unclear-{uuid4()}"
    initial_state = ConversationState(
        conversation_id=conversation_id,
        customer_phone=laura.phone,
        customer_name=laura.first_name,
        customer_id=laura.id,
        is_returning_customer=True,
        customer_identified=True,
        messages=[
            HumanMessage(content="Quiero hacerme mechas el viernes"),
        ],
        current_intent="booking",
        requested_services=[mechas_service.id],
        clarification_attempts=0,
        metadata={},
    )

    config = {"configurable": {"thread_id": conversation_id}}

    try:
        # Step 1: Get pack suggestion
        result_state = await graph.ainvoke(initial_state, config=config)

        assert result_state.get("suggested_pack") is not None

        # Step 2: Customer gives unclear response
        unclear_state = ConversationState(
            **result_state,
            messages=[
                *result_state["messages"],
                HumanMessage(content="Hmm, no sé..."),
            ]
        )

        result_state_2 = await graph.ainvoke(unclear_state, config=config)

        # Verify clarification was requested
        assert result_state_2.get("clarification_attempts", 0) >= 1

        # Verify clarification message
        final_bot_response = result_state_2.get("bot_response")
        assert final_bot_response is not None
        assert "prefieres" in final_bot_response.lower()

        # Verify no decision made yet
        assert result_state_2.get("pack_id") is None
        assert result_state_2.get("pack_declined") != True

        print("✓ Scenario 1 unclear test passed: Bot asks for clarification on unclear responses")

    except Exception as e:
        pytest.fail(f"Scenario 1 unclear test failed: {e}")

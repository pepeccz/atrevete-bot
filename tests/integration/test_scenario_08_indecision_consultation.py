"""
Integration test for Story 3.5 - Indecision detection and free consultation offering.

Tests the complete conversation flow from initial indecision message
through consultation offer, acceptance, and booking without payment.

Scenario 8 (from docs/specs/scenarios.md):
1. Customer: "Hola, quiero un cambio de color pero no sé si elegir óleos o barro gol, ¿cuál me recomiendas?"
2. Bot: Greets, confirms identity (Laura)
3. Customer: "Sí, soy Laura"
4. Bot: Describes both services (OLEO PIGMENTO, BARRO GOLD) with prices and durations
5. Bot: Offers consultation: "¿Quieres que reserve una **consulta gratuita de 15 minutos**...?"
6. Customer: "Sí, prefiero la consulta primero"
7. Bot: Asks for preferred day
8. Customer: "El jueves por la mañana"
9. Bot: Offers 2 availability slots
10. Customer: "10:00"
11. Bot: Asks for last name
12. Customer: "Martínez"
13. Bot: Confirmation: "Perfecto, Laura **Martínez**. Tu consulta gratuita queda confirmada..."
"""

import pytest
from datetime import datetime
from uuid import uuid4

from agent.graphs.conversation_flow import create_conversation_graph
from agent.state.schemas import ConversationState
from database.connection import get_async_session
from database.models import Customer, Service
from langchain_core.messages import HumanMessage


@pytest.mark.asyncio
async def test_scenario8_indecision_consultation_full_flow():
    """
    Test Scenario 8: Customer shows indecision, bot offers consultation, customer accepts.

    This integration test verifies:
    - Indecision detection from customer message
    - Consultation offer triggered
    - Free consultation (CONSULTA GRATUITA) service retrieved
    - Consultation acceptance handling
    - State updates (consultation_accepted=true, skip_payment_flow=true)
    - No payment link generated for free consultation

    NOTE: Full booking flow (availability checking, calendar creation) depends on
    Stories 3.3 and 4.x. This test focuses on indecision detection and consultation
    offer/acceptance logic.
    """
    # Setup: Query actual services from database
    async for session in get_async_session():
        from sqlalchemy import select

        # Find OLEO PIGMENTO service
        stmt = select(Service).where(Service.name == "OLEO PIGMENTO")
        result = await session.execute(stmt)
        oleo_service = result.scalar_one_or_none()

        if not oleo_service:
            pytest.skip("OLEO PIGMENTO service not found in database. Run seeds first.")

        # Find BARRO GOLD service
        stmt = select(Service).where(Service.name == "BARRO GOLD")
        result = await session.execute(stmt)
        barro_gold_service = result.scalar_one_or_none()

        if not barro_gold_service:
            pytest.skip("BARRO GOLD service not found in database. Run seeds first.")

        # Find CONSULTA GRATUITA service
        stmt = select(Service).where(Service.name == "CONSULTA GRATUITA")
        result = await session.execute(stmt)
        consulta_service = result.scalar_one_or_none()

        if not consulta_service:
            pytest.skip("CONSULTA GRATUITA service not found in database. Run seeds first.")

        # Verify consultation service has correct attributes
        assert consulta_service.duration_minutes == 15, "CONSULTA GRATUITA should be 15 minutes"
        assert consulta_service.price_euros == 0, "CONSULTA GRATUITA should be free (0€)"
        assert consulta_service.requires_advance_payment is False, "CONSULTA GRATUITA should not require payment"

        # Find or create test customer Laura
        stmt = select(Customer).where(Customer.phone == "+34612000001")
        result = await session.execute(stmt)
        laura = result.scalar_one_or_none()

        if not laura:
            pytest.skip("Test customer Laura not found. Run seeds first.")

    # Create conversation graph (no checkpointer for test)
    graph = create_conversation_graph(checkpointer=None)

    # Initial state simulating new customer after identification
    conversation_id = f"test-scenario8-{uuid4()}"
    initial_state = ConversationState(
        conversation_id=conversation_id,
        customer_phone=laura.phone,
        customer_name=laura.first_name,
        customer_id=laura.id,
        is_returning_customer=False,  # New customer in Scenario 8
        customer_identified=True,
        messages=[
            HumanMessage(content="Hola, quiero un cambio de color pero no sé si elegir óleos o barro gol, ¿cuál me recomiendas?"),
        ],
        current_intent="inquiry",  # Customer is asking, not yet booking
        metadata={},
    )

    config = {"configurable": {"thread_id": conversation_id}}

    try:
        # Step 1: Process initial indecision message
        # This should trigger: detect_indecision → offer_consultation
        result_state = await graph.ainvoke(initial_state, config=config)

        # Verify indecision was detected
        assert result_state.get("indecision_detected") is True, "Indecision should be detected"
        assert result_state.get("confidence", 0) > 0.7, f"Confidence should be > 0.7, got {result_state.get('confidence')}"
        assert result_state.get("indecision_type") in ["service_choice", "treatment_comparison"], \
            f"Indecision type should be service_choice or treatment_comparison, got {result_state.get('indecision_type')}"

        # Verify detected services include the compared services
        detected_services = result_state.get("detected_services", [])
        assert len(detected_services) > 0, "Should detect at least one service being compared"

        # Verify consultation was offered
        assert result_state.get("consultation_offered") is True, "Consultation should be offered"
        assert result_state.get("consultation_service_id") == consulta_service.id, \
            "Consultation service ID should be set to CONSULTA GRATUITA"

        # Verify bot response contains consultation offer
        bot_response = result_state.get("bot_response")
        assert bot_response is not None, "Bot should provide response"
        assert "consulta gratuita" in bot_response.lower(), "Response should mention 'consulta gratuita'"
        assert "15 minutos" in bot_response.lower(), "Response should mention duration (15 minutos)"

        # Step 2: Customer accepts consultation
        acceptance_state = ConversationState(
            **result_state,
            messages=[
                *result_state["messages"],
                HumanMessage(content="Sí, prefiero la consulta primero"),
            ]
        )

        result_state_2 = await graph.ainvoke(acceptance_state, config=config)

        # Verify consultation was accepted
        assert result_state_2.get("consultation_accepted") is True, "Consultation should be accepted"

        # Verify requested_services updated to consultation
        requested_services = result_state_2.get("requested_services", [])
        assert consulta_service.id in requested_services, \
            f"Consultation service ID should be in requested_services, got {requested_services}"

        # Verify skip_payment_flow flag set
        assert result_state_2.get("skip_payment_flow") is True, \
            "skip_payment_flow should be true for free consultation"

        # Verify current_intent updated to booking
        assert result_state_2.get("current_intent") == "booking", \
            f"Intent should change to 'booking' after acceptance, got {result_state_2.get('current_intent')}"

        # Verify no payment link generated (this would be in future booking flow)
        # For now, we just verify the flag is set correctly
        assert result_state_2.get("payment_link") is None, "No payment link should be generated for free consultation"

        print("✓ Scenario 8 test passed: Indecision detection and consultation acceptance flow works correctly")

    except Exception as e:
        pytest.fail(f"Scenario 8 test failed: {e}")


@pytest.mark.asyncio
async def test_scenario8_consultation_decline():
    """
    Test Scenario 8 variant: Customer declines consultation, proceeds with service selection.

    Verifies:
    - Consultation offered after indecision detection
    - Customer declines consultation
    - State updated with consultation_declined=true
    - Bot re-presents service options for customer to choose
    """
    # Setup: Query services from database
    async for session in get_async_session():
        from sqlalchemy import select

        # Find CONSULTA GRATUITA service
        stmt = select(Service).where(Service.name == "CONSULTA GRATUITA")
        result = await session.execute(stmt)
        consulta_service = result.scalar_one_or_none()

        if not consulta_service:
            pytest.skip("CONSULTA GRATUITA service not found in database. Run seeds first.")

        # Find test customer Laura
        stmt = select(Customer).where(Customer.phone == "+34612000001")
        result = await session.execute(stmt)
        laura = result.scalar_one_or_none()

        if not laura:
            pytest.skip("Test customer Laura not found. Run seeds first.")

    # Create conversation graph
    graph = create_conversation_graph(checkpointer=None)

    conversation_id = f"test-scenario8-decline-{uuid4()}"
    initial_state = ConversationState(
        conversation_id=conversation_id,
        customer_phone=laura.phone,
        customer_name=laura.first_name,
        customer_id=laura.id,
        is_returning_customer=False,
        customer_identified=True,
        messages=[
            HumanMessage(content="No sé si elegir mechas o color, ¿cuál es mejor?"),
        ],
        current_intent="inquiry",
        metadata={},
    )

    config = {"configurable": {"thread_id": conversation_id}}

    try:
        # Step 1: Get consultation offer
        result_state = await graph.ainvoke(initial_state, config=config)

        assert result_state.get("consultation_offered") is True, "Consultation should be offered"

        # Step 2: Customer declines consultation
        decline_state = ConversationState(
            **result_state,
            messages=[
                *result_state["messages"],
                HumanMessage(content="No gracias, prefiero decidirme ahora"),
            ]
        )

        result_state_2 = await graph.ainvoke(decline_state, config=config)

        # Verify consultation was declined
        assert result_state_2.get("consultation_declined") is True, "Consultation should be marked as declined"

        # Verify consultation NOT accepted
        assert result_state_2.get("consultation_accepted") != True, "Consultation should not be accepted"

        # Verify requested_services does NOT contain consultation
        requested_services = result_state_2.get("requested_services", [])
        assert consulta_service.id not in requested_services, \
            "Consultation service should not be in requested_services after decline"

        # Verify skip_payment_flow NOT set (normal service booking will require payment)
        assert result_state_2.get("skip_payment_flow") != True, \
            "skip_payment_flow should not be set after declining consultation"

        # Verify bot response acknowledges decline and re-presents options
        bot_response = result_state_2.get("bot_response")
        assert bot_response is not None, "Bot should provide response"
        assert "entendido" in bot_response.lower() or "perfecto" in bot_response.lower(), \
            "Response should acknowledge customer's decision"

        print("✓ Scenario 8 decline test passed: Customer can decline consultation and proceed with service selection")

    except Exception as e:
        pytest.fail(f"Scenario 8 decline test failed: {e}")


@pytest.mark.asyncio
async def test_scenario8_no_indecision_detected():
    """
    Test Scenario 8 variant: Customer makes clear service request, no indecision detected.

    Verifies:
    - Clear service request does NOT trigger indecision detection
    - Consultation NOT offered
    - Normal booking flow proceeds
    """
    # Setup: Query services from database
    async for session in get_async_session():
        from sqlalchemy import select

        # Find test customer Laura
        stmt = select(Customer).where(Customer.phone == "+34612000001")
        result = await session.execute(stmt)
        laura = result.scalar_one_or_none()

        if not laura:
            pytest.skip("Test customer Laura not found. Run seeds first.")

    # Create conversation graph
    graph = create_conversation_graph(checkpointer=None)

    conversation_id = f"test-scenario8-no-indecision-{uuid4()}"
    initial_state = ConversationState(
        conversation_id=conversation_id,
        customer_phone=laura.phone,
        customer_name=laura.first_name,
        customer_id=laura.id,
        is_returning_customer=False,
        customer_identified=True,
        messages=[
            HumanMessage(content="Quiero hacerme mechas el viernes"),  # Clear request, no indecision
        ],
        current_intent="booking",
        metadata={},
    )

    config = {"configurable": {"thread_id": conversation_id}}

    try:
        result_state = await graph.ainvoke(initial_state, config=config)

        # Verify NO indecision detected
        assert result_state.get("indecision_detected") != True, \
            "Indecision should NOT be detected for clear service request"

        # Verify confidence is low (if indecision detection ran)
        confidence = result_state.get("confidence", 0)
        if confidence > 0:  # If detection ran
            assert confidence <= 0.7, f"Confidence should be <= 0.7 for clear request, got {confidence}"

        # Verify consultation NOT offered
        assert result_state.get("consultation_offered") != True, \
            "Consultation should NOT be offered for clear service request"

        # Verify consultation_service_id NOT set
        assert result_state.get("consultation_service_id") is None, \
            "Consultation service ID should not be set"

        # Verify bot response does NOT contain consultation offer
        bot_response = result_state.get("bot_response")
        if bot_response:
            assert "consulta gratuita" not in bot_response.lower(), \
                "Response should NOT mention consultation for clear request"

        print("✓ Scenario 8 no indecision test passed: Clear requests skip consultation flow correctly")

    except Exception as e:
        pytest.fail(f"Scenario 8 no indecision test failed: {e}")


@pytest.mark.asyncio
async def test_scenario8_unclear_response_clarification():
    """
    Test Scenario 8 variant: Customer gives unclear response to consultation offer.

    Verifies:
    - Consultation offered after indecision detection
    - Customer gives unclear response
    - Bot asks for clarification
    - Clarification attempt counter incremented
    """
    # Setup: Query services from database
    async for session in get_async_session():
        from sqlalchemy import select

        # Find test customer Laura
        stmt = select(Customer).where(Customer.phone == "+34612000001")
        result = await session.execute(stmt)
        laura = result.scalar_one_or_none()

        if not laura:
            pytest.skip("Test customer Laura not found. Run seeds first.")

    # Create conversation graph
    graph = create_conversation_graph(checkpointer=None)

    conversation_id = f"test-scenario8-unclear-{uuid4()}"
    initial_state = ConversationState(
        conversation_id=conversation_id,
        customer_phone=laura.phone,
        customer_name=laura.first_name,
        customer_id=laura.id,
        is_returning_customer=False,
        customer_identified=True,
        messages=[
            HumanMessage(content="¿Qué diferencia hay entre mechas y color?"),
        ],
        current_intent="inquiry",
        clarification_attempts=0,
        metadata={},
    )

    config = {"configurable": {"thread_id": conversation_id}}

    try:
        # Step 1: Get consultation offer
        result_state = await graph.ainvoke(initial_state, config=config)

        assert result_state.get("consultation_offered") is True, "Consultation should be offered"

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
        clarification_attempts = result_state_2.get("clarification_attempts", 0)
        assert clarification_attempts >= 1, \
            f"Clarification attempts should be >= 1, got {clarification_attempts}"

        # Verify NO decision made yet
        assert result_state_2.get("consultation_accepted") != True, \
            "Consultation should not be accepted yet"
        assert result_state_2.get("consultation_declined") != True, \
            "Consultation should not be declined yet"

        # Verify clarification message
        bot_response = result_state_2.get("bot_response")
        assert bot_response is not None, "Bot should provide response"
        assert "prefieres" in bot_response.lower() or "quieres" in bot_response.lower(), \
            "Response should ask for clarification with 'prefieres' or 'quieres'"

        print("✓ Scenario 8 unclear test passed: Bot asks for clarification on unclear responses")

    except Exception as e:
        pytest.fail(f"Scenario 8 unclear test failed: {e}")

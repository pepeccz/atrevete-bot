"""
Integration tests for Story 3.6: Service Category Mixing Prevention

Tests full conversation flow with mixed service categories and customer choices.
"""

import pytest
from uuid import uuid4
from sqlalchemy import select
from database.models import Service, ServiceCategory, Customer
from database.connection import get_async_session
from agent.state.schemas import ConversationState
from agent.graphs.conversation_flow import create_conversation_graph


@pytest.mark.asyncio
async def test_mixed_category_scenario_corte_plus_bioterapia():
    """
    AC 8: Integration test for 'corte + bioterapia facial' scenario.

    Flow:
    1. Customer requests mixed services (Hairdressing + Aesthetics)
    2. Bot detects mixed categories and offers alternatives
    3. Customer chooses to book separately
    4. Bot initiates first booking flow

    Verifies:
    - mixed_category_detected=true
    - Alternatives offered in bot response
    - Services grouped by category correctly
    - pending_bookings created with 2 entries
    - First booking flow initiated with Hairdressing service
    """
    # Setup: Get service IDs from database
    async for session in get_async_session():
        # Get CORTAR (Hairdressing) and BIOTERAPIA FACIAL (Aesthetics)
        result = await session.execute(
            select(Service).where(
                Service.name.in_(["Corte de pelo", "BIOTERAPIA FACIAL"])
            )
        )
        services = result.scalars().all()

        corte_service = next(s for s in services if s.category == ServiceCategory.HAIRDRESSING)
        bioterapia_service = next(s for s in services if s.category == ServiceCategory.AESTHETICS)

        # Create test customer
        customer = Customer(
            id=uuid4(),
            phone="+34600000001",
            first_name="Laura",
            last_name="Test",
            email="laura.test@example.com"
        )
        session.add(customer)
        await session.commit()

        # Initialize conversation state
        state: ConversationState = {
            "conversation_id": str(uuid4()),
            "customer_id": str(customer.id),
            "customer_name": "Laura",
            "requested_services": [corte_service.id, bioterapia_service.id],
            "messages": [],
            "booking_validation_passed": False,
            "mixed_category_detected": False,
            "awaiting_category_choice": False,
            "services_by_category": {},
            "pending_bookings": [],
            "current_booking_index": 0,
            "is_multi_booking_flow": False,
        }

        # Create conversation graph
        graph = create_conversation_graph()

        # Execute validation node
        from agent.nodes.booking_nodes import validate_booking_request
        result_state = await validate_booking_request(state)

        # Verify AC 8: Mixed category detected
        assert result_state["mixed_category_detected"] is True, \
            "Mixed category should be detected for Hairdressing + Aesthetics"

        assert result_state["booking_validation_passed"] is False, \
            "Validation should fail for mixed categories"

        assert result_state["awaiting_category_choice"] is True, \
            "Should be awaiting customer's category choice"

        # Verify alternatives offered in bot response
        bot_response = result_state.get("bot_response", "")
        assert "peluquería" in bot_response.lower() and "estética" in bot_response.lower(), \
            "Bot response should mention both categories"

        assert "1️⃣" in bot_response and "2️⃣" in bot_response, \
            "Bot response should offer numbered options"

        assert "por separado" in bot_response.lower() or "reservar ambos" in bot_response.lower(), \
            "Bot response should offer booking separately option"

        # Verify services grouped by category
        services_by_cat = result_state.get("services_by_category", {})
        assert len(services_by_cat) == 2, \
            "Should have services grouped into 2 categories"

        assert ServiceCategory.HAIRDRESSING.value in services_by_cat, \
            "Should have Hairdressing category"

        assert ServiceCategory.AESTHETICS.value in services_by_cat, \
            "Should have Aesthetics category"

        # Simulate customer choice: "Prefiero hacer ambos por separado"
        state_with_choice = {**result_state}
        state_with_choice["messages"].append({
            "role": "user",
            "content": "Prefiero hacer ambos por separado"
        })

        # Execute handle_category_choice node
        from agent.nodes.booking_nodes import handle_category_choice
        final_state = await handle_category_choice(state_with_choice)

        # Verify pending_bookings created with 2 entries
        pending = final_state.get("pending_bookings", [])
        assert len(pending) == 2, \
            "Should have 2 pending bookings for separate booking flow"

        assert pending[0]["category"] == ServiceCategory.HAIRDRESSING.value, \
            "First booking should be Hairdressing"

        assert pending[1]["category"] == ServiceCategory.AESTHETICS.value, \
            "Second booking should be Aesthetics"

        assert final_state.get("is_multi_booking_flow") is True, \
            "Should be in multi-booking flow"

        assert final_state.get("current_booking_index") == 0, \
            "Should start with first booking (index 0)"

        # Verify bot initiates first booking
        final_response = final_state.get("bot_response", "")
        assert "corte" in final_response.lower() or "pelo" in final_response.lower(), \
            "Bot should mention Hairdressing service for first booking"

        assert "día" in final_response.lower() or "fecha" in final_response.lower(), \
            "Bot should ask for preferred date"

        # Cleanup
        await session.delete(customer)
        await session.commit()


@pytest.mark.asyncio
async def test_same_category_passes_corte_plus_color():
    """
    AC 10: Edge case test for 'corte + color' (both Hairdressing).

    Verifies:
    - Both services are Hairdressing category
    - Validation passes without user interaction
    - booking_validation_passed=true
    - No mixed category message
    - Flow proceeds directly to availability checking
    """
    # Setup: Get service IDs from database
    async for session in get_async_session():
        # Get Corte de pelo and Corte + Color (both Hairdressing)
        result = await session.execute(
            select(Service).where(
                Service.name.in_(["Corte de pelo", "Corte + Color"])
            )
        )
        services = result.scalars().all()

        assert len(services) == 2, "Should find both Hairdressing services"
        assert all(s.category == ServiceCategory.HAIRDRESSING for s in services), \
            "Both services should be Hairdressing category"

        service_ids = [s.id for s in services]

        # Initialize conversation state
        state: ConversationState = {
            "conversation_id": str(uuid4()),
            "customer_id": str(uuid4()),
            "customer_name": "Maria",
            "requested_services": service_ids,
            "messages": [],
            "booking_validation_passed": False,
            "mixed_category_detected": False,
            "awaiting_category_choice": False,
            "services_by_category": {},
            "pending_bookings": [],
            "current_booking_index": 0,
            "is_multi_booking_flow": False,
        }

        # Execute validation node
        from agent.nodes.booking_nodes import validate_booking_request
        result_state = await validate_booking_request(state)

        # Verify AC 10: Validation passes for same category
        assert result_state["booking_validation_passed"] is True, \
            "Validation should pass for same category services"

        assert result_state.get("mixed_category_detected") is not True, \
            "Mixed category should NOT be detected for same category services"

        assert result_state.get("awaiting_category_choice") is not True, \
            "Should NOT be awaiting category choice for same category"

        # Verify no alternatives message
        bot_response = result_state.get("bot_response")
        assert bot_response is None or "por separado" not in bot_response.lower(), \
            "Should NOT offer alternatives for same category services"

        # Verify flow can proceed to availability
        assert result_state.get("booking_validation_passed") is True, \
            "Should be ready to proceed to availability checking"


@pytest.mark.asyncio
async def test_customer_chooses_hairdressing_only():
    """
    Test customer choosing Hairdressing only after mixed category detection.

    Verifies:
    - requested_services filtered to Hairdressing only
    - mixed_category_detected cleared
    - booking_validation_passed set to true
    - Bot confirms choice and proceeds
    """
    async for session in get_async_session():
        # Get mixed services
        result = await session.execute(
            select(Service).where(
                Service.name.in_(["Corte de pelo", "MANICURA PERMANENTE"])
            )
        )
        services = result.scalars().all()

        corte = next(s for s in services if s.category == ServiceCategory.HAIRDRESSING)
        manicura = next(s for s in services if s.category == ServiceCategory.AESTHETICS)

        # State after mixed category detection
        state: ConversationState = {
            "conversation_id": str(uuid4()),
            "customer_id": str(uuid4()),
            "customer_name": "Ana",
            "requested_services": [corte.id, manicura.id],
            "messages": [
                {"role": "user", "content": "Solo quiero el corte, olvida la manicura"}
            ],
            "booking_validation_passed": False,
            "mixed_category_detected": True,
            "awaiting_category_choice": True,
            "services_by_category": {
                ServiceCategory.HAIRDRESSING.value: [corte.id],
                ServiceCategory.AESTHETICS.value: [manicura.id]
            },
            "pending_bookings": [],
            "current_booking_index": 0,
            "is_multi_booking_flow": False,
        }

        # Execute handle_category_choice
        from agent.nodes.booking_nodes import handle_category_choice
        result_state = await handle_category_choice(state)

        # Verify services filtered to Hairdressing only
        filtered_services = result_state.get("requested_services", [])
        assert len(filtered_services) == 1, \
            "Should have only 1 service after filtering"

        assert filtered_services[0] == corte.id, \
            "Should keep only Hairdressing service"

        # Verify flags cleared/set
        assert result_state.get("mixed_category_detected") is not True, \
            "Mixed category flag should be cleared"

        assert result_state.get("booking_validation_passed") is True, \
            "Validation should pass after filtering to single category"

        # Verify bot response confirms choice
        bot_response = result_state.get("bot_response", "")
        assert "corte" in bot_response.lower(), \
            "Bot should confirm Hairdressing service choice"


@pytest.mark.asyncio
async def test_customer_cancels_mixed_booking():
    """
    Test customer canceling booking after mixed category detection.

    Verifies:
    - requested_services cleared
    - Bot acknowledges cancellation
    - Returns to normal conversation flow
    """
    async for session in get_async_session():
        # State after mixed category detection
        state: ConversationState = {
            "conversation_id": str(uuid4()),
            "customer_id": str(uuid4()),
            "customer_name": "Carlos",
            "requested_services": [uuid4(), uuid4()],
            "messages": [
                {"role": "user", "content": "Mejor déjalo, no voy a reservar"}
            ],
            "booking_validation_passed": False,
            "mixed_category_detected": True,
            "awaiting_category_choice": True,
            "services_by_category": {},
            "pending_bookings": [],
            "current_booking_index": 0,
            "is_multi_booking_flow": False,
        }

        # Execute handle_category_choice
        from agent.nodes.booking_nodes import handle_category_choice
        result_state = await handle_category_choice(state)

        # Verify services cleared
        assert len(result_state.get("requested_services", [])) == 0, \
            "Should clear requested_services on cancellation"

        # Verify bot acknowledges
        bot_response = result_state.get("bot_response", "")
        assert "entendido" in bot_response.lower() or "entiendo" in bot_response.lower(), \
            "Bot should acknowledge cancellation"

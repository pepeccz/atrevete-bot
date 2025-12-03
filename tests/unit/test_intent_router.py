"""
Tests for IntentRouter routing logic.

This module tests the intent routing system that separates booking intents
(FSM-prescribed tools) from non-booking intents (LLM conversational).

Coverage:
- BOOKING_INTENTS constant completeness
- NON_BOOKING_INTENTS constant completeness
- No overlap between intent sets
- All IntentTypes covered
- Routing decision logic
- Handler instantiation and invocation
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.fsm.models import BookingState, Intent, IntentType
from agent.routing.intent_router import IntentRouter


class TestIntentRouterConstants:
    """Test BOOKING_INTENTS and NON_BOOKING_INTENTS constants."""

    def test_booking_intents_complete(self):
        """Verify all 9 booking intent types are included."""
        expected = {
            IntentType.START_BOOKING,
            IntentType.SELECT_SERVICE,
            IntentType.CONFIRM_SERVICES,
            IntentType.SELECT_STYLIST,
            IntentType.CHECK_AVAILABILITY,
            IntentType.SELECT_SLOT,
            IntentType.PROVIDE_CUSTOMER_DATA,
            IntentType.CONFIRM_BOOKING,
            IntentType.CANCEL_BOOKING,
        }
        assert IntentRouter.BOOKING_INTENTS == expected, (
            f"Expected {len(expected)} booking intents, "
            f"got {len(IntentRouter.BOOKING_INTENTS)}"
        )

    def test_non_booking_intents_complete(self):
        """Verify all 4 non-booking intent types are included."""
        expected = {
            IntentType.GREETING,
            IntentType.FAQ,
            IntentType.ESCALATE,
            IntentType.UNKNOWN,
        }
        assert IntentRouter.NON_BOOKING_INTENTS == expected, (
            f"Expected {len(expected)} non-booking intents, "
            f"got {len(IntentRouter.NON_BOOKING_INTENTS)}"
        )

    def test_no_overlap_between_intent_sets(self):
        """Verify booking and non-booking sets don't overlap."""
        overlap = IntentRouter.BOOKING_INTENTS & IntentRouter.NON_BOOKING_INTENTS
        assert len(overlap) == 0, f"Found overlapping intents: {overlap}"

    def test_all_intent_types_covered(self):
        """Verify every IntentType is in one of the two sets."""
        all_intents = set(IntentType)
        covered = IntentRouter.BOOKING_INTENTS | IntentRouter.NON_BOOKING_INTENTS
        assert all_intents == covered, (
            f"Missing coverage for: {all_intents - covered}"
        )

    def test_booking_intents_count(self):
        """Verify BOOKING_INTENTS has exactly 9 members."""
        assert len(IntentRouter.BOOKING_INTENTS) == 9, (
            f"BOOKING_INTENTS should have 9 members, "
            f"got {len(IntentRouter.BOOKING_INTENTS)}"
        )

    def test_non_booking_intents_count(self):
        """Verify NON_BOOKING_INTENTS has exactly 4 members."""
        assert len(IntentRouter.NON_BOOKING_INTENTS) == 4, (
            f"NON_BOOKING_INTENTS should have 4 members, "
            f"got {len(IntentRouter.NON_BOOKING_INTENTS)}"
        )

    def test_check_availability_is_booking_intent(self):
        """Verify CHECK_AVAILABILITY is classified as booking intent."""
        assert IntentType.CHECK_AVAILABILITY in IntentRouter.BOOKING_INTENTS, (
            "CHECK_AVAILABILITY should be a booking intent"
        )

    def test_greeting_is_non_booking_intent(self):
        """Verify GREETING is classified as non-booking intent."""
        assert IntentType.GREETING in IntentRouter.NON_BOOKING_INTENTS, (
            "GREETING should be a non-booking intent"
        )


class TestIntentRouterRouting:
    """Test routing decision logic."""

    @pytest.mark.asyncio
    async def test_routes_start_booking_to_booking_handler(
        self, mock_fsm, mock_llm, mock_state
    ):
        """Verify START_BOOKING intent routes to BookingHandler."""
        intent = Intent(type=IntentType.START_BOOKING, raw_message="Quiero reservar")

        # Mock BookingHandler.handle to avoid real execution
        with patch("agent.routing.booking_handler.BookingHandler") as MockHandler:
            mock_instance = MockHandler.return_value
            mock_instance.handle = AsyncMock(return_value="Booking response")

            response = await IntentRouter.route(intent, mock_fsm, mock_state, mock_llm)

            # Verify handler was instantiated with correct args
            MockHandler.assert_called_once_with(mock_fsm, mock_state, mock_llm)
            # Verify handle was called with intent
            mock_instance.handle.assert_called_once_with(intent)
            # Verify response is correct
            assert response == "Booking response"

    @pytest.mark.asyncio
    async def test_routes_select_service_to_booking_handler(
        self, mock_fsm, mock_llm, mock_state
    ):
        """Verify SELECT_SERVICE intent routes to BookingHandler."""
        intent = Intent(
            type=IntentType.SELECT_SERVICE,
            raw_message="Corte de señora",
            entities={"service": "Corte de señora"}
        )

        with patch("agent.routing.booking_handler.BookingHandler") as MockHandler:
            mock_instance = MockHandler.return_value
            mock_instance.handle = AsyncMock(return_value="Service selected")

            response = await IntentRouter.route(intent, mock_fsm, mock_state, mock_llm)

            MockHandler.assert_called_once()
            mock_instance.handle.assert_called_once_with(intent)
            assert response == "Service selected"

    @pytest.mark.asyncio
    async def test_routes_greeting_to_non_booking_handler(
        self, mock_fsm, mock_llm, mock_state
    ):
        """Verify GREETING intent routes to NonBookingHandler."""
        intent = Intent(type=IntentType.GREETING, raw_message="Hola")

        with patch("agent.routing.non_booking_handler.NonBookingHandler") as MockHandler:
            mock_instance = MockHandler.return_value
            mock_instance.handle = AsyncMock(return_value="¡Hola! Soy Maite")

            response = await IntentRouter.route(intent, mock_fsm, mock_state, mock_llm)

            # Verify handler was instantiated with correct args (note different order)
            MockHandler.assert_called_once_with(mock_state, mock_llm, mock_fsm)
            mock_instance.handle.assert_called_once_with(intent)
            assert response == "¡Hola! Soy Maite"

    @pytest.mark.asyncio
    async def test_routes_faq_to_non_booking_handler(
        self, mock_fsm, mock_llm, mock_state
    ):
        """Verify FAQ intent routes to NonBookingHandler."""
        intent = Intent(
            type=IntentType.FAQ,
            raw_message="¿Cuál es el horario?",
            entities={"query": "horario"}
        )

        with patch("agent.routing.non_booking_handler.NonBookingHandler") as MockHandler:
            mock_instance = MockHandler.return_value
            mock_instance.handle = AsyncMock(return_value="Nuestro horario es...")

            response = await IntentRouter.route(intent, mock_fsm, mock_state, mock_llm)

            MockHandler.assert_called_once()
            mock_instance.handle.assert_called_once_with(intent)
            assert response == "Nuestro horario es..."

    @pytest.mark.asyncio
    async def test_routes_all_booking_intents_to_booking_handler(
        self, mock_fsm, mock_llm, mock_state
    ):
        """Verify all BOOKING_INTENTS route to BookingHandler."""
        for intent_type in IntentRouter.BOOKING_INTENTS:
            intent = Intent(type=intent_type, raw_message=f"Test {intent_type.value}")

            with patch("agent.routing.booking_handler.BookingHandler") as MockHandler:
                mock_instance = MockHandler.return_value
                mock_instance.handle = AsyncMock(return_value="Handler response")

                await IntentRouter.route(intent, mock_fsm, mock_state, mock_llm)

                # Verify BookingHandler was used
                MockHandler.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_all_non_booking_intents_to_non_booking_handler(
        self, mock_fsm, mock_llm, mock_state
    ):
        """Verify all NON_BOOKING_INTENTS route to NonBookingHandler."""
        for intent_type in IntentRouter.NON_BOOKING_INTENTS:
            intent = Intent(type=intent_type, raw_message=f"Test {intent_type.value}")

            with patch("agent.routing.non_booking_handler.NonBookingHandler") as MockHandler:
                mock_instance = MockHandler.return_value
                mock_instance.handle = AsyncMock(return_value="Handler response")

                await IntentRouter.route(intent, mock_fsm, mock_state, mock_llm)

                # Verify NonBookingHandler was used
                MockHandler.assert_called_once()

    @pytest.mark.asyncio
    async def test_routing_with_fsm_context(
        self, mock_llm, mock_state
    ):
        """Verify routing works with different FSM states."""
        # Test with FSM in SERVICE_SELECTION state
        fsm_service_selection = MagicMock()
        fsm_service_selection.state = BookingState.SERVICE_SELECTION
        fsm_service_selection.collected_data = {}

        intent = Intent(type=IntentType.SELECT_SERVICE, raw_message="Corte")

        with patch("agent.routing.booking_handler.BookingHandler") as MockHandler:
            mock_instance = MockHandler.return_value
            mock_instance.handle = AsyncMock(return_value="Service response")

            response = await IntentRouter.route(
                intent, fsm_service_selection, mock_state, mock_llm
            )

            # Verify FSM was passed to handler
            MockHandler.assert_called_once_with(
                fsm_service_selection, mock_state, mock_llm
            )
            assert response == "Service response"

    @pytest.mark.asyncio
    async def test_routing_preserves_intent_entities(
        self, mock_fsm, mock_llm, mock_state
    ):
        """Verify routing preserves intent entities through to handler."""
        intent = Intent(
            type=IntentType.SELECT_SERVICE,
            raw_message="Corte de señora y tinte",
            entities={"services": ["Corte de señora", "Tinte"]},
            confidence=0.95
        )

        with patch("agent.routing.booking_handler.BookingHandler") as MockHandler:
            mock_instance = MockHandler.return_value

            # Capture the intent passed to handle()
            called_intent = None
            async def capture_intent(intent_arg):
                nonlocal called_intent
                called_intent = intent_arg
                return "Response"

            mock_instance.handle = AsyncMock(side_effect=capture_intent)

            await IntentRouter.route(intent, mock_fsm, mock_state, mock_llm)

            # Verify intent was passed through unchanged
            assert called_intent is intent
            assert called_intent.entities == {"services": ["Corte de señora", "Tinte"]}
            assert called_intent.confidence == 0.95


# ==============================================================================
# FIXTURES
# ==============================================================================


@pytest.fixture
def mock_fsm():
    """Mock FSM instance."""
    fsm = MagicMock()
    fsm.state = BookingState.IDLE
    fsm.collected_data = {}
    return fsm


@pytest.fixture
def mock_llm():
    """Mock ChatOpenAI instance."""
    return MagicMock()


@pytest.fixture
def mock_state():
    """Mock ConversationState."""
    return {
        "conversation_id": "test-123",
        "messages": [],
        "fsm_state": None,
    }

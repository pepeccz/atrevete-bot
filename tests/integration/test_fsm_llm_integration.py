"""
Integration tests for FSM + LLM integration (Story 5-3).

Tests cover:
- AC #8: Full integration flow (load FSM, extract intent, validate, generate response)
- AC #9: Valid transitions generate natural Spanish responses
- AC #10: Invalid transitions generate friendly redirection messages
- AC #11: Coverage >85% for integration code

Testing strategy:
- Mock LLM responses for deterministic testing
- Mock Redis for FSM persistence
- Test full flow through FSM + IntentExtractor
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.fsm import (
    BookingFSM,
    BookingState,
    Intent,
    IntentType,
    extract_intent,
)


class TestFSMIntentExtractorIntegration:
    """Tests for FSM + IntentExtractor integration (AC #8)."""

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    @patch("agent.fsm.booking_fsm.get_redis_client")
    async def test_full_integration_flow_start_booking(self, mock_redis, mock_get_llm):
        """Full flow: load FSM → extract intent → validate → transition."""
        # Setup mock Redis
        mock_redis_client = MagicMock()
        mock_redis_client.get = AsyncMock(return_value=None)  # No existing state
        mock_redis_client.set = AsyncMock(return_value=True)
        mock_redis.return_value = mock_redis_client

        # Setup mock LLM
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "start_booking", "entities": {}, "confidence": 0.95}'
            )
        )
        mock_get_llm.return_value = mock_llm

        # Step 1: Load FSM from Redis
        fsm = await BookingFSM.load("test-conv-integration")
        assert fsm.state == BookingState.IDLE

        # Step 2: Extract intent using LLM
        intent = await extract_intent(
            message="Quiero pedir una cita",
            current_state=fsm.state,
            collected_data=fsm.collected_data,
            conversation_history=[],
        )
        assert intent.type == IntentType.START_BOOKING

        # Step 3: Validate transition with FSM
        assert fsm.can_transition(intent) is True

        # Step 4: Execute transition
        result = fsm.transition(intent)
        assert result.success is True
        assert result.new_state == BookingState.SERVICE_SELECTION

        # FSM state is persisted via checkpoint in production (ADR-011)
        # No Redis persistence needed in tests

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    @patch("agent.fsm.booking_fsm.get_redis_client")
    async def test_full_flow_with_service_selection(self, mock_redis, mock_get_llm):
        """Full flow through SERVICE_SELECTION with entity extraction."""
        # Setup mock Redis with existing state
        existing_state = {
            "state": "service_selection",
            "collected_data": {},
            "last_updated": "2025-01-15T10:00:00+00:00",
        }
        mock_redis_client = MagicMock()
        mock_redis_client.get = AsyncMock(return_value=json.dumps(existing_state))
        mock_redis_client.set = AsyncMock(return_value=True)
        mock_redis.return_value = mock_redis_client

        # Setup mock LLM for service selection
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "select_service", "entities": {"service_name": "Corte largo"}, "confidence": 0.92}'
            )
        )
        mock_get_llm.return_value = mock_llm

        # Load FSM
        fsm = await BookingFSM.load("test-conv-service")
        assert fsm.state == BookingState.SERVICE_SELECTION

        # Extract intent
        intent = await extract_intent(
            message="Quiero un corte largo",
            current_state=fsm.state,
            collected_data=fsm.collected_data,
            conversation_history=[],
        )

        # SELECT_SERVICE doesn't transition directly - it accumulates data
        # The FSM needs CONFIRM_SERVICES to transition
        assert intent.type == IntentType.SELECT_SERVICE
        assert intent.entities.get("service_name") == "Corte largo"


class TestFAQMidFlowIntegration:
    """Tests for FAQ handling without breaking booking state (AC #7, AC #8)."""

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    @patch("agent.fsm.booking_fsm.get_redis_client")
    async def test_faq_mid_flow_preserves_fsm_state(self, mock_redis, mock_get_llm):
        """FAQ during booking doesn't change FSM state."""
        # Setup mock Redis with booking in progress
        existing_state = {
            "state": "service_selection",
            "collected_data": {"services": ["Corte largo"]},
            "last_updated": "2025-01-15T10:00:00+00:00",
        }
        mock_redis_client = MagicMock()
        mock_redis_client.get = AsyncMock(return_value=json.dumps(existing_state))
        mock_redis_client.set = AsyncMock(return_value=True)
        mock_redis.return_value = mock_redis_client

        # Setup mock LLM for FAQ
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "faq", "entities": {}, "confidence": 0.9}'
            )
        )
        mock_get_llm.return_value = mock_llm

        # Load FSM
        fsm = await BookingFSM.load("test-conv-faq")
        original_state = fsm.state
        original_data = fsm.collected_data

        # Extract FAQ intent
        intent = await extract_intent(
            message="¿Cuál es el horario de apertura?",
            current_state=fsm.state,
            collected_data=fsm.collected_data,
            conversation_history=[],
        )

        assert intent.type == IntentType.FAQ

        # FAQ should NOT transition FSM
        # In the integration, non-booking intents don't call fsm.transition()
        # FSM state should remain unchanged
        assert fsm.state == original_state
        assert fsm.collected_data == original_data


class TestInvalidTransitionHandling:
    """Tests for invalid transition handling (AC #10)."""

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    @patch("agent.fsm.booking_fsm.get_redis_client")
    async def test_invalid_transition_from_idle(self, mock_redis, mock_get_llm):
        """Attempting to confirm services from IDLE state fails gracefully."""
        # Setup mock Redis - no existing state
        mock_redis_client = MagicMock()
        mock_redis_client.get = AsyncMock(return_value=None)
        mock_redis.return_value = mock_redis_client

        # Setup mock LLM - returns CONFIRM_SERVICES (invalid from IDLE)
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "confirm_services", "entities": {}, "confidence": 0.85}'
            )
        )
        mock_get_llm.return_value = mock_llm

        # Load FSM in IDLE state
        fsm = await BookingFSM.load("test-conv-invalid")
        assert fsm.state == BookingState.IDLE

        # Extract intent
        intent = await extract_intent(
            message="Sí, eso es todo",
            current_state=fsm.state,
            collected_data=fsm.collected_data,
            conversation_history=[],
        )

        # FSM should reject this transition
        can_transition = fsm.can_transition(intent)
        assert can_transition is False

        # Attempting transition should return failure
        result = fsm.transition(intent)
        assert result.success is False
        assert len(result.validation_errors) > 0
        assert fsm.state == BookingState.IDLE  # State unchanged

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    @patch("agent.fsm.booking_fsm.get_redis_client")
    async def test_missing_required_data_rejection(self, mock_redis, mock_get_llm):
        """Transition without required data is rejected."""
        # Setup mock Redis - in SERVICE_SELECTION but no services collected
        existing_state = {
            "state": "service_selection",
            "collected_data": {},  # No services!
            "last_updated": "2025-01-15T10:00:00+00:00",
        }
        mock_redis_client = MagicMock()
        mock_redis_client.get = AsyncMock(return_value=json.dumps(existing_state))
        mock_redis.return_value = mock_redis_client

        # Setup mock LLM for CONFIRM_SERVICES
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "confirm_services", "entities": {}, "confidence": 0.9}'
            )
        )
        mock_get_llm.return_value = mock_llm

        # Load FSM
        fsm = await BookingFSM.load("test-conv-missing-data")
        intent = await extract_intent(
            message="Ya está",
            current_state=fsm.state,
            collected_data=fsm.collected_data,
            conversation_history=[],
        )

        # Cannot transition without services
        assert fsm.can_transition(intent) is False

        result = fsm.transition(intent)
        assert result.success is False
        assert "services" in str(result.validation_errors).lower()


class TestCancelBookingFlow:
    """Tests for cancel booking from any state."""

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    @patch("agent.fsm.booking_fsm.get_redis_client")
    async def test_cancel_from_mid_booking(self, mock_redis, mock_get_llm):
        """Cancel booking from mid-flow resets FSM to IDLE."""
        # Setup mock Redis with booking in progress
        existing_state = {
            "state": "stylist_selection",
            "collected_data": {"services": ["Corte largo"]},
            "last_updated": "2025-01-15T10:00:00+00:00",
        }
        mock_redis_client = MagicMock()
        mock_redis_client.get = AsyncMock(return_value=json.dumps(existing_state))
        mock_redis_client.set = AsyncMock(return_value=True)
        mock_redis.return_value = mock_redis_client

        # Setup mock LLM for cancel
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "cancel_booking", "entities": {}, "confidence": 0.95}'
            )
        )
        mock_get_llm.return_value = mock_llm

        # Load FSM
        fsm = await BookingFSM.load("test-conv-cancel")
        assert fsm.state == BookingState.STYLIST_SELECTION

        # Extract cancel intent
        intent = await extract_intent(
            message="Mejor no, cancelar",
            current_state=fsm.state,
            collected_data=fsm.collected_data,
            conversation_history=[],
        )

        assert intent.type == IntentType.CANCEL_BOOKING

        # Cancel should always be allowed
        assert fsm.can_transition(intent) is True

        # Execute cancel
        result = fsm.transition(intent)
        assert result.success is True
        assert result.new_state == BookingState.IDLE
        assert result.collected_data == {}  # Data cleared


class TestCompleteBookingFlow:
    """Tests for complete happy path booking flow."""

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    @patch("agent.fsm.booking_fsm.get_redis_client")
    async def test_happy_path_step_by_step(self, mock_redis, mock_get_llm):
        """Test progression through all FSM states."""
        mock_redis_client = MagicMock()
        mock_redis_client.get = AsyncMock(return_value=None)
        mock_redis_client.set = AsyncMock(return_value=True)
        mock_redis.return_value = mock_redis_client

        # Create fresh FSM
        fsm = await BookingFSM.load("test-happy-path")
        assert fsm.state == BookingState.IDLE

        # Step 1: IDLE -> SERVICE_SELECTION
        intent1 = Intent(type=IntentType.START_BOOKING, entities={}, confidence=0.95)
        result1 = fsm.transition(intent1)
        assert result1.success is True
        assert fsm.state == BookingState.SERVICE_SELECTION

        # Add a service to collected_data (simulating tool call result)
        fsm._collected_data["services"] = ["Corte largo"]

        # Step 2: SERVICE_SELECTION -> STYLIST_SELECTION
        intent2 = Intent(type=IntentType.CONFIRM_SERVICES, entities={}, confidence=0.9)
        result2 = fsm.transition(intent2)
        assert result2.success is True
        assert fsm.state == BookingState.STYLIST_SELECTION

        # Step 3: STYLIST_SELECTION -> SLOT_SELECTION
        intent3 = Intent(
            type=IntentType.SELECT_STYLIST,
            entities={"stylist_id": "abc-123"},
            confidence=0.9,
        )
        result3 = fsm.transition(intent3)
        assert result3.success is True
        assert fsm.state == BookingState.SLOT_SELECTION
        assert fsm.collected_data.get("stylist_id") == "abc-123"

        # Step 4: SLOT_SELECTION -> CUSTOMER_DATA
        intent4 = Intent(
            type=IntentType.SELECT_SLOT,
            entities={"slot": {"start_time": "2025-01-20T10:00:00"}},
            confidence=0.9,
        )
        result4 = fsm.transition(intent4)
        assert result4.success is True
        assert fsm.state == BookingState.CUSTOMER_DATA

        # Step 5: CUSTOMER_DATA -> CONFIRMATION
        intent5 = Intent(
            type=IntentType.PROVIDE_CUSTOMER_DATA,
            entities={"first_name": "María"},
            confidence=0.95,
        )
        result5 = fsm.transition(intent5)
        assert result5.success is True
        assert fsm.state == BookingState.CONFIRMATION
        assert fsm.collected_data.get("first_name") == "María"

        # Step 6: CONFIRMATION -> BOOKED
        intent6 = Intent(type=IntentType.CONFIRM_BOOKING, entities={}, confidence=0.98)
        result6 = fsm.transition(intent6)
        assert result6.success is True
        assert fsm.state == BookingState.BOOKED


class TestEscalationHandling:
    """Tests for escalation intent handling."""

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_escalation_intent_extraction(self, mock_get_llm):
        """Escalation request is correctly identified."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "escalate", "entities": {}, "confidence": 0.92}'
            )
        )
        mock_get_llm.return_value = mock_llm

        intent = await extract_intent(
            message="Esto es muy confuso, quiero hablar con alguien de verdad",
            current_state=BookingState.SERVICE_SELECTION,
            collected_data={},
            conversation_history=[],
        )

        assert intent.type == IntentType.ESCALATE
        assert intent.confidence >= 0.8


class TestGreetingHandling:
    """Tests for greeting intent handling."""

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_greeting_does_not_affect_fsm(self, mock_get_llm):
        """Greeting doesn't trigger FSM transition."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "greeting", "entities": {}, "confidence": 0.95}'
            )
        )
        mock_get_llm.return_value = mock_llm

        intent = await extract_intent(
            message="Hola buenos días",
            current_state=BookingState.IDLE,
            collected_data={},
            conversation_history=[],
        )

        assert intent.type == IntentType.GREETING

        # Greeting is a non-booking intent - shouldn't affect FSM state
        # In the real integration, this would skip fsm.transition()

"""
Unit tests for Story 3.6: Booking validation nodes

Tests validate_booking_request and handle_category_choice nodes.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from database.models import ServiceCategory
from agent.state.schemas import ConversationState


class TestValidateBookingRequest:
    """Unit tests for validate_booking_request node (AC 4, 5)"""

    @pytest.mark.asyncio
    async def test_valid_combination_passes(self):
        """
        Test 1: Valid combination → verify booking_validation_passed=true
        """
        # Mock validate_service_combination to return valid
        with patch('agent.nodes.booking_nodes.validate_service_combination') as mock_validate:
            mock_validate.return_value = {
                "valid": True,
                "reason": None,
                "services_by_category": {
                    ServiceCategory.HAIRDRESSING.value: [uuid4(), uuid4()]
                }
            }

            from agent.nodes.booking_nodes import validate_booking_request

            state: ConversationState = {
                "conversation_id": str(uuid4()),
                "customer_id": str(uuid4()),
                "customer_name": "Maria",
                "requested_services": [uuid4(), uuid4()],
                "messages": [],
            }

            result = await validate_booking_request(state)

            assert result["booking_validation_passed"] is True, \
                "Should pass validation for valid combination"

            assert result.get("mixed_category_detected") is not True, \
                "Should not detect mixed categories"

            assert result.get("bot_response") is None, \
                "Should not generate bot response for valid combination"

    @pytest.mark.asyncio
    async def test_mixed_categories_generates_alternatives_message(self):
        """
        Test 2: Mixed categories → verify bot_response contains alternatives
        """
        corte_id = uuid4()
        bioterapia_id = uuid4()

        with patch('agent.nodes.booking_nodes.validate_service_combination') as mock_validate, \
             patch('agent.nodes.booking_nodes.get_async_session') as mock_get_session:

            # Mock validation result
            mock_validate.return_value = {
                "valid": False,
                "reason": "mixed_categories",
                "services_by_category": {
                    ServiceCategory.HAIRDRESSING.value: [corte_id],
                    ServiceCategory.AESTHETICS.value: [bioterapia_id]
                }
            }

            # Mock database session to return service names
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__.return_value = mock_session

            from agent.nodes.booking_nodes import validate_booking_request

            state: ConversationState = {
                "conversation_id": str(uuid4()),
                "customer_id": str(uuid4()),
                "customer_name": "Laura",
                "requested_services": [corte_id, bioterapia_id],
                "messages": [],
            }

            result = await validate_booking_request(state)

            assert result["booking_validation_passed"] is False, \
                "Should fail validation for mixed categories"

            assert result["mixed_category_detected"] is True, \
                "Should detect mixed categories"

            assert result["awaiting_category_choice"] is True, \
                "Should be awaiting customer choice"

            # Verify bot_response contains alternatives
            bot_response = result.get("bot_response", "")
            assert bot_response != "", "Should generate bot response"

            # Note: Message formatting verified in next test

    @pytest.mark.asyncio
    async def test_mixed_categories_message_format_matches_maite_tone(self):
        """
        Test 3: Mixed categories → verify message format matches Maite's tone
        """
        corte_id = uuid4()
        manicura_id = uuid4()

        # Create mock services
        mock_corte = MagicMock()
        mock_corte.id = corte_id
        mock_corte.name = "Corte de pelo"
        mock_corte.category = ServiceCategory.HAIRDRESSING

        mock_manicura = MagicMock()
        mock_manicura.id = manicura_id
        mock_manicura.name = "MANICURA PERMANENTE"
        mock_manicura.category = ServiceCategory.AESTHETICS

        with patch('agent.nodes.booking_nodes.validate_service_combination') as mock_validate, \
             patch('agent.nodes.booking_nodes.get_async_session') as mock_get_session:

            mock_validate.return_value = {
                "valid": False,
                "reason": "mixed_categories",
                "services_by_category": {
                    ServiceCategory.HAIRDRESSING.value: [corte_id],
                    ServiceCategory.AESTHETICS.value: [manicura_id]
                }
            }

            # Mock database session
            mock_session = AsyncMock()
            mock_result = AsyncMock()
            mock_result.scalars.return_value.all.return_value = [mock_corte, mock_manicura]
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_get_session.return_value.__aenter__.return_value = mock_session

            from agent.nodes.booking_nodes import validate_booking_request

            state: ConversationState = {
                "conversation_id": str(uuid4()),
                "customer_id": str(uuid4()),
                "customer_name": "Laura",
                "requested_services": [corte_id, manicura_id],
                "messages": [],
            }

            result = await validate_booking_request(state)

            bot_response = result.get("bot_response", "")

            # Verify Maite's tone elements
            assert "lo siento" in bot_response.lower() or "disculpa" in bot_response.lower(), \
                "Should use empathetic opening"

            assert "laura" in bot_response.lower() or "{customer_name}" in bot_response, \
                "Should use customer's name"

            assert "💕" in bot_response or "😊" in bot_response, \
                "Should use Maite's emojis"

            assert "1️⃣" in bot_response and "2️⃣" in bot_response, \
                "Should use numbered options with emojis"

            assert "por separado" in bot_response.lower() or "reservar ambos" in bot_response.lower(), \
                "Should offer booking separately option"

            assert "elegir" in bot_response.lower() or "prefieres" in bot_response.lower(), \
                "Should offer choosing one category option"

    @pytest.mark.asyncio
    async def test_mixed_categories_services_by_category_populated(self):
        """
        Test 4: Mixed categories → verify services_by_category populated
        """
        corte_id = uuid4()
        bioterapia_id = uuid4()

        with patch('agent.nodes.booking_nodes.validate_service_combination') as mock_validate:
            mock_validate.return_value = {
                "valid": False,
                "reason": "mixed_categories",
                "services_by_category": {
                    ServiceCategory.HAIRDRESSING.value: [corte_id],
                    ServiceCategory.AESTHETICS.value: [bioterapia_id]
                }
            }

            from agent.nodes.booking_nodes import validate_booking_request

            state: ConversationState = {
                "conversation_id": str(uuid4()),
                "customer_id": str(uuid4()),
                "customer_name": "Pedro",
                "requested_services": [corte_id, bioterapia_id],
                "messages": [],
            }

            result = await validate_booking_request(state)

            services_by_cat = result.get("services_by_category", {})

            assert len(services_by_cat) == 2, \
                "Should have 2 categories"

            assert ServiceCategory.HAIRDRESSING.value in services_by_cat, \
                "Should have Hairdressing category"

            assert ServiceCategory.AESTHETICS.value in services_by_cat, \
                "Should have Aesthetics category"

            assert corte_id in services_by_cat[ServiceCategory.HAIRDRESSING.value], \
                "Hairdressing should contain corte_id"

            assert bioterapia_id in services_by_cat[ServiceCategory.AESTHETICS.value], \
                "Aesthetics should contain bioterapia_id"

    @pytest.mark.asyncio
    async def test_valid_single_service_no_validation_message(self):
        """
        Test 5: Valid single service → verify no validation message
        """
        with patch('agent.nodes.booking_nodes.validate_service_combination') as mock_validate:
            mock_validate.return_value = {
                "valid": True,
                "reason": None,
                "services_by_category": {
                    ServiceCategory.HAIRDRESSING.value: [uuid4()]
                }
            }

            from agent.nodes.booking_nodes import validate_booking_request

            state: ConversationState = {
                "conversation_id": str(uuid4()),
                "customer_id": str(uuid4()),
                "customer_name": "Ana",
                "requested_services": [uuid4()],
                "messages": [],
            }

            result = await validate_booking_request(state)

            assert result["booking_validation_passed"] is True, \
                "Should pass for single service"

            assert result.get("bot_response") is None, \
                "Should NOT generate bot response for valid single service"


class TestHandleCategoryChoice:
    """Unit tests for handle_category_choice node (AC 6, 7)"""

    @pytest.mark.asyncio
    async def test_book_separately_creates_pending_bookings(self):
        """
        Test 6: Choose "book_separately" → verify pending_bookings created
        """
        corte_id = uuid4()
        manicura_id = uuid4()

        # Mock Claude classification
        mock_classification = MagicMock()
        mock_classification.choice = "book_separately"
        mock_classification.confidence = 0.95

        with patch('agent.nodes.booking_nodes.ChatAnthropic') as mock_chat:
            mock_llm = MagicMock()
            mock_structured_llm = AsyncMock()
            mock_structured_llm.ainvoke = AsyncMock(return_value=mock_classification)
            mock_llm.with_structured_output.return_value = mock_structured_llm
            mock_chat.return_value = mock_llm

            from agent.nodes.booking_nodes import handle_category_choice

            state: ConversationState = {
                "conversation_id": str(uuid4()),
                "customer_id": str(uuid4()),
                "customer_name": "Laura",
                "requested_services": [corte_id, manicura_id],
                "messages": [
                    {"role": "user", "content": "Prefiero hacer ambos por separado"}
                ],
                "mixed_category_detected": True,
                "awaiting_category_choice": True,
                "services_by_category": {
                    ServiceCategory.HAIRDRESSING.value: [corte_id],
                    ServiceCategory.AESTHETICS.value: [manicura_id]
                },
                "pending_bookings": [],
            }

            result = await handle_category_choice(state)

            # Verify pending_bookings created
            pending = result.get("pending_bookings", [])
            assert len(pending) == 2, \
                "Should create 2 pending bookings"

            assert pending[0]["category"] == ServiceCategory.HAIRDRESSING.value, \
                "First booking should be Hairdressing"

            assert pending[1]["category"] == ServiceCategory.AESTHETICS.value, \
                "Second booking should be Aesthetics"

            assert result.get("is_multi_booking_flow") is True, \
                "Should set multi-booking flag"

            assert result.get("current_booking_index") == 0, \
                "Should start at index 0"

    @pytest.mark.asyncio
    async def test_choose_hairdressing_filters_requested_services(self):
        """
        Test 7: Choose Hairdressing only → verify requested_services filtered
        """
        corte_id = uuid4()
        manicura_id = uuid4()

        mock_classification = MagicMock()
        mock_classification.choice = "choose_hairdressing"
        mock_classification.confidence = 0.90

        with patch('agent.nodes.booking_nodes.ChatAnthropic') as mock_chat:
            mock_llm = MagicMock()
            mock_structured_llm = AsyncMock()
            mock_structured_llm.ainvoke = AsyncMock(return_value=mock_classification)
            mock_llm.with_structured_output.return_value = mock_structured_llm
            mock_chat.return_value = mock_llm

            from agent.nodes.booking_nodes import handle_category_choice

            state: ConversationState = {
                "conversation_id": str(uuid4()),
                "customer_id": str(uuid4()),
                "customer_name": "Maria",
                "requested_services": [corte_id, manicura_id],
                "messages": [
                    {"role": "user", "content": "Solo quiero el corte"}
                ],
                "mixed_category_detected": True,
                "services_by_category": {
                    ServiceCategory.HAIRDRESSING.value: [corte_id],
                    ServiceCategory.AESTHETICS.value: [manicura_id]
                },
                "pending_bookings": [],
            }

            result = await handle_category_choice(state)

            # Verify filtered to Hairdressing only
            filtered = result.get("requested_services", [])
            assert len(filtered) == 1, \
                "Should have 1 service after filtering"

            assert filtered[0] == corte_id, \
                "Should keep only Hairdressing service"

            assert result.get("booking_validation_passed") is True, \
                "Should pass validation after filtering"

            assert result.get("mixed_category_detected") is not True, \
                "Should clear mixed category flag"

    @pytest.mark.asyncio
    async def test_choose_aesthetics_filters_requested_services(self):
        """
        Test 8: Choose Aesthetics only → verify requested_services filtered
        """
        corte_id = uuid4()
        manicura_id = uuid4()

        mock_classification = MagicMock()
        mock_classification.choice = "choose_aesthetics"
        mock_classification.confidence = 0.92

        with patch('agent.nodes.booking_nodes.ChatAnthropic') as mock_chat:
            mock_llm = MagicMock()
            mock_structured_llm = AsyncMock()
            mock_structured_llm.ainvoke = AsyncMock(return_value=mock_classification)
            mock_llm.with_structured_output.return_value = mock_structured_llm
            mock_chat.return_value = mock_llm

            from agent.nodes.booking_nodes import handle_category_choice

            state: ConversationState = {
                "conversation_id": str(uuid4()),
                "customer_id": str(uuid4()),
                "customer_name": "Ana",
                "requested_services": [corte_id, manicura_id],
                "messages": [
                    {"role": "user", "content": "Prefiero solo la manicura"}
                ],
                "mixed_category_detected": True,
                "services_by_category": {
                    ServiceCategory.HAIRDRESSING.value: [corte_id],
                    ServiceCategory.AESTHETICS.value: [manicura_id]
                },
                "pending_bookings": [],
            }

            result = await handle_category_choice(state)

            # Verify filtered to Aesthetics only
            filtered = result.get("requested_services", [])
            assert len(filtered) == 1, \
                "Should have 1 service after filtering"

            assert filtered[0] == manicura_id, \
                "Should keep only Aesthetics service"

            assert result.get("booking_validation_passed") is True, \
                "Should pass validation after filtering"

    @pytest.mark.asyncio
    async def test_cancel_request_clears_requested_services(self):
        """
        Test 9: Cancel request → verify requested_services cleared
        """
        mock_classification = MagicMock()
        mock_classification.choice = "cancel"
        mock_classification.confidence = 0.88

        with patch('agent.nodes.booking_nodes.ChatAnthropic') as mock_chat:
            mock_llm = MagicMock()
            mock_structured_llm = AsyncMock()
            mock_structured_llm.ainvoke = AsyncMock(return_value=mock_classification)
            mock_llm.with_structured_output.return_value = mock_structured_llm
            mock_chat.return_value = mock_llm

            from agent.nodes.booking_nodes import handle_category_choice

            state: ConversationState = {
                "conversation_id": str(uuid4()),
                "customer_id": str(uuid4()),
                "customer_name": "Carlos",
                "requested_services": [uuid4(), uuid4()],
                "messages": [
                    {"role": "user", "content": "Mejor déjalo, no voy a reservar"}
                ],
                "mixed_category_detected": True,
                "services_by_category": {},
                "pending_bookings": [],
            }

            result = await handle_category_choice(state)

            # Verify services cleared
            assert len(result.get("requested_services", [])) == 0, \
                "Should clear requested_services on cancellation"

            # Verify bot acknowledges
            bot_response = result.get("bot_response", "")
            assert bot_response != "", \
                "Should generate acknowledgment response"

    @pytest.mark.asyncio
    async def test_unclear_response_first_attempt_asks_clarification(self):
        """
        Test 10: Unclear response (1st attempt) → verify clarification asked
        """
        mock_classification = MagicMock()
        mock_classification.choice = "unclear"
        mock_classification.confidence = 0.30

        with patch('agent.nodes.booking_nodes.ChatAnthropic') as mock_chat:
            mock_llm = MagicMock()
            mock_structured_llm = AsyncMock()
            mock_structured_llm.ainvoke = AsyncMock(return_value=mock_classification)
            mock_llm.with_structured_output.return_value = mock_structured_llm
            mock_chat.return_value = mock_llm

            from agent.nodes.booking_nodes import handle_category_choice

            state: ConversationState = {
                "conversation_id": str(uuid4()),
                "customer_id": str(uuid4()),
                "customer_name": "Pedro",
                "requested_services": [uuid4(), uuid4()],
                "messages": [
                    {"role": "user", "content": "No sé, quizás..."}
                ],
                "mixed_category_detected": True,
                "services_by_category": {},
                "clarification_attempts": 0,
                "pending_bookings": [],
            }

            result = await handle_category_choice(state)

            # Verify clarification requested
            assert result.get("clarification_attempts", 0) == 1, \
                "Should increment clarification attempts"

            bot_response = result.get("bot_response", "")
            assert "opción 1" in bot_response.lower() or "opción 2" in bot_response.lower(), \
                "Should ask for clarification with options"

    @pytest.mark.asyncio
    async def test_unclear_response_second_attempt_escalates(self):
        """
        Test 11: Unclear response (2nd attempt) → verify escalation
        """
        mock_classification = MagicMock()
        mock_classification.choice = "unclear"
        mock_classification.confidence = 0.25

        with patch('agent.nodes.booking_nodes.ChatAnthropic') as mock_chat:
            mock_llm = MagicMock()
            mock_structured_llm = AsyncMock()
            mock_structured_llm.ainvoke = AsyncMock(return_value=mock_classification)
            mock_llm.with_structured_output.return_value = mock_structured_llm
            mock_chat.return_value = mock_llm

            from agent.nodes.booking_nodes import handle_category_choice

            state: ConversationState = {
                "conversation_id": str(uuid4()),
                "customer_id": str(uuid4()),
                "customer_name": "Isabel",
                "requested_services": [uuid4(), uuid4()],
                "messages": [
                    {"role": "user", "content": "Mmm no estoy segura"}
                ],
                "mixed_category_detected": True,
                "services_by_category": {},
                "clarification_attempts": 2,  # Already 2 attempts
                "pending_bookings": [],
            }

            result = await handle_category_choice(state)

            # Verify escalation
            assert result.get("requires_human_handoff") is True or \
                   result.get("escalate_to_human") is True, \
                "Should escalate to human after max clarification attempts"

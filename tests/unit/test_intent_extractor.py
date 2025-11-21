"""
Unit tests for IntentExtractor - LLM-based intent extraction for FSM hybrid architecture.

Tests cover:
- AC #1: extract_intent() function exists and returns Intent object
- AC #2: START_BOOKING intent extraction with confidence >= 0.8
- AC #3: SELECT_SERVICE intent with entities (service_name, selection_number)
- AC #4: State-aware disambiguation (same message, different states)
- AC #5: Fallback to UNKNOWN on LLM error
- AC #6: Prompt includes FSM context
- AC #7: FAQ intent doesn't break booking state

Testing strategy:
- Mock LLM responses for deterministic testing
- Use patch on ChatOpenAI to control LLM output
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.fsm import (
    BookingState,
    Intent,
    IntentType,
    extract_intent,
)
from agent.fsm.intent_extractor import (
    _build_extraction_prompt,
    _build_state_context,
    _parse_llm_response,
)


class TestExtractIntentFunction:
    """Tests for extract_intent() function existence and basic behavior (AC #1)."""

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_extract_intent_returns_intent_object(self, mock_get_llm):
        """extract_intent() returns an Intent object."""
        # Mock LLM response
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "start_booking", "entities": {}, "confidence": 0.95}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="Quiero una cita",
            current_state=BookingState.IDLE,
            collected_data={},
            conversation_history=[],
        )

        assert isinstance(result, Intent)
        assert hasattr(result, "type")
        assert hasattr(result, "entities")
        assert hasattr(result, "confidence")
        assert hasattr(result, "raw_message")

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_extract_intent_preserves_raw_message(self, mock_get_llm):
        """extract_intent() preserves the original message in raw_message."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "greeting", "entities": {}, "confidence": 0.9}'
            )
        )
        mock_get_llm.return_value = mock_llm

        original_message = "Hola buenos días"
        result = await extract_intent(
            message=original_message,
            current_state=BookingState.IDLE,
            collected_data={},
            conversation_history=[],
        )

        assert result.raw_message == original_message


class TestStartBookingIntent:
    """Tests for START_BOOKING intent extraction (AC #2)."""

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_extract_start_booking_intent(self, mock_get_llm):
        """Message 'Quiero pedir cita' returns START_BOOKING with confidence >= 0.8."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "start_booking", "entities": {}, "confidence": 0.95}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="Quiero pedir cita",
            current_state=BookingState.IDLE,
            collected_data={},
            conversation_history=[],
        )

        assert result.type == IntentType.START_BOOKING
        assert result.confidence >= 0.8

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_extract_booking_intent_variations(self, mock_get_llm):
        """Various booking intent phrases are recognized."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "start_booking", "entities": {}, "confidence": 0.92}'
            )
        )
        mock_get_llm.return_value = mock_llm

        phrases = [
            "Necesito reservar",
            "Quiero agendar una cita",
            "Me gustaría pedir turno",
        ]

        for phrase in phrases:
            result = await extract_intent(
                message=phrase,
                current_state=BookingState.IDLE,
                collected_data={},
                conversation_history=[],
            )
            assert result.type == IntentType.START_BOOKING


class TestSelectServiceIntent:
    """Tests for SELECT_SERVICE intent extraction (AC #3)."""

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_extract_select_service_by_name(self, mock_get_llm):
        """Message 'Corte largo' returns SELECT_SERVICE with service_name entity."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "select_service", "entities": {"service_name": "Corte largo"}, "confidence": 0.9}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="Corte largo",
            current_state=BookingState.SERVICE_SELECTION,
            collected_data={},
            conversation_history=[],
        )

        assert result.type == IntentType.SELECT_SERVICE
        assert result.entities.get("service_name") == "Corte largo"

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_extract_select_service_by_number(self, mock_get_llm):
        """Message '1' in SERVICE_SELECTION returns SELECT_SERVICE with selection_number."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "select_service", "entities": {"selection_number": 1}, "confidence": 0.95}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="1",
            current_state=BookingState.SERVICE_SELECTION,
            collected_data={},
            conversation_history=[],
        )

        assert result.type == IntentType.SELECT_SERVICE
        assert result.entities.get("selection_number") == 1


class TestStateAwareDisambiguation:
    """Tests for state-aware disambiguation (AC #4)."""

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_number_1_in_service_selection(self, mock_get_llm):
        """'1' in SERVICE_SELECTION means select service."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "select_service", "entities": {"selection_number": 1}, "confidence": 0.9}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="1",
            current_state=BookingState.SERVICE_SELECTION,
            collected_data={},
            conversation_history=[],
        )

        assert result.type == IntentType.SELECT_SERVICE

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_number_1_in_stylist_selection(self, mock_get_llm):
        """'1' in STYLIST_SELECTION means select stylist."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "select_stylist", "entities": {"selection_number": 1}, "confidence": 0.9}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="1",
            current_state=BookingState.STYLIST_SELECTION,
            collected_data={"services": ["Corte largo"]},
            conversation_history=[],
        )

        assert result.type == IntentType.SELECT_STYLIST

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_number_1_in_slot_selection(self, mock_get_llm):
        """'1' in SLOT_SELECTION means select slot."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "select_slot", "entities": {"selection_number": 1}, "confidence": 0.9}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="1",
            current_state=BookingState.SLOT_SELECTION,
            collected_data={"services": ["Corte largo"], "stylist_id": "abc-123"},
            conversation_history=[],
        )

        assert result.type == IntentType.SELECT_SLOT


class TestErrorFallback:
    """Tests for error handling and fallback to UNKNOWN (AC #5)."""

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_fallback_on_llm_exception(self, mock_get_llm):
        """LLM exception returns Intent with type=UNKNOWN and confidence=0.0."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("API timeout"))
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="Quiero una cita",
            current_state=BookingState.IDLE,
            collected_data={},
            conversation_history=[],
        )

        assert result.type == IntentType.UNKNOWN
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_fallback_on_invalid_json(self, mock_get_llm):
        """Invalid JSON response returns UNKNOWN."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="This is not valid JSON")
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="Quiero una cita",
            current_state=BookingState.IDLE,
            collected_data={},
            conversation_history=[],
        )

        assert result.type == IntentType.UNKNOWN
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_fallback_on_low_confidence(self, mock_get_llm):
        """Low confidence (< 0.7) returns UNKNOWN."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "start_booking", "entities": {}, "confidence": 0.5}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="algo raro",
            current_state=BookingState.IDLE,
            collected_data={},
            conversation_history=[],
        )

        assert result.type == IntentType.UNKNOWN
        assert result.confidence == 0.5  # Preserves the low confidence value


class TestPromptContext:
    """Tests for prompt structure and context inclusion (AC #6)."""

    def test_build_state_context_includes_current_state(self):
        """State context includes current FSM state."""
        context = _build_state_context(
            current_state=BookingState.SERVICE_SELECTION,
            collected_data={},
        )

        assert "SERVICE_SELECTION" in context or "service_selection" in context

    def test_build_state_context_includes_collected_data(self):
        """State context includes collected data."""
        context = _build_state_context(
            current_state=BookingState.STYLIST_SELECTION,
            collected_data={"services": ["Corte largo", "Tinte"]},
        )

        assert "Corte largo" in context or "Servicios seleccionados" in context

    def test_build_state_context_includes_valid_intents(self):
        """State context includes valid intents for the state."""
        context = _build_state_context(
            current_state=BookingState.SERVICE_SELECTION,
            collected_data={},
        )

        assert "select_service" in context or "SELECT_SERVICE" in context

    def test_build_extraction_prompt_includes_message(self):
        """Extraction prompt includes the user message."""
        prompt = _build_extraction_prompt(
            message="Quiero corte",
            current_state=BookingState.SERVICE_SELECTION,
            collected_data={},
            conversation_history=[],
        )

        assert "Quiero corte" in prompt

    def test_build_extraction_prompt_requests_json_output(self):
        """Extraction prompt requests JSON output format."""
        prompt = _build_extraction_prompt(
            message="Hola",
            current_state=BookingState.IDLE,
            collected_data={},
            conversation_history=[],
        )

        assert "JSON" in prompt or "json" in prompt


class TestFAQIntentHandling:
    """Tests for FAQ intent handling mid-booking (AC #7)."""

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_faq_intent_mid_booking(self, mock_get_llm):
        """FAQ intent during booking returns FAQ without breaking state."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "faq", "entities": {}, "confidence": 0.92}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="¿Cuál es el horario de apertura?",
            current_state=BookingState.SERVICE_SELECTION,
            collected_data={"services": ["Corte largo"]},
            conversation_history=[],
        )

        assert result.type == IntentType.FAQ
        assert result.confidence >= 0.8

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_greeting_intent(self, mock_get_llm):
        """Greeting messages are recognized as GREETING intent."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "greeting", "entities": {}, "confidence": 0.95}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="Hola, buenos días",
            current_state=BookingState.IDLE,
            collected_data={},
            conversation_history=[],
        )

        assert result.type == IntentType.GREETING

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_escalate_intent(self, mock_get_llm):
        """Request to speak with human recognized as ESCALATE."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "escalate", "entities": {}, "confidence": 0.9}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="Quiero hablar con una persona real",
            current_state=BookingState.SERVICE_SELECTION,
            collected_data={},
            conversation_history=[],
        )

        assert result.type == IntentType.ESCALATE


class TestEntityExtraction:
    """Tests for entity extraction from intents."""

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_extract_customer_data_entities(self, mock_get_llm):
        """PROVIDE_CUSTOMER_DATA extracts first_name and last_name."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "provide_customer_data", "entities": {"first_name": "María", "last_name": "García"}, "confidence": 0.95}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="Me llamo María García",
            current_state=BookingState.CUSTOMER_DATA,
            collected_data={
                "services": ["Corte largo"],
                "stylist_id": "abc-123",
                "slot": {"start_time": "2025-01-15T10:00:00"},
            },
            conversation_history=[],
        )

        assert result.type == IntentType.PROVIDE_CUSTOMER_DATA
        assert result.entities.get("first_name") == "María"
        assert result.entities.get("last_name") == "García"

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_extract_stylist_selection(self, mock_get_llm):
        """SELECT_STYLIST extracts stylist identifier."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "select_stylist", "entities": {"selection_number": 2}, "confidence": 0.9}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="La segunda opción",
            current_state=BookingState.STYLIST_SELECTION,
            collected_data={"services": ["Corte largo"]},
            conversation_history=[],
        )

        assert result.type == IntentType.SELECT_STYLIST
        assert result.entities.get("selection_number") == 2


class TestParseLLMResponse:
    """Tests for _parse_llm_response helper function."""

    def test_parse_valid_json(self):
        """Valid JSON is parsed correctly."""
        response = '{"intent_type": "start_booking", "entities": {}, "confidence": 0.95}'
        result = _parse_llm_response(response, "Quiero cita")

        assert result.type == IntentType.START_BOOKING
        assert result.confidence == 0.95

    def test_parse_json_with_markdown_fence(self):
        """JSON with markdown code fence is parsed correctly."""
        response = '```json\n{"intent_type": "greeting", "entities": {}, "confidence": 0.9}\n```'
        result = _parse_llm_response(response, "Hola")

        assert result.type == IntentType.GREETING

    def test_parse_unknown_intent_type(self):
        """Unknown intent type falls back to UNKNOWN."""
        response = '{"intent_type": "invalid_type", "entities": {}, "confidence": 0.9}'
        result = _parse_llm_response(response, "test")

        assert result.type == IntentType.UNKNOWN

    def test_parse_invalid_json_returns_unknown(self):
        """Invalid JSON returns UNKNOWN intent."""
        response = "not valid json at all"
        result = _parse_llm_response(response, "test")

        assert result.type == IntentType.UNKNOWN
        assert result.confidence == 0.0

    def test_parse_removes_null_entities(self):
        """Null entities are filtered out."""
        response = '{"intent_type": "select_service", "entities": {"service_name": "Corte", "selection_number": null}, "confidence": 0.9}'
        result = _parse_llm_response(response, "Corte")

        assert result.entities.get("service_name") == "Corte"
        assert "selection_number" not in result.entities


class TestConfirmationIntents:
    """Tests for booking confirmation/cancellation intents."""

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_confirm_booking_intent(self, mock_get_llm):
        """Affirmative response in CONFIRMATION state returns CONFIRM_BOOKING."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "confirm_booking", "entities": {}, "confidence": 0.98}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="Sí, confirmo la reserva",
            current_state=BookingState.CONFIRMATION,
            collected_data={
                "services": ["Corte largo"],
                "stylist_id": "abc-123",
                "slot": {"start_time": "2025-01-15T10:00:00"},
                "first_name": "María",
            },
            conversation_history=[],
        )

        assert result.type == IntentType.CONFIRM_BOOKING

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_cancel_booking_intent(self, mock_get_llm):
        """Cancel request returns CANCEL_BOOKING."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "cancel_booking", "entities": {}, "confidence": 0.9}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="No, mejor cancelo",
            current_state=BookingState.CONFIRMATION,
            collected_data={"services": ["Corte largo"]},
            conversation_history=[],
        )

        assert result.type == IntentType.CANCEL_BOOKING


class TestConfirmServicesIntent:
    """Tests for CONFIRM_SERVICES intent (user done selecting services)."""

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_confirm_services_intent(self, mock_get_llm):
        """'Eso es todo' in SERVICE_SELECTION returns CONFIRM_SERVICES."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "confirm_services", "entities": {}, "confidence": 0.95}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="Eso es todo, no necesito más",
            current_state=BookingState.SERVICE_SELECTION,
            collected_data={"services": ["Corte largo"]},
            conversation_history=[],
        )

        assert result.type == IntentType.CONFIRM_SERVICES

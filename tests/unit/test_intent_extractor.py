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
    INTENT_SYNONYMS,
    _build_extraction_prompt,
    _build_state_context,
    _normalize_start_time_timezone,
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
        """Message 'Corte largo' returns SELECT_SERVICE with services list (converted from service_name)."""
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
        # service_name is now converted to services list for FSM compatibility
        assert result.entities.get("services") == ["Corte largo"]

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

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_extract_notes_with_content(self, mock_get_llm):
        """PROVIDE_CUSTOMER_DATA extracts notes when user provides preferences."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "provide_customer_data", "entities": {"notes": "Quiero rubio"}, "confidence": 0.95}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="Quiero rubio",
            current_state=BookingState.CUSTOMER_DATA,
            collected_data={
                "services": ["Tinte"],
                "stylist_id": "abc-123",
                "slot": {"start_time": "2025-01-15T10:00:00"},
                "first_name": "María",  # Name already collected
            },
            conversation_history=[],
        )

        assert result.type == IntentType.PROVIDE_CUSTOMER_DATA
        # notes_asked is now managed internally by FSM, not extracted
        assert result.entities.get("notes") == "Quiero rubio"

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_extract_empty_entities_when_no_notes(self, mock_get_llm):
        """PROVIDE_CUSTOMER_DATA can have empty entities when user says 'no' to notes."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "provide_customer_data", "entities": {}, "confidence": 0.95}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="No, ninguna",
            current_state=BookingState.CUSTOMER_DATA,
            collected_data={
                "services": ["Corte"],
                "stylist_id": "abc-123",
                "slot": {"start_time": "2025-01-15T10:00:00"},
                "first_name": "María",  # Name already collected
            },
            conversation_history=[],
        )

        assert result.type == IntentType.PROVIDE_CUSTOMER_DATA
        # FSM handles notes_asked flag internally, extractor just returns empty entities
        assert result.entities.get("notes") is None


class TestParseLLMResponse:
    """Tests for _parse_llm_response helper function (async)."""

    @pytest.mark.asyncio
    async def test_parse_valid_json(self):
        """Valid JSON is parsed correctly."""
        response = '{"intent_type": "start_booking", "entities": {}, "confidence": 0.95}'
        result = await _parse_llm_response(response, "Quiero cita")

        assert result.type == IntentType.START_BOOKING
        assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_parse_json_with_markdown_fence(self):
        """JSON with markdown code fence is parsed correctly."""
        response = '```json\n{"intent_type": "greeting", "entities": {}, "confidence": 0.9}\n```'
        result = await _parse_llm_response(response, "Hola")

        assert result.type == IntentType.GREETING

    @pytest.mark.asyncio
    async def test_parse_unknown_intent_type(self):
        """Unknown intent type falls back to UNKNOWN."""
        response = '{"intent_type": "invalid_type", "entities": {}, "confidence": 0.9}'
        result = await _parse_llm_response(response, "test")

        assert result.type == IntentType.UNKNOWN

    @pytest.mark.asyncio
    async def test_parse_invalid_json_returns_unknown(self):
        """Invalid JSON returns UNKNOWN intent."""
        response = "not valid json at all"
        result = await _parse_llm_response(response, "test")

        assert result.type == IntentType.UNKNOWN
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_parse_removes_null_entities(self):
        """Null entities are filtered out and service_name converted to services."""
        response = '{"intent_type": "select_service", "entities": {"service_name": "Corte", "selection_number": null}, "confidence": 0.9}'
        result = await _parse_llm_response(response, "Corte")

        # service_name is converted to services list for FSM compatibility
        assert result.entities.get("services") == ["Corte"]
        assert "selection_number" not in result.entities
        assert "service_name" not in result.entities  # Removed after conversion

    @pytest.mark.asyncio
    async def test_parse_removes_empty_string_entities(self):
        """Empty string entities are filtered out."""
        response = '{"intent_type": "select_service", "entities": {"service_name": "", "stylist_name": ""}, "confidence": 0.9}'
        result = await _parse_llm_response(response, "test")

        # Empty strings should be filtered
        assert "service_name" not in result.entities
        assert "stylist_name" not in result.entities
        # services list should not be created from empty service_name
        assert "services" not in result.entities

    @pytest.mark.asyncio
    async def test_parse_skips_empty_service_name_conversion(self):
        """Empty service_name is not converted to services list."""
        response = '{"intent_type": "select_service", "entities": {"service_name": "  ", "selection_number": 1}, "confidence": 0.9}'
        result = await _parse_llm_response(response, "1")

        # Empty/whitespace service_name should not create services list
        assert "services" not in result.entities
        # But selection_number should be kept
        assert result.entities.get("selection_number") == 1

    @pytest.mark.asyncio
    async def test_parse_start_time_creates_slot_with_zero_duration(self):
        """start_time is converted to slot with duration_minutes=0 (calculated by FSM)."""
        response = '{"intent_type": "select_slot", "entities": {"start_time": "2025-11-25T10:00:00"}, "confidence": 0.95}'
        result = await _parse_llm_response(response, "las 10")

        # start_time should be converted to slot dict
        assert "slot" in result.entities
        # start_time should be normalized with timezone
        assert result.entities["slot"]["start_time"] == "2025-11-25T10:00:00+01:00"
        # Duration should be 0, not 90 (FSM calculates real duration)
        assert result.entities["slot"]["duration_minutes"] == 0
        # start_time should be removed after conversion
        assert "start_time" not in result.entities


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


class TestIntentSynonymsNormalizer:
    """Tests for INTENT_SYNONYMS normalization (Bug #1 fix)."""

    def test_intent_synonyms_dict_exists(self):
        """INTENT_SYNONYMS dictionary is defined and non-empty."""
        assert isinstance(INTENT_SYNONYMS, dict)
        assert len(INTENT_SYNONYMS) > 0

    def test_synonyms_for_confirm_services(self):
        """Common Spanish variations for confirm_services are mapped."""
        confirm_services_synonyms = [
            "continua", "continúa", "sigamos", "ya está", "solo eso", "listo"
        ]
        for synonym in confirm_services_synonyms:
            assert INTENT_SYNONYMS.get(synonym) == "confirm_services", f"'{synonym}' should map to confirm_services"

    def test_synonyms_for_confirm_booking(self):
        """Common Spanish variations for confirm_booking are mapped."""
        confirm_booking_synonyms = [
            "confirmo", "confirmar", "perfecto", "vale", "ok", "dale"
        ]
        for synonym in confirm_booking_synonyms:
            assert INTENT_SYNONYMS.get(synonym) == "confirm_booking", f"'{synonym}' should map to confirm_booking"

    @pytest.mark.asyncio
    async def test_parse_normalizes_synonyms(self):
        """_parse_llm_response normalizes intent synonyms before parsing (Bug #1 fix)."""
        # LLM returns "continua" which is not a valid IntentType
        response = '{"intent_type": "continua", "entities": {}, "confidence": 0.95}'
        result = await _parse_llm_response(response, "Continua")

        # Should be normalized to confirm_services
        assert result.type == IntentType.CONFIRM_SERVICES

    @pytest.mark.asyncio
    async def test_parse_normalizes_sigamos(self):
        """'sigamos' is normalized to confirm_services."""
        response = '{"intent_type": "sigamos", "entities": {}, "confidence": 0.90}'
        result = await _parse_llm_response(response, "Sigamos")

        assert result.type == IntentType.CONFIRM_SERVICES

    @pytest.mark.asyncio
    async def test_parse_normalizes_confirmo(self):
        """'confirmo' is normalized to confirm_booking."""
        response = '{"intent_type": "confirmo", "entities": {}, "confidence": 0.95}'
        result = await _parse_llm_response(response, "Confirmo")

        assert result.type == IntentType.CONFIRM_BOOKING

    @pytest.mark.asyncio
    async def test_parse_keeps_valid_intent_types(self):
        """Valid IntentType values are not modified by normalizer."""
        response = '{"intent_type": "start_booking", "entities": {}, "confidence": 0.95}'
        result = await _parse_llm_response(response, "Quiero cita")

        assert result.type == IntentType.START_BOOKING

    @pytest.mark.asyncio
    async def test_parse_case_insensitive_normalization(self):
        """Normalization is case-insensitive."""
        response = '{"intent_type": "CONTINUA", "entities": {}, "confidence": 0.95}'
        result = await _parse_llm_response(response, "CONTINUA")

        assert result.type == IntentType.CONFIRM_SERVICES

    @pytest.mark.asyncio
    async def test_unmapped_synonyms_still_fallback_to_unknown(self):
        """Unmapped intent types still fall back to UNKNOWN."""
        response = '{"intent_type": "some_random_intent", "entities": {}, "confidence": 0.95}'
        result = await _parse_llm_response(response, "test")

        assert result.type == IntentType.UNKNOWN


class TestServiceNameToServicesConversion:
    """Tests for service_name to services list conversion (root cause fix)."""

    @pytest.mark.asyncio
    async def test_service_name_converted_to_services_list(self):
        """service_name entity is converted to services list for FSM compatibility."""
        response = '{"intent_type": "select_service", "entities": {"service_name": "Corte de Caballero", "selection_number": 5}, "confidence": 0.95}'
        result = await _parse_llm_response(response, "5")

        assert result.type == IntentType.SELECT_SERVICE
        assert "services" in result.entities
        assert result.entities["services"] == ["Corte de Caballero"]
        # selection_number should still be present
        assert result.entities.get("selection_number") == 5

    @pytest.mark.asyncio
    async def test_service_name_alone_converted(self):
        """service_name without selection_number is also converted."""
        response = '{"intent_type": "select_service", "entities": {"service_name": "Tinte Largo"}, "confidence": 0.9}'
        result = await _parse_llm_response(response, "Tinte largo")

        assert result.entities["services"] == ["Tinte Largo"]
        assert "service_name" not in result.entities  # Should be removed after conversion

    @pytest.mark.asyncio
    async def test_services_not_overwritten_if_present(self):
        """If services is already present, service_name doesn't overwrite it."""
        response = '{"intent_type": "select_service", "entities": {"services": ["Corte Largo"], "service_name": "Otro"}, "confidence": 0.9}'
        result = await _parse_llm_response(response, "test")

        # Original services should be preserved
        assert result.entities["services"] == ["Corte Largo"]


class TestStartTimeToSlotConversion:
    """Tests for start_time to slot dict conversion (slot selection fix)."""

    @pytest.mark.asyncio
    async def test_start_time_converted_to_slot_dict(self):
        """start_time entity is converted to slot dict for FSM compatibility."""
        response = '{"intent_type": "select_slot", "entities": {"start_time": "2025-11-25T10:00:00", "selection_number": 2}, "confidence": 0.95}'
        result = await _parse_llm_response(response, "2")

        assert result.type == IntentType.SELECT_SLOT
        assert "slot" in result.entities
        # start_time should be normalized with timezone
        assert result.entities["slot"]["start_time"] == "2025-11-25T10:00:00+01:00"
        # Duration is 0 - FSM calculates actual duration from selected services
        assert result.entities["slot"]["duration_minutes"] == 0
        # selection_number should still be present
        assert result.entities.get("selection_number") == 2

    @pytest.mark.asyncio
    async def test_start_time_alone_converted(self):
        """start_time without selection_number is also converted."""
        response = '{"intent_type": "select_slot", "entities": {"start_time": "2025-11-26T14:30:00"}, "confidence": 0.9}'
        result = await _parse_llm_response(response, "a las 2:30")

        assert "slot" in result.entities
        # start_time should be normalized with timezone
        assert result.entities["slot"]["start_time"] == "2025-11-26T14:30:00+01:00"
        # Duration is 0 - FSM calculates actual duration from selected services
        assert result.entities["slot"]["duration_minutes"] == 0
        assert "start_time" not in result.entities  # Should be removed after conversion

    @pytest.mark.asyncio
    async def test_slot_not_overwritten_if_present(self):
        """If slot is already present, start_time doesn't overwrite it."""
        response = '{"intent_type": "select_slot", "entities": {"slot": {"start_time": "2025-11-25T09:00:00", "duration_minutes": 60}, "start_time": "2025-11-25T11:00:00"}, "confidence": 0.9}'
        result = await _parse_llm_response(response, "test")

        # Original slot should be preserved
        assert result.entities["slot"]["start_time"] == "2025-11-25T09:00:00"
        assert result.entities["slot"]["duration_minutes"] == 60


class TestBug1DescriptionToFAQConversion:
    """Tests for Bug #1 fix: converting description-based select_service to FAQ."""

    @pytest.mark.asyncio
    async def test_select_service_with_number_is_valid(self):
        """select_service with selection_number is not converted to FAQ."""
        response = '{"intent_type": "select_service", "entities": {"service_name": "corte", "selection_number": 5}, "confidence": 0.9}'
        result = await _parse_llm_response(response, "5")

        assert result.type == IntentType.SELECT_SERVICE
        assert result.entities.get("selection_number") == 5

    @pytest.mark.asyncio
    async def test_select_service_exact_name_is_valid(self):
        """select_service with exact service name (not description) is valid."""
        response = '{"intent_type": "select_service", "entities": {"service_name": "Corte de Caballero"}, "confidence": 0.9}'
        result = await _parse_llm_response(response, "Corte de Caballero")

        assert result.type == IntentType.SELECT_SERVICE
        assert result.entities.get("services") == ["Corte de Caballero"]

    @pytest.mark.asyncio
    async def test_description_pattern_converts_to_faq(self):
        """Description like 'quiero cortarme el pelo' converts select_service to FAQ."""
        response = '{"intent_type": "select_service", "entities": {"service_name": "corte"}, "confidence": 0.9}'
        result = await _parse_llm_response(response, "quiero cortarme el pelo")

        assert result.type == IntentType.FAQ
        assert "services" not in result.entities

    @pytest.mark.asyncio
    async def test_me_gustaria_pattern_converts_to_faq(self):
        """Description like 'me gustaría un tinte' converts select_service to FAQ."""
        response = '{"intent_type": "select_service", "entities": {"service_name": "tinte"}, "confidence": 0.9}'
        result = await _parse_llm_response(response, "me gustaría un tinte")

        assert result.type == IntentType.FAQ
        assert "services" not in result.entities

    @pytest.mark.asyncio
    async def test_generic_term_pelo_converts_to_faq(self):
        """Generic term 'pelo' without number converts select_service to FAQ."""
        response = '{"intent_type": "select_service", "entities": {"service_name": "pelo"}, "confidence": 0.9}'
        result = await _parse_llm_response(response, "pelo")

        assert result.type == IntentType.FAQ
        assert "services" not in result.entities

    @pytest.mark.asyncio
    async def test_short_corte_without_pattern_is_valid(self):
        """Short 'Corte' as raw message is valid selection (abbreviation)."""
        response = '{"intent_type": "select_service", "entities": {"service_name": "Corte"}, "confidence": 0.9}'
        result = await _parse_llm_response(response, "Corte")

        # "Corte" alone without description pattern should be valid
        assert result.type == IntentType.SELECT_SERVICE
        assert result.entities.get("services") == ["Corte"]


class TestIntentAwareEntityFiltering:
    """Tests for intent-aware entity filtering (ghost service bug fix)."""

    @pytest.mark.asyncio
    async def test_start_booking_discards_service_entities(self):
        """START_BOOKING intent should NOT carry service entities."""
        # LLM incorrectly extracts service_name for start_booking
        response = '{"intent_type": "start_booking", "entities": {"service_name": "Corte de Pelo"}, "confidence": 0.9}'
        result = await _parse_llm_response(response, "quiero cortarme el pelo")

        assert result.type == IntentType.START_BOOKING
        # Services should be discarded - not allowed for START_BOOKING
        assert "services" not in result.entities
        assert "service_name" not in result.entities

    @pytest.mark.asyncio
    async def test_select_service_keeps_service_entities(self):
        """SELECT_SERVICE intent should keep service entities."""
        response = '{"intent_type": "select_service", "entities": {"service_name": "Corte de Caballero", "selection_number": 5}, "confidence": 0.95}'
        result = await _parse_llm_response(response, "5")

        assert result.type == IntentType.SELECT_SERVICE
        # Services should be kept for SELECT_SERVICE
        assert result.entities.get("services") == ["Corte de Caballero"]
        assert result.entities.get("selection_number") == 5

    @pytest.mark.asyncio
    async def test_greeting_discards_all_entities(self):
        """GREETING intent should have no entities."""
        response = '{"intent_type": "greeting", "entities": {"service_name": "test", "random": "data"}, "confidence": 0.95}'
        result = await _parse_llm_response(response, "Hola")

        assert result.type == IntentType.GREETING
        assert result.entities == {}

    @pytest.mark.asyncio
    async def test_confirm_services_discards_service_entities(self):
        """CONFIRM_SERVICES intent should have no entities."""
        response = '{"intent_type": "confirm_services", "entities": {"service_name": "extra"}, "confidence": 0.9}'
        result = await _parse_llm_response(response, "eso es todo")

        assert result.type == IntentType.CONFIRM_SERVICES
        assert "services" not in result.entities

    @pytest.mark.asyncio
    async def test_provide_customer_data_keeps_name_entities(self):
        """PROVIDE_CUSTOMER_DATA should keep name/notes entities."""
        response = '{"intent_type": "provide_customer_data", "entities": {"first_name": "Juan", "last_name": "García", "notes": "sin prisa"}, "confidence": 0.95}'
        result = await _parse_llm_response(response, "Me llamo Juan García, sin prisa")

        assert result.type == IntentType.PROVIDE_CUSTOMER_DATA
        assert result.entities.get("first_name") == "Juan"
        assert result.entities.get("last_name") == "García"
        assert result.entities.get("notes") == "sin prisa"


class TestTimezoneNormalization:
    """Tests for _normalize_start_time_timezone function (book() failure fix)."""

    def test_adds_timezone_to_naive_datetime(self):
        """Naive datetime without timezone should get +01:00 added (Europe/Madrid)."""
        result = _normalize_start_time_timezone("2025-11-27T10:30:00")

        # Should have Madrid timezone (CET = +01:00 in November)
        assert result == "2025-11-27T10:30:00+01:00"

    def test_preserves_existing_timezone_plus(self):
        """Datetime with +01:00 timezone should be preserved."""
        result = _normalize_start_time_timezone("2025-11-27T10:30:00+01:00")

        assert result == "2025-11-27T10:30:00+01:00"

    def test_preserves_existing_timezone_minus(self):
        """Datetime with negative timezone offset should be preserved."""
        result = _normalize_start_time_timezone("2025-11-27T10:30:00-05:00")

        assert result == "2025-11-27T10:30:00-05:00"

    def test_preserves_z_timezone(self):
        """Datetime with Z (UTC) timezone should be preserved."""
        result = _normalize_start_time_timezone("2025-11-27T10:30:00Z")

        assert result == "2025-11-27T10:30:00Z"

    def test_handles_summer_time(self):
        """Summer datetime should get +02:00 (CEST) in Madrid."""
        result = _normalize_start_time_timezone("2025-07-15T14:00:00")

        # July is summer time in Madrid (CEST = +02:00)
        assert result == "2025-07-15T14:00:00+02:00"

    def test_returns_original_on_invalid_format(self):
        """Invalid datetime format should return original string."""
        result = _normalize_start_time_timezone("not-a-datetime")

        assert result == "not-a-datetime"

    def test_returns_original_on_partial_datetime(self):
        """Partial datetime (date only) should return original."""
        result = _normalize_start_time_timezone("2025-11-27")

        # fromisoformat handles date-only strings
        # It should add timezone to the date-only (00:00:00)
        assert "+01:00" in result or result == "2025-11-27"

    def test_empty_string_returns_empty(self):
        """Empty string should return empty string."""
        result = _normalize_start_time_timezone("")

        # Empty string should trigger ValueError and return original
        assert result == ""


class TestCheckAvailabilityVagueTerms:
    """Tests for vague temporal terms detection (slot selection bug fix)."""

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_tarde_returns_check_availability_with_time_range(self, mock_get_llm):
        """'Por la tarde' in SLOT_SELECTION returns CHECK_AVAILABILITY with time_range='afternoon'."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "check_availability", "entities": {"time_range": "afternoon"}, "confidence": 0.95}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="Por la tarde",
            current_state=BookingState.SLOT_SELECTION,
            collected_data={"services": ["Corte"], "stylist_id": "abc-123"},
            conversation_history=[],
        )

        assert result.type == IntentType.CHECK_AVAILABILITY
        assert result.entities.get("time_range") == "afternoon"
        assert result.confidence >= 0.8

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_de_tarde_returns_check_availability(self, mock_get_llm):
        """'De tarde' in SLOT_SELECTION returns CHECK_AVAILABILITY with time_range='afternoon'."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "check_availability", "entities": {"time_range": "afternoon"}, "confidence": 0.92}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="De tarde",
            current_state=BookingState.SLOT_SELECTION,
            collected_data={"services": ["Corte"], "stylist_id": "abc-123"},
            conversation_history=[],
        )

        assert result.type == IntentType.CHECK_AVAILABILITY
        assert result.entities.get("time_range") == "afternoon"

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_manana_returns_check_availability_with_morning_time_range(self, mock_get_llm):
        """'Por la mañana' in SLOT_SELECTION returns CHECK_AVAILABILITY with time_range='morning'."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "check_availability", "entities": {"time_range": "morning"}, "confidence": 0.94}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="Por la mañana",
            current_state=BookingState.SLOT_SELECTION,
            collected_data={"services": ["Corte"], "stylist_id": "abc-123"},
            conversation_history=[],
        )

        assert result.type == IntentType.CHECK_AVAILABILITY
        assert result.entities.get("time_range") == "morning"

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_de_manana_returns_check_availability(self, mock_get_llm):
        """'De mañana' in SLOT_SELECTION returns CHECK_AVAILABILITY with time_range='morning'."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "check_availability", "entities": {"time_range": "morning"}, "confidence": 0.93}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="De mañana",
            current_state=BookingState.SLOT_SELECTION,
            collected_data={"services": ["Corte"], "stylist_id": "abc-123"},
            conversation_history=[],
        )

        assert result.type == IntentType.CHECK_AVAILABILITY
        assert result.entities.get("time_range") == "morning"

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_mas_opciones_returns_check_availability_without_time_range(self, mock_get_llm):
        """'Más opciones' in SLOT_SELECTION returns CHECK_AVAILABILITY without time_range."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "check_availability", "entities": {}, "confidence": 0.9}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="Más opciones",
            current_state=BookingState.SLOT_SELECTION,
            collected_data={"services": ["Corte"], "stylist_id": "abc-123"},
            conversation_history=[],
        )

        assert result.type == IntentType.CHECK_AVAILABILITY
        assert "time_range" not in result.entities or result.entities.get("time_range") is None

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_otro_horario_returns_check_availability(self, mock_get_llm):
        """'Otro horario' in SLOT_SELECTION returns CHECK_AVAILABILITY."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "check_availability", "entities": {}, "confidence": 0.91}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="Otro horario",
            current_state=BookingState.SLOT_SELECTION,
            collected_data={"services": ["Corte"], "stylist_id": "abc-123"},
            conversation_history=[],
        )

        assert result.type == IntentType.CHECK_AVAILABILITY

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_date_with_vague_time_range(self, mock_get_llm):
        """'1 de diciembre por la tarde' returns CHECK_AVAILABILITY with both date and time_range."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "check_availability", "entities": {"date": "1 diciembre", "time_range": "afternoon"}, "confidence": 0.96}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="El 1 de diciembre por la tarde",
            current_state=BookingState.SLOT_SELECTION,
            collected_data={"services": ["Corte"], "stylist_id": "abc-123"},
            conversation_history=[],
        )

        assert result.type == IntentType.CHECK_AVAILABILITY
        assert result.entities.get("date") == "1 diciembre"
        assert result.entities.get("time_range") == "afternoon"

    @pytest.mark.asyncio
    async def test_check_availability_time_range_allowed_entity(self):
        """time_range is allowed entity for CHECK_AVAILABILITY intent (entity filtering)."""
        response = '{"intent_type": "check_availability", "entities": {"time_range": "afternoon", "date": "1 diciembre"}, "confidence": 0.95}'
        result = await _parse_llm_response(response, "El 1 de diciembre por la tarde")

        assert result.type == IntentType.CHECK_AVAILABILITY
        assert result.entities.get("time_range") == "afternoon"
        assert result.entities.get("date") == "1 diciembre"

    @pytest.mark.asyncio
    @patch("agent.fsm.intent_extractor._get_llm_client")
    async def test_specific_hour_vs_vague_range(self, mock_get_llm):
        """'A las 15:00' is SELECT_SLOT, but 'por la tarde' is CHECK_AVAILABILITY (not confused)."""
        # Test SELECT_SLOT first (specific hour)
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "select_slot", "entities": {"start_time": "2025-12-01T15:00:00+01:00"}, "confidence": 0.95}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="A las 15:00",
            current_state=BookingState.SLOT_SELECTION,
            collected_data={"services": ["Corte"], "stylist_id": "abc-123"},
            conversation_history=[],
        )

        assert result.type == IntentType.SELECT_SLOT
        assert "slot" in result.entities
        assert "time_range" not in result.entities

        # Now test CHECK_AVAILABILITY (vague range)
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"intent_type": "check_availability", "entities": {"time_range": "afternoon"}, "confidence": 0.95}'
            )
        )
        mock_get_llm.return_value = mock_llm

        result = await extract_intent(
            message="Por la tarde",
            current_state=BookingState.SLOT_SELECTION,
            collected_data={"services": ["Corte"], "stylist_id": "abc-123"},
            conversation_history=[],
        )

        assert result.type == IntentType.CHECK_AVAILABILITY
        assert result.entities.get("time_range") == "afternoon"
        assert "slot" not in result.entities


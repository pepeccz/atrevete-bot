"""
Unit tests for ResponseValidator (Story 5-7a).

Tests the Response Coherence Layer that validates LLM responses
against FSM state before sending to users.

Coverage targets:
- CoherenceResult dataclass (AC #1)
- Pattern detection for SERVICE_SELECTION (AC #2)
- Pattern detection for STYLIST_SELECTION (AC #3)
- Pattern detection for SLOT_SELECTION (AC #4)
- Validation performance <100ms (AC #6)
- Logging structure (AC #7)
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from agent.fsm.models import BookingState, CoherenceResult
from agent.fsm.response_validator import (
    CORRECTION_HINTS,
    FORBIDDEN_PATTERNS,
    GENERIC_FALLBACK_RESPONSE,
    ResponseValidator,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def validator():
    """Create a ResponseValidator instance."""
    return ResponseValidator()


@pytest.fixture
def mock_fsm():
    """Create a mock FSM for testing."""
    fsm = MagicMock()
    fsm.conversation_id = "test-conv-123"
    fsm.collected_data = {}
    return fsm


# ============================================================================
# TEST: CoherenceResult DATACLASS (AC #1)
# ============================================================================


class TestCoherenceResult:
    """Tests for CoherenceResult dataclass."""

    def test_coherent_result_defaults(self):
        """Test CoherenceResult with coherent defaults."""
        result = CoherenceResult(is_coherent=True)

        assert result.is_coherent is True
        assert result.violations == []
        assert result.correction_hint is None
        assert result.confidence == 1.0

    def test_incoherent_result_with_violations(self):
        """Test CoherenceResult with violations."""
        result = CoherenceResult(
            is_coherent=False,
            violations=["Menciona nombres de estilistas", "Muestra horarios específicos"],
            correction_hint="NO menciones estilistas ni horarios.",
            confidence=0.9,
        )

        assert result.is_coherent is False
        assert len(result.violations) == 2
        assert "estilistas" in result.violations[0]
        assert result.correction_hint is not None
        assert result.confidence == 0.9

    def test_coherence_result_immutable_fields(self):
        """Test that CoherenceResult fields are accessible."""
        result = CoherenceResult(
            is_coherent=False,
            violations=["test violation"],
            correction_hint="test hint",
            confidence=0.85,
        )

        # All fields should be accessible
        assert result.is_coherent is False
        assert result.violations[0] == "test violation"
        assert result.correction_hint == "test hint"
        assert result.confidence == 0.85


# ============================================================================
# TEST: FORBIDDEN_PATTERNS CONFIGURATION
# ============================================================================


class TestForbiddenPatterns:
    """Tests for FORBIDDEN_PATTERNS configuration."""

    def test_all_states_have_patterns(self):
        """Verify all BookingState values have pattern entries."""
        for state in BookingState:
            assert state in FORBIDDEN_PATTERNS, f"Missing patterns for {state.value}"

    def test_service_selection_has_patterns(self):
        """SERVICE_SELECTION should have patterns for stylists and times."""
        patterns = FORBIDDEN_PATTERNS[BookingState.SERVICE_SELECTION]
        assert len(patterns) >= 2, "SERVICE_SELECTION needs multiple patterns"

    def test_stylist_selection_has_patterns(self):
        """STYLIST_SELECTION should have patterns for times."""
        patterns = FORBIDDEN_PATTERNS[BookingState.STYLIST_SELECTION]
        assert len(patterns) >= 1, "STYLIST_SELECTION needs time patterns"

    def test_slot_selection_has_patterns(self):
        """SLOT_SELECTION should have patterns for premature confirmation."""
        patterns = FORBIDDEN_PATTERNS[BookingState.SLOT_SELECTION]
        assert len(patterns) >= 1, "SLOT_SELECTION needs confirmation patterns"

    def test_idle_has_no_patterns(self):
        """IDLE state should have no forbidden patterns."""
        patterns = FORBIDDEN_PATTERNS[BookingState.IDLE]
        assert len(patterns) == 0, "IDLE should allow any response"

    def test_booked_has_no_patterns(self):
        """BOOKED state should have no forbidden patterns."""
        patterns = FORBIDDEN_PATTERNS[BookingState.BOOKED]
        assert len(patterns) == 0, "BOOKED should allow any response"


# ============================================================================
# TEST: SERVICE_SELECTION STATE VALIDATION (AC #2)
# ============================================================================


class TestServiceSelectionValidation:
    """Tests for SERVICE_SELECTION state coherence validation."""

    def test_detects_stylist_name_ana(self, validator, mock_fsm):
        """Detect stylist name 'Ana' in SERVICE_SELECTION."""
        mock_fsm.state = BookingState.SERVICE_SELECTION
        response = "Las estilistas disponibles son: 1. Ana, 2. María"

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is False
        assert any("estilista" in v.lower() for v in result.violations)

    def test_detects_stylist_name_maria(self, validator, mock_fsm):
        """Detect stylist name 'María' in SERVICE_SELECTION."""
        mock_fsm.state = BookingState.SERVICE_SELECTION
        response = "María está disponible el lunes."

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is False
        assert len(result.violations) >= 1

    def test_detects_stylist_name_carlos(self, validator, mock_fsm):
        """Detect stylist name 'Carlos' in SERVICE_SELECTION."""
        mock_fsm.state = BookingState.SERVICE_SELECTION
        response = "Carlos tiene disponibilidad."

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is False

    def test_detects_time_slots(self, validator, mock_fsm):
        """Detect specific time slots (HH:MM) in SERVICE_SELECTION."""
        mock_fsm.state = BookingState.SERVICE_SELECTION
        response = "Hay disponibilidad a las 10:30 y 14:00."

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is False
        assert any("horario" in v.lower() for v in result.violations)

    def test_detects_availability_language(self, validator, mock_fsm):
        """Detect availability language in SERVICE_SELECTION."""
        mock_fsm.state = BookingState.SERVICE_SELECTION
        response = "Está disponible el lunes por la mañana."

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is False

    def test_allows_service_listing(self, validator, mock_fsm):
        """Allow service listing in SERVICE_SELECTION (coherent)."""
        mock_fsm.state = BookingState.SERVICE_SELECTION
        response = """¡Estos son nuestros servicios!
1. Corte de pelo - 25€
2. Tinte - 45€
3. Mechas - 65€

¿Cuál te gustaría reservar?"""

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is True
        assert len(result.violations) == 0

    def test_allows_service_questions(self, validator, mock_fsm):
        """Allow questions about services in SERVICE_SELECTION."""
        mock_fsm.state = BookingState.SERVICE_SELECTION
        response = "¿Qué servicio te gustaría reservar hoy?"

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is True


# ============================================================================
# TEST: STYLIST_SELECTION STATE VALIDATION (AC #3)
# ============================================================================


class TestStylistSelectionValidation:
    """Tests for STYLIST_SELECTION state coherence validation."""

    def test_detects_specific_times(self, validator, mock_fsm):
        """Detect specific times (HH:MM) in STYLIST_SELECTION."""
        mock_fsm.state = BookingState.STYLIST_SELECTION
        response = "Ana está disponible a las 10:30 y 15:00."

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is False
        assert any("horario" in v.lower() for v in result.violations)

    def test_detects_day_with_number(self, validator, mock_fsm):
        """Detect day + number patterns in STYLIST_SELECTION."""
        mock_fsm.state = BookingState.STYLIST_SELECTION
        response = "Hay disponibilidad el lunes 25 de noviembre."

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is False

    def test_allows_stylist_listing(self, validator, mock_fsm):
        """Allow stylist listing in STYLIST_SELECTION (coherent)."""
        mock_fsm.state = BookingState.STYLIST_SELECTION
        response = """Nuestras estilistas son:
1. Ana - Especialista en cortes
2. María - Experta en color
3. Pilar - Tratamientos capilares

¿Con quién prefieres tu cita?"""

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is True

    def test_allows_stylist_questions(self, validator, mock_fsm):
        """Allow questions about stylists in STYLIST_SELECTION."""
        mock_fsm.state = BookingState.STYLIST_SELECTION
        response = "¿Con qué estilista te gustaría agendar tu cita?"

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is True


# ============================================================================
# TEST: SLOT_SELECTION STATE VALIDATION (AC #4)
# ============================================================================


class TestSlotSelectionValidation:
    """Tests for SLOT_SELECTION state coherence validation."""

    def test_detects_premature_confirmation(self, validator, mock_fsm):
        """Detect premature booking confirmation in SLOT_SELECTION."""
        mock_fsm.state = BookingState.SLOT_SELECTION
        response = "¡Tu cita ha sido confirmada! Te esperamos el lunes."

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is False
        assert any("confirm" in v.lower() for v in result.violations)

    def test_detects_customer_data_request(self, validator, mock_fsm):
        """Detect premature customer data request in SLOT_SELECTION."""
        mock_fsm.state = BookingState.SLOT_SELECTION
        response = "¿Me puedes dar tu nombre y apellido para la reserva?"

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is False

    def test_detects_booking_summary(self, validator, mock_fsm):
        """Detect premature booking summary in SLOT_SELECTION."""
        mock_fsm.state = BookingState.SLOT_SELECTION
        response = "Aquí tienes el resumen de tu cita: Corte con Ana el lunes a las 10:30."

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is False

    def test_allows_time_slot_presentation(self, validator, mock_fsm):
        """Allow time slot presentation in SLOT_SELECTION (coherent)."""
        mock_fsm.state = BookingState.SLOT_SELECTION
        response = """Ana tiene estos horarios disponibles:
1. Lunes 10:30
2. Lunes 14:00
3. Martes 11:00

¿Cuál prefieres?"""

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is True


# ============================================================================
# TEST: CUSTOMER_DATA STATE VALIDATION
# ============================================================================


class TestCustomerDataValidation:
    """Tests for CUSTOMER_DATA state coherence validation."""

    def test_detects_confirmation_without_data(self, validator, mock_fsm):
        """Detect booking confirmation without customer data."""
        mock_fsm.state = BookingState.CUSTOMER_DATA
        response = "¡Perfecto! Tu cita ha sido confirmada."

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is False

    def test_allows_name_request(self, validator, mock_fsm):
        """Allow name request in CUSTOMER_DATA (coherent)."""
        mock_fsm.state = BookingState.CUSTOMER_DATA
        response = "Para finalizar la reserva, ¿me podrías dar tu nombre?"

        result = validator.validate(response, mock_fsm)

        # This should be coherent - asking for data is appropriate
        assert result.is_coherent is True


# ============================================================================
# TEST: IDLE AND CONFIRMATION STATES (NO RESTRICTIONS)
# ============================================================================


class TestNoRestrictionStates:
    """Tests for states with no forbidden patterns."""

    def test_idle_allows_anything(self, validator, mock_fsm):
        """IDLE state should allow any response."""
        mock_fsm.state = BookingState.IDLE
        response = "Ana está disponible a las 10:30 para tu corte confirmado."

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is True

    def test_confirmation_allows_anything(self, validator, mock_fsm):
        """CONFIRMATION state should allow booking confirmation."""
        mock_fsm.state = BookingState.CONFIRMATION
        response = "Tu cita está confirmada con Ana el lunes a las 10:30."

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is True

    def test_booked_allows_anything(self, validator, mock_fsm):
        """BOOKED state should allow any response."""
        mock_fsm.state = BookingState.BOOKED
        response = "¡Tu cita ha sido reservada! Te esperamos."

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is True


# ============================================================================
# TEST: CORRECTION HINTS
# ============================================================================


class TestCorrectionHints:
    """Tests for correction hint generation."""

    def test_service_selection_hint(self, validator, mock_fsm):
        """SERVICE_SELECTION should get appropriate correction hint."""
        mock_fsm.state = BookingState.SERVICE_SELECTION
        response = "Ana está disponible."

        result = validator.validate(response, mock_fsm)

        assert result.correction_hint is not None
        assert "servicio" in result.correction_hint.lower() or "estilista" in result.correction_hint.lower()

    def test_stylist_selection_hint(self, validator, mock_fsm):
        """STYLIST_SELECTION should get appropriate correction hint."""
        mock_fsm.state = BookingState.STYLIST_SELECTION
        response = "Disponible a las 10:30."

        result = validator.validate(response, mock_fsm)

        assert result.correction_hint is not None
        assert "estilista" in result.correction_hint.lower() or "horario" in result.correction_hint.lower()

    def test_all_states_have_hints(self):
        """Verify all states have correction hints defined."""
        for state in BookingState:
            assert state in CORRECTION_HINTS, f"Missing hint for {state.value}"


# ============================================================================
# TEST: VALIDATION PERFORMANCE (AC #6)
# ============================================================================


class TestValidationPerformance:
    """Tests for validation performance requirements."""

    def test_validation_under_100ms(self, validator, mock_fsm):
        """Validation should complete in under 100ms."""
        mock_fsm.state = BookingState.SERVICE_SELECTION

        # Long response to test performance
        response = """
        Aquí tienes nuestra lista completa de servicios:
        1. Corte de pelo - Incluye lavado y secado
        2. Tinte completo - Color a elegir
        3. Mechas californianas - Efecto natural
        4. Tratamiento de keratina - Alisado duradero
        5. Peinado especial - Para ocasiones especiales

        Todos nuestros servicios incluyen consulta gratuita.
        """ * 10  # Make it longer

        start = time.perf_counter()
        result = validator.validate(response, mock_fsm)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 100, f"Validation took {elapsed_ms:.2f}ms (>100ms)"
        assert isinstance(result, CoherenceResult)

    def test_multiple_validations_under_100ms_each(self, validator, mock_fsm):
        """Multiple validations should each complete under 100ms."""
        mock_fsm.state = BookingState.SERVICE_SELECTION
        responses = [
            "Las estilistas disponibles son Ana, María y Carlos.",
            "Tenemos disponibilidad a las 10:30, 14:00 y 16:30.",
            "¿Qué servicio te gustaría reservar hoy?",
            "El corte cuesta 25€ y el tinte 45€.",
        ]

        for response in responses:
            start = time.perf_counter()
            validator.validate(response, mock_fsm)
            elapsed_ms = (time.perf_counter() - start) * 1000

            assert elapsed_ms < 100, f"Validation took {elapsed_ms:.2f}ms for: {response[:50]}"


# ============================================================================
# TEST: LOGGING (AC #7)
# ============================================================================


class TestValidationLogging:
    """Tests for validation logging requirements."""

    def test_logs_coherent_validation(self, validator, mock_fsm, caplog):
        """Coherent validation should log success."""
        import logging
        caplog.set_level(logging.INFO)

        mock_fsm.state = BookingState.IDLE
        response = "¡Hola! ¿En qué puedo ayudarte?"

        validator.validate(response, mock_fsm)

        # Check log contains expected info
        assert any("coherent=True" in record.message or "coherence validated" in record.message.lower()
                   for record in caplog.records)

    def test_logs_incoherent_validation(self, validator, mock_fsm, caplog):
        """Incoherent validation should log warning with violations."""
        import logging
        caplog.set_level(logging.WARNING)

        mock_fsm.state = BookingState.SERVICE_SELECTION
        response = "Ana está disponible."

        validator.validate(response, mock_fsm)

        # Check log contains violations
        assert any("FAILED" in record.message or "violations" in record.message.lower()
                   for record in caplog.records)

    def test_log_includes_fsm_state(self, validator, mock_fsm, caplog):
        """Log should include FSM state."""
        import logging
        caplog.set_level(logging.INFO)

        mock_fsm.state = BookingState.SERVICE_SELECTION
        response = "¿Qué servicio deseas?"

        validator.validate(response, mock_fsm)

        assert any("service_selection" in record.message.lower()
                   for record in caplog.records)


# ============================================================================
# TEST: EDGE CASES
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_response(self, validator, mock_fsm):
        """Empty response should be coherent (no violations possible)."""
        mock_fsm.state = BookingState.SERVICE_SELECTION
        response = ""

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is True

    def test_whitespace_only_response(self, validator, mock_fsm):
        """Whitespace-only response should be coherent."""
        mock_fsm.state = BookingState.SERVICE_SELECTION
        response = "   \n\t  "

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is True

    def test_case_insensitive_detection(self, validator, mock_fsm):
        """Pattern detection should be case-insensitive."""
        mock_fsm.state = BookingState.SERVICE_SELECTION

        # Test uppercase
        result1 = validator.validate("ANA está disponible", mock_fsm)
        assert result1.is_coherent is False

        # Test lowercase
        result2 = validator.validate("ana está disponible", mock_fsm)
        assert result2.is_coherent is False

        # Test mixed case
        result3 = validator.validate("AnA está disponible", mock_fsm)
        assert result3.is_coherent is False

    def test_multiple_violations(self, validator, mock_fsm):
        """Multiple violations should all be captured."""
        mock_fsm.state = BookingState.SERVICE_SELECTION
        response = "Ana y María están disponibles a las 10:30 y 14:00."

        result = validator.validate(response, mock_fsm)

        assert result.is_coherent is False
        assert len(result.violations) >= 2  # At least stylist + time violations

    def test_confidence_increases_with_violations(self, validator, mock_fsm):
        """Confidence should increase with more violations."""
        mock_fsm.state = BookingState.SERVICE_SELECTION

        # Single violation
        result1 = validator.validate("Ana disponible", mock_fsm)

        # Multiple violations
        result2 = validator.validate("Ana y María disponibles a las 10:30", mock_fsm)

        # More violations = higher confidence it's wrong
        assert result2.confidence >= result1.confidence


# ============================================================================
# TEST: GENERIC FALLBACK RESPONSE
# ============================================================================


class TestGenericFallback:
    """Tests for generic fallback response."""

    def test_fallback_exists(self):
        """Generic fallback response should exist."""
        assert GENERIC_FALLBACK_RESPONSE is not None
        assert len(GENERIC_FALLBACK_RESPONSE) > 0

    def test_fallback_is_friendly(self):
        """Fallback should be a friendly greeting."""
        assert "Atrévete" in GENERIC_FALLBACK_RESPONSE or "asistente" in GENERIC_FALLBACK_RESPONSE
        assert "🌸" in GENERIC_FALLBACK_RESPONSE or "ayudar" in GENERIC_FALLBACK_RESPONSE

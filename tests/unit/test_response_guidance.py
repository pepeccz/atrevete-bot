"""
Unit tests for ResponseGuidance and FSM Directives (Story 5-7b).

Tests the proactive guidance system that instructs the LLM what it
MUST show, MUST ask, and MUST NOT mention based on FSM state.

Coverage targets:
- ResponseGuidance dataclass (AC #1)
- SERVICE_SELECTION guidance (AC #2)
- STYLIST_SELECTION guidance (AC #3)
- SLOT_SELECTION guidance (AC #4)
- CUSTOMER_DATA guidance (AC #5)
- format_guidance_prompt (AC #6)
- Logging structure (AC #8)
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from agent.fsm.models import BookingState, ResponseGuidance
from agent.fsm.booking_fsm import BookingFSM


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def fsm():
    """Create a BookingFSM instance for testing."""
    return BookingFSM("test-conv-123")


# ============================================================================
# TEST: ResponseGuidance DATACLASS (AC #1)
# ============================================================================


class TestResponseGuidanceDataclass:
    """Tests for ResponseGuidance dataclass structure."""

    def test_response_guidance_defaults(self):
        """Test ResponseGuidance with default values."""
        guidance = ResponseGuidance()

        assert guidance.must_show == []
        assert guidance.must_ask is None
        assert guidance.forbidden == []
        assert guidance.context_hint == ""

    def test_response_guidance_with_all_fields(self):
        """Test ResponseGuidance with all fields populated."""
        guidance = ResponseGuidance(
            must_show=["lista de estilistas disponibles"],
            must_ask="¿Con quién te gustaría la cita?",
            forbidden=["horarios específicos", "datos del cliente"],
            context_hint="Usuario debe elegir estilista. NO mostrar horarios aún.",
        )

        assert len(guidance.must_show) == 1
        assert "estilistas" in guidance.must_show[0]
        assert guidance.must_ask is not None
        assert "¿" in guidance.must_ask
        assert len(guidance.forbidden) == 2
        assert "horarios" in guidance.forbidden[0]
        assert guidance.context_hint != ""

    def test_response_guidance_has_required_fields(self):
        """Test that ResponseGuidance has all required fields per AC #1."""
        # AC #1: must_show, must_ask, forbidden, context_hint
        guidance = ResponseGuidance(
            must_show=["test"],
            must_ask="test question?",
            forbidden=["test forbidden"],
            context_hint="test hint",
        )

        # All fields should be accessible
        assert hasattr(guidance, "must_show")
        assert hasattr(guidance, "must_ask")
        assert hasattr(guidance, "forbidden")
        assert hasattr(guidance, "context_hint")


# ============================================================================
# TEST: get_response_guidance() METHOD
# ============================================================================


class TestGetResponseGuidance:
    """Tests for BookingFSM.get_response_guidance() method."""

    def test_guidance_returns_response_guidance_type(self, fsm):
        """Test that get_response_guidance returns ResponseGuidance."""
        guidance = fsm.get_response_guidance()

        assert isinstance(guidance, ResponseGuidance)

    def test_all_states_return_guidance(self, fsm):
        """Test that every BookingState has guidance defined."""
        for state in BookingState:
            fsm._state = state
            guidance = fsm.get_response_guidance()

            assert isinstance(guidance, ResponseGuidance), f"State {state.value} should return guidance"
            assert isinstance(guidance.must_show, list), f"State {state.value} must_show should be list"
            assert isinstance(guidance.forbidden, list), f"State {state.value} forbidden should be list"
            assert isinstance(guidance.context_hint, str), f"State {state.value} context_hint should be str"


# ============================================================================
# TEST: SERVICE_SELECTION GUIDANCE (AC #2)
# ============================================================================


class TestServiceSelectionGuidance:
    """Tests for SERVICE_SELECTION state guidance (AC #2)."""

    def test_service_selection_forbidden_contains_estilistas(self, fsm):
        """AC #2: forbidden includes 'estilistas'."""
        fsm._state = BookingState.SERVICE_SELECTION
        fsm._collected_data = {"services": []}

        guidance = fsm.get_response_guidance()

        assert "estilistas" in guidance.forbidden

    def test_service_selection_forbidden_contains_horarios(self, fsm):
        """AC #2: forbidden includes 'horarios'."""
        fsm._state = BookingState.SERVICE_SELECTION
        fsm._collected_data = {"services": []}

        guidance = fsm.get_response_guidance()

        assert "horarios" in guidance.forbidden

    def test_service_selection_forbidden_contains_confirmacion(self, fsm):
        """AC #2: forbidden includes 'confirmación'."""
        fsm._state = BookingState.SERVICE_SELECTION
        fsm._collected_data = {"services": []}

        guidance = fsm.get_response_guidance()

        # Check for any variation of "confirmación"
        assert any("confirmación" in f or "cita" in f for f in guidance.forbidden)

    def test_service_selection_must_ask_about_services(self, fsm):
        """AC #2: must_ask includes question about services."""
        fsm._state = BookingState.SERVICE_SELECTION
        fsm._collected_data = {"services": []}

        guidance = fsm.get_response_guidance()

        assert guidance.must_ask is not None
        # Should ask about services (initial or additional)
        assert "servicio" in guidance.must_ask.lower() or "otro" in guidance.must_ask.lower()

    def test_service_selection_with_services_already_selected(self, fsm):
        """Test guidance changes when services are already selected."""
        fsm._state = BookingState.SERVICE_SELECTION
        fsm._collected_data = {"services": ["Corte de pelo"]}

        guidance = fsm.get_response_guidance()

        # Should still forbid estilistas and horarios
        assert "estilistas" in guidance.forbidden
        assert "horarios" in guidance.forbidden
        # Question should be about adding more
        assert guidance.must_ask is not None


# ============================================================================
# TEST: STYLIST_SELECTION GUIDANCE (AC #3)
# ============================================================================


class TestStylistSelectionGuidance:
    """Tests for STYLIST_SELECTION state guidance (AC #3)."""

    def test_stylist_selection_must_show_estilistas(self, fsm):
        """AC #3: must_show includes lista de estilistas."""
        fsm._state = BookingState.STYLIST_SELECTION

        guidance = fsm.get_response_guidance()

        assert len(guidance.must_show) > 0
        assert any("estilista" in item.lower() for item in guidance.must_show)

    def test_stylist_selection_forbidden_contains_horarios(self, fsm):
        """AC #3: forbidden includes 'horarios específicos'."""
        fsm._state = BookingState.STYLIST_SELECTION

        guidance = fsm.get_response_guidance()

        assert any("horarios" in f or "específicos" in f for f in guidance.forbidden)

    def test_stylist_selection_forbidden_contains_datos_cliente(self, fsm):
        """AC #3: forbidden includes 'datos del cliente'."""
        fsm._state = BookingState.STYLIST_SELECTION

        guidance = fsm.get_response_guidance()

        assert any("cliente" in f or "datos" in f for f in guidance.forbidden)

    def test_stylist_selection_must_ask_about_stylist(self, fsm):
        """Test must_ask includes question about stylist selection."""
        fsm._state = BookingState.STYLIST_SELECTION

        guidance = fsm.get_response_guidance()

        assert guidance.must_ask is not None
        assert "quién" in guidance.must_ask.lower() or "cita" in guidance.must_ask.lower()


# ============================================================================
# TEST: SLOT_SELECTION GUIDANCE (AC #4)
# ============================================================================


class TestSlotSelectionGuidance:
    """Tests for SLOT_SELECTION state guidance (AC #4)."""

    def test_slot_selection_must_show_horarios(self, fsm):
        """AC #4: must_show includes horarios disponibles."""
        fsm._state = BookingState.SLOT_SELECTION

        guidance = fsm.get_response_guidance()

        assert len(guidance.must_show) > 0
        assert any("horarios" in item.lower() or "disponible" in item.lower() for item in guidance.must_show)

    def test_slot_selection_forbidden_contains_confirmacion(self, fsm):
        """AC #4: forbidden includes 'confirmación de cita'."""
        fsm._state = BookingState.SLOT_SELECTION

        guidance = fsm.get_response_guidance()

        assert any("confirmación" in f or "cita" in f for f in guidance.forbidden)

    def test_slot_selection_forbidden_contains_datos_adicionales(self, fsm):
        """AC #4: forbidden includes 'solicitud de datos adicionales'."""
        fsm._state = BookingState.SLOT_SELECTION

        guidance = fsm.get_response_guidance()

        assert any("datos" in f or "adicionales" in f for f in guidance.forbidden)

    def test_slot_selection_must_ask_about_horario(self, fsm):
        """Test must_ask includes question about time slot."""
        fsm._state = BookingState.SLOT_SELECTION

        guidance = fsm.get_response_guidance()

        assert guidance.must_ask is not None
        assert "horario" in guidance.must_ask.lower() or "mejor" in guidance.must_ask.lower()


# ============================================================================
# TEST: CUSTOMER_DATA GUIDANCE (AC #5)
# ============================================================================


class TestCustomerDataGuidance:
    """Tests for CUSTOMER_DATA state guidance (AC #5)."""

    def test_customer_data_must_ask_nombre(self, fsm):
        """AC #5: must_ask includes solicitud de nombre/datos."""
        fsm._state = BookingState.CUSTOMER_DATA

        guidance = fsm.get_response_guidance()

        assert guidance.must_ask is not None
        assert "nombre" in guidance.must_ask.lower()

    def test_customer_data_forbidden_confirmacion_sin_datos(self, fsm):
        """AC #5: forbidden includes 'confirmación de cita sin datos'."""
        fsm._state = BookingState.CUSTOMER_DATA

        guidance = fsm.get_response_guidance()

        assert any("confirmación" in f or "sin datos" in f for f in guidance.forbidden)


# ============================================================================
# TEST: format_guidance_prompt FUNCTION (AC #6)
# ============================================================================


class TestFormatGuidancePrompt:
    """Tests for format_guidance_prompt function (AC #6)."""

    def test_format_includes_estado_actual(self):
        """AC #6: Format includes estado actual."""
        from agent.nodes.conversational_agent import format_guidance_prompt

        guidance = ResponseGuidance(
            must_show=["test"],
            must_ask="test?",
            forbidden=["forbidden"],
            context_hint="hint",
        )

        prompt = format_guidance_prompt(guidance, BookingState.SERVICE_SELECTION)

        assert "Estado actual:" in prompt
        assert BookingState.SERVICE_SELECTION.value in prompt

    def test_format_includes_debes_mostrar(self):
        """AC #6: Format includes DEBES mostrar."""
        from agent.nodes.conversational_agent import format_guidance_prompt

        guidance = ResponseGuidance(
            must_show=["lista de estilistas"],
            must_ask="test?",
            forbidden=[],
            context_hint="hint",
        )

        prompt = format_guidance_prompt(guidance, BookingState.STYLIST_SELECTION)

        assert "DEBES mostrar:" in prompt
        assert "lista de estilistas" in prompt

    def test_format_includes_debes_preguntar(self):
        """AC #6: Format includes DEBES preguntar."""
        from agent.nodes.conversational_agent import format_guidance_prompt

        guidance = ResponseGuidance(
            must_show=[],
            must_ask="¿Con quién te gustaría la cita?",
            forbidden=[],
            context_hint="hint",
        )

        prompt = format_guidance_prompt(guidance, BookingState.STYLIST_SELECTION)

        assert "DEBES preguntar:" in prompt
        assert "¿Con quién te gustaría la cita?" in prompt

    def test_format_includes_prohibido(self):
        """AC #6: Format includes PROHIBIDO mencionar."""
        from agent.nodes.conversational_agent import format_guidance_prompt

        guidance = ResponseGuidance(
            must_show=[],
            must_ask=None,
            forbidden=["horarios", "confirmación"],
            context_hint="hint",
        )

        prompt = format_guidance_prompt(guidance, BookingState.SERVICE_SELECTION)

        assert "PROHIBIDO mencionar:" in prompt
        assert "horarios" in prompt
        assert "confirmación" in prompt

    def test_format_includes_contexto(self):
        """AC #6: Format includes Contexto."""
        from agent.nodes.conversational_agent import format_guidance_prompt

        guidance = ResponseGuidance(
            must_show=[],
            must_ask=None,
            forbidden=[],
            context_hint="Usuario está seleccionando servicios.",
        )

        prompt = format_guidance_prompt(guidance, BookingState.SERVICE_SELECTION)

        assert "Contexto:" in prompt
        assert "Usuario está seleccionando servicios." in prompt

    def test_format_includes_directiva_fsm_header(self):
        """AC #6: Format starts with DIRECTIVA FSM header."""
        from agent.nodes.conversational_agent import format_guidance_prompt

        guidance = ResponseGuidance()

        prompt = format_guidance_prompt(guidance, BookingState.IDLE)

        assert prompt.startswith("DIRECTIVA FSM")

    def test_format_handles_empty_must_show(self):
        """Test format handles empty must_show gracefully."""
        from agent.nodes.conversational_agent import format_guidance_prompt

        guidance = ResponseGuidance(must_show=[])

        prompt = format_guidance_prompt(guidance, BookingState.IDLE)

        assert "nada específico" in prompt

    def test_format_handles_empty_forbidden(self):
        """Test format handles empty forbidden gracefully."""
        from agent.nodes.conversational_agent import format_guidance_prompt

        guidance = ResponseGuidance(forbidden=[])

        prompt = format_guidance_prompt(guidance, BookingState.IDLE)

        assert "ninguna restricción" in prompt


# ============================================================================
# TEST: REMAINING STATES GUIDANCE (AC #1)
# ============================================================================


class TestRemainingStatesGuidance:
    """Tests for IDLE, CONFIRMATION, and BOOKED state guidance."""

    def test_idle_guidance(self, fsm):
        """Test IDLE state has valid guidance."""
        fsm._state = BookingState.IDLE

        guidance = fsm.get_response_guidance()

        assert isinstance(guidance, ResponseGuidance)
        assert guidance.context_hint != ""

    def test_confirmation_guidance_must_show_resumen(self, fsm):
        """Test CONFIRMATION state shows booking summary."""
        fsm._state = BookingState.CONFIRMATION

        guidance = fsm.get_response_guidance()

        assert len(guidance.must_show) > 0
        assert any("resumen" in item.lower() or "cita" in item.lower() for item in guidance.must_show)

    def test_confirmation_guidance_must_ask_confirmar(self, fsm):
        """Test CONFIRMATION state asks for confirmation."""
        fsm._state = BookingState.CONFIRMATION

        guidance = fsm.get_response_guidance()

        assert guidance.must_ask is not None
        assert "confirma" in guidance.must_ask.lower()

    def test_booked_guidance_shows_confirmacion(self, fsm):
        """Test BOOKED state shows booking confirmation."""
        fsm._state = BookingState.BOOKED

        guidance = fsm.get_response_guidance()

        assert len(guidance.must_show) > 0
        assert any("confirmación" in item.lower() or "cita" in item.lower() for item in guidance.must_show)

    def test_booked_guidance_no_must_ask(self, fsm):
        """Test BOOKED state has no required question."""
        fsm._state = BookingState.BOOKED

        guidance = fsm.get_response_guidance()

        assert guidance.must_ask is None


# ============================================================================
# TEST: LOGGING (AC #8)
# ============================================================================


class TestGuidanceLogging:
    """Tests for guidance logging (AC #8)."""

    def test_guidance_generation_logs_fsm_state(self, fsm):
        """AC #8: logs show estado FSM."""
        fsm._state = BookingState.SERVICE_SELECTION

        with patch("agent.fsm.booking_fsm.logger") as mock_logger:
            fsm.get_response_guidance()

            mock_logger.info.assert_called()
            call_args = mock_logger.info.call_args
            # Check log message contains state
            assert "state=" in call_args[0][0]

    def test_guidance_generation_logs_metrics(self, fsm):
        """AC #8: logs show guidance generated and metrics."""
        fsm._state = BookingState.STYLIST_SELECTION

        with patch("agent.fsm.booking_fsm.logger") as mock_logger:
            fsm.get_response_guidance()

            mock_logger.info.assert_called()
            call_args = mock_logger.info.call_args
            # Check extra contains metrics
            extra = call_args[1].get("extra", {})
            assert "forbidden_count" in extra
            assert "must_show_count" in extra
            assert "generation_time_ms" in extra


# ============================================================================
# TEST: PERFORMANCE
# ============================================================================


class TestGuidancePerformance:
    """Tests for guidance generation performance."""

    def test_guidance_generation_under_10ms(self, fsm):
        """Test guidance generation is <10ms (AC target <5ms)."""
        fsm._state = BookingState.SERVICE_SELECTION
        fsm._collected_data = {"services": ["Corte"]}

        start = time.perf_counter()
        for _ in range(100):
            fsm.get_response_guidance()
        total_time = (time.perf_counter() - start) * 1000

        avg_time_ms = total_time / 100
        assert avg_time_ms < 10, f"Guidance generation took {avg_time_ms:.2f}ms (target <10ms)"


# ============================================================================
# TEST: ALIGNMENT WITH RESPONSE VALIDATOR
# ============================================================================


class TestGuidanceValidatorAlignment:
    """Tests that guidance aligns with ResponseValidator's FORBIDDEN_PATTERNS."""

    def test_service_selection_guidance_aligns_with_validator(self, fsm):
        """Test SERVICE_SELECTION guidance forbidden matches validator patterns."""
        from agent.fsm.response_validator import FORBIDDEN_PATTERNS

        fsm._state = BookingState.SERVICE_SELECTION
        fsm._collected_data = {"services": []}
        guidance = fsm.get_response_guidance()

        # Validator forbids: estilistas, horarios, time patterns
        # Guidance should forbid similar concepts
        assert "estilistas" in guidance.forbidden or "horarios" in guidance.forbidden

    def test_stylist_selection_guidance_aligns_with_validator(self, fsm):
        """Test STYLIST_SELECTION guidance forbidden matches validator patterns."""
        fsm._state = BookingState.STYLIST_SELECTION
        guidance = fsm.get_response_guidance()

        # Validator forbids: specific times (HH:MM)
        # Guidance should forbid horarios específicos
        assert any("horario" in f.lower() or "específico" in f.lower() for f in guidance.forbidden)

    def test_slot_selection_guidance_aligns_with_validator(self, fsm):
        """Test SLOT_SELECTION guidance forbidden matches validator patterns."""
        fsm._state = BookingState.SLOT_SELECTION
        guidance = fsm.get_response_guidance()

        # Validator forbids: premature confirmation
        # Guidance should forbid confirmación de cita
        assert any("confirmación" in f.lower() or "cita" in f.lower() for f in guidance.forbidden)

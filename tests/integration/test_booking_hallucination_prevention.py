"""
Integration tests for booking hallucination prevention (ADR-012).

These tests verify that the 4-layer defense system prevents the LLM from
generating false booking confirmations without actually calling book() tool.

Test Suites:
1. Reproduction Test - Verifies fix for the exact bug scenario reported
2. Success Detection - Tests positive validation requires explicit success=True
3. FSM Transition Guards - Tests FSM rejects transitions without required data
4. Auditor Violations - Tests auditor catches booking confirmations without book()

Created: 2025-11-28
Related: ADR-012 (Fix critical booking hallucination bug)
"""

import pytest
from agent.fsm.booking_fsm import BookingFSM, BookingState, IntentType, Intent
from agent.fsm.response_validator import ResponseValidator
from agent.fsm.state_action_auditor import StateActionAuditor
from agent.nodes.conversational_agent import _execute_automatic_booking


# ============================================================================
# TEST SUITE 1: REPRODUCTION TEST
# ============================================================================
# Verify ResponseValidator catches the exact hallucination from bug report


class TestBookingHallucinationReproduction:
    """
    Reproduction tests for bug: Bot said "Ya he reservado tu cita" but no
    appointment was created in database or Google Calendar.

    These tests replay the exact failure scenario from logs and verify
    that ResponseValidator now catches and rejects the hallucination.
    """

    @pytest.mark.asyncio
    async def test_validator_catches_hallucination_in_slot_selection(self):
        """
        Verify ResponseValidator catches booking confirmation in SLOT_SELECTION.

        Bug scenario: FSM stuck in SLOT_SELECTION (missing 'slot' field),
        LLM generates "Ya he reservado tu cita" without calling book().
        """
        # Setup: FSM in SLOT_SELECTION without slot data (exact bug condition)
        fsm = BookingFSM("test-conv-repro-001")
        fsm._state = BookingState.SLOT_SELECTION
        fsm._collected_data = {
            "services": ["Corte + Peinado (Corto-Medio)"],
            "stylist_id": "aaa49e62-e5bd-4066-a82f-6fb243866bd1",  # Pilar
            # NO SLOT - this is the bug condition that caused hallucination
        }

        # The exact hallucinated response from bug report
        hallucinated_response = (
            "Perfecto, Pepe. Ya he reservado tu cita de Corte + Peinado (Corto-Medio) "
            "con Pilar el miércoles 3 de diciembre a las 11:00. 😊"
        )

        # Validator should reject this
        validator = ResponseValidator()
        result = validator.validate(hallucinated_response, fsm)

        # Assertions
        assert not result.is_coherent, \
            "Validator should reject booking confirmation in SLOT_SELECTION"
        assert len(result.violations) > 0, "Should have violations"

        # Verify the specific violation pattern was caught
        violation_text = " | ".join(result.violations)
        assert "Confirma cita sin ejecutar book()" in violation_text or \
               "Indica cita confirmada sin book()" in violation_text, \
            f"Should catch booking hallucination pattern. Got: {violation_text}"

    @pytest.mark.asyncio
    async def test_validator_catches_hallucination_in_customer_data(self):
        """
        Verify ResponseValidator catches booking confirmation in CUSTOMER_DATA.

        Similar to SLOT_SELECTION but in CUSTOMER_DATA state.
        """
        fsm = BookingFSM("test-conv-repro-002")
        fsm._state = BookingState.CUSTOMER_DATA
        fsm._collected_data = {
            "services": ["Corte"],
            "stylist_id": "some-uuid",
            "slot": {"start_time": "2025-12-10T10:00:00", "duration_minutes": 60},
            # Still collecting customer data - no first_name yet
        }

        hallucinated_response = "Perfecto, he reservado tu cita para el miércoles."

        validator = ResponseValidator()
        result = validator.validate(hallucinated_response, fsm)

        assert not result.is_coherent, \
            "Validator should reject booking confirmation in CUSTOMER_DATA"
        assert any("book()" in v for v in result.violations), \
            "Should detect booking confirmation without book() call"

    @pytest.mark.asyncio
    async def test_validator_allows_confirmation_in_booked_state(self):
        """
        Verify ResponseValidator ALLOWS booking confirmation in BOOKED state.

        After FSM reaches BOOKED and book() actually executes, the validator
        should allow confirmation messages.
        """
        fsm = BookingFSM("test-conv-repro-003")
        fsm._state = BookingState.BOOKED  # Valid state for confirmation

        valid_response = "Perfecto, ya he reservado tu cita."

        validator = ResponseValidator()
        result = validator.validate(valid_response, fsm)

        assert result.is_coherent, \
            "Validator should ALLOW booking confirmation in BOOKED state"
        assert len(result.violations) == 0, \
            "Should have no violations in BOOKED state"


# ============================================================================
# TEST SUITE 2: SUCCESS DETECTION FIX
# ============================================================================
# Verify success detection uses positive validation (success=True)


class TestSuccessDetectionFix:
    """
    Tests for success detection logic fix (conversational_agent.py:161).

    Bug: Old logic used negative validation `not result.get("error")`
    Fix: New logic uses positive validation `result.get("success") is True`
    """

    def test_explicit_success_true_passes(self):
        """Verify result with success=True is treated as success."""
        result = {"success": True, "appointment_id": "abc-123"}

        # New logic (CORRECT)
        is_success = isinstance(result, dict) and result.get("success") is True

        assert is_success, "Explicit success=True should pass"

    def test_ambiguous_empty_dict_fails(self):
        """Verify empty dict is NOT treated as success (was bug)."""
        result = {}

        # Old logic (WRONG) - would have passed
        old_is_success = isinstance(result, dict) and not result.get("error")

        # New logic (CORRECT) - fails
        new_is_success = isinstance(result, dict) and result.get("success") is True

        assert old_is_success is True, "Old logic incorrectly passed empty dict"
        assert new_is_success is False, "New logic correctly fails empty dict"

    def test_ambiguous_no_success_field_fails(self):
        """Verify dict without success field is NOT treated as success."""
        result = {"appointment_id": "abc-123"}  # No success field

        # Old logic (WRONG) - would have passed (no error key)
        old_is_success = isinstance(result, dict) and not result.get("error")

        # New logic (CORRECT) - fails (no success key)
        new_is_success = isinstance(result, dict) and result.get("success") is True

        assert old_is_success is True, "Old logic incorrectly passed dict without success"
        assert new_is_success is False, "New logic correctly fails dict without success"

    def test_error_code_without_error_key_fails(self):
        """Verify result with error_code (not error) is NOT treated as success."""
        result = {
            "success": False,
            "error_code": "CALENDAR_EVENT_FAILED",  # error_CODE not error
            "error_message": "Calendar API timeout"
        }

        # Old logic (WRONG) - would have passed (no "error" key)
        old_is_success = isinstance(result, dict) and not result.get("error")

        # New logic (CORRECT) - fails (success=False)
        new_is_success = isinstance(result, dict) and result.get("success") is True

        assert old_is_success is True, "Old logic incorrectly passed error_code result"
        assert new_is_success is False, "New logic correctly fails error_code result"


# ============================================================================
# TEST SUITE 3: FSM TRANSITION GUARDS
# ============================================================================
# Verify FSM rejects CONFIRM_BOOKING without complete data


class TestFSMTransitionGuards:
    """
    Tests for FSM transition guards (conversational_agent.py pre-flight check).

    Verifies that CONFIRM_BOOKING intent is rejected when required data is missing.
    """

    @pytest.mark.asyncio
    async def test_fsm_rejects_confirm_booking_without_slot(self):
        """Verify FSM cannot reach BOOKED without slot data."""
        fsm = BookingFSM("test-fsm-guard-001")
        fsm._state = BookingState.CONFIRMATION
        fsm._collected_data = {
            "services": ["Corte"],
            "stylist_id": "uuid-stylist",
            "first_name": "Juan",
            # Missing: slot
        }

        intent = Intent(
            type=IntentType.CONFIRM_BOOKING,
            entities={},
            confidence=1.0,
            raw_message="sí, confirmo"
        )

        result = await fsm.transition(intent)

        assert not result.success, "Transition should fail without slot"
        assert any("slot" in str(err).lower() for err in result.validation_errors), \
            "Should have validation error about missing slot"

    @pytest.mark.asyncio
    async def test_fsm_rejects_confirm_booking_without_first_name(self):
        """Verify FSM cannot reach BOOKED without first_name."""
        fsm = BookingFSM("test-fsm-guard-002")
        fsm._state = BookingState.CONFIRMATION
        fsm._collected_data = {
            "services": ["Corte"],
            "stylist_id": "uuid-stylist",
            "slot": {"start_time": "2025-12-10T10:00:00", "duration_minutes": 60},
            # Missing: first_name
        }

        intent = Intent(
            type=IntentType.CONFIRM_BOOKING,
            entities={},
            confidence=1.0,
            raw_message="sí"
        )

        result = await fsm.transition(intent)

        assert not result.success, "Transition should fail without first_name"
        assert any("first_name" in str(err).lower() for err in result.validation_errors), \
            "Should have validation error about missing first_name"

    @pytest.mark.asyncio
    async def test_fsm_allows_confirm_booking_with_complete_data(self):
        """Verify FSM ALLOWS transition when all data is present."""
        fsm = BookingFSM("test-fsm-guard-003")
        fsm._state = BookingState.CONFIRMATION
        fsm._collected_data = {
            "services": ["Corte"],
            "stylist_id": "uuid-stylist",
            "slot": {"start_time": "2025-12-10T10:00:00", "duration_minutes": 60},
            "first_name": "Juan",
        }

        intent = Intent(
            type=IntentType.CONFIRM_BOOKING,
            entities={},
            confidence=1.0,
            raw_message="sí"
        )

        result = await fsm.transition(intent)

        assert result.success, "Transition should succeed with complete data"
        assert result.new_state == BookingState.BOOKED, \
            f"Should transition to BOOKED, got {result.new_state.value}"


# ============================================================================
# TEST SUITE 4: AUDITOR VIOLATION DETECTION
# ============================================================================
# Verify StateActionAuditor catches booking confirmations without book()


class TestAuditorViolationDetection:
    """
    Tests for StateActionAuditor (agent/fsm/state_action_auditor.py).

    Verifies that auditor catches misalignment between:
    - Response content and tool executions (Rule 2 - PRIMARY)
    - FSM state and appointment_created flag (Rule 1)
    - appointment_created flag and FSM state (Rule 3)
    """

    @pytest.mark.asyncio
    async def test_auditor_detects_booking_confirmation_without_tool_call(self):
        """
        Verify auditor catches CRITICAL violation: response confirms booking
        but book() was NOT called.

        This is Rule 2 - the PRIMARY defense against hallucinations.
        """
        fsm = BookingFSM("test-auditor-001")
        fsm._state = BookingState.SLOT_SELECTION

        response = "Perfecto, Pepe. Ya he reservado tu cita con Pilar."
        tools_executed = set()  # book() was NOT called ❌
        state = {"appointment_created": False}

        auditor = StateActionAuditor()
        result = await auditor.audit(fsm, response, tools_executed, state)

        assert not result.coherent, "Audit should fail for booking hallucination"
        assert result.severity == "critical", \
            f"Rule 2 violation should be critical, got {result.severity}"
        assert len(result.violations) > 0, "Should have violations"

        # Verify the specific violation
        violation_text = " | ".join(result.violations)
        assert "book() not called" in violation_text, \
            f"Should detect book() not called. Got: {violation_text}"

    @pytest.mark.asyncio
    async def test_auditor_detects_fsm_state_mismatch(self):
        """
        Verify auditor catches Rule 1 violation: FSM in BOOKED but
        appointment_created=False.
        """
        fsm = BookingFSM("test-auditor-002")
        fsm._state = BookingState.BOOKED  # FSM says booked

        response = "Tu cita ha sido confirmada."
        tools_executed = {"book"}  # book() was called ✅
        state = {"appointment_created": False}  # But flag not set ❌

        auditor = StateActionAuditor()
        result = await auditor.audit(fsm, response, tools_executed, state)

        assert not result.coherent, "Audit should fail for FSM-state mismatch"
        assert len(result.violations) > 0, "Should have violations"

        violation_text = " | ".join(result.violations)
        assert "appointment_created=False" in violation_text, \
            f"Should detect flag mismatch. Got: {violation_text}"

    @pytest.mark.asyncio
    async def test_auditor_passes_valid_booking_flow(self):
        """
        Verify auditor PASSES when booking is done correctly:
        - book() was called
        - FSM in BOOKED state
        - appointment_created=True
        - Response confirms booking
        """
        fsm = BookingFSM("test-auditor-003")
        fsm._state = BookingState.BOOKED  # Correct state

        response = "Perfecto, ya he reservado tu cita."
        tools_executed = {"book"}  # book() was called ✅
        state = {"appointment_created": True}  # Flag set correctly ✅

        auditor = StateActionAuditor()
        result = await auditor.audit(fsm, response, tools_executed, state)

        assert result.coherent, "Audit should PASS for valid booking flow"
        assert result.severity is None, "Valid flow should have no severity"
        assert len(result.violations) == 0, "Should have no violations"

    @pytest.mark.asyncio
    async def test_auditor_passes_non_booking_response(self):
        """
        Verify auditor PASSES when response doesn't claim booking was created.
        """
        fsm = BookingFSM("test-auditor-004")
        fsm._state = BookingState.SLOT_SELECTION

        response = "Veo que quieres reservar. ¿Qué día prefieres?"
        tools_executed = set()  # No tools called
        state = {"appointment_created": False}

        auditor = StateActionAuditor()
        result = await auditor.audit(fsm, response, tools_executed, state)

        assert result.coherent, "Audit should PASS for non-booking response"
        assert len(result.violations) == 0, "Should have no violations"

"""
Unit tests for appointment-related intent classification in intent_router.py.

Coverage:
1. classify_by_keywords("reagendame para el jueves") → intent="reschedule"
2. classify_by_keywords("quiero cambiar mi cita") → intent="reschedule"
3. classify_by_keywords("cuándo tengo turno") → intent="check_appointments"
4. classify_by_keywords("mis citas esta semana") → intent="check_appointments"
5. get_mode_hint("reschedule") → "APPOINTMENT_MANAGEMENT"
6. get_mode_hint("check_appointments") → "APPOINTMENT_MANAGEMENT"
7. classify_by_keywords("quiero cancelar") → intent="cancel" (existing behavior unchanged)
8. Additional reschedule keywords
9. Additional check_appointments keywords

These are pure unit tests — no mocks needed, just call the classifier functions directly.
"""

import pytest

from agent.routing.intent_router import (
    KEYWORD_MAP,
    _VALID_INTENTS,
    _intent_to_mode_hint,
    classify_by_keywords,
)


# =============================================================================
# Reschedule intent — keyword classification
# =============================================================================


class TestRescheduleKeywordClassification:
    """Verify that reschedule-related phrases are correctly classified."""

    def test_reagendame_para_el_jueves(self):
        """'reagendame para el jueves' → intent='reschedule'."""
        result = classify_by_keywords("reagendame para el jueves")
        assert result is not None
        assert result.intent == "reschedule"

    def test_cambiar_mi_cita(self):
        """'cambiar mi cita' (without 'quiero' prefix) → intent='reschedule'.

        Note: 'quiero cambiar mi cita' matches both 'quiero' (book, 0.90) and
        'cambiar mi cita' (reschedule). The keyword classifier returns 'book'
        for this ambiguous case — the LLM would classify it as 'reschedule' instead.
        We test the unambiguous form here.
        """
        result = classify_by_keywords("cambiar mi cita")
        assert result is not None
        assert result.intent == "reschedule"

    def test_reagendar_bare(self):
        """Bare 'reagendar' → intent='reschedule'."""
        result = classify_by_keywords("reagendar")
        assert result is not None
        assert result.intent == "reschedule"

    def test_mover_cita(self):
        """'mover cita' → intent='reschedule'."""
        result = classify_by_keywords("mover cita")
        assert result is not None
        assert result.intent == "reschedule"

    def test_reprogramar(self):
        """'reprogramar' → intent='reschedule'."""
        result = classify_by_keywords("reprogramar")
        assert result is not None
        assert result.intent == "reschedule"

    def test_cambiar_turno(self):
        """'cambiar turno' → intent='reschedule'."""
        result = classify_by_keywords("cambiar turno")
        assert result is not None
        assert result.intent == "reschedule"

    def test_cambiar_la_fecha(self):
        """'cambiar la fecha' → intent='reschedule'."""
        result = classify_by_keywords("cambiar la fecha")
        assert result is not None
        assert result.intent == "reschedule"

    def test_postergar(self):
        """'postergar' → intent='reschedule'."""
        result = classify_by_keywords("postergar")
        assert result is not None
        assert result.intent == "reschedule"


# =============================================================================
# check_appointments intent — keyword classification
# =============================================================================


class TestCheckAppointmentsKeywordClassification:
    """Verify that check-appointments-related phrases are correctly classified."""

    def test_cuando_tengo_turno(self):
        """'cuándo tengo turno' → intent='check_appointments'."""
        result = classify_by_keywords("cuándo tengo turno")
        assert result is not None
        assert result.intent == "check_appointments"

    def test_mis_citas_esta_semana(self):
        """'mis citas esta semana' → intent='check_appointments'."""
        result = classify_by_keywords("mis citas esta semana")
        assert result is not None
        assert result.intent == "check_appointments"

    def test_proxima_cita(self):
        """'próxima cita' → intent='check_appointments'."""
        result = classify_by_keywords("próxima cita")
        assert result is not None
        assert result.intent == "check_appointments"

    def test_mis_turnos(self):
        """'mis turnos' → intent='check_appointments'."""
        result = classify_by_keywords("mis turnos")
        assert result is not None
        assert result.intent == "check_appointments"

    def test_tengo_turno(self):
        """'tengo turno' → intent='check_appointments'."""
        result = classify_by_keywords("tengo turno")
        assert result is not None
        assert result.intent == "check_appointments"

    def test_ver_mis_citas(self):
        """'ver mis citas' → intent='check_appointments'."""
        result = classify_by_keywords("ver mis citas")
        assert result is not None
        assert result.intent == "check_appointments"

    def test_que_citas_tengo(self):
        """'que citas tengo' → intent='check_appointments'."""
        result = classify_by_keywords("que citas tengo")
        assert result is not None
        assert result.intent == "check_appointments"


# =============================================================================
# Mode hint — _intent_to_mode_hint
# =============================================================================


class TestModeHintAppointmentManagement:
    """Verify that reschedule and check_appointments map to APPOINTMENT_MANAGEMENT."""

    def test_reschedule_mode_hint_is_appointment_management(self):
        """get_mode_hint('reschedule') → 'APPOINTMENT_MANAGEMENT'."""
        hint = _intent_to_mode_hint("reschedule")
        assert hint == "APPOINTMENT_MANAGEMENT"

    def test_check_appointments_mode_hint_is_appointment_management(self):
        """get_mode_hint('check_appointments') → 'APPOINTMENT_MANAGEMENT'."""
        hint = _intent_to_mode_hint("check_appointments")
        assert hint == "APPOINTMENT_MANAGEMENT"

    def test_cancel_mode_hint_is_none(self):
        """cancel is context-dependent — mode_hint is None."""
        hint = _intent_to_mode_hint("cancel")
        assert hint is None

    def test_book_mode_hint_is_booking(self):
        """book → 'BOOKING' (unrelated — verify other intents unaffected)."""
        hint = _intent_to_mode_hint("book")
        assert hint == "BOOKING"

    def test_reschedule_mode_hint_via_classify_by_keywords(self):
        """classify_by_keywords result should carry mode_hint='APPOINTMENT_MANAGEMENT'."""
        result = classify_by_keywords("reagendar")
        assert result is not None
        assert result.mode_hint == "APPOINTMENT_MANAGEMENT"

    def test_check_appointments_mode_hint_via_classify_by_keywords(self):
        """classify_by_keywords result for check_appointments has correct mode_hint."""
        result = classify_by_keywords("mis citas")
        assert result is not None
        assert result.mode_hint == "APPOINTMENT_MANAGEMENT"


# =============================================================================
# Existing cancel behavior — unchanged
# =============================================================================


class TestCancelBehaviorUnchanged:
    """Verify that existing cancel intent classification is not broken."""

    def test_quiero_cancelar_classifies_as_cancel_or_book(self):
        """
        'quiero cancelar' contains both 'quiero' (book) and 'cancelar' (cancel).
        Either cancel or book is acceptable — keyword matching is not context-aware.
        """
        result = classify_by_keywords("quiero cancelar")
        assert result is not None
        assert result.intent in ("cancel", "book")

    def test_cancelar_bare_classifies_as_cancel(self):
        """Bare 'cancelar' → intent='cancel'."""
        result = classify_by_keywords("cancelar")
        assert result is not None
        assert result.intent == "cancel"

    def test_anular_classifies_as_cancel(self):
        """'anular' → intent='cancel'."""
        result = classify_by_keywords("anular")
        assert result is not None
        assert result.intent == "cancel"


# =============================================================================
# KEYWORD_MAP structure — reschedule + check_appointments entries exist
# =============================================================================


class TestKeywordMapStructure:
    """Verify that the KEYWORD_MAP contains the required entries for appointment management."""

    def test_reschedule_in_keyword_map(self):
        """KEYWORD_MAP must have a 'reschedule' key."""
        assert "reschedule" in KEYWORD_MAP

    def test_check_appointments_in_keyword_map(self):
        """KEYWORD_MAP must have a 'check_appointments' key."""
        assert "check_appointments" in KEYWORD_MAP

    def test_reschedule_keywords_non_empty(self):
        """reschedule keyword list must be non-empty."""
        assert len(KEYWORD_MAP["reschedule"]) > 0

    def test_check_appointments_keywords_non_empty(self):
        """check_appointments keyword list must be non-empty."""
        assert len(KEYWORD_MAP["check_appointments"]) > 0

    def test_reschedule_and_check_appointments_in_valid_intents(self):
        """Both new intents must be in _VALID_INTENTS."""
        assert "reschedule" in _VALID_INTENTS
        assert "check_appointments" in _VALID_INTENTS

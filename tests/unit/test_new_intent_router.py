"""
Unit tests for agent/routing/intent_router.py — keyword + LLM hybrid classifier (v6.0).

Coverage:
- classify_by_keywords() — all intent types, confidence levels, no-match cases
- IntentRouter.classify() — keyword fast path (LLM NOT called when confidence >= 0.8)
- IntentRouter.classify() — LLM fallback when no keyword match
- IntentRouter.classify() — error handling (LLM failure → ambiguous)
- IntentResult fields: intent, confidence, raw_input, mode_hint
- _intent_to_mode_hint mapping

Test naming follows project convention: test_<scenario_description>
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.routing.intent_router import (
    KEYWORD_MAP,
    IntentResult,
    IntentRouter,
    _KEYWORD_MATCH_THRESHOLD,
    classify_by_keywords,
)


# =============================================================================
# classify_by_keywords() — keyword-only, synchronous
# =============================================================================


class TestClassifyByKeywords:
    """Tests for the fast synchronous keyword classifier."""

    # ------ greet intent ------

    def test_hola_returns_greet(self):
        result = classify_by_keywords("hola")
        assert result is not None
        assert result.intent == "greet"

    def test_hola_has_high_confidence(self):
        """Exact match → 0.90 confidence."""
        result = classify_by_keywords("hola")
        assert result is not None
        assert result.confidence == 0.90

    def test_buenas_returns_greet(self):
        result = classify_by_keywords("buenas")
        assert result is not None
        assert result.intent == "greet"

    def test_hola_uppercase_returns_greet(self):
        """Classification is case-insensitive."""
        result = classify_by_keywords("HOLA")
        assert result is not None
        assert result.intent == "greet"

    # ------ book intent ------

    def test_quiero_una_cita_returns_book(self):
        result = classify_by_keywords("quiero una cita")
        assert result is not None
        assert result.intent == "book"

    def test_reservar_returns_book(self):
        result = classify_by_keywords("reservar")
        assert result is not None
        assert result.intent == "book"

    def test_quiero_returns_book(self):
        """'quiero' is a book keyword that appears in the text."""
        result = classify_by_keywords("quiero algo")
        assert result is not None
        assert result.intent == "book"

    # ------ ask_info intent ------

    def test_cuanto_cuesta_returns_ask_info(self):
        result = classify_by_keywords("cuanto cuesta")
        assert result is not None
        assert result.intent == "ask_info"

    def test_precio_returns_ask_info(self):
        result = classify_by_keywords("precio")
        assert result is not None
        assert result.intent == "ask_info"

    def test_horario_returns_ask_info(self):
        result = classify_by_keywords("horario")
        assert result is not None
        assert result.intent == "ask_info"

    # ------ confirm intent ------

    def test_si_returns_confirm(self):
        result = classify_by_keywords("si")
        assert result is not None
        assert result.intent == "confirm"

    def test_si_accented_returns_confirm(self):
        result = classify_by_keywords("sí")
        assert result is not None
        assert result.intent == "confirm"

    def test_ok_returns_confirm(self):
        result = classify_by_keywords("ok")
        assert result is not None
        assert result.intent == "confirm"

    def test_dale_returns_confirm(self):
        result = classify_by_keywords("dale")
        assert result is not None
        assert result.intent == "confirm"

    # ------ reject intent ------

    def test_no_returns_reject(self):
        result = classify_by_keywords("no")
        assert result is not None
        assert result.intent == "reject"

    def test_mejor_no_returns_reject(self):
        result = classify_by_keywords("mejor no")
        assert result is not None
        assert result.intent == "reject"

    # ------ cancel intent ------

    def test_cancelar_returns_cancel(self):
        result = classify_by_keywords("cancelar")
        assert result is not None
        assert result.intent == "cancel"

    def test_quiero_cancelar_returns_cancel_or_book(self):
        """
        'quiero cancelar' contains both 'quiero' (book) and 'cancelar' (cancel).
        The classifier uses the highest confidence match. 'cancelar' is a multi-word
        keyword match and 'quiero' is a single-word match — both at 0.70 confidence.
        The implementation iterates in dict order: whichever is found first wins.
        We verify the text IS classified (not None) and has a reasonable intent.
        """
        result = classify_by_keywords("quiero cancelar")
        assert result is not None
        # Either book or cancel is acceptable — keyword matching is not context-aware
        assert result.intent in ("book", "cancel")

    # ------ escalate intent ------

    def test_hablar_con_una_persona_returns_escalate(self):
        result = classify_by_keywords("hablar con una persona")
        assert result is not None
        assert result.intent == "escalate"

    def test_humano_returns_escalate(self):
        result = classify_by_keywords("humano")
        assert result is not None
        assert result.intent == "escalate"

    def test_urgente_returns_escalate(self):
        result = classify_by_keywords("urgente")
        assert result is not None
        assert result.intent == "escalate"

    # ------ no match ------

    def test_xyz_abc_returns_none(self):
        """Gibberish with no keyword match → None."""
        result = classify_by_keywords("xyz abc pqr")
        assert result is None

    def test_empty_string_returns_none(self):
        result = classify_by_keywords("")
        assert result is None

    def test_whitespace_only_returns_none(self):
        result = classify_by_keywords("   ")
        assert result is None

    # ------ confidence levels ------

    def test_exact_match_confidence_090(self):
        """Exact full-text match → 0.90 (HIGH)."""
        result = classify_by_keywords("hola")
        assert result is not None
        assert result.confidence == 0.90

    def test_starts_with_match_confidence_090(self):
        """Text starts with keyword → 0.90 (HIGH)."""
        result = classify_by_keywords("hola, buenos días")
        assert result is not None
        assert result.confidence == 0.90

    # ------ raw_input preserved ------

    def test_raw_input_preserved(self):
        """raw_input field stores the original text when a keyword matches."""
        text = "reservar una cita"
        result = classify_by_keywords(text)
        assert result is not None
        assert result.raw_input == text

    def test_greet_plus_book_defers_to_llm(self):
        """Multi-intent conflict: greeting + booking → None (LLM fallback).

        'Hola, quiero una cita' contains both greet ('hola') and book ('quiero')
        keywords. The keyword classifier should return None to defer to the
        LLM, which is better at classifying the dominant intent.
        """
        result = classify_by_keywords("Hola, quiero una cita")
        assert result is None

    def test_greet_plus_ask_info_defers_to_llm(self):
        """Multi-intent conflict: greeting + info query → None (LLM fallback)."""
        result = classify_by_keywords("Hola, cuánto cuesta un corte")
        assert result is None

    def test_greet_plus_cancel_defers_to_llm(self):
        """Multi-intent conflict: greeting + cancel → None (LLM fallback)."""
        result = classify_by_keywords("Buenas, quiero cancelar mi cita")
        assert result is None

    def test_greet_plus_escalate_defers_to_llm(self):
        """Multi-intent conflict: greeting + escalate → None (LLM fallback)."""
        result = classify_by_keywords("Hola, necesito hablar con una persona")
        assert result is None

    def test_pure_greet_still_works(self):
        """Pure greeting without actionable intent still returns greet."""
        result = classify_by_keywords("Hola, buenas tardes")
        assert result is not None
        assert result.intent == "greet"

    def test_pure_book_still_works(self):
        """Pure booking without greeting still returns book."""
        result = classify_by_keywords("Quiero una cita para mañana")
        assert result is not None
        assert result.intent == "book"

    # ------ mode_hint ------

    def test_greet_mode_hint_is_greeting(self):
        result = classify_by_keywords("hola")
        assert result is not None
        assert result.mode_hint == "GREETING"

    def test_book_mode_hint_is_booking(self):
        result = classify_by_keywords("quiero una cita")
        assert result is not None
        assert result.mode_hint == "BOOKING"

    def test_ask_info_mode_hint_is_general(self):
        result = classify_by_keywords("precio")
        assert result is not None
        assert result.mode_hint == "GENERAL"

    def test_escalate_mode_hint_is_escalation(self):
        result = classify_by_keywords("hablar con una persona")
        assert result is not None
        assert result.mode_hint == "ESCALATION"

    def test_confirm_mode_hint_is_none(self):
        """confirm/reject are context-dependent — no mode hint."""
        result = classify_by_keywords("si")
        assert result is not None
        assert result.mode_hint is None

    def test_reject_mode_hint_is_none(self):
        result = classify_by_keywords("no")
        assert result is not None
        assert result.mode_hint is None


# =============================================================================
# IntentRouter.classify() — hybrid keyword + LLM
# =============================================================================


class TestIntentRouterClassify:
    """Tests for the full hybrid IntentRouter.classify() method."""

    def _make_mock_llm(self, response_json: str | None = None) -> AsyncMock:
        """Build a mock LLM client for IntentRouter."""
        mock = AsyncMock()
        if response_json is not None:
            mock_response = MagicMock()
            mock_response.content = response_json
            mock.ainvoke = AsyncMock(return_value=mock_response)
        return mock

    # ------ Keyword fast path — LLM must NOT be called ------

    async def test_hola_does_not_call_llm(self):
        """High-confidence keyword match → LLM is never called."""
        mock_llm = self._make_mock_llm()
        router = IntentRouter(llm_client=mock_llm)

        result = await router.classify("hola")

        assert result.intent == "greet"
        mock_llm.ainvoke.assert_not_called()

    async def test_quiero_una_cita_does_not_call_llm(self):
        mock_llm = self._make_mock_llm()
        router = IntentRouter(llm_client=mock_llm)

        result = await router.classify("quiero una cita")

        assert result.intent == "book"
        mock_llm.ainvoke.assert_not_called()

    async def test_si_does_not_call_llm(self):
        mock_llm = self._make_mock_llm()
        router = IntentRouter(llm_client=mock_llm)

        result = await router.classify("si")

        assert result.intent == "confirm"
        mock_llm.ainvoke.assert_not_called()

    async def test_no_does_not_call_llm(self):
        mock_llm = self._make_mock_llm()
        router = IntentRouter(llm_client=mock_llm)

        result = await router.classify("no")

        assert result.intent == "reject"
        mock_llm.ainvoke.assert_not_called()

    async def test_cancelar_does_not_call_llm(self):
        mock_llm = self._make_mock_llm()
        router = IntentRouter(llm_client=mock_llm)

        result = await router.classify("cancelar")

        assert result.intent == "cancel"
        mock_llm.ainvoke.assert_not_called()

    async def test_hablar_con_persona_does_not_call_llm(self):
        mock_llm = self._make_mock_llm()
        router = IntentRouter(llm_client=mock_llm)

        result = await router.classify("hablar con una persona")

        assert result.intent == "escalate"
        mock_llm.ainvoke.assert_not_called()

    # ------ LLM fallback — called when no keyword match ------

    async def test_llm_called_when_no_keyword_match(self):
        """When no keyword matches, the LLM must be called."""
        llm_response = json.dumps({"intent": "ask_info", "confidence": 0.7})
        mock_llm = self._make_mock_llm(llm_response)
        router = IntentRouter(llm_client=mock_llm)

        result = await router.classify("xyz abc pqr totally unknown text")

        # LLM was called
        mock_llm.ainvoke.assert_called_once()
        # Result reflects LLM output
        assert result.intent == "ask_info"
        assert result.confidence == 0.7

    async def test_llm_response_parsed_correctly(self):
        """Valid LLM JSON response is parsed into IntentResult."""
        llm_response = json.dumps({"intent": "book", "confidence": 0.85})
        mock_llm = self._make_mock_llm(llm_response)
        router = IntentRouter(llm_client=mock_llm)

        result = await router.classify("Quisiera agendar una sesión de peluquería para el martes")

        assert result.intent == "book"
        assert result.confidence == 0.85

    async def test_llm_response_with_markdown_fences_parsed(self):
        """LLM responses wrapped in ```json ... ``` are handled."""
        llm_response = '```json\n{"intent": "ask_info", "confidence": 0.75}\n```'
        mock_llm = self._make_mock_llm(llm_response)
        router = IntentRouter(llm_client=mock_llm)

        result = await router.classify("cuéntame más sobre los servicios")

        assert result.intent == "ask_info"

    # ------ Error handling — LLM failure ------

    async def test_llm_failure_returns_ambiguous(self):
        """If LLM raises an exception, return ambiguous with confidence=0.0."""
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=ConnectionError("Network error"))
        router = IntentRouter(llm_client=mock_llm)

        result = await router.classify("completely unknown text that needs llm")

        assert result.intent == "ambiguous"
        assert result.confidence == 0.0

    async def test_llm_invalid_json_returns_ambiguous(self):
        """If LLM returns non-JSON, return ambiguous."""
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "not valid json at all"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        router = IntentRouter(llm_client=mock_llm)

        result = await router.classify("some unknown text for llm")

        assert result.intent == "ambiguous"
        assert result.confidence == 0.0

    async def test_llm_unknown_intent_mapped_to_ambiguous(self):
        """LLM response with unknown intent type → ambiguous."""
        llm_response = json.dumps({"intent": "totally_unknown", "confidence": 0.9})
        mock_llm = self._make_mock_llm(llm_response)
        router = IntentRouter(llm_client=mock_llm)

        result = await router.classify("some text that needs llm classification")

        assert result.intent == "ambiguous"

    # ------ Empty input ------

    async def test_empty_text_returns_ambiguous(self):
        mock_llm = self._make_mock_llm()
        router = IntentRouter(llm_client=mock_llm)

        result = await router.classify("")

        assert result.intent == "ambiguous"
        assert result.confidence == 0.0
        mock_llm.ainvoke.assert_not_called()

    # ------ IntentResult clamping ------

    def test_intent_result_confidence_clamped_above_1(self):
        r = IntentResult(intent="greet", confidence=1.5, raw_input="test")
        assert r.confidence == 1.0

    def test_intent_result_confidence_clamped_below_0(self):
        r = IntentResult(intent="greet", confidence=-0.5, raw_input="test")
        assert r.confidence == 0.0

    def test_intent_result_mode_hint_default_none(self):
        r = IntentResult(intent="greet", confidence=0.9, raw_input="test")
        assert r.mode_hint is None

    # ------ current_mode context passed to LLM ------

    async def test_classify_passes_current_mode_to_llm(self):
        """The current_mode is included in the LLM prompt context."""
        llm_response = json.dumps({"intent": "confirm", "confidence": 0.8})
        mock_llm = self._make_mock_llm(llm_response)
        router = IntentRouter(llm_client=mock_llm)

        await router.classify("es que no sé qué quiero hacer", current_mode="BOOKING")

        # LLM was called with messages that include BOOKING context
        call_args = mock_llm.ainvoke.call_args
        messages = call_args[0][0]
        # The human message should include the current_mode
        human_message = messages[1]
        assert "BOOKING" in human_message.content

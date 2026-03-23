"""
Tests for the retry intent in the v6.0 intent router.

Coverage:
- T-1.1: "retry" exists in _VALID_INTENTS
- T-1.2: KEYWORD_MAP["retry"] matches all Spanish retry phrases
- T-1.3: _intent_to_mode_hint("retry") returns None (stay in current mode)
- T-1.3: _LLM_SYSTEM_PROMPT includes retry intent description
- T-1.4: IntentResult.is_retry() convenience method
- T-1.5: classify_by_keywords integration tests for retry phrases
"""

import pytest
from unittest.mock import AsyncMock

from agent.routing.intent_router import (
    IntentResult,
    IntentRouter,
    KEYWORD_MAP,
    _VALID_INTENTS,
    _LLM_SYSTEM_PROMPT,
    _intent_to_mode_hint,
    classify_by_keywords,
)


# ============================================================================
# T-1.1: "retry" in _VALID_INTENTS
# ============================================================================


class TestRetryInValidIntents:
    """Verify 'retry' is a recognized intent."""

    def test_retry_in_valid_intents(self):
        assert "retry" in _VALID_INTENTS

    def test_valid_intents_count(self):
        """9 intents: greet, book, ask_info, confirm, reject, cancel, escalate, retry, ambiguous."""
        assert len(_VALID_INTENTS) == 9


# ============================================================================
# T-1.2: KEYWORD_MAP["retry"] phrases
# ============================================================================


class TestRetryKeywords:
    """Verify KEYWORD_MAP contains all required retry phrases."""

    EXPECTED_PHRASES = [
        "intentar",
        "intentalo",
        "otra vez",
        "de nuevo",
        "reintentar",
        "vuelve a intentar",
        "intenta de nuevo",
        "intentalo de nuevo",
        "volver a intentar",
        "probemos de nuevo",
        "una vez mas",
        "repetir",
    ]

    def test_retry_key_exists(self):
        assert "retry" in KEYWORD_MAP

    @pytest.mark.parametrize("phrase", EXPECTED_PHRASES)
    def test_phrase_present(self, phrase: str):
        assert phrase in KEYWORD_MAP["retry"], f"Missing retry phrase: {phrase!r}"

    def test_phrase_count(self):
        """All 12 phrases are present."""
        assert len(KEYWORD_MAP["retry"]) == 12


# ============================================================================
# T-1.3: _intent_to_mode_hint mapping + LLM prompt
# ============================================================================


class TestRetryModeHint:
    """retry is context-dependent → mode_hint should be None."""

    def test_retry_maps_to_none(self):
        assert _intent_to_mode_hint("retry") is None

    def test_llm_prompt_contains_retry(self):
        assert "retry" in _LLM_SYSTEM_PROMPT

    def test_llm_prompt_retry_description(self):
        """LLM system prompt describes what retry means."""
        assert "volver a intentar" in _LLM_SYSTEM_PROMPT


# ============================================================================
# T-1.4: IntentResult.is_retry() convenience method
# ============================================================================


class TestIntentResultIsRetry:
    """Verify the is_retry() convenience method."""

    def test_is_retry_true(self):
        result = IntentResult(intent="retry", confidence=0.9, raw_input="otra vez")
        assert result.is_retry() is True

    def test_is_retry_false_for_other_intents(self):
        for intent in ("greet", "book", "ask_info", "confirm", "reject", "cancel", "escalate"):
            result = IntentResult(intent=intent, confidence=0.9, raw_input="test")
            assert result.is_retry() is False, f"is_retry() should be False for {intent!r}"

    def test_retry_result_mode_hint_is_none(self):
        """IntentResult for retry should have mode_hint=None."""
        result = IntentResult(
            intent="retry",
            confidence=0.9,
            raw_input="de nuevo",
            mode_hint=_intent_to_mode_hint("retry"),
        )
        assert result.mode_hint is None


# ============================================================================
# T-1.5: classify_by_keywords integration for retry phrases
# ============================================================================


class TestClassifyByKeywordsRetry:
    """Integration: classify_by_keywords correctly classifies retry phrases."""

    @pytest.mark.parametrize(
        "text",
        [
            "intentalo de nuevo",
            "probemos de nuevo",
            "vuelve a intentar",
            "volver a intentar",
            "intenta de nuevo",
            "reintentar",
            "repetir",
            "una vez mas",
        ],
    )
    def test_exact_retry_phrases_high_confidence(self, text: str):
        """Multi-word phrases that match the full text should get 0.90 confidence."""
        result = classify_by_keywords(text)
        assert result is not None, f"Expected IntentResult for {text!r}, got None"
        assert result.intent == "retry", f"Expected retry for {text!r}, got {result.intent!r}"
        assert result.confidence >= 0.80, (
            f"Expected confidence >= 0.80 for {text!r}, got {result.confidence}"
        )

    @pytest.mark.parametrize(
        "text",
        [
            "otra vez",
            "de nuevo",
        ],
    )
    def test_short_retry_phrases(self, text: str):
        """Short retry phrases should match (exact or substring)."""
        result = classify_by_keywords(text)
        assert result is not None, f"Expected IntentResult for {text!r}, got None"
        assert result.intent == "retry", f"Expected retry for {text!r}, got {result.intent!r}"

    def test_retry_in_sentence(self):
        """Retry keyword within a longer sentence → may be substring match."""
        result = classify_by_keywords("puedes reintentar por favor")
        assert result is not None
        assert result.intent == "retry"

    def test_retry_mode_hint_is_none(self):
        """classify_by_keywords returns mode_hint=None for retry."""
        result = classify_by_keywords("reintentar")
        assert result is not None
        assert result.mode_hint is None

    def test_retry_does_not_conflict_with_booking(self):
        """Retry phrases should not be misclassified as booking."""
        result = classify_by_keywords("intentalo de nuevo")
        assert result is not None
        assert result.intent != "book"


class TestClassifyRetryWithLLMFallback:
    """Test IntentRouter.classify() accepts retry from LLM."""

    @pytest.mark.asyncio
    async def test_llm_returns_retry_intent(self):
        """When the LLM returns retry, it should be accepted as a valid intent."""
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AsyncMock(
            content='{"intent": "retry", "confidence": 0.85}'
        )

        router = IntentRouter(llm_client=mock_llm)
        # Use a phrase that won't match any keyword above threshold to force LLM path
        result = await router.classify("hazlo nuevamente por favor")

        assert result.intent == "retry"
        assert result.confidence == 0.85
        assert result.mode_hint is None

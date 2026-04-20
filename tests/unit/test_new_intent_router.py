"""
Unit tests for agent/routing/intent_router.py — keyword-only classifier (v7.1).

Coverage:
- classify_by_keywords() — all intent types, confidence levels, no-match cases
- IntentRouter.classify() — keyword fast path + ambiguous fallthrough (no LLM)
- IntentResult fields: intent, confidence, raw_input, mode_hint
- _intent_to_mode_hint mapping

Test naming follows project convention: test_<scenario_description>
"""

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
        assert result is None

    def test_hola_has_high_confidence(self):
        """Greet defers to LLM — no keyword result to inspect."""
        result = classify_by_keywords("hola")
        assert result is None

    def test_buenas_returns_greet(self):
        result = classify_by_keywords("buenas")
        assert result is None

    def test_hola_uppercase_returns_greet(self):
        """Greet defers to LLM regardless of case."""
        result = classify_by_keywords("HOLA")
        assert result is None

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

    @pytest.mark.parametrize("typo", ["dlae", "dlee", "dales"])
    def test_confirm_intent_typo_variants(self, typo):
        """T-10e: 'dlae', 'dlee', 'dales' are common typos of 'dale' → confirm intent."""
        result = classify_by_keywords(typo)
        assert result is not None
        assert result.intent == "confirm", f"Expected 'confirm' for typo '{typo}', got {result}"

    def test_dale_still_confirm_regression(self):
        """T-10e regression: 'dale' still maps to 'confirm' after typo variants added."""
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
        result = classify_by_keywords("reservar")
        assert result is not None
        assert result.confidence == 0.90

    def test_starts_with_match_confidence_090(self):
        """Text starts with keyword → 0.90 (HIGH)."""
        result = classify_by_keywords("reservar algo para mañana")
        assert result is not None
        assert result.confidence == 0.90

    # ------ raw_input preserved ------

    def test_raw_input_preserved(self):
        """raw_input field stores the original text when a keyword matches."""
        text = "reservar una cita"
        result = classify_by_keywords(text)
        assert result is not None
        assert result.raw_input == text

    def test_greet_plus_book_prioritises_book(self):
        """Multi-intent: greet + book → actionable wins (was: defer to LLM).

        'Hola, quiero una cita' contains greet ('hola') and book ('quiero',
        'cita'). The v6.0 refactor removed the router-layer LLM, so deferring
        with None traps the user in GENERAL mode. Actionable intents now
        win over co-occurring greetings.
        """
        result = classify_by_keywords("Hola, quiero una cita")
        assert result is not None
        assert result.intent == "book"

    def test_greet_plus_ask_info_prioritises_ask_info(self):
        """Multi-intent: greet + ask_info → ask_info wins (priority over book)."""
        result = classify_by_keywords("Hola, cuánto cuesta un corte")
        assert result is not None
        assert result.intent == "ask_info"

    def test_greet_plus_cancel_prioritises_cancel(self):
        """Multi-intent: greet + cancel → cancel wins (priority over book)."""
        result = classify_by_keywords("Buenas, quiero cancelar mi cita")
        assert result is not None
        assert result.intent == "cancel"

    def test_greet_plus_escalate_prioritises_escalate(self):
        """Multi-intent: greet + escalate → escalate wins (highest priority)."""
        result = classify_by_keywords("Hola, necesito hablar con una persona")
        assert result is not None
        assert result.intent == "escalate"

    def test_pure_greet_defers_to_llm(self):
        """Pure greeting without actionable intent defers to LLM (not keyword fast-path)."""
        result = classify_by_keywords("Hola, buenas tardes")
        assert result is None

    def test_pure_book_still_works(self):
        """Pure booking without greeting still returns book."""
        result = classify_by_keywords("Quiero una cita para mañana")
        assert result is not None
        assert result.intent == "book"

    # ------ mode_hint ------

    def test_greet_mode_hint_is_greeting(self):
        """Greet defers to LLM — no keyword result, no mode_hint to inspect."""
        result = classify_by_keywords("hola")
        assert result is None

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
# IntentRouter.classify() — keyword-only (no LLM fallback)
# =============================================================================


class TestIntentRouterClassify:
    """Tests for the keyword-only IntentRouter.classify() method."""

    # ------ Keyword fast path ------

    async def test_hola_returns_ambiguous(self):
        """Greet passthrough → keyword returns None → classify returns ambiguous."""
        router = IntentRouter()

        result = await router.classify("hola")

        # Greet is intentionally deferred (keyword classifier returns None),
        # so the router now surfaces ambiguous and the mode node's LLM resolves
        # the intent with full conversation context.
        assert result.intent == "ambiguous"

    async def test_quiero_una_cita_fast_path(self):
        router = IntentRouter()

        result = await router.classify("quiero una cita")

        assert result.intent == "book"
        assert result.confidence >= _KEYWORD_MATCH_THRESHOLD

    async def test_si_fast_path(self):
        router = IntentRouter()

        result = await router.classify("si")

        assert result.intent == "confirm"

    async def test_no_fast_path(self):
        router = IntentRouter()

        result = await router.classify("no")

        assert result.intent == "reject"

    async def test_cancelar_fast_path(self):
        router = IntentRouter()

        result = await router.classify("cancelar")

        assert result.intent == "cancel"

    async def test_hablar_con_persona_fast_path(self):
        router = IntentRouter()

        result = await router.classify("hablar con una persona")

        assert result.intent == "escalate"

    # ------ Ambiguous fallthrough (no keyword match) ------

    async def test_no_keyword_match_returns_ambiguous(self):
        """When no keyword matches above threshold, classify returns ambiguous
        (mode node's LLM resolves the turn)."""
        router = IntentRouter()

        result = await router.classify("xyz abc pqr totally unknown text")

        assert result.intent == "ambiguous"
        assert result.mode_hint is None

    async def test_ambiguous_preserves_keyword_confidence_when_below_threshold(self):
        """A sub-threshold keyword match still surfaces its confidence for telemetry."""
        router = IntentRouter()

        # A weak substring match sits below _KEYWORD_MATCH_THRESHOLD; the router
        # must still return ambiguous without raising.
        result = await router.classify("esto es otro texto sin intención clara")

        assert result.intent == "ambiguous"
        assert 0.0 <= result.confidence < 1.0

    # ------ Empty input ------

    async def test_empty_text_returns_ambiguous(self):
        router = IntentRouter()

        result = await router.classify("")

        assert result.intent == "ambiguous"
        assert result.confidence == 0.0

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

    # ------ current_mode context routed to the keyword classifier ------

    async def test_classify_passes_current_mode_to_keyword_layer(self):
        """current_mode still drives context shortcuts in classify_by_keywords
        (e.g. BOOKING slot_selection bare-digit handling)."""
        router = IntentRouter()

        # "1" in BOOKING/slot_selection should keyword-classify as confirm(0.95)
        result = await router.classify(
            "1", current_mode="BOOKING", booking_step="slot_selection"
        )

        assert result.intent == "confirm"


# =============================================================================
# New keyword additions — tone-polish-medium
# =============================================================================


@pytest.mark.parametrize(
    "text,expected",
    [
        ("va", "confirm"),
        ("listo", "confirm"),
        ("hecho", "confirm"),
        ("venga ya", "confirm"),
        ("nel", "reject"),
        ("nop", "reject"),
        ("qué va", "reject"),
        ("ni hablar", "reject"),
        ("reclamación", "escalate"),
        ("quiero quejarme", "escalate"),
    ],
)
def test_new_keywords_classify_correctly(text, expected):
    """All keywords added in tone-polish-medium classify to their expected intent."""
    result = classify_by_keywords(text)
    assert result is not None, f"Expected intent '{expected}' for text {text!r}, got None"
    assert result.intent == expected, (
        f"Expected intent '{expected}' for text {text!r}, got '{result.intent}'"
    )


# =============================================================================
# Greet passthrough regression tests — greeting-intent-passthrough
# =============================================================================


@pytest.mark.parametrize(
    "text",
    [
        "como estas",
        "wenas",
        "qué tal",
    ],
)
def test_greet_keywords_defer_to_llm(text):
    """Greet keywords always return None — greet intent is never fast-pathed."""
    result = classify_by_keywords(text)
    assert result is None, f"Expected None for greet text {text!r}, got {result}"


def test_classify_keywords_greet_with_partial_typo_resolves_to_book():
    """Compound greeting + book with typos: 'cortarme' survives, book wins.

    'hola queiro cortarme el eplo' — 'queiro'/'eplo' have typos but 'cortarme'
    still matches the book keyword list. Multi-intent conflict resolution
    prioritises the actionable intent over the greeting.
    """
    result = classify_by_keywords("hola queiro cortarme el eplo")
    assert result is not None
    assert result.intent == "book"


def test_classify_keywords_book_still_fast_path():
    """Non-greet intents with high-confidence keywords still bypass the LLM."""
    result = classify_by_keywords("quiero reservar una cita")
    assert result is not None
    assert result.intent == "book"

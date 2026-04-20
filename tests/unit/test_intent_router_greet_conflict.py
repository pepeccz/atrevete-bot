"""
Regression tests for multi-intent conflict resolution in the v6.0 keyword classifier.

Background: when a greeting co-occurs with an actionable intent ("Hola, quiero
cortarme el pelo"), the classifier used to return None under the assumption that
a router-layer LLM would resolve the ambiguity. The v6.0 refactor removed that
LLM (single-LLM-per-turn, inside mode nodes) but the conflict resolution rule
was never updated, so ambiguity fell through the router and trapped users in
GENERAL mode — observed on conversation_id=5, 2026-04-20.

Fix: prioritise the actionable intent (escalate > cancel > ask_info > book) over
the greeting, preserving the confidence and mode_hint of the actionable match.
ask_info wins over book because ask_info keywords are specific intent signals
while many book keywords are ambiguous topic nouns (e.g. "corte", "pelo").
"""

from agent.routing.intent_router import classify_by_keywords


class TestGreetBookConflictPrioritisesBook:
    """When a message carries both a greeting and booking intent, book wins."""

    def test_hola_quiero_cortarme_el_pelo(self):
        result = classify_by_keywords("Hola, quiero cortarme el pelo")

        assert result is not None, "multi-intent conflict must not return None"
        assert result.intent == "book"
        assert result.confidence >= 0.80
        assert result.mode_hint == "BOOKING"

    def test_buenas_quiero_una_cita(self):
        result = classify_by_keywords("Buenas, quiero una cita")

        assert result is not None
        assert result.intent == "book"
        assert result.confidence >= 0.80
        assert result.mode_hint == "BOOKING"

    def test_hola_me_gustaria_una_reserva(self):
        result = classify_by_keywords("Hola, me gustaría una reserva")

        assert result is not None
        assert result.intent == "book"
        assert result.mode_hint == "BOOKING"


class TestGreetAloneStillDefersToModeNode:
    """Pure greetings keep the existing passthrough behavior (return None)."""

    def test_bare_hola_returns_none(self):
        result = classify_by_keywords("Hola")
        assert result is None, "pure greet must still defer to mode node"

    def test_bare_buenas_returns_none(self):
        result = classify_by_keywords("Buenas")
        assert result is None

    def test_multi_word_greeting_only(self):
        result = classify_by_keywords("Buenos días")
        assert result is None


class TestActionablePriority:
    """Priority order: escalate > cancel > ask_info > book."""

    def test_greet_plus_cancel_prioritises_cancel(self):
        result = classify_by_keywords("Hola, necesito cancelar mi cita")

        assert result is not None
        assert result.intent == "cancel"

    def test_greet_plus_ask_info_prioritises_ask_info(self):
        result = classify_by_keywords("Hola, cuanto cuesta")

        assert result is not None
        assert result.intent == "ask_info"

    def test_ask_info_wins_over_book_when_both_match(self):
        """'cuánto cuesta' (ask_info) + 'corte' (book) → ask_info wins."""
        result = classify_by_keywords("Hola, cuánto cuesta un corte")

        assert result is not None
        assert result.intent == "ask_info"

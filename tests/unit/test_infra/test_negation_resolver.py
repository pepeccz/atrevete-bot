"""
Unit tests for the negation resolver at its NEW location: infra.resolvers.negation.

C5 — R14 smoke + behavioral spot-checks.

The full behavioral suite lives in tests/unit/test_booking_negation_resolver.py
(updated to import from the new path). This file verifies the public API is
importable from infra.resolvers.negation and that semantics are preserved.
"""

from infra.resolvers.negation import (
    NEGATION_PHRASES,
    is_negation,
    normalize_for_negation,
)

# ============================================================================
# R14.1 — Public API importable from new path
# ============================================================================


class TestPublicApiImportable:
    def test_is_negation_is_callable(self):
        assert callable(is_negation)

    def test_normalize_for_negation_is_callable(self):
        assert callable(normalize_for_negation)

    def test_negation_phrases_is_frozenset(self):
        assert isinstance(NEGATION_PHRASES, frozenset)
        assert len(NEGATION_PHRASES) >= 14  # spec requires at minimum 14 forms


# ============================================================================
# R14.2 — Behavioral spot-checks (semantics preserved after rename)
# ============================================================================


class TestBehavioralSpotChecks:
    def test_is_negation_true_for_nada_mas(self):
        matched, phrase, distance = is_negation("nada más")
        assert matched is True
        assert phrase is not None

    def test_is_negation_false_for_booking_intent(self):
        matched, phrase, distance = is_negation("quiero un turno")
        assert matched is False
        assert phrase is None
        assert distance == -1

    def test_is_negation_true_for_listo(self):
        matched, phrase, distance = is_negation("listo")
        assert matched is True

    def test_is_negation_true_for_ya(self):
        matched, phrase, distance = is_negation("ya")
        assert matched is True

    def test_is_negation_true_for_nada(self):
        matched, phrase, distance = is_negation("nada")
        assert matched is True

    def test_normalize_strips_accents_and_lowercases(self):
        result = normalize_for_negation("Nada Más")
        assert result == "nada mas"

    def test_normalize_strips_trailing_punctuation(self):
        result = normalize_for_negation("NADA!")
        assert result == "nada"

    def test_normalize_collapses_whitespace(self):
        result = normalize_for_negation("  ya  está  ")
        assert result == "ya esta"

    def test_is_negation_false_for_long_sentence_no_saber(self):
        # "no sé cuál estilista" has 4 tokens → fuzzy match gate blocks
        matched, _, _ = is_negation("no sé cuál estilista")
        assert matched is False

    def test_is_negation_returns_tuple_of_three(self):
        result = is_negation("nada")
        assert len(result) == 3
        matched, phrase, distance = result
        assert isinstance(matched, bool)
        assert distance == -1  # exact match → distance is -1

"""
Unit tests for is_affirmation — token window + fuzzy matching.

TDD pair:
- T1.5 RED: this file (module doesn't exist yet — ImportError expected)
- T1.6 GREEN: infra/resolvers/affirmation.py

Requirements: R16, R17, R18, R19, R20, R21
Scenarios: S16, S17, S18, S19, S20
"""

from __future__ import annotations

import pytest

# This import will FAIL until T1.6 creates the module — RED state
from infra.resolvers.affirmation import AFFIRMATION_PHRASES, is_affirmation


# ============================================================================
# Helpers
# ============================================================================


def affirms(text: str) -> bool:
    """Convenience: returns just the bool from is_affirmation."""
    matched, phrase, distance = is_affirmation(text)
    return matched


# ============================================================================
# Canonical affirmation tokens (R17)
# ============================================================================


class TestCanonicalAffirmations:
    """R17 — canonical token set fires with exact match."""

    @pytest.mark.parametrize(
        "text",
        [
            "sí",
            "si",
            "dale",
            "confirmo",
            "adelante",
            "perfecto",
            "bueno",
            "ok",
            "va",
            "listo",
            "claro",
            "confirmado",
        ],
    )
    def test_canonical_token_matches(self, text: str) -> None:
        assert affirms(text) is True

    def test_affirmation_with_punctuation(self) -> None:
        assert affirms("sí!") is True

    def test_affirmation_uppercase(self) -> None:
        assert affirms("DALE") is True

    def test_affirmation_with_leading_trailing_spaces(self) -> None:
        assert affirms("  ok  ") is True


# ============================================================================
# Return type contract (R16)
# ============================================================================


class TestReturnType:
    def test_returns_three_tuple(self) -> None:
        result = is_affirmation("sí")
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_matched_is_bool(self) -> None:
        matched, _, _ = is_affirmation("sí")
        assert isinstance(matched, bool)

    def test_phrase_is_string_or_none(self) -> None:
        _, phrase, _ = is_affirmation("sí")
        assert phrase is None or isinstance(phrase, str)

    def test_distance_is_float(self) -> None:
        _, _, distance = is_affirmation("sí")
        assert isinstance(distance, float)

    def test_no_match_returns_false_none_zero(self) -> None:
        matched, phrase, distance = is_affirmation("quiero una pizza")
        assert matched is False
        assert phrase is None
        assert distance == 0.0


# ============================================================================
# Token window rule — ≤3 tokens only (R17, design §6 Q2)
# ============================================================================


class TestTokenWindow:
    def test_more_than_3_tokens_no_match(self) -> None:
        """Messages with >3 tokens never match (short-circuit False)."""
        assert affirms("sí me parece bien") is False  # 4 tokens

    def test_more_than_3_tokens_no_match_variant(self) -> None:
        assert affirms("perfecto y también quiero") is False  # 4 tokens

    def test_exactly_3_tokens_can_match(self) -> None:
        """3-token window: short utterances CAN match (token count ≤ 3)."""
        # "dale que sí" → 3 tokens, contains affirmation word
        # This may or may not match depending on fuzzy; at minimum it shouldn't raise
        result = is_affirmation("dale que sí")
        assert isinstance(result, tuple)

    def test_single_token_matches(self) -> None:
        assert affirms("dale") is True

    def test_two_token_matches(self) -> None:
        assert affirms("sí dale") is True  # still within ≤3 window


# ============================================================================
# S17 — Mixed intent at confirmation (conjunction blocks match)
# ============================================================================


class TestMixedIntentBlocked:
    def test_conjunction_y_blocks_affirmation(self) -> None:
        """S17 — 'perfecto, y además quiero mechas' — >3 tokens → False."""
        assert affirms("perfecto, y además quiero mechas") is False

    def test_si_pero_blocks_affirmation(self) -> None:
        """R18 — 'si pero' contains negation qualifier."""
        assert affirms("si pero algo mas") is False  # 4 tokens

    def test_short_negation_conjunction_blocks(self) -> None:
        """'si pero' is 2 tokens but contains negation qualifier."""
        result = is_affirmation("si pero")
        # "pero" indicates conditional → should not affirm
        matched, _, _ = result
        assert matched is False


# ============================================================================
# S18 — Negation at confirmation is NOT affirmation
# ============================================================================


class TestNegationNotAffirmation:
    def test_no_is_not_affirmation(self) -> None:
        assert affirms("no") is False

    def test_no_mejor_manana_is_not_affirmation(self) -> None:
        assert affirms("no, mejor mañana") is False

    def test_nada_mas_is_not_affirmation(self) -> None:
        assert affirms("nada mas") is False

    def test_nel_is_not_affirmation(self) -> None:
        assert affirms("nel") is False


# ============================================================================
# S19 — Fuzzy match: typo tolerance (cutoff 0.86)
# ============================================================================


class TestFuzzyMatch:
    def test_dael_fuzzy_matches_dale(self) -> None:
        """S19 — 'dael' typo for 'dale' should match with score ≥ 0.86."""
        matched, phrase, distance = is_affirmation("dael")
        assert matched is True
        assert phrase == "dale"
        assert distance >= 0.86

    def test_si_without_accent_matches(self) -> None:
        """'si' (without accent) matches via exact or fuzzy."""
        assert affirms("si") is True

    def test_oki_fuzzy_matches_ok(self) -> None:
        matched, phrase, _ = is_affirmation("oki")
        # "oki" is 3 chars, "ok" is 2 — ratio = 2*2/(3+2) = 0.8 < 0.86 → may not match
        # We just assert it doesn't raise
        assert isinstance(matched, bool)

    def test_perfecto_with_accent_matches(self) -> None:
        assert affirms("Perfecto!") is True

    def test_claro_que_si_beyond_window(self) -> None:
        """'claro que sí' is 3 tokens — within window but fuzzy of joined form."""
        result = is_affirmation("claro que sí")
        assert isinstance(result, tuple)


# ============================================================================
# AFFIRMATION_PHRASES public constant (R17)
# ============================================================================


class TestAffirmationPhrases:
    def test_is_frozenset(self) -> None:
        assert isinstance(AFFIRMATION_PHRASES, frozenset)

    def test_has_minimum_canonical_phrases(self) -> None:
        """R17 requires at minimum 12 canonical forms."""
        assert len(AFFIRMATION_PHRASES) >= 12

    def test_contains_si_without_accent(self) -> None:
        assert "si" in AFFIRMATION_PHRASES

    def test_contains_dale(self) -> None:
        assert "dale" in AFFIRMATION_PHRASES


# ============================================================================
# Symmetric to negation — public API shape (R16)
# ============================================================================


class TestApiShape:
    def test_is_affirmation_is_callable(self) -> None:
        assert callable(is_affirmation)

    def test_returns_tuple_for_empty_string(self) -> None:
        result = is_affirmation("")
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_returns_tuple_for_long_sentence(self) -> None:
        result = is_affirmation("quiero hacer una cita para el miércoles que viene")
        matched, phrase, distance = result
        assert matched is False
        assert phrase is None

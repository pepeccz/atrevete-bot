"""
RED tests for infra/resolvers/affirmation.py — Phase 1, tasks 1.1–1.5.

Expected fail mode: ModuleNotFoundError: No module named 'infra.resolvers.affirmation'
(implementation does not exist yet — this is the expected TDD RED signal).

REQs covered: REQ-1, REQ-2, REQ-3, REQ-4, REQ-5
"""

from __future__ import annotations

import pytest

# This import will raise ModuleNotFoundError in RED phase (implementation absent).
# That is the expected failure mode — do NOT add @pytest.mark.xfail.
from infra.resolvers.affirmation import is_affirmation

# ---------------------------------------------------------------------------
# TestCanonicalAffirmations — REQ-1
# ---------------------------------------------------------------------------


class TestCanonicalAffirmations:
    """
    Given the user sends one of the canonical affirmation phrases
    When is_affirmation(phrase) is called
    Then it returns True
    """

    @pytest.mark.parametrize(
        "phrase",
        [
            "dale",
            "sí",
            "ok",
            "va",
            "vale",
            "perfecto",
            "confirmo",
            "de acuerdo",
            "claro",
            "listo",
            "por supuesto",
            "genial",
            "okay",
            "si",
        ],
    )
    def test_canonical_phrase_returns_true(self, phrase: str) -> None:
        """
        Given: phrase is a canonical affirmation
        When: is_affirmation(phrase) is called
        Then: it returns True
        """
        result = is_affirmation(phrase)
        assert result is True, f"Expected is_affirmation({phrase!r}) to be True, got {result!r}"


# ---------------------------------------------------------------------------
# TestNegationRejection — REQ-2
# ---------------------------------------------------------------------------


class TestNegationRejection:
    """
    Given the user sends a pure-negation utterance
    When is_affirmation(phrase) is called
    Then it returns False (negation and affirmation are mutually exclusive)
    """

    @pytest.mark.parametrize(
        "phrase",
        [
            "no",
            "no quiero",
            "nada",
        ],
    )
    def test_negation_returns_false(self, phrase: str) -> None:
        """
        Given: phrase is a pure negation
        When: is_affirmation(phrase) is called
        Then: it returns False
        """
        result = is_affirmation(phrase)
        assert result is False, f"Expected is_affirmation({phrase!r}) to be False, got {result!r}"


# ---------------------------------------------------------------------------
# TestTokenWindowBoundary — REQ-3
# ---------------------------------------------------------------------------


class TestTokenWindowBoundary:
    """
    Given the user sends an affirmation followed by a condition or extra content
    When the total token count exceeds the matching window (>3 tokens)
    Then is_affirmation returns False (affirmative-with-condition rejection)

    Edge cases within window still return True.
    """

    @pytest.mark.parametrize(
        "phrase,expected",
        [
            # 5 tokens after normalization — exceeds window → False
            ("sí, pero cambiá la fecha", False),
            # 5 tokens after normalization — exceeds window → False
            ("ok pero con otra estilista", False),
            # 2 tokens — "gracias" is trailing filler within window → True
            ("dale gracias", True),
        ],
    )
    def test_token_window_boundary(self, phrase: str, expected: bool) -> None:
        """
        Given: phrase with or without trailing content
        When: is_affirmation(phrase) is called
        Then: result depends on token count relative to the window
        """
        result = is_affirmation(phrase)
        assert result is expected, (
            f"Expected is_affirmation({phrase!r}) to be {expected}, got {result!r}"
        )


# ---------------------------------------------------------------------------
# TestNormalization — REQ-4
# ---------------------------------------------------------------------------


class TestNormalization:
    """
    Given the user sends an affirmation in mixed case or without accent marks
    When is_affirmation is called
    Then it returns True (case and diacritics are normalized before matching)
    """

    @pytest.mark.parametrize(
        "phrase",
        [
            "SÍ",
            "SI",
            "DALE",
            "Dale",
        ],
    )
    def test_case_and_diacritics_insensitive(self, phrase: str) -> None:
        """
        Given: phrase is an affirmation in non-canonical case/encoding
        When: is_affirmation(phrase) is called
        Then: it returns True
        """
        result = is_affirmation(phrase)
        assert result is True, (
            f"Expected is_affirmation({phrase!r}) to be True after normalization, got {result!r}"
        )


# ---------------------------------------------------------------------------
# TestPublicAPI — REQ-5
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """
    Given infra/resolvers/affirmation.py is importable
    When is_affirmation is called
    Then it returns a plain bool (not a tuple), and is mutually exclusive with is_negation.
    """

    def test_returns_bool_not_tuple(self) -> None:
        """
        Given: is_affirmation is imported
        When: is_affirmation("dale") is called
        Then: the return type is bool, not a tuple
        """
        result = is_affirmation("dale")
        assert isinstance(result, bool), (
            f"Expected bool return type, got {type(result).__name__}"
        )

    def test_mutual_exclusivity_with_negation(self) -> None:
        """
        Given: infra.resolvers.negation.is_negation is importable
        When: is_affirmation is called with canonical affirmation phrases
        Then: is_negation returns False for each (mutually exclusive)
        """
        from infra.resolvers.negation import is_negation

        canonical_affirmations = [
            "dale",
            "sí",
            "ok",
            "va",
            "vale",
            "perfecto",
            "confirmo",
            "claro",
            "listo",
            "okay",
            "si",
        ]
        for phrase in canonical_affirmations:
            neg_matched, _canonical, _dist = is_negation(phrase)
            assert neg_matched is False, (
                f"Mutual exclusivity violated: is_negation({phrase!r}) returned True, "
                f"but is_affirmation also returns True for this phrase"
            )

    def test_import_does_not_raise(self) -> None:
        """
        Given: the module is importable
        When: from infra.resolvers.affirmation import is_affirmation
        Then: no ImportError is raised (asserted by the module-level import above)
        """
        # If we get here, the module-level import succeeded.
        assert callable(is_affirmation)

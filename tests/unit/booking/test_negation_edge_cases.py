"""
B.2.3 [RED] — Extended negation phrase coverage + resolve_add_more_negation wrapper.

Tests that the NEGATION_PHRASES set covers all canonical colloquial variants
and that resolve_add_more_negation() from patch_pipeline.py returns a ResolverResult.

Expected failures on master:
1. "no quiero nada más", "ninguna", "paso" not in NEGATION_PHRASES → is_negation returns False
2. resolve_add_more_negation does not exist yet in patch_pipeline.py
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Negation phrase coverage (B.2.3)
# ---------------------------------------------------------------------------

NEGATION_PHRASES_CANONICAL = [
    "nada más",
    "nada mas",      # no accent
    "nel",
    "nope",
    "nah",
    "ya está",
    "ya esta",       # no accent
    "ya estamos",
    "basta",
    "eso es todo",
    "es todo",
    "ya",
    "nada",
    "no más",
    "no mas",
    # B.2 additions (must be added to NEGATION_PHRASES to pass)
    "ninguna",
    "paso",
    "no quiero nada más",
    "no quiero nada mas",
]


class TestNegationPhraseCoverage:
    """All canonical negation variants must be recognized by is_negation()."""

    @pytest.mark.parametrize("phrase", NEGATION_PHRASES_CANONICAL)
    def test_is_negation_matches_phrase(self, phrase: str):
        """is_negation must return matched=True for all canonical variants.

        RED for "ninguna", "paso", "no quiero nada más" on master
        (not in NEGATION_PHRASES and > 3 tokens for the last one).
        GREEN after B.2 extends NEGATION_PHRASES.
        """
        from infra.resolvers.negation import is_negation

        matched, canonical, distance = is_negation(phrase)
        assert matched is True, (
            f"is_negation({phrase!r}) returned matched=False. "
            f"canonical={canonical!r}, distance={distance}. "
            f"Add this phrase to NEGATION_PHRASES in infra/resolvers/negation.py."
        )

    def test_negation_does_not_match_positive_phrases(self):
        """Positive phrases must NOT match is_negation()."""
        from infra.resolvers.negation import is_negation

        positive_phrases = ["sí", "dale", "perfecto", "me parece bien", "quiero otro servicio"]
        for phrase in positive_phrases:
            matched, _, _ = is_negation(phrase)
            assert matched is False, (
                f"is_negation({phrase!r}) incorrectly returned matched=True. "
                f"Positive phrases must not be negations."
            )


# ---------------------------------------------------------------------------
# resolve_add_more_negation wrapper (B.2.3 / B.2.4)
# ---------------------------------------------------------------------------


def _make_state_add_more_active(user_msg: str = "nada más") -> dict:
    """State where add_more_asked=False and action=ASK_MORE_SERVICES."""
    return {
        "conversation_id": "test-negation-edge",
        "booking_context": {"last_services": ["Corte señora"], "add_more_asked": False},
        "messages": [{"role": "user", "content": user_msg, "timestamp": ""}],
        "customer_phone": "+34600000001",
        "conversation_summary": "",
        "customer_memories": None,
        "total_message_count": 3,
    }


class TestResolveAddMoreNegation:
    """resolve_add_more_negation must return a ResolverResult on match."""

    def test_resolve_add_more_negation_importable(self):
        """resolve_add_more_negation must exist in agent.booking.patch_pipeline.

        RED on master: module/function does not exist yet.
        GREEN after B.2.4: module created with this function.
        """
        from agent.booking.patch_pipeline import resolve_add_more_negation
        assert callable(resolve_add_more_negation)

    @pytest.mark.parametrize("negation_phrase", [
        "nada más", "nel", "ya está", "eso es todo", "nada", "ninguna", "paso",
    ])
    def test_resolve_returns_matched_result(self, negation_phrase: str):
        """resolve_add_more_negation returns matched=True for known negations.

        RED on master: function doesn't exist.
        GREEN after B.2.4.
        """
        from agent.booking.patch_pipeline import resolve_add_more_negation

        state = _make_state_add_more_active(negation_phrase)
        bc = dict(state["booking_context"])

        result = resolve_add_more_negation(negation_phrase, state, bc)

        assert result is not None, (
            f"resolve_add_more_negation({negation_phrase!r}) returned None — "
            f"expected a ResolverResult with matched=True."
        )
        assert result.get("matched") is True, (
            f"result['matched'] must be True for {negation_phrase!r}"
        )
        assert "patch" in result, "ResolverResult must have a 'patch' key"
        assert result["patch"].get("add_more_asked") is True, (
            f"patch must set add_more_asked=True for {negation_phrase!r}"
        )
        assert "source" in result, "ResolverResult must have a 'source' key"
        assert result.get("source") == "is_negation"

    def test_resolve_returns_none_when_add_more_already_asked(self):
        """resolve_add_more_negation returns None when add_more_asked is already True."""
        from agent.booking.patch_pipeline import resolve_add_more_negation

        state = _make_state_add_more_active("nada más")
        bc = {"last_services": ["Corte señora"], "add_more_asked": True}  # already set

        result = resolve_add_more_negation("nada más", state, bc)
        assert result is None, (
            "Must return None when add_more_asked is already True — no-op for idempotency."
        )

    def test_resolve_returns_none_for_non_negation(self):
        """resolve_add_more_negation returns None when user message is NOT a negation."""
        from agent.booking.patch_pipeline import resolve_add_more_negation

        state = _make_state_add_more_active("sí, quiero otro servicio")
        bc = {"last_services": ["Corte señora"], "add_more_asked": False}

        result = resolve_add_more_negation("sí, quiero otro servicio", state, bc)
        assert result is None or result.get("matched") is False, (
            "Non-negation phrase must return None or matched=False."
        )

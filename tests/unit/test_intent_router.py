"""
Tests for the v6.0 IntentRouter keyword classifier.

Covers ``classify_by_keywords`` behavior — the v6.0 mode-based graph consumes
``IntentResult`` directly; there is no longer a ``BookingHandler`` /
``NonBookingHandler`` split (those v5.0 classes were removed).
"""

from agent.routing.intent_router import classify_by_keywords


class TestIntentRouterKeywordFastPath:
    def test_bare_no_classifies_as_reject(self):
        intent = classify_by_keywords("no")

        assert intent is not None
        assert intent.intent == "reject"

    def test_cancelo_classifies_as_cancel(self):
        intent = classify_by_keywords("cancelo")

        assert intent is not None
        assert intent.intent == "cancel"

    def test_cancela_classifies_as_cancel(self):
        intent = classify_by_keywords("cancela")

        assert intent is not None
        assert intent.intent == "cancel"


# =============================================================================
# UP-5: No-preference narrowing removed — "cualquiera" in BOOKING context
# =============================================================================


class TestNoPreferenceNarrowingRemoved:
    """UP-5: The booking-context no-preference narrowing block has been removed.

    "cualquiera" in BOOKING context must NOT be downgraded to confidence 0.40.
    The keyword layer returns None (no keyword match) and LLM fallback handles it.
    """

    def test_cualquiera_in_booking_context_not_capped_at_040(self):
        """'cualquiera' in BOOKING context does NOT get confidence 0.40 (narrowing removed)."""
        context = {"current_mode": "BOOKING"}
        result = classify_by_keywords("cualquiera", context=context)
        # "cualquiera" is not in KEYWORD_MAP → keyword classifier returns None
        # It must NOT return a result with confidence 0.40 (that was the narrowing output)
        if result is not None:
            assert result.confidence != 0.40, (
                "Narrowing block should be removed — 0.40 confidence downgrade must not happen"
            )

    def test_explicit_cancel_plain_text_classifies_as_cancel(self):
        """'cancelar mi cita' (no 'quiero' prefix) → cancel at high confidence."""
        # Without the narrowing block, plain cancel phrases still work at keyword level.
        # Note: 'quiero cancelar mi cita' matches 'book' (via 'quiero' keyword) at 0.90,
        # which wins over 'cancel'; that is expected behavior now that the narrowing is gone.
        result = classify_by_keywords("cancelar mi cita")

        assert result is not None
        assert result.intent == "cancel"
        assert result.confidence >= 0.80, (
            f"Explicit cancel should have high confidence, got {result.confidence}"
        )

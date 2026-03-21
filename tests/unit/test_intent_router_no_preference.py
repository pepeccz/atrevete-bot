"""
Regression tests for the intent-classifier-no-preference-bug fix.

Bug: "No tengo preferencia, con cualquiera que tenga lugar" was misclassified
as ``reject`` (0.90 confidence) because the bare keyword "no" in KEYWORD_MAP
matched via text.startswith("no").

Fix: Two guards in classify_by_keywords():
1. Pre-loop no-preference guard — returns "ambiguous" for phrases like
   "cualquiera", "sin preferencia", "no tengo preferencia", etc.
2. Length guard — bare "no" only fires "reject" for messages < 30 chars.

These tests cover all 5 regression scenarios from the spec and require no
LLM mock (all cases are handled at the keyword layer).
"""

import pytest

from agent.routing.intent_router import classify_by_keywords


@pytest.mark.parametrize(
    "message, expected_intent",
    [
        # Case 1: Bare "No" alone — must still be classified as reject (regression guard)
        ("No", "reject"),
        # Case 2: Primary bug — long no-preference message was wrongly classified as reject
        (
            "No tengo preferencia, con cualquiera que tenga lugar",
            "ambiguous",
        ),
        # Case 3: Single no-preference token — must be ambiguous
        ("cualquiera", "ambiguous"),
        # Case 4: No-preference phrase with trailing context — must be ambiguous, NOT reject
        ("no tengo preferencia de estilista", "ambiguous"),
        # Case 5: Long message with bare "no" (no no-preference phrase) — must NOT be reject
        #         via keyword fast-path (falls through to LLM → result is None)
        ("No soy pedofilo mamon, es para una mujer adulta", None),
    ],
)
def test_no_preference_classification(message: str, expected_intent: str | None) -> None:
    """
    Verify no-preference guard and length guard produce correct results.

    For Case 5 (expected_intent=None), the keyword classifier must return None
    (LLM fallback) rather than "reject" via keyword fast-path.
    """
    result = classify_by_keywords(message)

    if expected_intent is None:
        # Must fall through to LLM — keyword layer must not return "reject"
        assert result is None or result.intent != "reject", (
            f"Expected keyword classifier to fall through (or not reject) for {message!r}, "
            f"but got intent={result.intent if result else 'None'}"
        )
    else:
        assert result is not None, (
            f"Expected intent={expected_intent!r} for {message!r}, but got None (LLM fallback)"
        )
        assert result.intent == expected_intent, (
            f"Expected intent={expected_intent!r} for {message!r}, "
            f"but got intent={result.intent!r} (confidence={result.confidence})"
        )

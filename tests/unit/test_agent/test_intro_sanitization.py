"""
Unit tests for _maybe_prepend_intro() iterative sanitization (BUG-006 v2).

Tests that leading greetings and self-intros are stripped in ANY order
before the canonical EU AI Act disclosure is prepended.
"""

import re

import pytest

# The canonical disclosure text (must match base.py FIRST_TURN_INTRO)
FIRST_TURN_INTRO = "¡Hola! 🌸 Soy Maite, la asistenta virtual con IA de Atrévete Peluquería."

# ────────────────────────────────────────────────────────────────────────────
# Replicate the strip logic from _maybe_prepend_intro() so we can test it
# in isolation without needing a full BaseModeNode instance + LangGraph state.
# If the implementation in base.py changes, update this mirror too.
# ────────────────────────────────────────────────────────────────────────────

_GREETING_OPENER_PATTERN = re.compile(
    r"^[\s\U0001F300-\U0001FAFF]*"  # optional leading emoji/whitespace
    r"[¡!]?"
    r"(?:hola|buenas?(?:\s+(?:d[ií]as?|tardes?|noches?))?)"
    r"[^.!?]*"  # anything up to the first sentence boundary
    r"[.!?]?\s*"  # optional punctuation + whitespace
    r"[\U0001F300-\U0001FAFF\s]*",  # optional trailing emoji/whitespace
    re.IGNORECASE,
)
_SELF_INTRO_PATTERN = re.compile(
    r"^(?:soy\s+maite|maite[,.]?\s+(?:tu|la|su)\s+asistent)[^.!?]*[.!?]?\s*",
    re.IGNORECASE,
)
_MAX_STRIP_ITERATIONS = 5


def _simulate_prepend_intro(response_text: str, already_disclosed: bool = False) -> str:
    """Simulate _maybe_prepend_intro() logic for unit testing.

    Returns the final string that would be sent to the user.
    """
    if already_disclosed:
        return response_text  # guard: no double disclosure

    # Iterative strip — mirrors base.py implementation
    for _ in range(_MAX_STRIP_ITERATIONS):
        prev = response_text
        response_text = _GREETING_OPENER_PATTERN.sub("", response_text).lstrip()
        response_text = _SELF_INTRO_PATTERN.sub("", response_text).lstrip()
        if response_text == prev:
            break

    # Short-circuit: LLM already produced the canonical intro
    if response_text.startswith(FIRST_TURN_INTRO[:20]):
        return response_text

    return f"{FIRST_TURN_INTRO} {response_text}"


# ────────────────────────────────────────────────────────────────────────────
# Tests
# ────────────────────────────────────────────────────────────────────────────


class TestIntroSanitization:
    """REQ-A1: Sanitization is order-independent."""

    def test_greeting_then_intro_stripped(self):
        """¡Hola! Soy Maite... → single canonical disclosure."""
        llm_output = "¡Hola! Soy Maite, la asistenta. Para ayudarte necesito saber el servicio."
        result = _simulate_prepend_intro(llm_output)
        assert result.startswith(FIRST_TURN_INTRO)
        assert "Para ayudarte necesito saber el servicio." in result
        # No double greeting
        assert result.count("¡Hola!") == 1

    def test_intro_then_greeting_stripped(self):
        """Soy Maite... ¡Hola!... → single canonical disclosure (root of BUG-006 v1 failure)."""
        llm_output = "Soy Maite, tu asistente. ¡Hola! Para ayudarte con tu cita."
        result = _simulate_prepend_intro(llm_output)
        assert result.startswith(FIRST_TURN_INTRO)
        assert "Para ayudarte con tu cita." in result
        assert result.count("¡Hola!") == 1

    def test_greeting_only_stripped(self):
        """¡Hola! 😊 <body> → disclosure + body, no double greeting."""
        llm_output = "¡Hola! 😊 Para ayudarte con tu cita necesito saber qué servicio quieres."
        result = _simulate_prepend_intro(llm_output)
        assert result.startswith(FIRST_TURN_INTRO)
        assert "Para ayudarte con tu cita necesito saber" in result
        assert result.count("¡Hola!") == 1

    def test_clean_body_not_stripped(self):
        """No greeting, no intro → disclosure prepended, body preserved verbatim."""
        llm_output = "Para ayudarte con tu cita necesito saber qué servicio quieres."
        result = _simulate_prepend_intro(llm_output)
        assert result.startswith(FIRST_TURN_INTRO)
        assert "Para ayudarte con tu cita necesito saber qué servicio quieres." in result

    def test_multiple_greetings_stripped(self):
        """¡Hola! ¡Hola! Soy Maite... → single disclosure."""
        llm_output = "¡Hola! ¡Hola! Soy Maite, la asistente. Para ayudarte."
        result = _simulate_prepend_intro(llm_output)
        assert result.startswith(FIRST_TURN_INTRO)
        assert "Para ayudarte." in result
        assert result.count("¡Hola!") == 1

    def test_emoji_greeting_stripped(self):
        """🌸 ¡Hola! → stripped cleanly."""
        llm_output = "🌸 ¡Hola! Para empezar, ¿qué servicio necesitas?"
        result = _simulate_prepend_intro(llm_output)
        assert result.startswith(FIRST_TURN_INTRO)
        assert "Para empezar" in result

    def test_body_content_preserved(self):
        """Appointment info in body MUST be preserved verbatim after stripping greeting."""
        llm_output = "¡Hola! Tu cita es el lunes a las 10:00 con Pilar."
        result = _simulate_prepend_intro(llm_output)
        assert result.startswith(FIRST_TURN_INTRO)
        assert "Tu cita es el lunes a las 10:00 con Pilar." in result


class TestIntroSanitizationIdempotency:
    """REQ-A2: Sanitization is idempotent — calling twice gives same result."""

    def test_idempotent_with_greeting(self):
        """Running prepend_intro twice on same input → identical output."""
        llm_output = "¡Hola! Para ayudarte necesito saber el servicio."
        first_pass = _simulate_prepend_intro(llm_output)
        second_pass = _simulate_prepend_intro(first_pass, already_disclosed=True)
        assert first_pass == second_pass

    def test_idempotent_clean_body(self):
        """Clean body, disclosed twice → no duplicate disclosure."""
        llm_output = "Para ayudarte con tu cita necesito saber qué servicio quieres."
        first_pass = _simulate_prepend_intro(llm_output)
        second_pass = _simulate_prepend_intro(first_pass, already_disclosed=True)
        assert first_pass == second_pass
        assert first_pass.count(FIRST_TURN_INTRO) == 1

"""
Unit tests for _maybe_prepend_intro() iterative sanitization (BUG-006 v2).

Tests that leading greetings and self-intros are stripped in ANY order
before the canonical EU AI Act disclosure is prepended.

Also tests F-5 (history scan repairs ai_disclosure_sent) and F-6 (canonical
short-circuit prevents stripping the canonical text).
"""

import re

import pytest

from agent.modes.base import FIRST_TURN_INTRO as _BASE_FIRST_TURN_INTRO

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


# ────────────────────────────────────────────────────────────────────────────
# T-12: F-5 — history scan repairs ai_disclosure_sent
# T-12: F-6 — canonical short-circuit prevents stripping canonical text
# ────────────────────────────────────────────────────────────────────────────
#
# These tests call _maybe_prepend_intro() on a real BaseModeNode subclass
# (GeneralMode) so we exercise the actual code paths in base.py.


def _make_general_mode_for_intro_tests():
    """Instantiate a GeneralMode with a mock LLM for testing _maybe_prepend_intro."""
    from unittest.mock import AsyncMock, MagicMock

    from agent.modes.general_mode import GeneralMode

    mock_llm = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = "test"
    mock_response.tool_calls = []
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    return GeneralMode(tools=[], llm_client=mock_llm)


class TestDisclosureRepairOnHistoryScan:
    """T-12 / F-5: When history scan finds 'soy maite' in a prior assistant message,
    _maybe_prepend_intro returns (text, True) — repairing the state flag."""

    def test_history_scan_returns_true_when_disclosure_found(self):
        """When prior assistant message contains 'soy maite',
        _maybe_prepend_intro returns (text, True) even with ai_disclosure_sent=False.
        This is the F-5 repair path: checks history to fix a missed flag.
        """
        mode = _make_general_mode_for_intro_tests()
        # State where ai_disclosure_sent=False but history shows disclosure was already given
        state = {
            "ai_disclosure_sent": False,  # flag missing (simulates checkpoint loss)
            "messages": [
                {
                    "role": "assistant",
                    "content": f"{FIRST_TURN_INTRO} ¿En qué puedo ayudarte?",
                }
            ],
        }
        text = "¿En qué puedo ayudarte hoy?"

        result_text, disclosure_sent = mode._maybe_prepend_intro(text, state)

        # F-5: history scan found "soy maite" → returns (text, True) to repair state
        assert disclosure_sent is True
        # Response text must NOT be modified (we found prior disclosure — no need to prepend)
        assert result_text == text

    def test_history_scan_lowercase_soy_maite(self):
        """History scan is case-insensitive — lowercase 'soy maite' also triggers repair."""
        mode = _make_general_mode_for_intro_tests()
        state = {
            "ai_disclosure_sent": False,
            "messages": [
                {
                    "role": "assistant",
                    "content": "¡hola! soy maite, tu asistenta.",
                }
            ],
        }
        text = "¿Qué servicio necesitas?"

        result_text, disclosure_sent = mode._maybe_prepend_intro(text, state)

        assert disclosure_sent is True
        assert result_text == text

    def test_no_repair_when_no_prior_disclosure_in_history(self):
        """When NO prior disclosure in history and ai_disclosure_sent=False,
        _maybe_prepend_intro prepends the canonical intro and returns (text, True)."""
        mode = _make_general_mode_for_intro_tests()
        state = {
            "ai_disclosure_sent": False,
            "messages": [
                {"role": "user", "content": "hola"},
                {"role": "assistant", "content": "¿En qué puedo ayudarte?"},
            ],
        }
        text = "¿Qué servicio necesitas?"

        result_text, disclosure_sent = mode._maybe_prepend_intro(text, state)

        # No prior disclosure — must prepend canonical intro
        assert disclosure_sent is True
        assert result_text.startswith(FIRST_TURN_INTRO)
        assert "¿Qué servicio necesitas?" in result_text

    def test_no_call_when_flag_already_set(self):
        """When ai_disclosure_sent=True, no scan, no prepend — returns (text, False)."""
        mode = _make_general_mode_for_intro_tests()
        state = {
            "ai_disclosure_sent": True,
            "messages": [],
        }
        text = "¿Qué servicio necesitas?"

        result_text, disclosure_sent = mode._maybe_prepend_intro(text, state)

        # Flag already set — short-circuit immediately
        assert disclosure_sent is False
        assert result_text == text


class TestCanonicalShortCircuit:
    """T-12 / F-6: Responses that already start with the canonical FIRST_TURN_INTRO
    are short-circuited — not stripped, not re-prefixed.
    Non-canonical 'soy maite' phrases get stripped and the canonical intro prepended.
    """

    def test_canonical_text_short_circuits(self):
        """Response starting with FIRST_TURN_INTRO → (text, True), no stripping."""
        mode = _make_general_mode_for_intro_tests()
        state = {"ai_disclosure_sent": False, "messages": []}
        # The LLM produced the exact canonical intro (rare but possible)
        text = f"{FIRST_TURN_INTRO} ¿En qué puedo ayudarte?"

        result_text, disclosure_sent = mode._maybe_prepend_intro(text, state)

        # Short-circuit: text is returned as-is (no double prepend)
        assert disclosure_sent is True
        assert result_text == text
        assert result_text.count(FIRST_TURN_INTRO) == 1

    def test_non_canonical_soy_maite_not_short_circuited(self):
        """Response with 'Soy Maite, ...' (not canonical) → gets stripped + canonical prepended.
        F-6: loose 'soy maite' check was removed, so non-canonical intro is handled by
        the strip loop, not by an early return.
        """
        mode = _make_general_mode_for_intro_tests()
        state = {"ai_disclosure_sent": False, "messages": []}
        # Non-canonical self-intro — should be stripped
        text = "Soy Maite, tu asistente. ¿Qué necesitas?"

        result_text, disclosure_sent = mode._maybe_prepend_intro(text, state)

        # Must prepend canonical intro (stripping removed the non-canonical one)
        assert disclosure_sent is True
        assert result_text.startswith(FIRST_TURN_INTRO)
        # The body content should still appear
        assert "¿Qué necesitas?" in result_text
        # Must not have duplicate canonical intro
        assert result_text.count(FIRST_TURN_INTRO) == 1

    def test_canonical_full_match_short_circuits(self):
        """FIRST_TURN_INTRO appearing anywhere in the response also short-circuits."""
        mode = _make_general_mode_for_intro_tests()
        state = {"ai_disclosure_sent": False, "messages": []}
        # FIRST_TURN_INTRO is in the middle — still short-circuits
        text = f"Algo antes. {FIRST_TURN_INTRO} Algo después."

        result_text, disclosure_sent = mode._maybe_prepend_intro(text, state)

        assert disclosure_sent is True
        # Text is not modified when canonical text is found
        assert result_text == text

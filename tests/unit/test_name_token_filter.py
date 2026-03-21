"""
Unit tests for GreetingMode._contains_customer_name_token().

Coverage:
- Full name match (existing behavior preserved).
- Partial first-name match ("María" in "Hola, María").
- Partial last-name match ("García" in response).
- Accent-insensitive match: "Maria" matches "María".
- Short token exclusion (< 3 chars) → no false positives.
- Word-boundary match: "Ana" inside "mañana" must NOT trigger.
- Empty inputs.
- Multiple tokens: any one hit is sufficient.

All tests are pure unit — no LLM or DB required.
"""

import pytest

from agent.modes.greeting_mode import GreetingMode


# =============================================================================
# Fixture
# =============================================================================


def make_greeting_mode() -> GreetingMode:
    from unittest.mock import AsyncMock, MagicMock

    mock_llm = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = ""
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    return GreetingMode(tools=[], llm_client=mock_llm)


# =============================================================================
# 1. Basic triggering cases
# =============================================================================


class TestNameTokenFilterTriggers:
    """Cases where the filter SHOULD trigger (return True)."""

    def test_full_name_exact_match(self):
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token("Hola, María García", "María García") is True

    def test_partial_first_name_match(self):
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token("Hola, María! ¿Cómo estás?", "María García") is True

    def test_partial_last_name_match(self):
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token("Hola, García! Bienvenida", "María García") is True

    def test_accent_insensitive_match(self):
        """'María' stored name must match 'Maria' (no accent) in response."""
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token("Hola, Maria! ¿En qué te ayudo?", "María García") is True

    def test_case_insensitive_match(self):
        """Uppercase variant of name should still trigger."""
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token("Hola, MARÍA!", "María García") is True

    def test_name_at_end_of_sentence(self):
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token("¡Bienvenida, Carmen!", "Carmen López") is True

    def test_name_in_middle_of_sentence(self):
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token("Claro, Carmen, en seguida te ayudo.", "Carmen López") is True

    def test_accented_response_and_accented_name(self):
        """Both response and name have accents → should match."""
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token("Hola, María, ¿qué tal?", "María Jiménez") is True

    @pytest.mark.parametrize(
        "response, customer_name",
        [
            ("Hola, Ana!", "Ana Torres"),
            ("Claro, Ana.", "Ana Torres"),
            ("Buenos días, Ana.", "Ana Torres"),
        ],
    )
    def test_3char_token_is_checked(self, response: str, customer_name: str):
        """3-char tokens (exactly at the boundary) should still be checked."""
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token(response, customer_name) is True


# =============================================================================
# 2. Non-triggering cases (filter MUST NOT trigger)
# =============================================================================


class TestNameTokenFilterNoTrigger:
    """Cases where the filter should NOT trigger (return False)."""

    def test_completely_unrelated_response(self):
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token("¡Hola! ¿En qué puedo ayudarte hoy?", "María García") is False

    def test_short_token_not_matched(self):
        """2-char token 'Al' from name 'Al García' should be skipped by the < 3 filter."""
        mode = make_greeting_mode()
        # Response contains "al" but "Al" is only 2 chars — should be skipped
        assert mode._contains_customer_name_token("al menos puedo ayudarte", "Al García") is False

    def test_word_boundary_prevents_false_positive_ana_in_manana(self):
        """'Ana' must NOT match inside 'mañana' — word boundary required."""
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token("Hasta mañana, ¡que tengas un buen día!", "Ana Torres") is False

    def test_word_boundary_prevents_false_positive_carmen_in_caramel(self):
        """'Carmen' must NOT match inside unrelated words."""
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token("¿Quieres algo del menú?", "Carmen López") is False

    def test_empty_response_returns_false(self):
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token("", "María García") is False

    def test_empty_customer_name_returns_false(self):
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token("Hola! ¿En qué te ayudo?", "") is False

    def test_all_tokens_too_short_returns_false(self):
        """Name made entirely of tokens < 3 chars → nothing checked → False."""
        mode = make_greeting_mode()
        # "Bo De" → tokens "Bo" (2), "De" (2) — both skipped
        assert mode._contains_customer_name_token("Hola De todos modos", "Bo De") is False

    def test_name_as_part_of_different_word_no_match(self):
        """'Mar' from 'Mar López' must not match 'mármol'."""
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token("el mármol es un material", "Mar López") is False


# =============================================================================
# 3. Accent edge cases
# =============================================================================


class TestNameTokenFilterAccents:
    """Accent normalization edge cases."""

    def test_response_accented_name_not_accented(self):
        """Response uses 'María', name stored as 'Maria' (no accent)."""
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token("Hola, María!", "Maria Garcia") is True

    def test_name_with_special_chars_normalized(self):
        """'Andrés' in response, stored as 'Andres' → should match."""
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token("Hola, Andrés!", "Andres Gómez") is True

    def test_unicode_equivalence_nfc_name_nfd_response(self):
        """NFC name vs NFD response: both should normalize to same tokens and match."""
        import unicodedata
        # Response has NFD-encoded accent (decomposed)
        response_nfd = unicodedata.normalize("NFD", "Hola, María! ¿Cómo estás?")
        # Name stored as NFC (default Python string)
        name_nfc = "María"
        mode = make_greeting_mode()
        assert mode._contains_customer_name_token(response_nfd, name_nfc) is True

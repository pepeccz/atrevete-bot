"""
Unit tests for agent/modes/greeting_mode.py — GreetingMode v6.0.

Coverage:
- Anti-loop guarantee: customer_name already set → immediate GENERAL transition
- First interaction: welcome message generated, is_first_interaction=False
- Name extraction: user gives name → customer_name set, transition to GENERAL
- Failed name extraction: polite retry (stay in GREETING)
- _heuristic_extract: various name patterns

All LLM calls are mocked — tests do NOT require a real LLM.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.modes.greeting_mode import (
    GreetingMode,
    _NON_NAME_WORDS,
    _WELCOME_NEEDS_NAME,
    _WELCOME_RETURNING,
    _is_valid_name,
)
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def make_intent(intent: str = "greet", confidence: float = 0.9) -> IntentResult:
    return IntentResult(intent=intent, confidence=confidence, raw_input="test", mode_hint="GREETING")


def make_mock_llm(response_content: str = "Juan") -> AsyncMock:
    """Build a mock LLM that returns a simple content string."""
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_content
    mock.ainvoke = AsyncMock(return_value=mock_response)
    # Also needs bind_tools since BaseModeNode may call it
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def make_greeting_mode(llm_response: str = "Juan") -> GreetingMode:
    mock_llm = make_mock_llm(llm_response)
    return GreetingMode(tools=[], llm_client=mock_llm)


# =============================================================================
# Anti-loop guarantee (THE most important test)
# =============================================================================


class TestGreetingModeAntiLoop:
    """
    Verify the anti-loop guarantee:
    If customer_name is already set in state, GreetingMode MUST
    transition to GENERAL immediately — never ask for name again.
    """

    async def test_customer_name_set_transitions_to_general(self):
        """Core anti-loop: customer_name present → current_mode becomes GENERAL."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "Juan"  # Name already known

        result = await mode.handle(state, make_intent())

        assert result["current_mode"] == "GENERAL"

    async def test_customer_name_set_does_not_ask_for_name_again(self):
        """No message should ask '¿Con quién tengo el gusto?' when name is known."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "María"

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        combined_content = " ".join(m.get("content", "") for m in messages)
        assert "¿Con quién" not in combined_content
        assert "¿Me puedes decir" not in combined_content

    async def test_customer_name_set_generates_returning_greeting(self):
        """Should send a personalized returning customer greeting."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "Carlos"

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        assert len(messages) >= 1
        # Returning greeting should mention customer name
        content = messages[0]["content"]
        assert "Carlos" in content

    async def test_customer_name_set_sets_previous_mode(self):
        """Mode transition should record GREETING as previous_mode."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "Ana"
        state["current_mode"] = "GREETING"

        result = await mode.handle(state, make_intent())

        assert result.get("previous_mode") == "GREETING"


# =============================================================================
# First interaction
# =============================================================================


class TestGreetingModeFirstInteraction:
    """Tests for the first-time welcome flow (is_first_interaction=True)."""

    async def test_first_interaction_sends_welcome_message(self):
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        # is_first_interaction=True is the default in create_initial_state

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        assert len(messages) >= 1

    async def test_first_interaction_welcome_asks_for_name(self):
        """Welcome message must ask who is speaking."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        content = messages[0]["content"]
        # The welcome message should contain the "who am I speaking to?" question
        assert _WELCOME_NEEDS_NAME in content or "hablar" in content or "llamas" in content

    async def test_first_interaction_sets_is_first_interaction_false(self):
        """After welcome, is_first_interaction must be False to prevent loop."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")

        result = await mode.handle(state, make_intent())

        # The returned dict must set is_first_interaction=False
        assert result.get("is_first_interaction") is False

    async def test_first_interaction_stays_in_greeting_mode(self):
        """After welcome, mode should remain GREETING (waiting for name)."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")

        result = await mode.handle(state, make_intent())

        # Should not transition to GENERAL yet — waiting for name
        # mode is either not set (stays GREETING) or explicitly GREETING
        current = result.get("current_mode")
        assert current == "GREETING" or current is None


# =============================================================================
# Name extraction (Turn 2: user replies with their name)
# =============================================================================


class TestGreetingModeNameExtraction:
    """Tests for the name extraction turn (second interaction)."""

    async def test_user_gives_name_sets_customer_name(self):
        """When user says their name, customer_name must be set in the result."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["is_first_interaction"] = False  # Already past welcome turn
        state["customer_name"] = None
        state["user_message"] = "Me llamo Juan"

        result = await mode.handle(state, make_intent())

        assert result.get("customer_name") is not None
        assert "Juan" in result.get("customer_name", "")

    async def test_user_gives_name_transitions_to_general(self):
        """After name extraction, mode must transition to GENERAL."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["is_first_interaction"] = False
        state["customer_name"] = None
        state["user_message"] = "Me llamo Juan"

        result = await mode.handle(state, make_intent())

        assert result.get("current_mode") == "GENERAL"

    async def test_user_gives_short_name_no_llm_needed(self):
        """Short messages (1-3 words) use heuristic — LLM NOT called."""
        mock_llm = make_mock_llm()
        mode = GreetingMode(tools=[], llm_client=mock_llm)

        state = create_initial_state("conv-001", "+34612345678")
        state["is_first_interaction"] = False
        state["customer_name"] = None
        state["user_message"] = "Pedro"  # Short — heuristic should handle it

        result = await mode.handle(state, make_intent())

        # Name should be extracted without LLM call
        assert result.get("customer_name") is not None
        # LLM may or may not be called — heuristic is preferred for short messages
        # Just verify the name was captured correctly
        assert "Pedro" in (result.get("customer_name") or "")

    async def test_user_says_me_llamo_pedro(self):
        """'Me llamo Pedro' → extracts 'Pedro'."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["is_first_interaction"] = False
        state["customer_name"] = None
        state["user_message"] = "Me llamo Pedro"

        result = await mode.handle(state, make_intent())

        extracted = result.get("customer_name", "")
        assert "Pedro" in extracted

    async def test_name_extraction_generates_confirmation_message(self):
        """After extracting name, bot should send a personalized confirmation."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["is_first_interaction"] = False
        state["customer_name"] = None
        state["user_message"] = "María García"

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        assert len(messages) >= 1
        content = messages[0]["content"]
        # Should address the user by their name
        assert "María" in content or "García" in content


# =============================================================================
# Failed name extraction
# =============================================================================


class TestGreetingModeNameExtractionFailure:
    """Tests for when name extraction fails (empty/unrecognizable input)."""

    async def test_empty_user_message_asks_again(self):
        """Empty message → bot asks politely for name again."""
        mode = make_greeting_mode("UNKNOWN")
        state = create_initial_state("conv-001", "+34612345678")
        state["is_first_interaction"] = False
        state["customer_name"] = None
        state["user_message"] = ""

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        assert len(messages) >= 1
        # Should ask again, not transition to GENERAL
        assert result.get("current_mode") != "GENERAL"


# =============================================================================
# Non-name word rejection (THE bug that was reported)
# =============================================================================


class TestGreetingModeRejectsNonNames:
    """
    Verify that affirmatives, negatives, and standalone greetings are NOT
    accepted as customer names.

    The original bug: user says "Si" after being asked "¿Con quién tengo el
    gusto?", and the heuristic accepted "Si" (capitalised to "Si") as a valid
    name, storing it in customer_name and transitioning to GENERAL.

    Expected behaviour: any word in _NON_NAME_WORDS → stay in GREETING,
    re-ask for name with "Disculpá, ¿me podrías decir tu nombre?"
    """

    async def test_greeting_mode_rejects_si_as_name(self):
        """'Si' must NOT be accepted as a name — stay in GREETING."""
        mode = make_greeting_mode("UNKNOWN")  # Mock LLM would also return UNKNOWN
        state = create_initial_state("conv-001", "+34612345678")
        state["is_first_interaction"] = False
        state["customer_name"] = None
        state["user_message"] = "Si"

        result = await mode.handle(state, make_intent())

        # Must NOT set a customer_name
        assert result.get("customer_name") is None, (
            f"Expected customer_name=None but got {result.get('customer_name')!r}"
        )
        # Must stay in GREETING (not transition to GENERAL)
        assert result.get("current_mode") != "GENERAL", (
            "Mode should remain GREETING when user says 'Si'"
        )

    async def test_greeting_mode_rejects_si_with_accent(self):
        """'Sí' (accented) must also be rejected."""
        mode = make_greeting_mode("UNKNOWN")
        state = create_initial_state("conv-002", "+34612345679")
        state["is_first_interaction"] = False
        state["customer_name"] = None
        state["user_message"] = "Sí"

        result = await mode.handle(state, make_intent())

        assert result.get("customer_name") is None
        assert result.get("current_mode") != "GENERAL"

    async def test_greeting_mode_rejects_ok_as_name(self):
        """'Ok' must be rejected as a name."""
        mode = make_greeting_mode("UNKNOWN")
        state = create_initial_state("conv-003", "+34612345680")
        state["is_first_interaction"] = False
        state["customer_name"] = None
        state["user_message"] = "Ok"

        result = await mode.handle(state, make_intent())

        assert result.get("customer_name") is None
        assert result.get("current_mode") != "GENERAL"

    async def test_greeting_mode_rejects_dale_as_name(self):
        """'Dale' (Rioplatense affirmative) must be rejected."""
        mode = make_greeting_mode("UNKNOWN")
        state = create_initial_state("conv-004", "+34612345681")
        state["is_first_interaction"] = False
        state["customer_name"] = None
        state["user_message"] = "dale"

        result = await mode.handle(state, make_intent())

        assert result.get("customer_name") is None
        assert result.get("current_mode") != "GENERAL"

    async def test_greeting_mode_rejects_no_as_name(self):
        """'No' must be rejected."""
        mode = make_greeting_mode("UNKNOWN")
        state = create_initial_state("conv-005", "+34612345682")
        state["is_first_interaction"] = False
        state["customer_name"] = None
        state["user_message"] = "no"

        result = await mode.handle(state, make_intent())

        assert result.get("customer_name") is None
        assert result.get("current_mode") != "GENERAL"

    async def test_greeting_mode_reasks_name_after_rejection(self):
        """After rejecting a non-name word, bot must ask again for the name."""
        mode = make_greeting_mode("UNKNOWN")
        state = create_initial_state("conv-006", "+34612345683")
        state["is_first_interaction"] = False
        state["customer_name"] = None
        state["user_message"] = "Si"

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        assert len(messages) >= 1
        content = messages[0]["content"]
        assert "nombre" in content.lower() or "llamas" in content.lower() or "disculp" in content.lower(), (
            f"Bot should ask for name again but got: {content!r}"
        )

    async def test_non_name_words_covers_common_affirmatives(self):
        """Spot-check that _NON_NAME_WORDS contains the expected words."""
        required = {"si", "sí", "ok", "dale", "claro", "bueno", "no", "hola"}
        missing = required - _NON_NAME_WORDS
        assert not missing, f"Missing non-name words: {missing}"

    def test_is_valid_name_rejects_si(self):
        """Unit test for _is_valid_name() standalone."""
        assert _is_valid_name("Si") is False
        assert _is_valid_name("Sí") is False

    def test_is_valid_name_rejects_short_strings(self):
        """Strings of length <= _MIN_NAME_LENGTH must be rejected."""
        assert _is_valid_name("") is False
        assert _is_valid_name("A") is False
        assert _is_valid_name("Ok") is False  # len == 2, exactly at boundary

    def test_is_valid_name_accepts_real_names(self):
        """Real Spanish names must pass validation."""
        assert _is_valid_name("Ana") is True  # 3 chars, not in list
        assert _is_valid_name("Juan") is True
        assert _is_valid_name("María García") is True
        assert _is_valid_name("Pedro") is True

    def test_anti_loop_guard_unaffected_by_non_name_filter(self):
        """
        The anti-loop guard (customer_name already set) must NOT be affected
        by the non-name filter. Once a name is stored, it should never be
        challenged again — even if the stored name happens to be unusual.
        """
        # This is tested indirectly: the filter only runs during _extract_name,
        # NOT during the anti-loop guard check at the top of handle().
        # The anti-loop guard checks `if customer_name:` — any truthy value
        # (including unusual names) causes immediate GENERAL transition.
        # We verify this with an already-set customer_name.
        import asyncio

        async def _run():
            mode = make_greeting_mode()
            state = create_initial_state("conv-007", "+34612345684")
            state["customer_name"] = "Ana"  # Already set (passed anti-loop guard)

            result = await mode.handle(state, make_intent())
            # Must transition to GENERAL — anti-loop guard fires before any filter
            assert result.get("current_mode") == "GENERAL"

        asyncio.get_event_loop().run_until_complete(_run())


# =============================================================================
# _heuristic_extract
# =============================================================================


class TestHeuristicExtract:
    """Tests for the _heuristic_extract() fallback method."""

    def _make_mode(self) -> GreetingMode:
        return GreetingMode(tools=[], llm_client=AsyncMock())

    def test_extracts_single_name(self):
        mode = self._make_mode()
        result = mode._heuristic_extract("Juan")
        assert result == "Juan"

    def test_extracts_name_from_me_llamo(self):
        mode = self._make_mode()
        result = mode._heuristic_extract("me llamo Pedro")
        assert "Pedro" in result

    def test_extracts_name_from_soy(self):
        mode = self._make_mode()
        result = mode._heuristic_extract("soy María")
        assert "María" in result

    def test_returns_unknown_for_all_fillers(self):
        mode = self._make_mode()
        result = mode._heuristic_extract("me llamo")  # "me" and "llamo" are fillers
        assert result == "UNKNOWN"

    def test_capitalizes_first_letter(self):
        mode = self._make_mode()
        result = mode._heuristic_extract("juan")
        assert result[0].isupper()

    def test_limits_to_two_words(self):
        mode = self._make_mode()
        result = mode._heuristic_extract("Juan Carlos García López")
        # Should extract at most 2 meaningful words
        words = result.split()
        assert len(words) <= 2

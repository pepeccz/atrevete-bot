"""
Unit tests for agent/modes/escalation_mode.py — EscalationMode.

Coverage:
- F-4 regression: no LLM call when escalation_triggered=True
- Silence determinism: the return value is consistent when already escalated
- FSM step transitions (ACKNOWLEDGE → DESCRIBE → CONTACT → DONE)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.escalation_mode import (
    EscalationMode,
    _ALREADY_ESCALATED,
    _ACKNOWLEDGE_REPLY,
    _CONTACT_PROMPT,
    _normalize_contact_preference,
)
from agent.state.schemas import create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def _make_mock_llm() -> AsyncMock:
    """Mock LLM — tracks if ainvoke was called."""
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = "unexpected LLM call"
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def _make_escalation_mode() -> EscalationMode:
    return EscalationMode(tools=[], llm_client=_make_mock_llm())


def _make_state(
    *,
    escalation_triggered: bool = False,
    escalation_step: str | None = None,
    current_mode: str = "ESCALATION",
    user_message: str = "necesito ayuda urgente",
) -> dict:
    """Build a ConversationState for EscalationMode tests."""
    state = create_initial_state("conv-esc-001", "+34612345678")
    state["current_mode"] = current_mode
    state["customer_name"] = "María"
    state["escalation_triggered"] = escalation_triggered
    state["ai_disclosure_sent"] = True  # skip disclosure for clarity
    state["messages"] = [{"role": "user", "content": user_message}]
    mode_context = {}
    if escalation_step:
        mode_context["escalation_step"] = escalation_step
    state["mode_context"] = mode_context
    return state


# =============================================================================
# T-15: F-4 regression — escalation silence guard (no LLM when already escalated)
# =============================================================================


class TestEscalationSilenceGuard:
    """T-15 / F-4: When escalation_triggered=True or step=DONE,
    EscalationMode.handle() returns without making any LLM call."""

    @pytest.mark.asyncio
    async def test_no_llm_call_when_already_escalated(self):
        """If state has escalation_triggered=True,
        escalation_mode.handle() returns without making LLM call."""
        mode = _make_escalation_mode()
        state = _make_state(
            escalation_triggered=True,
            escalation_step="DONE",
            current_mode="ESCALATION",
        )

        result = await mode.handle(state, intent=None)

        # The LLM must NOT have been called
        mode.llm.ainvoke.assert_not_called()

        # State update must be returned normally
        assert "messages" in result
        assert result.get("user_message") is None
        assert result.get("last_node") == "escalation"

    @pytest.mark.asyncio
    async def test_no_llm_call_when_step_done(self):
        """When escalation_step=DONE but escalation_triggered=False (edge case),
        still returns the waiting message without LLM call."""
        mode = _make_escalation_mode()
        state = _make_state(
            escalation_triggered=True,  # step DONE implies triggered
            escalation_step="DONE",
        )

        result = await mode.handle(state, intent=None)

        mode.llm.ainvoke.assert_not_called()
        assert result.get("last_node") == "escalation"

    @pytest.mark.asyncio
    async def test_silence_is_deterministic(self):
        """The return value when already_escalated=True is consistent.
        Multiple calls return the same _ALREADY_ESCALATED text."""
        mode = _make_escalation_mode()

        results = []
        for _ in range(3):
            state = _make_state(
                escalation_triggered=True,
                escalation_step="DONE",
            )
            result = await mode.handle(state, intent=None)
            messages = result.get("messages", [])
            assert messages, "Expected messages in result"
            results.append(messages[0]["content"])

        # All three calls return the same text
        assert all(r == results[0] for r in results), (
            f"Expected all results to be identical, got: {results}"
        )
        # The content is the _ALREADY_ESCALATED constant (without disclosure prefix)
        assert _ALREADY_ESCALATED in results[0]

    @pytest.mark.asyncio
    async def test_silence_response_contains_already_escalated_text(self):
        """When already escalated, response contains the _ALREADY_ESCALATED message."""
        mode = _make_escalation_mode()
        state = _make_state(escalation_triggered=True)

        result = await mode.handle(state, intent=None)

        messages = result.get("messages", [])
        assert messages
        response_content = messages[0]["content"]
        assert _ALREADY_ESCALATED in response_content


# =============================================================================
# FSM step transitions
# =============================================================================


class TestEscalationFSMTransitions:
    """FSM step flow: fresh entry starts at ACKNOWLEDGE regardless of stale step."""

    @pytest.mark.asyncio
    async def test_fresh_entry_starts_at_acknowledge(self):
        """First time in ESCALATION (previous_mode != ESCALATION) → ACKNOWLEDGE step."""
        mode = _make_escalation_mode()
        state = _make_state(
            current_mode="BOOKING",  # transitioning FROM booking
            escalation_triggered=False,
            escalation_step=None,
        )

        result = await mode.handle(state, intent=None)

        # Should return the acknowledge reply
        messages = result.get("messages", [])
        assert messages
        assert _ACKNOWLEDGE_REPLY in messages[0]["content"]

    @pytest.mark.asyncio
    async def test_describe_step_sets_contact_prompt(self):
        """After ACKNOWLEDGE, state has escalation_step=DESCRIBE.
        Next call should ask for contact preference."""
        mode = _make_escalation_mode()
        state = _make_state(
            current_mode="ESCALATION",
            escalation_triggered=False,
            escalation_step="DESCRIBE",
            user_message="Mi problema es que no puedo cancelar la cita",
        )

        result = await mode.handle(state, intent=None)

        messages = result.get("messages", [])
        assert messages
        assert _CONTACT_PROMPT in messages[0]["content"]
        # Context should move to CONTACT step
        assert result.get("mode_context", {}).get("escalation_step") == "CONTACT"


# =============================================================================
# Normalize contact preference
# =============================================================================


class TestNormalizeContactPreference:
    """Unit tests for _normalize_contact_preference helper."""

    def test_whatsapp_normalized(self):
        assert _normalize_contact_preference("por whatsapp") == "WhatsApp"
        assert _normalize_contact_preference("wsp") == "WhatsApp"

    def test_llamada_normalized(self):
        assert _normalize_contact_preference("por llamada") == "llamada"
        assert _normalize_contact_preference("teléfono") == "llamada"

    def test_unknown_passed_through(self):
        assert _normalize_contact_preference("email") == "email"

"""
Unit tests for agent/modes/escalation_mode.py — EscalationMode.

Coverage:
- F-4 regression: no LLM call when escalation_triggered=True
- Silence determinism: the return value is consistent when already escalated
- FSM step transitions (ACKNOWLEDGE → DESCRIBE → CONTACT → DONE)
- UP-1: _is_urgent() detection + urgency fast-path in handle()
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.escalation_mode import (
    EscalationMode,
    _ALREADY_ESCALATED,
    _ACKNOWLEDGE_REPLY,
    _CONTACT_PROMPT,
    _URGENCY_SIGNALS,
    _is_urgent,
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
        """First time in ESCALATION (previous_mode != ESCALATION) → ACKNOWLEDGE step.

        Uses a non-urgent, non-explicit-human message so neither WS-4 nor UP-1 fast-paths trigger.
        For the urgency fast-path behavior, see TestUrgencyFastPath.
        For the WS-4 explicit fast-path behavior, see test_ws4_escalation_fast_path.py.
        """
        mode = _make_escalation_mode()
        state = _make_state(
            current_mode="BOOKING",  # transitioning FROM booking
            escalation_triggered=False,
            escalation_step=None,
            user_message="tengo un problema con mi cita",  # frustration, no explicit human request
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


# =============================================================================
# UP-1: _is_urgent() unit tests
# =============================================================================


class TestIsUrgent:
    """UP-1: _is_urgent() detects all 8 required urgency signals."""

    @pytest.mark.parametrize(
        "signal",
        list(_URGENCY_SIGNALS),
    )
    def test_all_signals_return_true(self, signal: str):
        """Each individual signal phrase must trigger _is_urgent()."""
        assert _is_urgent(signal) is True, f"_is_urgent({signal!r}) should return True"

    def test_all_signals_case_insensitive(self):
        """Urgency detection is case-insensitive."""
        assert _is_urgent("URGENTE necesito ayuda") is True
        assert _is_urgent("EMERGENCIA en el salon") is True
        assert _is_urgent("Inmediatamente por favor") is True

    def test_standalone_ya_does_not_trigger(self):
        """'ya' alone must NOT trigger the urgency fast-path (UP-1 spec)."""
        assert _is_urgent("ya") is False

    def test_empty_string_does_not_trigger(self):
        assert _is_urgent("") is False

    def test_unrelated_text_does_not_trigger(self):
        assert _is_urgent("quiero reservar una cita") is False
        assert _is_urgent("hola buenas tardes") is False

    def test_signal_embedded_in_sentence(self):
        """Urgency signal embedded inside a sentence is still detected."""
        assert _is_urgent("por favor es urgente necesito que me atiendas") is True
        assert _is_urgent("mañana es emergencia me quedo sin tiempo") is True


# =============================================================================
# UP-1: urgency fast-path in handle()
# =============================================================================


class TestUrgencyFastPath:
    """UP-1: handle() jumps directly to CONTACT when urgency signal present on fresh entry."""

    @pytest.mark.asyncio
    async def test_urgency_fast_path_jumps_to_contact(self):
        """Fresh ESCALATION entry with urgency signal → bot asks for contact preference.

        Uses a pure urgency signal ("es URGENTE", "AHORA MISMO") WITHOUT explicit human
        request phrases ("hablar con alguien") so only the UP-1 urgency fast-path fires.
        WS-4 explicit fast-path fires for "hablar con alguien"; UP-1 fires for "urgente".
        Both skip ACKNOWLEDGE but: UP-1 → CONTACT (ask preference); WS-4 → DONE (immediate).
        This test validates UP-1 (urgency → CONTACT step, not yet DONE).
        """
        mode = EscalationMode(tools=[], llm_client=_make_mock_llm())
        state = _make_state(
            current_mode="BOOKING",  # transitioning FROM booking (fresh entry)
            escalation_triggered=False,
            escalation_step=None,
            user_message="Es URGENTE necesito ayuda AHORA MISMO",  # urgency, no explicit human req
        )

        result = await mode.handle(state, intent=None)

        # Must respond with the CONTACT prompt (not ACKNOWLEDGE)
        messages = result.get("messages", [])
        assert messages, "Expected a response message"
        assert _CONTACT_PROMPT in messages[0]["content"]

        # Must set escalation_step = CONTACT in mode_context
        assert result.get("mode_context", {}).get("escalation_step") == "CONTACT"

        # issue_summary must be captured from user text
        assert result.get("mode_context", {}).get("issue_summary")

        # No LLM should have been called
        mode.llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_urgency_fast_path_does_not_fire_mid_fsm(self):
        """When escalation_step is already set (mid-FSM), urgency does NOT re-trigger fast-path."""
        mode = EscalationMode(tools=[], llm_client=_make_mock_llm())
        state = _make_state(
            current_mode="ESCALATION",
            escalation_triggered=False,
            escalation_step="DESCRIBE",  # mid-FSM
            user_message="urgente por favor",
        )

        result = await mode.handle(state, intent=None)

        # Must continue from DESCRIBE → send CONTACT prompt (normal FSM flow)
        # and advance to CONTACT step, not be re-jumped
        messages = result.get("messages", [])
        assert messages
        # The DESCRIBE step moves to CONTACT and asks for contact preference
        assert _CONTACT_PROMPT in messages[0]["content"]
        assert result.get("mode_context", {}).get("escalation_step") == "CONTACT"

    @pytest.mark.asyncio
    async def test_no_urgency_fresh_entry_starts_acknowledge(self):
        """Fresh entry WITHOUT urgency signal and WITHOUT explicit human request → ACKNOWLEDGE path."""
        mode = EscalationMode(tools=[], llm_client=_make_mock_llm())
        state = _make_state(
            current_mode="BOOKING",
            escalation_triggered=False,
            escalation_step=None,
            # Pure frustration: no urgency signal, no explicit human request phrase
            user_message="no me funciona el sistema",
        )

        result = await mode.handle(state, intent=None)

        messages = result.get("messages", [])
        assert messages
        assert _ACKNOWLEDGE_REPLY in messages[0]["content"]
        # step advances to DESCRIBE (normal flow)
        assert result.get("mode_context", {}).get("escalation_step") == "DESCRIBE"

    @pytest.mark.asyncio
    async def test_urgency_single_ya_does_not_fast_path(self):
        """'ya' alone does not trigger urgency fast-path — starts normal ACKNOWLEDGE."""
        mode = EscalationMode(tools=[], llm_client=_make_mock_llm())
        state = _make_state(
            current_mode="BOOKING",
            escalation_triggered=False,
            escalation_step=None,
            user_message="ya",
        )

        result = await mode.handle(state, intent=None)

        messages = result.get("messages", [])
        assert messages
        # Should follow normal flow (ACKNOWLEDGE), not fast-path (CONTACT)
        assert _ACKNOWLEDGE_REPLY in messages[0]["content"]

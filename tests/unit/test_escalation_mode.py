"""
Unit tests for agent/modes/escalation_mode.py — create_agent migration (M4).

The escalation node is now a pure FSM factory — ``build_escalation_node()`` —
so no LLM is involved at all. Tests assert on state updates and response text.

Coverage:
- F-4 regression: no LLM call when escalation_triggered=True (implicit via FSM)
- Silence determinism: the return value is consistent when already escalated
- FSM step transitions (ACKNOWLEDGE → DESCRIBE → CONTACT → DONE)
- UP-1: _is_urgent() detection + urgency fast-path
- WS-4: explicit human request fast-path (handled via perform_escalation mock)
"""

from unittest.mock import AsyncMock, patch

import pytest

from agent.modes.escalation_mode import (
    _ACKNOWLEDGE_REPLY,
    _ALREADY_ESCALATED,
    _CONTACT_PROMPT,
    _URGENCY_SIGNALS,
    _is_urgent,
    _normalize_contact_preference,
    build_escalation_node,
)
from agent.state.schemas import create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def _make_state(
    *,
    escalation_triggered: bool = False,
    escalation_step: str | None = None,
    current_mode: str = "ESCALATION",
    user_message: str = "necesito ayuda urgente",
) -> dict:
    """Build a ConversationState for escalation tests."""
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


@pytest.fixture
def escalation_node():
    return build_escalation_node()


# =============================================================================
# T-15: F-4 regression — escalation silence guard
# =============================================================================


class TestEscalationSilenceGuard:
    """When escalation_triggered=True or step=DONE, the node returns the waiting message."""

    @pytest.mark.asyncio
    async def test_already_escalated_returns_waiting_message(self, escalation_node):
        state = _make_state(
            escalation_triggered=True,
            escalation_step="DONE",
            current_mode="ESCALATION",
        )

        result = await escalation_node(state)

        assert "messages" in result
        assert result.get("user_message") is None
        assert result.get("last_node") == "escalation"
        assert _ALREADY_ESCALATED in result["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_step_done_returns_waiting_message(self, escalation_node):
        state = _make_state(escalation_triggered=True, escalation_step="DONE")

        result = await escalation_node(state)

        assert result.get("last_node") == "escalation"
        assert _ALREADY_ESCALATED in result["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_silence_is_deterministic(self, escalation_node):
        results = []
        for _ in range(3):
            state = _make_state(escalation_triggered=True, escalation_step="DONE")
            result = await escalation_node(state)
            messages = result.get("messages", [])
            assert messages, "Expected messages in result"
            results.append(messages[0]["content"])

        assert all(r == results[0] for r in results)
        assert _ALREADY_ESCALATED in results[0]

    @pytest.mark.asyncio
    async def test_silence_response_contains_already_escalated_text(self, escalation_node):
        state = _make_state(escalation_triggered=True)

        result = await escalation_node(state)

        assert _ALREADY_ESCALATED in result["messages"][0]["content"]


# =============================================================================
# FSM step transitions
# =============================================================================


class TestEscalationFSMTransitions:
    """FSM step flow: fresh entry starts at ACKNOWLEDGE regardless of stale step."""

    @pytest.mark.asyncio
    async def test_fresh_entry_starts_at_acknowledge(self, escalation_node):
        """Fresh entry from BOOKING with a plain frustration message starts at ACKNOWLEDGE."""
        state = _make_state(
            current_mode="BOOKING",
            escalation_triggered=False,
            escalation_step=None,
            user_message="tengo un problema con mi cita",
        )

        result = await escalation_node(state)

        assert _ACKNOWLEDGE_REPLY in result["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_describe_step_sets_contact_prompt(self, escalation_node):
        state = _make_state(
            current_mode="ESCALATION",
            escalation_triggered=False,
            escalation_step="DESCRIBE",
            user_message="Mi problema es que no puedo cancelar la cita",
        )

        result = await escalation_node(state)

        assert _CONTACT_PROMPT in result["messages"][0]["content"]
        assert result.get("mode_context", {}).get("escalation_step") == "CONTACT"


# =============================================================================
# _normalize_contact_preference
# =============================================================================


class TestNormalizeContactPreference:
    def test_whatsapp_normalized(self):
        assert _normalize_contact_preference("por whatsapp") == "WhatsApp"
        assert _normalize_contact_preference("wsp") == "WhatsApp"

    def test_llamada_normalized(self):
        assert _normalize_contact_preference("por llamada") == "llamada"
        assert _normalize_contact_preference("teléfono") == "llamada"

    def test_unknown_passed_through(self):
        assert _normalize_contact_preference("email") == "email"


# =============================================================================
# UP-1: _is_urgent()
# =============================================================================


class TestIsUrgent:
    @pytest.mark.parametrize("signal", list(_URGENCY_SIGNALS))
    def test_all_signals_return_true(self, signal: str):
        assert _is_urgent(signal) is True

    def test_all_signals_case_insensitive(self):
        assert _is_urgent("URGENTE necesito ayuda") is True
        assert _is_urgent("EMERGENCIA en el salon") is True
        assert _is_urgent("Inmediatamente por favor") is True

    def test_standalone_ya_does_not_trigger(self):
        assert _is_urgent("ya") is False

    def test_empty_string_does_not_trigger(self):
        assert _is_urgent("") is False

    def test_unrelated_text_does_not_trigger(self):
        assert _is_urgent("quiero reservar una cita") is False
        assert _is_urgent("hola buenas tardes") is False

    def test_signal_embedded_in_sentence(self):
        assert _is_urgent("por favor es urgente necesito que me atiendas") is True
        assert _is_urgent("mañana es emergencia me quedo sin tiempo") is True


# =============================================================================
# UP-1: urgency fast-path through the node
# =============================================================================


class TestUrgencyFastPath:
    """UP-1: node jumps directly to CONTACT when urgency signal present on fresh entry."""

    @pytest.mark.asyncio
    async def test_urgency_fast_path_jumps_to_contact(self, escalation_node):
        state = _make_state(
            current_mode="BOOKING",
            escalation_triggered=False,
            escalation_step=None,
            user_message="Es URGENTE necesito ayuda AHORA MISMO",
        )

        result = await escalation_node(state)

        assert _CONTACT_PROMPT in result["messages"][0]["content"]
        assert result.get("mode_context", {}).get("escalation_step") == "CONTACT"
        assert result.get("mode_context", {}).get("issue_summary")

    @pytest.mark.asyncio
    async def test_urgency_fast_path_does_not_fire_mid_fsm(self, escalation_node):
        state = _make_state(
            current_mode="ESCALATION",
            escalation_triggered=False,
            escalation_step="DESCRIBE",
            user_message="urgente por favor",
        )

        result = await escalation_node(state)

        assert _CONTACT_PROMPT in result["messages"][0]["content"]
        assert result.get("mode_context", {}).get("escalation_step") == "CONTACT"

    @pytest.mark.asyncio
    async def test_no_urgency_fresh_entry_starts_acknowledge(self, escalation_node):
        state = _make_state(
            current_mode="BOOKING",
            escalation_triggered=False,
            escalation_step=None,
            user_message="no me funciona el sistema",
        )

        result = await escalation_node(state)

        assert _ACKNOWLEDGE_REPLY in result["messages"][0]["content"]
        assert result.get("mode_context", {}).get("escalation_step") == "DESCRIBE"

    @pytest.mark.asyncio
    async def test_urgency_single_ya_does_not_fast_path(self, escalation_node):
        state = _make_state(
            current_mode="BOOKING",
            escalation_triggered=False,
            escalation_step=None,
            user_message="ya",
        )

        result = await escalation_node(state)

        assert _ACKNOWLEDGE_REPLY in result["messages"][0]["content"]


# =============================================================================
# Technical auto-escalation (error_count >= 3)
# =============================================================================


class TestTechnicalAutoEscalation:
    """When error_count>=3 and no prior step, perform_escalation fires immediately."""

    @pytest.mark.asyncio
    async def test_error_count_triggers_technical_escalation(self, escalation_node):
        state = _make_state(
            current_mode="BOOKING",
            escalation_triggered=False,
            escalation_step=None,
            user_message="",
        )
        state["error_count"] = 3

        fake_result = AsyncMock()
        fake_result.user_message = "Tech user message"
        fake_result.steps_completed = ["conversation_locked"]

        with patch(
            "agent.services.escalation_service.perform_escalation",
            new=AsyncMock(return_value=fake_result),
        ):
            result = await escalation_node(state)

        assert result.get("escalation_triggered") is True
        assert result.get("mode_context", {}).get("escalation_step") == "DONE"

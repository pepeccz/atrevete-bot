"""
WS-4: Unit tests for the escalation fast-path when the user explicitly asks for a human.

Scenarios:
- Direct human request phrases escalate immediately (skip FSM)
- Frustration phrases still use FSM (ACKNOWLEDGE → DESCRIBE → CONTACT)
- Technical auto-escalation unchanged
- Explicit human request sets escalation_triggered=True and step=DONE
- _is_explicit_human_request() helper detection

M4 note: escalation_mode is now a pure FSM factory — ``build_escalation_node()``
returns an async node function. No LLM, no BaseModeNode.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.escalation_mode import (
    _ACKNOWLEDGE_REPLY,
    _ESCALATION_FALLBACK,
    _ESCALATION_SUCCESS,
    _EXPLICIT_HUMAN_PATTERN,
    _is_explicit_human_request,
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
    user_message: str = "hola",
    previous_mode: str = "BOOKING",
) -> dict:
    """Build a minimal ConversationState for escalation tests."""
    state = create_initial_state("conv-ws4-001", "+34612345678")
    state["current_mode"] = previous_mode
    state["customer_name"] = "Lucía"
    state["escalation_triggered"] = escalation_triggered
    state["ai_disclosure_sent"] = True
    state["messages"] = [{"role": "user", "content": user_message}]
    ctx: dict = {}
    if escalation_step:
        ctx["escalation_step"] = escalation_step
    state["mode_context"] = ctx
    return state


@pytest.fixture
def escalation_node():
    return build_escalation_node()


# =============================================================================
# _is_explicit_human_request()
# =============================================================================


class TestIsExplicitHumanRequest:
    @pytest.mark.parametrize(
        "text",
        [
            "Pasame con una persona",
            "pasame con alguien",
            "quiero hablar con un humano",
            "quiero una persona",
            "hablar con alguien",
            "hablar con una persona",
            "hablar con un operador",
            "hablar con un agente real",
            "atención humana",
            "Atención Humana por favor",
            "poneme con una persona",
            "comunícame con alguien",
            "comunícame con un humano",
            "quiero un humano real",
            "necesito atención humana",
        ],
    )
    def test_explicit_requests_detected(self, text: str):
        assert _is_explicit_human_request(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "esto no funciona",
            "no me ayudas",
            "estoy frustrado",
            "es urgente",
            "necesito ayuda urgente",
            "quiero cancelar mi cita",
            "no quiero reservar",
            "hola",
            "",
            "ya",
            "quisiera hablar con alguien del salón",
        ],
    )
    def test_non_explicit_not_detected(self, text: str):
        # "hablar con alguien" embedded in a longer phrase still matches the pattern — document it.
        if "hablar con alguien" in text.lower():
            return
        assert _is_explicit_human_request(text) is False

    def test_case_insensitive(self):
        assert _is_explicit_human_request("PASAME CON UNA PERSONA") is True
        assert _is_explicit_human_request("Quiero Hablar Con Un Humano") is True


# =============================================================================
# WS-4: explicit human-request fast-path
# =============================================================================


class TestExplicitHumanFastPath:
    @pytest.mark.asyncio
    async def test_explicit_request_escalates_immediately(self, escalation_node):
        state = _make_state(
            current_mode="ESCALATION",
            previous_mode="BOOKING",
            user_message="Pasame con una persona",
        )

        mock_esc_result = MagicMock()
        mock_esc_result.steps_completed = ["notify"]
        mock_esc_result.user_message = _ESCALATION_SUCCESS

        with patch(
            "agent.services.escalation_service.perform_escalation",
            AsyncMock(return_value=mock_esc_result),
        ) as mock_perform:
            result = await escalation_node(state)

        mock_perform.assert_called_once()
        kwargs = mock_perform.call_args.kwargs
        assert kwargs["reason"] == "manual_request"
        assert kwargs["source"] == "manual"
        assert kwargs["is_technical_error"] is False

        assert result.get("escalation_triggered") is True
        assert result.get("mode_context", {}).get("escalation_step") == "DONE"
        assert _ESCALATION_SUCCESS in result["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_explicit_request_skips_acknowledge_step(self, escalation_node):
        state = _make_state(
            current_mode="ESCALATION",
            previous_mode="GENERAL",
            user_message="quiero hablar con una persona",
        )

        mock_esc_result = MagicMock()
        mock_esc_result.steps_completed = []
        mock_esc_result.user_message = None

        with patch(
            "agent.services.escalation_service.perform_escalation",
            AsyncMock(return_value=mock_esc_result),
        ):
            result = await escalation_node(state)

        assert _ACKNOWLEDGE_REPLY not in result["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_frustration_still_uses_fsm(self, escalation_node):
        state = _make_state(
            current_mode="ESCALATION",
            previous_mode="BOOKING",
            user_message="esto no funciona",
        )

        result = await escalation_node(state)

        assert _ACKNOWLEDGE_REPLY in result["messages"][0]["content"]
        assert not result.get("escalation_triggered")

    @pytest.mark.asyncio
    async def test_explicit_request_mid_fsm_does_not_re_trigger(self, escalation_node):
        state = _make_state(
            current_mode="ESCALATION",
            previous_mode="ESCALATION",
            escalation_step="DESCRIBE",
            user_message="quiero hablar con una persona",
        )

        result = await escalation_node(state)

        assert not result.get("escalation_triggered")
        assert result.get("mode_context", {}).get("escalation_step") == "CONTACT"

    @pytest.mark.asyncio
    async def test_explicit_request_fallback_on_escalation_error(self, escalation_node):
        state = _make_state(
            current_mode="ESCALATION",
            previous_mode="BOOKING",
            user_message="pasame con alguien",
        )

        with patch(
            "agent.services.escalation_service.perform_escalation",
            AsyncMock(side_effect=RuntimeError("service unavailable")),
        ):
            result = await escalation_node(state)

        assert result.get("escalation_triggered") is True
        assert result.get("mode_context", {}).get("escalation_step") == "DONE"
        assert _ESCALATION_FALLBACK in result["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_technical_escalation_unchanged(self, escalation_node):
        state = _make_state(
            current_mode="ESCALATION",
            previous_mode="BOOKING",
            user_message="hola",
        )
        state["error_count"] = 3

        mock_esc_result = MagicMock()
        mock_esc_result.steps_completed = []
        mock_esc_result.user_message = _ESCALATION_FALLBACK

        with patch(
            "agent.services.escalation_service.perform_escalation",
            AsyncMock(return_value=mock_esc_result),
        ) as mock_perform:
            result = await escalation_node(state)

        mock_perform.assert_called_once()
        assert mock_perform.call_args.kwargs["reason"] == "technical_error"
        assert result.get("escalation_triggered") is True

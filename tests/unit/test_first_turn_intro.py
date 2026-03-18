"""Unit tests for first-turn AI disclosure intro behavior."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.base import AgenticLoopResult, BaseModeNode, FIRST_TURN_INTRO
from agent.modes.booking_mode import BookingMode
from agent.modes.general_mode import GeneralMode
from agent.modes.greeting_mode import GreetingMode
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


class _DummyMode(BaseModeNode):
    @property
    def mode_name(self) -> str:
        return "GENERAL"

    async def handle(self, state, intent):  # pragma: no cover - helper-only dummy
        return {"last_node": "dummy"}


def _make_mock_llm(response_text: str = "OK") -> MagicMock:
    response = MagicMock()
    response.content = response_text
    response.tool_calls = []

    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=response)
    llm.bind_tools.return_value = llm
    return llm


def _make_intent(intent: str, confidence: float = 0.9) -> IntentResult:
    return IntentResult(intent=intent, confidence=confidence, raw_input="test", mode_hint=intent.upper())


@pytest.mark.asyncio
async def test_first_turn_booking_response_starts_with_intro():
    mode = BookingMode(tools=[], llm_client=_make_mock_llm())
    state = create_initial_state("conv-intro-booking", "+34612345678")
    state["current_mode"] = "BOOKING"
    state["mode_context"] = {"booking_step": "service_selection"}
    state["customer_name"] = "Ana"
    state["customer_id"] = "cust-123"
    state["user_message"] = "Quiero cortarme el pelo"

    with patch.object(mode, "_build_layered_messages", new=AsyncMock(return_value=[])), patch.object(
        mode,
        "_run_agentic_loop",
        new=AsyncMock(return_value=AgenticLoopResult(response_text="¿El corte es para caballero, dama, niño, niña o bebé?")),
    ):
        result = await mode.handle(state, _make_intent("book"))

    assert result["messages"][0]["content"].startswith(FIRST_TURN_INTRO)
    assert result["ai_disclosure_sent"] is True


@pytest.mark.asyncio
async def test_first_turn_greeting_response_starts_with_intro():
    mode = GreetingMode(tools=[], llm_client=_make_mock_llm())
    state = create_initial_state("conv-intro-greeting", "+34612345679")
    state["user_message"] = "Hola"

    with patch.object(
        mode,
        "_render_layered_response",
        new=AsyncMock(return_value="¿En qué puedo ayudarte hoy?"),
    ):
        result = await mode.handle(state, _make_intent("greet"))

    assert result["messages"][0]["content"].startswith(FIRST_TURN_INTRO)
    assert result["ai_disclosure_sent"] is True


@pytest.mark.asyncio
async def test_second_turn_response_does_not_start_with_intro_when_flag_already_set():
    mode = GeneralMode(tools=[], llm_client=_make_mock_llm())
    state = create_initial_state("conv-intro-general", "+34612345670")
    state["is_first_interaction"] = False
    state["ai_disclosure_sent"] = True
    state["current_mode"] = "GENERAL"
    state["user_message"] = "¿A qué hora abrís?"

    with patch.object(mode, "_build_layered_messages", new=AsyncMock(return_value=[])), patch.object(
        mode,
        "_run_agentic_loop",
        new=AsyncMock(return_value=AgenticLoopResult(response_text="Abrimos de lunes a sábado de 9:00 a 20:00.")),
    ):
        result = await mode.handle(state, _make_intent("general"))

    assert not result["messages"][0]["content"].startswith(FIRST_TURN_INTRO)
    assert "ai_disclosure_sent" not in result


def test_helper_returns_text_unchanged_when_ai_disclosure_already_sent():
    mode = _DummyMode(tools=[], llm_client=_make_mock_llm())

    response_text, disclosure_sent = mode._maybe_prepend_intro(
        "Respuesta normal.",
        {"ai_disclosure_sent": True},
    )

    assert response_text == "Respuesta normal."
    assert disclosure_sent is False


def test_helper_does_not_double_prepend_when_intro_is_already_present():
    mode = _DummyMode(tools=[], llm_client=_make_mock_llm())
    original_text = f"{FIRST_TURN_INTRO} ¿En qué puedo ayudarte hoy?"

    response_text, disclosure_sent = mode._maybe_prepend_intro(
        original_text,
        {"ai_disclosure_sent": False},
    )

    assert response_text == original_text  # no duplication — text unchanged
    assert disclosure_sent is True  # disclosure IS present (LLM already included it)

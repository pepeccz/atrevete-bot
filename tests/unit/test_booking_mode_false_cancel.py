from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.modes.booking_mode import BookingMode
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


def _make_intent(intent: str = "reject", confidence: float = 0.9) -> IntentResult:
    return IntentResult(intent=intent, confidence=confidence, raw_input="test", mode_hint="BOOKING")


def _make_mode() -> BookingMode:
    mock_llm = MagicMock()
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    mock_llm.ainvoke = AsyncMock()
    return BookingMode(tools=[], llm_client=mock_llm)


def _make_state(step: str, user_message: str) -> dict:
    state = create_initial_state("conv-booking-false-cancel", "+34612345678")
    state["current_mode"] = "BOOKING"
    state["is_first_interaction"] = False
    state["customer_name"] = "Juan"
    state["customer_id"] = "cust-123"
    state["messages"] = [{"role": "user", "content": user_message, "timestamp": "2026-03-17T10:00:00+01:00"}]
    state["mode_context"] = {"booking_step": step}
    return state


@pytest.mark.asyncio
async def test_service_selection_false_cancel_asks_for_clarification() -> None:
    mode = _make_mode()
    state = _make_state("service_selection", "No soy pedofilo mamon, es para una mujer adulta")

    result = await mode.handle(state, _make_intent("reject"))

    assert result.get("current_mode") != "GENERAL"
    assert "corte, color" in result["messages"][0]["content"]
    assert result["mode_context"]["last_intent"] == "ambiguous"


@pytest.mark.asyncio
async def test_confirmation_explicit_no_quiero_cancels_booking() -> None:
    mode = _make_mode()
    state = _make_state("confirmation", "No quiero")

    result = await mode.handle(state, _make_intent("reject"))

    assert result["current_mode"] == "GENERAL"
    assert "he cancelado la reserva" in result["messages"][0]["content"].lower()

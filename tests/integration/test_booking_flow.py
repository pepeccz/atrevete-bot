from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent.modes.base import AgenticLoopResult
from agent.modes.booking_mode import BookingMode
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


def _make_intent(intent: str = "book") -> IntentResult:
    return IntentResult(intent=intent, confidence=0.9, raw_input="", mode_hint="BOOKING")


def _build_booking_state() -> dict:
    state = create_initial_state("conv-booking-happy-path", "+34600000003", customer_name="Ana")
    state["current_mode"] = "BOOKING"
    state["customer_name"] = "Ana"
    state["customer_first_name"] = "Ana"
    state["is_first_interaction"] = False
    return state


@pytest.mark.asyncio
async def test_booking_happy_path_keeps_existing_flow_working():
    mode = BookingMode(tools=[], llm_client=AsyncMock())
    state = _build_booking_state()
    state["user_message"] = "quiero corte dama"

    with patch.object(mode, "_build_layered_messages", new=AsyncMock(return_value=[])), patch.object(
        mode,
        "_run_agentic_loop",
        new=AsyncMock(
            side_effect=[
                AgenticLoopResult(
                    response_text="Perfecto, sigamos con la estilista.",
                    tool_results={
                        "search_services": {
                            "resolved_service": {
                                "id": "svc-1",
                                "name": "Cortar",
                                "category": "Peluquería",
                                "duration_minutes": 45,
                                "family": "haircut",
                            }
                        }
                    },
                ),
                AgenticLoopResult(
                    response_text="Te muestro estilistas.",
                    tool_results={"list_stylists": [{"id": "sty-1", "name": "María"}]},
                ),
                AgenticLoopResult(
                    response_text="Tengo este horario.",
                    tool_results={
                        "check_availability": {
                            "available_slots": [
                                {
                                    "start_time": "2026-03-25T10:00:00+01:00",
                                    "full_datetime": "2026-03-25T10:00:00+01:00",
                                    "date": "2026-03-25",
                                    "time": "10:00",
                                }
                            ],
                            "date_too_soon": False,
                            "holiday_detected": False,
                            "is_same_day": False,
                        }
                    },
                ),
                AgenticLoopResult(response_text="Anotado, vamos al resumen."),
                AgenticLoopResult(response_text="Perfecto, confirmemos."),
            ]
        ),
    ):
        result = await mode.handle(state, _make_intent())
        assert result["mode_context"]["booking_step"] == "stylist_selection"

        state.update(result)
        state["user_message"] = "con María"
        result = await mode.handle(state, _make_intent())
        assert result["mode_context"]["booking_step"] == "slot_selection"

        state.update(result)
        state["user_message"] = "el miércoles a las 10"
        result = await mode.handle(state, _make_intent())
        assert result["mode_context"]["booking_step"] == "notes"

        state.update(result)
        state["user_message"] = "no, nada más"
        result = await mode.handle(state, _make_intent())
        assert result["mode_context"]["booking_step"] == "confirmation"

        state.update(result)
        state["user_message"] = "sí"
        result = await mode.handle(state, _make_intent("confirm"))
        assert result["mode_context"]["booking_step"] == "completed"

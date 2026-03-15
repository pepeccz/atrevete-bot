"""Integration coverage for booking substep progression and digression recovery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.graphs.conversation_flow import router_node
from agent.modes.base import AgenticLoopResult
from agent.modes.booking_mode import BookingMode
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


def _make_intent(intent: str = "book") -> IntentResult:
    return IntentResult(intent=intent, confidence=0.9, raw_input="", mode_hint="BOOKING")


def _build_booking_state() -> dict:
    state = create_initial_state("conv-booking-flow", "+34600000001", customer_name="Ana")
    state["current_mode"] = "BOOKING"
    state["is_first_interaction"] = False
    state["customer_first_name"] = "Ana"
    state["customer_name"] = "Ana"
    return state


@pytest.mark.asyncio
async def test_booking_mode_progresses_through_canonical_substeps():
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
                        "find_next_available": [
                            {"start_time": "2026-03-20T10:00:00+01:00", "stylist_id": "sty-1"}
                        ]
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
        state["user_message"] = "con Maria"
        result = await mode.handle(state, _make_intent())
        assert result["mode_context"]["booking_step"] == "slot_selection"

        state.update(result)
        state["user_message"] = "el jueves a las 10"
        result = await mode.handle(state, _make_intent())
        assert result["mode_context"]["booking_step"] == "notes"

        state.update(result)
        state["user_message"] = "no, nada mas"
        result = await mode.handle(state, _make_intent())
        assert result["mode_context"]["booking_step"] == "confirmation"
        assert result["mode_context"]["customer_name"] == "Ana"

        state.update(result)
        state["user_message"] = "si"
        result = await mode.handle(state, _make_intent("confirm"))
        assert result["mode_context"]["booking_step"] == "completed"


@pytest.mark.asyncio
async def test_booking_digression_restores_preserved_context_on_reentry():
    state = create_initial_state("conv-booking-digression", "+34600000002", customer_name="Ana")
    state["current_mode"] = "BOOKING"
    state["customer_name"] = "Ana"
    state["is_first_interaction"] = False
    state["messages"] = [
        {"role": "user", "content": "que productos usan?", "timestamp": "2026-03-15T10:00:00"}
    ]
    state["user_message"] = "que productos usan?"
    state["mode_context"] = {
        "booking_step": "slot_selection",
        "service_id": "svc-1",
        "service_name": "Cortar",
        "stylist_id": "sty-1",
        "stylist_name": "María",
        "selected_slot": {"start_time": "2026-03-20T10:00:00+01:00"},
        "slot_summary": "20/03 10:00",
    }

    ask_info_router = SimpleNamespace(classify=AsyncMock(return_value=_make_intent("ask_info")))
    with patch("agent.graphs.conversation_flow._get_intent_router", return_value=ask_info_router):
        digression = await router_node(state)

    assert digression["current_mode"] == "GENERAL"
    assert digression["draft_contexts"]["BOOKING"]["booking_step"] == "slot_selection"

    resumed_state = create_initial_state("conv-booking-digression", "+34600000002", customer_name="Ana")
    resumed_state["current_mode"] = "GENERAL"
    resumed_state["customer_name"] = "Ana"
    resumed_state["is_first_interaction"] = False
    resumed_state["draft_contexts"] = digression["draft_contexts"]
    resumed_state["messages"] = [
        {"role": "user", "content": "dale, volvamos con el turno", "timestamp": "2026-03-15T10:05:00"}
    ]
    resumed_state["user_message"] = "dale, volvamos con el turno"

    book_router = SimpleNamespace(classify=AsyncMock(return_value=_make_intent("book")))
    with patch("agent.graphs.conversation_flow._get_intent_router", return_value=book_router):
        resume = await router_node(resumed_state)

    assert resume["current_mode"] == "BOOKING"
    assert resume["mode_context"]["booking_step"] == "slot_selection"
    assert resume["mode_context"]["service_id"] == "svc-1"
    assert resume["mode_context"]["selected_slot"]["start_time"] == "2026-03-20T10:00:00+01:00"


@pytest.mark.asyncio
async def test_booking_happy_path_executes_booking_and_returns_to_general():
    mode = BookingMode(tools=[], llm_client=AsyncMock())

    state = _build_booking_state()
    state["mode_context"] = {
        "booking_step": "completed",
        "service_id": "svc-1",
        "service_name": "Cortar",
        "selected_services": ["Cortar", "Peinado"],
        "stylist_id": "sty-1",
        "stylist_name": "María",
        "selected_slot": {"start_time": "2026-03-20T10:00:00+01:00"},
        "slot_summary": "jueves 20/03 a las 10:00",
        "notes": "Quiero algo natural",
        "customer_name": "Ana",
    }
    state["customer_id"] = "cust-1"
    state["user_message"] = "si, confirmo"

    book_tool = MagicMock()
    book_tool.ainvoke = AsyncMock(return_value={"appointment_id": "apt-1", "status": "booked"})

    with patch("agent.tools.booking_tools.book", new=book_tool), patch.object(
        mode,
        "_build_layered_messages",
        new=AsyncMock(return_value=[]),
    ), patch.object(
        mode,
        "_run_agentic_loop",
        new=AsyncMock(return_value=AgenticLoopResult(response_text="¡Listo! Tu turno quedó agendado. Te esperamos 💇‍♀️")),
    ):
        result = await mode.handle(state, _make_intent("confirm"))

    book_tool.ainvoke.assert_awaited_once()
    assert result["appointment_created"] is True
    assert result["current_mode"] == "GENERAL"


@pytest.mark.asyncio
async def test_booking_change_mind_mid_flow_rewinds_to_stylist_selection_without_losing_service():
    mode = BookingMode(tools=[], llm_client=AsyncMock())

    state = _build_booking_state()
    state["user_message"] = "mejor quiero con Lucía"
    state["mode_context"] = {
        "booking_step": "slot_selection",
        "service_id": "svc-1",
        "service_name": "Cortar",
        "stylist_id": "sty-1",
        "stylist_name": "María",
        "selected_slot": {"start_time": "2026-03-20T10:00:00+01:00"},
        "slot_summary": "20/03 10:00",
    }

    result = await mode.handle(state, _make_intent())

    assert result["mode_context"]["booking_step"] == "stylist_selection"
    assert result["mode_context"]["service_name"] == "Cortar"
    assert "selected_slot" not in result["mode_context"]


@pytest.mark.asyncio
async def test_booking_service_recommendations_are_offered_before_stylist_selection():
    mode = BookingMode(tools=[], llm_client=AsyncMock())

    state = _build_booking_state()
    state["user_message"] = "quiero corte dama"

    with patch.object(mode, "_build_layered_messages", new=AsyncMock(return_value=[])), patch.object(
        mode,
        "_run_agentic_loop",
        new=AsyncMock(
            return_value=AgenticLoopResult(
                response_text="Perfecto, ya tengo tu servicio.",
                tool_results={
                    "search_services": {
                        "resolved_service": {
                            "id": "svc-1",
                            "name": "Cortar",
                            "category": "Peluquería",
                            "duration_minutes": 45,
                            "family": "haircut",
                            "combo_recommendations": ["Peinado", "Barro"],
                        }
                    }
                },
            )
        ),
    ):
        result = await mode.handle(state, _make_intent())

    assert result["mode_context"]["booking_step"] == "stylist_selection"
    assert "Peinado" in result["messages"][0]["content"]
    assert "Barro" in result["messages"][0]["content"]

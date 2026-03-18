from unittest.mock import AsyncMock, MagicMock, patch

from agent.modes.base import AgenticLoopResult
from agent.modes.booking_mode import BookingMode
from agent.prompts.loader import build_step_context
from agent.state.schemas import create_initial_state


def make_mock_llm(response_text: str = "¿Con qué estilista prefieres?") -> AsyncMock:
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def make_booking_mode(llm_response: str = "¿Con qué estilista prefieres?") -> BookingMode:
    return BookingMode(tools=[], llm_client=make_mock_llm(llm_response))


def make_state_with_step(booking_step: str = "stylist_selection") -> dict:
    state = create_initial_state("conv-001", "+34612345678")
    state["customer_name"] = "Juan"
    state["customer_id"] = "cust-123"
    state["is_first_interaction"] = False
    state["current_mode"] = "BOOKING"
    state["mode_context"] = {"booking_step": booking_step}
    return state


class TestStylistProactiveListing:
    async def test_prefetch_returns_stylists_with_availability(self):
        mode = make_booking_mode()
        mode_context = {
            "service_category": "Peluquería",
            "service_duration_minutes": 40,
        }

        list_stylists_tool = MagicMock()
        list_stylists_tool.ainvoke = AsyncMock(
            return_value={
                "stylists": [
                    {"id": "uuid-1", "name": "Ana", "category": "HAIRDRESSING"}
                ],
                "count": 1,
            }
        )
        find_next_available_tool = MagicMock()
        find_next_available_tool.ainvoke = AsyncMock(
            return_value={
                "available_stylists": [
                    {
                        "stylist_name": "Ana",
                        "stylist_id": "uuid-1",
                        "slots": [
                            {
                                "time": "10:00",
                                "date": "2026-03-20",
                                "day_name": "viernes",
                                "full_datetime": "2026-03-20T10:00:00+01:00",
                            }
                        ],
                    }
                ],
                "total_slots_found": 1,
                "error": None,
            }
        )

        with patch("agent.tools.info_tools.list_stylists", new=list_stylists_tool), patch(
            "agent.tools.availability_tools.find_next_available", new=find_next_available_tool
        ):
            result = await mode._prefetch_stylist_options(mode_context)

        assert len(result["prefetched_stylists"]) == 1
        assert result["prefetched_stylists"][0]["name"] == "Ana"
        assert "viernes" in result["prefetched_stylists"][0]["next_slot_summary"]
        assert "10:00" in result["prefetched_stylists"][0]["next_slot_summary"]
        assert result["soonest_any_slot"] is not None
        assert "Ana" in result["soonest_any_slot"]

    async def test_prefetch_graceful_fallback_on_error(self):
        mode = make_booking_mode()
        mode_context = {"service_category": "Peluquería"}

        list_stylists_tool = MagicMock()
        list_stylists_tool.ainvoke = AsyncMock(side_effect=Exception("DB error"))

        with patch("agent.tools.info_tools.list_stylists", new=list_stylists_tool):
            result = await mode._prefetch_stylist_options(mode_context)

        assert result == mode_context
        assert not result.get("prefetched_stylists")

    async def test_prefetch_stylist_with_no_availability(self):
        mode = make_booking_mode()
        mode_context = {"service_category": "Peluquería"}

        list_stylists_tool = MagicMock()
        list_stylists_tool.ainvoke = AsyncMock(
            return_value={
                "stylists": [
                    {"id": "uuid-1", "name": "Ana", "category": "HAIRDRESSING"},
                    {"id": "uuid-2", "name": "María", "category": "HAIRDRESSING"},
                ],
                "count": 2,
            }
        )
        find_next_available_tool = MagicMock()
        find_next_available_tool.ainvoke = AsyncMock(
            return_value={
                "available_stylists": [],
                "total_slots_found": 0,
                "error": None,
            }
        )

        with patch("agent.tools.info_tools.list_stylists", new=list_stylists_tool), patch(
            "agent.tools.availability_tools.find_next_available", new=find_next_available_tool
        ):
            result = await mode._prefetch_stylist_options(mode_context)

        assert len(result["prefetched_stylists"]) == 2
        assert all(
            "Sin disponibilidad" in stylist["next_slot_summary"]
            for stylist in result["prefetched_stylists"]
        )
        assert result["soonest_any_slot"] is None

    def test_loader_injects_prefetched_stylists_into_context(self):
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "Juan"
        mode_context = {
            "booking_step": "stylist_selection",
            "service_name": "Cortar",
            "prefetched_stylists": [
                {
                    "name": "Ana",
                    "id": "uuid-1",
                    "next_slot_summary": "viernes 20 de marzo a las 10:00",
                }
            ],
            "soonest_any_slot": "viernes 20 de marzo a las 10:00 con Ana",
        }

        context = build_step_context(state, mode_context)

        assert "Ana" in context
        assert "viernes 20 de marzo" in context
        assert "Cualquier profesional disponible" in context

    async def test_stylist_selection_does_not_pass_tools_to_agentic_loop(self):
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="stylist_selection")
        state["mode_context"].update(
            {
                "service_name": "Cortar",
                "service_category": "Peluquería",
            }
        )

        run_loop_mock = AsyncMock(
            return_value=AgenticLoopResult(
                response_text="Elegí la profesional que prefieras.",
                tool_results={},
            )
        )

        with patch.object(
            mode,
            "_prefetch_stylist_options",
            new=AsyncMock(side_effect=lambda context: context),
        ), patch.object(
            mode,
            "_populate_recurrent_stylist",
            new=AsyncMock(side_effect=lambda _state, context: context),
        ), patch.object(
            mode,
            "_build_layered_messages",
            new=AsyncMock(return_value=[]),
        ), patch.object(mode, "_run_agentic_loop", new=run_loop_mock):
            await mode._handle_stylist_selection(state, state["mode_context"])

        assert run_loop_mock.await_args.kwargs["tools"] == []

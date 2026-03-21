from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.base import AgenticLoopResult
from agent.modes.booking_context import BookingSubstep
from agent.modes.booking_mode import BookingMode
from agent.state.schemas import create_initial_state


def make_mock_llm(response_text: str = "Perfecto") -> AsyncMock:
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def make_booking_mode() -> BookingMode:
    return BookingMode(tools=[], llm_client=make_mock_llm())


def make_service_state(user_message: str = "corte de dama") -> dict:
    state = create_initial_state("conv-audience", "+34611000100")
    state["current_mode"] = "BOOKING"
    state["customer_name"] = "Ana"
    state["customer_id"] = "cust-audience"
    state["messages"] = [{"role": "user", "content": user_message}]
    state["mode_context"] = {
        "booking_step": BookingSubstep.SERVICE_SELECTION.value,
        "service_audience_hint": "adult_female",
        "implicit_service_hint": user_message,
    }
    return state


class TestAudienceExtraction:
    def test_extracts_adult_female_audience_from_opening_request(self):
        hints = BookingMode._extract_opening_booking_hints("Hola, quiero corte de dama")

        assert hints["service_audience_hint"] == "adult_female"

    def test_extracts_child_female_audience_from_nina_request(self):
        hints = BookingMode._extract_opening_booking_hints("Quiero corte para niña")

        assert hints["service_audience_hint"] == "child_female"

    def test_extracts_adult_male_audience_from_caballero_request(self):
        hints = BookingMode._extract_opening_booking_hints("Hola, corte de caballero")

        assert hints["service_audience_hint"] == "adult_male"

    def test_missing_audience_does_not_set_structured_hint(self):
        hints = BookingMode._extract_opening_booking_hints("Hola, quiero un corte")

        assert "service_audience_hint" not in hints


class TestAudienceAwareResolution:
    @pytest.mark.asyncio
    async def test_service_selection_passes_structured_audience_to_search_services(self):
        mode = make_booking_mode()
        state = make_service_state()

        with (
            patch("agent.tools.search_services.search_services") as mock_search,
            patch.object(mode, "_use_optimized_prompts", return_value=False),
            patch.object(mode, "_run_agentic_loop", new_callable=AsyncMock) as mock_loop,
        ):
            mock_search.ainvoke = AsyncMock(
                return_value={
                    "resolved_service": {
                        "id": "svc-001",
                        "name": "Cortar",
                        "category": "Mujer",
                        "duration_minutes": 45,
                        "family": "haircut",
                    }
                }
            )
            mock_loop.return_value = AgenticLoopResult(
                response_text="Perfecto, seguimos con la reserva.",
                tool_results={},
                tool_events=[],
            )

            await mode._handle_service_selection(state, dict(state["mode_context"]))

        mock_search.ainvoke.assert_awaited_once_with(
            {
                "query": "corte de dama",
                "category": None,
                "audience": "adult_female",
            }
        )

    @pytest.mark.asyncio
    async def test_resolved_service_clears_pending_clarification_and_advances(self):
        mode = make_booking_mode()
        state = make_service_state()

        with (
            patch("agent.tools.search_services.search_services") as mock_search,
            patch.object(mode, "_use_optimized_prompts", return_value=False),
            patch.object(mode, "_run_agentic_loop", new_callable=AsyncMock) as mock_loop,
        ):
            mock_search.ainvoke = AsyncMock(
                return_value={
                    "resolved_service": {
                        "id": "svc-001",
                        "name": "Cortar",
                        "category": "Mujer",
                        "duration_minutes": 45,
                        "family": "haircut",
                    }
                }
            )
            mock_loop.return_value = AgenticLoopResult(
                response_text="Perfecto, vamos con Cortar.",
                tool_results={},
                tool_events=[],
            )

            result = await mode._handle_service_selection(state, dict(state["mode_context"]))

        mode_context = result["mode_context"]
        assert mode_context["service_name"] == "Cortar"
        assert mode_context["booking_step"] == BookingSubstep.ADD_ONS.value
        assert mode_context.get("pending_clarification") is None

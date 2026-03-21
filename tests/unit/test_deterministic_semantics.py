from unittest.mock import AsyncMock, MagicMock, patch
from typing import cast

import pytest

from agent.modes.base import AgenticLoopResult
from agent.modes.booking_context import BookingSubstep
from agent.modes.booking_mode import BookingMode
from agent.state.schemas import ConversationState, create_initial_state


def _make_mock_llm(response_text: str = "Perfecto") -> AsyncMock:
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def _make_mode() -> BookingMode:
    return BookingMode(tools=[], llm_client=_make_mock_llm())


def _make_state(user_message: str = "quiero corte") -> ConversationState:
    state = create_initial_state("conv-deterministic-semantics", "+34612345678")
    state["current_mode"] = "BOOKING"
    state["is_first_interaction"] = False
    state["customer_id"] = "cust-123"
    state["customer_name"] = "Ana"
    state["messages"] = [{"role": "user", "content": user_message, "timestamp": "2026-03-20T10:00:00+01:00"}]
    state["mode_context"] = {"booking_step": BookingSubstep.SERVICE_SELECTION.value}
    return cast(ConversationState, state)


class TestDeterministicSemanticHelpers:
    def test_is_addon_decline_accepts_no_gracias(self):
        assert BookingMode._is_addon_decline("no gracias") is True

    def test_is_addon_decline_rejects_explicit_cancel(self):
        assert BookingMode._is_addon_decline("cancelar la cita") is False

    def test_is_addon_decline_accepts_solo_eso(self):
        assert BookingMode._is_addon_decline("solo eso") is True

    def test_is_addon_decline_rejects_positive_add_on_selection(self):
        assert BookingMode._is_addon_decline("si, anade el peinado") is False

    @pytest.mark.parametrize(
        ("message", "pending_recommendations", "expected"),
        [
            ("No gracias, solo el corte", ["Peinado", "Barro"], "decline"),
            ("No", ["Peinado"], "decline"),
            ("Si, agrega peinado", ["Peinado", "Barro"], "accept"),
            ("Quiero cancelar", ["Peinado"], "cancel"),
            ("Cuanto cuesta el peinado?", ["Peinado"], "unknown"),
            ("Solo quiero lo que elegi", ["Peinado"], "decline"),
            ("Peinado no, barro tampoco", ["Peinado", "Barro"], "decline"),
        ],
    )
    def test_resolve_add_on_intent(self, message, pending_recommendations, expected):
        assert BookingMode._resolve_add_on_intent(message, pending_recommendations) == expected

    def test_is_explicit_booking_cancel_accepts_cancelar(self):
        assert BookingMode._is_explicit_booking_cancel("cancelar") is True

    def test_is_explicit_booking_cancel_rejects_no_gracias(self):
        assert BookingMode._is_explicit_booking_cancel("no gracias") is False


class TestDeterministicServiceResolution:
    @pytest.mark.asyncio
    async def test_service_resolution_passes_audience_to_search_services(self):
        mode = _make_mode()
        state = _make_state()
        mode_context = {
            "booking_step": BookingSubstep.SERVICE_SELECTION.value,
            "service_query": "corte",
            "service_audience_hint": "adult_female",
        }
        search_result = {
            "resolved_service": {
                "id": "svc-1",
                "name": "Cortar",
                "category": "Peluqueria",
                "duration_minutes": 45,
                "family": "haircut",
                "combo_recommendations": [],
            }
        }

        with (
            patch.object(mode, "_use_optimized_prompts", return_value=False),
            patch("agent.tools.search_services.search_services") as search_mock,
            patch.object(
                mode,
                "_run_agentic_loop",
                new=AsyncMock(return_value=AgenticLoopResult(response_text="Perfecto", tool_results={})),
            ),
        ):
            search_mock.ainvoke = AsyncMock(return_value=search_result)
            await mode._handle_service_selection(state, mode_context)

        search_mock.ainvoke.assert_awaited_once_with(
            {"query": "corte", "category": None, "audience": "adult_female"}
        )

    @pytest.mark.asyncio
    async def test_service_resolution_uses_resolved_service_without_clarification(self):
        mode = _make_mode()
        state = _make_state()
        mode_context = {
            "booking_step": BookingSubstep.SERVICE_SELECTION.value,
            "service_query": "corte",
            "service_audience_hint": "adult_female",
        }
        search_result = {
            "resolved_service": {
                "id": "svc-1",
                "name": "Cortar",
                "category": "Peluqueria",
                "duration_minutes": 45,
                "family": "haircut",
                "combo_recommendations": [],
            }
        }

        with (
            patch.object(mode, "_use_optimized_prompts", return_value=False),
            patch("agent.tools.search_services.search_services") as search_mock,
            patch.object(
                mode,
                "_run_agentic_loop",
                new=AsyncMock(return_value=AgenticLoopResult(response_text="Perfecto", tool_results={})),
            ),
        ):
            search_mock.ainvoke = AsyncMock(return_value=search_result)
            result = await mode._handle_service_selection(state, mode_context)

        assert result["mode_context"]["service_name"] == "Cortar"
        assert result["mode_context"]["service_id"] == "svc-1"
        assert result["mode_context"]["booking_step"] == BookingSubstep.ADD_ONS.value
        assert "pending_clarification" not in result["mode_context"]

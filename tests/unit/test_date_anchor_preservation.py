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


def make_booking_state(step: str, user_message: str) -> dict:
    state = create_initial_state("conv-date", "+34611000101")
    state["current_mode"] = "BOOKING"
    state["customer_name"] = "Ana"
    state["customer_id"] = "cust-date"
    state["messages"] = [{"role": "user", "content": user_message}]
    state["mode_context"] = {
        "booking_step": step,
        "service_name": "Cortar",
        "service_id": "svc-001",
        "service_category": "Mujer",
        "service_duration_minutes": 45,
    }
    return state


class TestOpeningDateHints:
    def test_opening_request_seeds_date_and_time_hints(self):
        mode = make_booking_mode()

        result = mode._seed_opening_booking_hints(
            {}, "Hola, quiero corte de dama para el jueves que viene por la tarde"
        )

        assert result["availability_start_date"] == (
            "Hola, quiero corte de dama para el jueves que viene por la tarde"
        )
        assert result["availability_time_range"] == "afternoon"


class TestSameTurnAnchorPreservation:
    @pytest.mark.asyncio
    async def test_same_turn_cualquiera_handoff_keeps_existing_anchor(self):
        mode = make_booking_mode()
        state = make_booking_state(BookingSubstep.STYLIST_SELECTION.value, "Cualquiera.")
        state["mode_context"].update({"availability_start_date": "jueves que viene"})
        captured: dict[str, str] = {}

        async def fake_slot_handler(_state: dict, mode_context: dict) -> dict:
            captured.update(mode_context)
            return {"mode_context": mode_context, "last_node": "booking", "user_message": None}

        with (
            patch.object(
                mode,
                "_prefetch_stylist_options",
                return_value={
                    "status": "ok",
                    "prefetched_stylists": [{"id": "stylist-1", "name": "Pilar"}],
                    "soonest_any_slot": "jueves 10:00",
                    "soonest_any_slot_candidate": {
                        "stylist_id": "stylist-1",
                        "stylist_name": "Pilar",
                        "slot_datetime": "2026-03-26T10:00:00",
                        "slot_summary": "jueves 10:00",
                    },
                },
            ),
            patch.object(mode, "_populate_recurrent_stylist", return_value=state["mode_context"]),
            patch.object(mode, "_handle_slot_selection", side_effect=fake_slot_handler),
        ):
            await mode._handle_stylist_selection(state, dict(state["mode_context"]))

        assert captured["availability_start_date"] == "jueves que viene"

    @pytest.mark.asyncio
    async def test_same_turn_cualquiera_without_existing_anchor_does_not_invent_date(self):
        mode = make_booking_mode()
        state = make_booking_state(BookingSubstep.STYLIST_SELECTION.value, "Cualquiera.")
        captured: dict[str, str] = {}

        async def fake_slot_handler(_state: dict, mode_context: dict) -> dict:
            captured.update(mode_context)
            return {"mode_context": mode_context, "last_node": "booking", "user_message": None}

        with (
            patch.object(
                mode,
                "_prefetch_stylist_options",
                return_value={
                    "status": "ok",
                    "prefetched_stylists": [{"id": "stylist-1", "name": "Pilar"}],
                    "soonest_any_slot": "jueves 10:00",
                    "soonest_any_slot_candidate": {
                        "stylist_id": "stylist-1",
                        "stylist_name": "Pilar",
                        "slot_datetime": "2026-03-26T10:00:00",
                        "slot_summary": "jueves 10:00",
                    },
                },
            ),
            patch.object(mode, "_populate_recurrent_stylist", return_value=state["mode_context"]),
            patch.object(mode, "_handle_slot_selection", side_effect=fake_slot_handler),
        ):
            await mode._handle_stylist_selection(state, dict(state["mode_context"]))

        assert "availability_start_date" not in captured

    @pytest.mark.asyncio
    async def test_slot_selection_preserves_existing_anchor_when_turn_has_no_new_date(self):
        mode = make_booking_mode()
        state = make_booking_state(BookingSubstep.SLOT_SELECTION.value, "Cualquiera.")
        state["mode_context"].update(
            {
                "availability_start_date": "jueves que viene",
                "stylist_id": "550e8400-e29b-41d4-a716-446655440000",
                "stylist_name": "Pilar",
            }
        )

        with (
            patch.object(mode, "_use_optimized_prompts", return_value=False),
            patch.object(mode, "_run_agentic_loop", new_callable=AsyncMock) as mock_loop,
        ):
            mock_loop.return_value = AgenticLoopResult(
                response_text="No tengo horarios todavía.",
                tool_results={},
                tool_events=[],
            )

            result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

        assert result["mode_context"]["availability_start_date"] == "jueves que viene"

    @pytest.mark.asyncio
    async def test_slot_selection_overrides_existing_anchor_with_new_explicit_date(self):
        mode = make_booking_mode()
        state = make_booking_state(
            BookingSubstep.SLOT_SELECTION.value,
            "este viernes por la tarde",
        )
        state["mode_context"].update(
            {
                "availability_start_date": "jueves que viene",
                "stylist_id": "550e8400-e29b-41d4-a716-446655440000",
                "stylist_name": "Pilar",
            }
        )

        with (
            patch.object(mode, "_use_optimized_prompts", return_value=False),
            patch.object(mode, "_run_agentic_loop", new_callable=AsyncMock) as mock_loop,
        ):
            mock_loop.return_value = AgenticLoopResult(
                response_text="Busco horarios para ese dia.",
                tool_results={},
                tool_events=[],
            )

            result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

        assert result["mode_context"]["availability_start_date"] == "este viernes por la tarde"
        assert result["mode_context"]["availability_time_range"] == "afternoon"

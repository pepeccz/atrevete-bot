from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


def make_state() -> dict:
    state = create_initial_state("conv-retry", "+34611000102")
    state["current_mode"] = "BOOKING"
    state["customer_name"] = "Ana"
    state["customer_id"] = "cust-retry"
    state["messages"] = [{"role": "user", "content": "Cualquiera."}]
    state["mode_context"] = {
        "booking_step": BookingSubstep.SLOT_SELECTION.value,
        "service_name": "Cortar",
        "service_id": "svc-001",
        "stylist_id": "550e8400-e29b-41d4-a716-446655440000",
        "stylist_name": "Pilar",
    }
    return state


class TestNoProgressGuard:
    def test_same_step_without_progress_increments_counter(self):
        mode = make_booking_mode()
        state = make_state()
        before_context = {
            **state["mode_context"],
            "no_progress_step": BookingSubstep.SLOT_SELECTION.value,
            "no_progress_turns": 1,
        }
        after_context = dict(before_context)

        guarded_context, escalation_update = mode._apply_no_progress_guard(
            state,
            before_context,
            after_context,
            current_step=BookingSubstep.SLOT_SELECTION,
            next_step=BookingSubstep.SLOT_SELECTION,
            tool_results={},
        )

        assert escalation_update is None
        assert guarded_context["no_progress_turns"] == 2
        assert guarded_context["no_progress_step"] == BookingSubstep.SLOT_SELECTION.value

    def test_step_change_resets_counter(self):
        mode = make_booking_mode()
        state = make_state()
        before_context = {
            **state["mode_context"],
            "no_progress_step": BookingSubstep.SLOT_SELECTION.value,
            "no_progress_turns": 2,
        }
        after_context = {**before_context, "booking_step": BookingSubstep.CUSTOMER_NAME.value}

        guarded_context, escalation_update = mode._apply_no_progress_guard(
            state,
            before_context,
            after_context,
            current_step=BookingSubstep.SLOT_SELECTION,
            next_step=BookingSubstep.CUSTOMER_NAME,
            tool_results={},
        )

        assert escalation_update is None
        assert "no_progress_turns" not in guarded_context
        assert "no_progress_step" not in guarded_context

    def test_new_structured_fact_breaks_dead_loop(self):
        mode = make_booking_mode()
        state = make_state()
        before_context = {
            **state["mode_context"],
            "booking_step": BookingSubstep.STYLIST_SELECTION.value,
            "no_progress_step": BookingSubstep.STYLIST_SELECTION.value,
            "no_progress_turns": 1,
        }
        after_context = {**before_context, "availability_start_date": "jueves que viene"}

        guarded_context, escalation_update = mode._apply_no_progress_guard(
            state,
            before_context,
            after_context,
            current_step=BookingSubstep.STYLIST_SELECTION,
            next_step=BookingSubstep.STYLIST_SELECTION,
            tool_results={},
        )

        assert escalation_update is None
        assert "no_progress_turns" not in guarded_context

    def test_meaningful_tool_payload_does_not_increment_counter(self):
        mode = make_booking_mode()
        state = make_state()
        before_context = {
            **state["mode_context"],
            "no_progress_step": BookingSubstep.SLOT_SELECTION.value,
            "no_progress_turns": 2,
        }
        after_context = dict(before_context)

        guarded_context, escalation_update = mode._apply_no_progress_guard(
            state,
            before_context,
            after_context,
            current_step=BookingSubstep.SLOT_SELECTION,
            next_step=BookingSubstep.SLOT_SELECTION,
            tool_results={
                "find_next_available": {
                    "available_dates": [{"date": "2026-03-26", "slots": ["10:00"]}]
                }
            },
        )

        assert escalation_update is None
        assert "no_progress_turns" not in guarded_context

    def test_third_no_progress_turn_auto_escalates_and_clears_stale_errors(self):
        mode = make_booking_mode()
        state = make_state()
        before_context = {
            **state["mode_context"],
            "no_progress_step": BookingSubstep.SLOT_SELECTION.value,
            "no_progress_turns": 2,
            "last_booking_error": "stale error",
            "booking_error_count": 2,
            "retryable_step": BookingSubstep.SLOT_SELECTION.value,
        }
        after_context = dict(before_context)

        guarded_context, escalation_update = mode._apply_no_progress_guard(
            state,
            before_context,
            after_context,
            current_step=BookingSubstep.SLOT_SELECTION,
            next_step=BookingSubstep.SLOT_SELECTION,
            tool_results={},
        )

        assert guarded_context == {
            "booking_step": BookingSubstep.SLOT_SELECTION.value,
            "service_name": "Cortar",
            "service_id": "svc-001",
            "stylist_id": "550e8400-e29b-41d4-a716-446655440000",
            "stylist_name": "Pilar",
        }
        assert escalation_update is not None
        assert escalation_update["current_mode"] == "ESCALATION"
        assert escalation_update["escalation_triggered"] is True
        frozen_draft = escalation_update["draft_contexts"]["BOOKING"]
        assert frozen_draft["awaiting_human"] is True
        assert "last_booking_error" not in frozen_draft
        assert "booking_error_count" not in frozen_draft

    @pytest.mark.asyncio
    async def test_technical_error_path_keeps_router_error_flow_and_skips_auto_escalation(self):
        mode = make_booking_mode()
        state = make_state()
        state["mode_context"].update(
            {
                "no_progress_step": BookingSubstep.SLOT_SELECTION.value,
                "no_progress_turns": 2,
            }
        )

        with (
            patch.object(mode, "_use_optimized_prompts", return_value=False),
            patch.object(mode, "_run_agentic_loop", side_effect=RuntimeError("DB down")),
        ):
            result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

        assert result["error_count"] == 1
        assert result["mode_context"]["booking_step"] == BookingSubstep.SLOT_SELECTION.value
        assert result.get("current_mode") != "ESCALATION"

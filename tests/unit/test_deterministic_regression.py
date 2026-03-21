from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.base import AgenticLoopResult
from agent.modes.booking_context import BookingSubstep
from agent.modes.booking_mode import BookingMode
from agent.modes.greeting_mode import _build_booking_handoff_context
from agent.state.schemas import create_initial_state


def _make_mock_llm(response_text: str = "OK") -> AsyncMock:
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def _make_mode() -> BookingMode:
    return BookingMode(tools=[], llm_client=_make_mock_llm())


def _make_state() -> dict:
    state = create_initial_state("conv-deterministic-regression", "+34612345678")
    state["current_mode"] = "BOOKING"
    state["is_first_interaction"] = False
    state["customer_id"] = "cust-123"
    state["customer_name"] = "Ana"
    state["messages"] = [{"role": "user", "content": "quiero corte", "timestamp": "2026-03-20T10:00:00+01:00"}]
    return state


class TestDeterministicRegression:
    def test_named_stylist_happy_path_still_advances(self):
        mode = _make_mode()
        next_step, updated_context = mode._advance_step(
            AgenticLoopResult(
                response_text="Perfecto",
                tool_results={"list_stylists": {"stylists": [{"id": "sty-1", "name": "Laura"}]}} ,
            ),
            BookingSubstep.STYLIST_SELECTION,
            {"service_id": "svc-1", "service_name": "Cortar"},
        )

        assert next_step == BookingSubstep.SLOT_SELECTION
        assert updated_context["stylist_id"] == "sty-1"
        assert updated_context["stylist_name"] == "Laura"

    def test_greeting_booking_handoff_keeps_opening_request_and_canonical_facts(self):
        handoff = _build_booking_handoff_context(
            "Hola, quiero un corte de dama para el jueves que viene"
        )

        assert handoff["opening_booking_request"] == "Hola, quiero un corte de dama para el jueves que viene"
        assert handoff["service_query"] == "corte"
        assert handoff["service_audience_hint"] == "adult_female"
        assert handoff["availability_start_date"] == "jueves que viene"

    def test_no_progress_guard_escalates_after_three_turns(self):
        mode = _make_mode()
        state = _make_state()
        before_context = {
            "booking_step": BookingSubstep.SERVICE_SELECTION.value,
            "no_progress_step": BookingSubstep.SERVICE_SELECTION.value,
            "no_progress_turns": 2,
        }
        after_context = {"booking_step": BookingSubstep.SERVICE_SELECTION.value}

        guarded_context, escalation_update = mode._apply_no_progress_guard(
            state,
            before_context,
            after_context,
            current_step=BookingSubstep.SERVICE_SELECTION,
            next_step=BookingSubstep.SERVICE_SELECTION,
            tool_results={},
        )

        assert guarded_context.get("no_progress_turns") is None
        assert escalation_update is not None
        assert escalation_update["current_mode"] == "ESCALATION"
        assert escalation_update["escalation_reason"] == "auto_escalation"

    def test_no_progress_guard_resets_when_new_structured_fact_arrives(self):
        mode = _make_mode()
        state = _make_state()
        guarded_context, escalation_update = mode._apply_no_progress_guard(
            state,
            {
                "booking_step": BookingSubstep.SERVICE_SELECTION.value,
                "no_progress_step": BookingSubstep.SERVICE_SELECTION.value,
                "no_progress_turns": 2,
            },
            {
                "booking_step": BookingSubstep.SERVICE_SELECTION.value,
                "service_name": "Cortar",
            },
            current_step=BookingSubstep.SERVICE_SELECTION,
            next_step=BookingSubstep.SERVICE_SELECTION,
            tool_results={},
        )

        assert escalation_update is None
        assert "no_progress_turns" not in guarded_context
        assert guarded_context["service_name"] == "Cortar"

    def test_error_backbone_persist_still_tracks_retry_state(self):
        mode = _make_mode()
        updated_context, delta = mode._persist_booking_error(
            {"booking_step": BookingSubstep.SLOT_SELECTION.value},
            "DB timeout",
            BookingSubstep.SLOT_SELECTION,
        )

        assert delta == 1
        assert updated_context["last_booking_error"] == "DB timeout"
        assert updated_context["booking_error_count"] == 1
        assert updated_context["retryable_step"] == BookingSubstep.SLOT_SELECTION.value

    def test_error_backbone_clear_still_removes_fields(self):
        cleared = BookingMode._clear_booking_error(
            {
                "booking_step": BookingSubstep.SLOT_SELECTION.value,
                "last_booking_error": "DB timeout",
                "booking_error_count": 2,
                "retryable_step": BookingSubstep.SLOT_SELECTION.value,
            }
        )

        assert "last_booking_error" not in cleared
        assert "booking_error_count" not in cleared
        assert "retryable_step" not in cleared

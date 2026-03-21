from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.booking_context import BookingSubstep
from agent.modes.booking_mode import BookingMode
from agent.routing.intent_router import IntentResult
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


def _make_intent(intent: str = "book") -> IntentResult:
    return IntentResult(intent=intent, confidence=0.9, raw_input="test", mode_hint="BOOKING")


def _make_booking_state(user_message: str) -> dict:
    state = create_initial_state("conv-deterministic-facts", "+34612345678")
    state["current_mode"] = "BOOKING"
    state["is_first_interaction"] = False
    state["customer_id"] = "cust-123"
    state["customer_name"] = "Ana"
    state["messages"] = [{"role": "user", "content": user_message, "timestamp": "2026-03-20T10:00:00+01:00"}]
    state["mode_context"] = {"booking_step": BookingSubstep.SERVICE_SELECTION.value}
    return state


class TestExtractDateSpan:
    def test_extracts_only_weekday_qualifier_span(self):
        assert (
            BookingMode._extract_date_span("Hola quiero un corte para el jueves que viene")
            == "jueves que viene"
        )

    def test_extracts_relative_day(self):
        assert BookingMode._extract_date_span("hoy") == "hoy"

    def test_extracts_range_phrase(self):
        assert BookingMode._extract_date_span("entre martes y jueves") == "entre martes y jueves"

    def test_returns_none_when_message_has_no_date(self):
        assert BookingMode._extract_date_span("quiero un corte") is None


class TestDeterministicFactExtraction:
    def test_extract_service_audience_hint(self):
        assert BookingMode._extract_service_audience_hint("corte de dama") == "adult_female"

    def test_extract_service_query_keeps_service_terms(self):
        query = BookingMode._extract_service_query("quiero un corte de pelo")
        assert query is not None
        assert "corte" in query

    def test_extract_turn_facts_returns_combined_dict(self):
        facts = BookingMode._extract_turn_facts("Hola, quiero un corte de dama para el jueves que viene por la tarde")

        assert facts["service_query"] == "corte"
        assert facts["service_audience_hint"] == "adult_female"
        assert facts["availability_start_date"] == "jueves que viene"
        assert facts["availability_time_range"] == "afternoon"
        assert facts["date_hint"]["kind"] == "weekday_qualifier"

    def test_merge_turn_facts_only_fills_missing_gaps(self):
        merged = BookingMode._merge_turn_facts(
            {
                "service_query": "corte",
                "availability_start_date": "jueves que viene",
                "availability_time_range": "afternoon",
            },
            {
                "service_query": "color",
                "service_audience_hint": "adult_female",
            },
        )

        assert merged["service_query"] == "corte"
        assert merged["availability_start_date"] == "jueves que viene"
        assert merged["availability_time_range"] == "afternoon"
        assert merged["service_audience_hint"] == "adult_female"

    @pytest.mark.asyncio
    async def test_direct_booking_entry_extracts_audience_from_first_message(self):
        mode = _make_mode()
        state = _make_booking_state("Quiero un corte de dama")
        handler_result = {"mode_context": {"booking_step": "service_selection"}, "last_node": "booking", "user_message": None}

        with (
            patch.object(mode, "_use_optimized_prompts", return_value=False),
            patch.object(mode, "_handle_service_selection", new=AsyncMock(return_value=handler_result)) as handler_mock,
        ):
            await mode.handle(state, _make_intent())

        forwarded_context = handler_mock.await_args.args[1]
        assert forwarded_context["service_audience_hint"] == "adult_female"
        assert forwarded_context["service_query"] == "corte"

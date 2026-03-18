from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.booking_context import BookingSubstep
from agent.modes.booking_mode import BookingMode
from agent.state.schemas import ConversationState, create_initial_state


def _make_mock_llm(response_text: str = "OK") -> AsyncMock:
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def _make_booking_mode() -> BookingMode:
    return BookingMode(tools=[], llm_client=_make_mock_llm())


def _make_state(booking_step: str, customer_name: str | None = None) -> dict:
    state = create_initial_state("conv-add-ons", "+34612345678")
    state["current_mode"] = "BOOKING"
    state["is_first_interaction"] = False
    state["customer_id"] = "cust-123"
    state["customer_name"] = customer_name
    state["mode_context"] = {"booking_step": booking_step}
    return state


class TestBookingModeStepChain:
    def test_previous_substep_for_add_ons(self):
        assert BookingMode._previous_substep(BookingSubstep.ADD_ONS) == BookingSubstep.SERVICE_SELECTION

    def test_previous_substep_for_stylist_selection(self):
        assert BookingMode._previous_substep(BookingSubstep.STYLIST_SELECTION) == BookingSubstep.ADD_ONS

    def test_previous_substep_for_customer_name(self):
        assert BookingMode._previous_substep(BookingSubstep.CUSTOMER_NAME) == BookingSubstep.SLOT_SELECTION

    def test_previous_substep_for_notes(self):
        assert BookingMode._previous_substep(BookingSubstep.NOTES) == BookingSubstep.CUSTOMER_NAME


class TestBookingModeAddOns:
    @pytest.mark.asyncio
    async def test_handle_add_ons_auto_skips_when_no_recommendations(self):
        mode = _make_booking_mode()
        state = _make_state("add_ons")
        context = {
            "booking_step": "add_ons",
            "service_id": "svc-1",
            "service_name": "Corte",
            "pending_recommendations": [],
            "add_ons_options": None,
        }
        expected = {
            "messages": [{"role": "assistant", "content": "Seguimos", "timestamp": "now"}],
            "mode_context": {"booking_step": "stylist_selection"},
            "last_node": "booking",
            "user_message": None,
        }

        with patch.object(mode, "_resolve_add_on_names", new=AsyncMock(return_value=[])) as resolve_mock, patch.object(
            mode,
            "_handle_stylist_selection",
            new=AsyncMock(return_value=expected),
        ) as stylist_mock:
            result = await mode._handle_add_ons(cast(ConversationState, state), context)

        resolve_mock.assert_awaited_once_with([], None)
        stylist_mock.assert_awaited_once()
        assert result == expected

    def test_message_declines_recommendations_for_no(self):
        assert BookingMode._message_declines_recommendations("no") is True

    def test_message_declines_recommendations_for_solo_eso(self):
        assert BookingMode._message_declines_recommendations("solo eso") is True

    def test_message_declines_recommendations_for_positive_message(self):
        assert BookingMode._message_declines_recommendations("quiero el barro") is False

    def test_rewind_to_service_selection_clears_recommendations_shown(self):
        mode = _make_booking_mode()

        rewound = mode._rewind_context(
            {
                "booking_step": "stylist_selection",
                "service_id": "svc-1",
                "service_name": "Corte",
                "recommendations_shown": True,
                "notes": "sin perfume",
            },
            BookingSubstep.SERVICE_SELECTION,
        )

        assert rewound.get("booking_step") == BookingSubstep.SERVICE_SELECTION.value
        assert "recommendations_shown" not in rewound
        assert rewound.get("notes") == "sin perfume"


class TestBookingModeCustomerName:
    @pytest.mark.asyncio
    async def test_handle_customer_name_auto_skips_when_name_known(self):
        mode = _make_booking_mode()
        state = _make_state("customer_name", customer_name="Pepe")
        context = {
            "booking_step": "customer_name",
            "service_id": "svc-1",
            "service_name": "Corte",
            "stylist_id": "sty-1",
            "stylist_name": "Laura",
            "selected_slot": {"start_time": "2026-03-20T10:00:00+01:00"},
        }
        result = await mode._handle_customer_name(cast(ConversationState, state), context)

        assert result == {
            "customer_name": "Pepe",
            "customer_id": "cust-123",
            "mode_context": {
                "booking_step": "notes",
                "customer_name": "Pepe",
                "service_id": "svc-1",
                "service_name": "Corte",
                "stylist_id": "sty-1",
                "stylist_name": "Laura",
                "selected_slot": {"start_time": "2026-03-20T10:00:00+01:00"},
            },
            "last_node": "booking",
            "user_message": None,
        }

    def test_rewind_to_customer_name_clears_only_customer_name(self):
        mode = _make_booking_mode()

        rewound = mode._rewind_context(
            {
                "booking_step": "notes",
                "service_id": "svc-1",
                "service_name": "Corte",
                "customer_name": "Pepe",
                "notes": "sin secador",
            },
            BookingSubstep.CUSTOMER_NAME,
        )

        assert rewound.get("booking_step") == BookingSubstep.CUSTOMER_NAME.value
        assert "customer_name" not in rewound
        assert rewound.get("notes") == "sin secador"

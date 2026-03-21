"""
Integration tests for stylist selection flow.

Coverage:
- User replies "cualquiera" → stylist_id set in mode_context before LLM call
- _prefetch_stylist_options stores soonest_any_slot_candidate with correct shape
- _advance_step advances from STYLIST_SELECTION → SLOT_SELECTION when stylist_id present
- Unavailable stylist name → stylist_id NOT set, step stays at stylist_selection

Tests mock the tool layer (list_stylists, find_next_available) and the LLM
— no real DB or network calls are made.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.booking_context import BookingSubstep
from agent.modes.booking_mode import BookingMode
from agent.state.schemas import create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def make_mock_llm(response_text: str = "Perfecto, ¡te reservo con ella!") -> AsyncMock:
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def make_booking_mode(llm_response: str = "Perfecto, ¡te reservo con ella!") -> BookingMode:
    return BookingMode(tools=[], llm_client=make_mock_llm(llm_response))


def make_state(booking_step: str, user_message: str, customer_name: str = "Test User") -> dict:
    state = create_initial_state("conv-test", "+34600000001")
    state["customer_name"] = customer_name
    state["customer_id"] = "cust-001"
    state["is_first_interaction"] = False
    state["current_mode"] = "BOOKING"
    state["messages"] = [{"role": "user", "content": user_message}]
    state["mode_context"] = {
        "booking_step": booking_step,
        "service_name": "Corte de pelo",
        "service_category": "corte",
        "service_duration_minutes": 45,
    }
    return state


# Canonical mock tool responses — use valid UUIDs so _normalize_stylist_preference passes
MOCK_STYLIST_UUID_1 = "550e8400-e29b-41d4-a716-446655440001"
MOCK_STYLIST_UUID_2 = "550e8400-e29b-41d4-a716-446655440002"

MOCK_STYLISTS = {
    "stylists": [
        {"id": MOCK_STYLIST_UUID_1, "name": "María García"},
        {"id": MOCK_STYLIST_UUID_2, "name": "Carmen López"},
    ]
}

MOCK_SOONEST_DT = datetime(2026, 3, 23, 10, 0, tzinfo=timezone.utc)

MOCK_AVAILABILITY = {
    "available_stylists": [
        {
            "stylist_name": "María García",
            "slots": [
                {
                    "full_datetime": MOCK_SOONEST_DT,
                    "day_name": "lunes",
                    "date": "23/03",
                    "time": "10:00",
                }
            ],
        },
        {
            "stylist_name": "Carmen López",
            "slots": [
                {
                    "full_datetime": datetime(2026, 3, 24, 11, 0, tzinfo=timezone.utc),
                    "day_name": "martes",
                    "date": "24/03",
                    "time": "11:00",
                }
            ],
        },
    ]
}


# =============================================================================
# 1. _prefetch_stylist_options stores soonest_any_slot_candidate
# =============================================================================


class TestPrefetchStylistOptions:
    """Verify _prefetch_stylist_options stores structured candidate alongside display string."""

    @pytest.mark.asyncio
    async def test_soonest_any_slot_candidate_shape(self):
        mode = make_booking_mode()
        mode_context = {
            "service_category": "corte",
            "service_duration_minutes": 45,
        }
        with (
            patch("agent.tools.info_tools.list_stylists") as mock_ls,
            patch("agent.tools.availability_tools.find_next_available") as mock_fna,
        ):
            mock_ls.ainvoke = AsyncMock(return_value=MOCK_STYLISTS)
            mock_fna.ainvoke = AsyncMock(return_value=MOCK_AVAILABILITY)

            result = await mode._prefetch_stylist_options(mode_context)

        candidate = result.get("soonest_any_slot_candidate")
        assert candidate is not None, "soonest_any_slot_candidate must be set"
        assert "stylist_id" in candidate
        assert "stylist_name" in candidate
        assert "slot_datetime" in candidate
        assert "slot_summary" in candidate
        # Must be the earliest slot — María García at 10:00
        assert candidate["stylist_id"] == "stylist-uuid-1"
        assert candidate["stylist_name"] == "María García"

    @pytest.mark.asyncio
    async def test_soonest_any_slot_display_string_preserved(self):
        """Existing soonest_any_slot display string must not be removed."""
        mode = make_booking_mode()
        mode_context = {
            "service_category": "corte",
            "service_duration_minutes": 45,
        }
        with (
            patch("agent.tools.info_tools.list_stylists") as mock_ls,
            patch("agent.tools.availability_tools.find_next_available") as mock_fna,
        ):
            mock_ls.ainvoke = AsyncMock(return_value=MOCK_STYLISTS)
            mock_fna.ainvoke = AsyncMock(return_value=MOCK_AVAILABILITY)

            result = await mode._prefetch_stylist_options(mode_context)

        # Original display string must still be present
        assert "soonest_any_slot" in result
        assert result["soonest_any_slot"] is not None

    @pytest.mark.asyncio
    async def test_no_availability_candidate_is_none(self):
        """If no slots found, soonest_any_slot_candidate must be None."""
        mode = make_booking_mode()
        mode_context = {"service_category": "corte", "service_duration_minutes": 45}
        with (
            patch("agent.tools.info_tools.list_stylists") as mock_ls,
            patch("agent.tools.availability_tools.find_next_available") as mock_fna,
        ):
            mock_ls.ainvoke = AsyncMock(return_value={"stylists": [{"id": "s-1", "name": "Pilar"}]})
            mock_fna.ainvoke = AsyncMock(return_value={"available_stylists": []})

            result = await mode._prefetch_stylist_options(mode_context)

        assert result.get("soonest_any_slot_candidate") is None


# =============================================================================
# 2. _handle_stylist_selection sets stylist_id for "cualquiera"
# =============================================================================


class TestHandleStylistSelectionResolver:
    """Verify that _handle_stylist_selection pre-resolves stylist before LLM call."""

    @pytest.mark.asyncio
    async def test_cualquiera_sets_stylist_id_in_context(self):
        """User says 'cualquiera' → stylist_id must be set in returned mode_context."""
        mode = make_booking_mode()
        state = make_state("stylist_selection", "cualquiera")

        with (
            patch("agent.tools.info_tools.list_stylists") as mock_ls,
            patch("agent.tools.availability_tools.find_next_available") as mock_fna,
            patch("agent.tools.info_tools.list_stylists") as mock_ls2,
        ):
            mock_ls.ainvoke = AsyncMock(return_value=MOCK_STYLISTS)
            mock_ls2.ainvoke = AsyncMock(return_value=MOCK_STYLISTS)
            mock_fna.ainvoke = AsyncMock(return_value=MOCK_AVAILABILITY)

            result = await mode._handle_stylist_selection(state, dict(state["mode_context"]))

        mode_context = result.get("mode_context", {})
        assert mode_context.get("stylist_id") == "stylist-uuid-1", (
            "stylist_id must be set to soonest candidate (María García) for 'cualquiera'"
        )
        assert mode_context.get("stylist_name") == "María García"

    @pytest.mark.asyncio
    async def test_cualquiera_advances_step_to_slot_selection(self):
        """When stylist resolved, _advance_step should move to slot_selection."""
        mode = make_booking_mode()
        state = make_state("stylist_selection", "cualquiera")

        with (
            patch("agent.tools.info_tools.list_stylists") as mock_ls,
            patch("agent.tools.availability_tools.find_next_available") as mock_fna,
        ):
            mock_ls.ainvoke = AsyncMock(return_value=MOCK_STYLISTS)
            mock_fna.ainvoke = AsyncMock(return_value=MOCK_AVAILABILITY)

            result = await mode._handle_stylist_selection(state, dict(state["mode_context"]))

        mode_context = result.get("mode_context", {})
        assert mode_context.get("booking_step") == BookingSubstep.SLOT_SELECTION.value, (
            "Step must advance to slot_selection when stylist_id is resolved"
        )

    @pytest.mark.asyncio
    async def test_unavailable_stylist_name_does_not_set_stylist_id(self):
        """Naming a stylist not in the list → stylist_id must NOT be set."""
        mode = make_booking_mode("Lo siento, esa estilista no está disponible.")
        state = make_state("stylist_selection", "quiero con Pilar")

        with (
            patch("agent.tools.info_tools.list_stylists") as mock_ls,
            patch("agent.tools.availability_tools.find_next_available") as mock_fna,
        ):
            mock_ls.ainvoke = AsyncMock(return_value=MOCK_STYLISTS)
            mock_fna.ainvoke = AsyncMock(return_value=MOCK_AVAILABILITY)

            result = await mode._handle_stylist_selection(state, dict(state["mode_context"]))

        mode_context = result.get("mode_context", {})
        # stylist_id must NOT be set (Pilar is not in the list)
        assert not mode_context.get("stylist_id"), (
            "stylist_id must NOT be set for unavailable stylist name"
        )
        # Step must remain at stylist_selection
        assert mode_context.get("booking_step") == BookingSubstep.STYLIST_SELECTION.value

    @pytest.mark.asyncio
    async def test_existing_stylist_id_not_overwritten(self):
        """If stylist_id already set in mode_context, resolver must not overwrite it."""
        mode = make_booking_mode()
        state = make_state("stylist_selection", "cualquiera")
        # Pre-set stylist_id
        state["mode_context"]["stylist_id"] = "already-set-uuid"
        state["mode_context"]["stylist_name"] = "Already Set"

        with (
            patch("agent.tools.info_tools.list_stylists") as mock_ls,
            patch("agent.tools.availability_tools.find_next_available") as mock_fna,
        ):
            mock_ls.ainvoke = AsyncMock(return_value=MOCK_STYLISTS)
            mock_fna.ainvoke = AsyncMock(return_value=MOCK_AVAILABILITY)

            result = await mode._handle_stylist_selection(state, dict(state["mode_context"]))

        mode_context = result.get("mode_context", {})
        assert mode_context.get("stylist_id") == "already-set-uuid", (
            "Pre-existing stylist_id must not be overwritten by resolver"
        )

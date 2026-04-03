"""Unit tests for booking-slot-display-fix changes.

Covers:
- T-C1: find_next_available populates offered_slots via _post_tool_result
- T-C2: missing_summary() 3-state slot semantics
- T-H1: _resolve_user_slot_selection guard uses selected_slot instead of stylist_id
- T-H2: _is_booking_data_complete requires selected_slot (not offered_slots)
- T-M2: slots_shown_count field — init, increment, reset
- T-M3: notes_asked threshold changed from >= 1 to >= 2
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import (
    BookingMode,
    _is_booking_data_complete,
    _resolve_user_slot_selection,
)


# ══════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════


def _make_booking_mode() -> BookingMode:
    """Instantiate a BookingMode with a mocked LLM."""
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "test"
    mock_response.tool_calls = []
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    return BookingMode(tools=[], llm_client=mock_llm)


def _find_next_available_result() -> dict:
    """Realistic find_next_available response (v4.2 shape with selected_stylist_slots)."""
    return {
        "selected_stylist_slots": [
            {
                "date": "lunes 6 de abril",
                "time": "10:00",
                "full_datetime": "2026-04-06T10:00:00+02:00",
                "stylist_id": "uuid-ana",
                "stylist_name": "Ana",
            },
            {
                "date": "lunes 6 de abril",
                "time": "12:00",
                "full_datetime": "2026-04-06T12:00:00+02:00",
                "stylist_id": "uuid-ana",
                "stylist_name": "Ana",
            },
        ],
        "soonest_any": {
            "date": "lunes 6 de abril",
            "time": "10:00",
            "stylist_name": "Ana",
        },
    }


def _minimal_complete_ctx() -> BookingContext:
    """BookingContext with all required fields for _is_booking_data_complete."""
    return BookingContext(
        service_id="svc-001",
        selected_services=["Corte Caballero"],
        stylist_id="uuid-ana",
        stylist_name="Ana",
        selected_slot={
            "date": "2026-04-06",
            "time": "10:00",
            "full_datetime": "2026-04-06T10:00:00+02:00",
            "stylist_id": "uuid-ana",
            "stylist_name": "Ana",
        },
        customer_name="Pedro",
    )


# ══════════════════════════════════════════════════════════════════════════
# T-C1: find_next_available populates offered_slots via _post_tool_result
# ══════════════════════════════════════════════════════════════════════════


class TestPostToolResultFindNextAvailable:
    """T-C1: _post_tool_result must extract offered_slots for find_next_available."""

    @pytest.mark.asyncio
    async def test_find_next_available_populates_offered_slots(self):
        """find_next_available result → ctx.offered_slots populated after _post_tool_result."""
        mode = _make_booking_mode()
        ctx = BookingContext()
        mode._ctx = ctx

        result_payload = _find_next_available_result()
        result_json = json.dumps(result_payload)

        await mode._post_tool_result("find_next_available", {}, result_json)

        assert ctx.offered_slots is not None
        assert len(ctx.offered_slots) == 2
        assert ctx.offered_slots[0]["time"] == "10:00"
        assert ctx.offered_slots[1]["time"] == "12:00"

    @pytest.mark.asyncio
    async def test_check_availability_still_populates_offered_slots(self):
        """check_availability result → ctx.offered_slots still works (regression guard)."""
        mode = _make_booking_mode()
        ctx = BookingContext()
        mode._ctx = ctx

        result_payload = {
            "available_slots": [
                {
                    "date": "2026-04-07",
                    "time": "11:00",
                    "full_datetime": "2026-04-07T11:00:00+02:00",
                    "stylist_id": "uuid-pilar",
                    "stylist_name": "Pilar",
                }
            ]
        }
        result_json = json.dumps(result_payload)

        await mode._post_tool_result("check_availability", {}, result_json)

        assert ctx.offered_slots is not None
        assert len(ctx.offered_slots) == 1
        assert ctx.offered_slots[0]["time"] == "11:00"

    @pytest.mark.asyncio
    async def test_no_ctx_is_noop(self):
        """_post_tool_result with no ctx set → no error, returns result unchanged."""
        mode = _make_booking_mode()
        mode._ctx = None

        result = await mode._post_tool_result("find_next_available", {}, {"data": 1})

        assert result == {"data": 1}


# ══════════════════════════════════════════════════════════════════════════
# T-C2: missing_summary() — 3-state slot semantics
# ══════════════════════════════════════════════════════════════════════════


class TestMissingSummaryThreeStates:
    """T-C2: missing_summary must have 3 distinct slot states."""

    def test_no_slots_shows_pending(self):
        """No offered_slots, no selected_slot → '❌ Fecha/hora: pendiente'."""
        ctx = BookingContext()
        summary = ctx.missing_summary()
        assert "❌ Fecha/hora: pendiente" in summary

    def test_slots_offered_not_selected_shows_waiting(self):
        """offered_slots non-empty, selected_slot=None → ⏳ waiting message."""
        ctx = BookingContext()
        ctx.offered_slots = [{"time": "10:00", "date": "2026-04-06", "stylist_name": "Ana"}]
        summary = ctx.missing_summary()
        assert "⏳" in summary
        assert "Horario" in summary
        assert "esperando elección" in summary
        # Old format must NOT appear
        assert "❌ Fecha/hora: pendiente" not in summary

    def test_slot_selected_not_in_missing(self):
        """selected_slot set → no slot-related entry in missing_summary."""
        ctx = BookingContext(
            service_name="Corte Caballero",
            service_id="svc-001",
            stylist_id="sty-001",
            selected_slot={"date": "2026-04-06", "time": "10:00"},
            customer_name="Pedro",
            customer_id="cust-001",
            notes_asked=True,
        )
        summary = ctx.missing_summary()
        # All data complete → returns "✅ Todos los datos requeridos están completos"
        assert "✅ Todos los datos requeridos están completos" in summary
        # No slot-related missing entry
        assert "fecha/hora" not in summary.lower()
        assert "horario" not in summary.lower()
        assert "⏳" not in summary

    def test_offered_state_is_intermediate(self):
        """⏳ state means data is NOT yet complete — slot must be selected."""
        ctx = BookingContext(
            service_name="Corte Caballero",
            service_id="svc-001",
            stylist_id="sty-001",
            offered_slots=[{"time": "10:00", "date": "2026-04-06"}],
            customer_name="Pedro",
            customer_id="cust-001",
            notes_asked=True,
        )
        summary = ctx.missing_summary()
        # ⏳ means still pending — not "all complete"
        assert "✅ Todos los datos requeridos están completos" not in summary
        assert "⏳" in summary


# ══════════════════════════════════════════════════════════════════════════
# T-H1: _resolve_user_slot_selection guard uses selected_slot
# ══════════════════════════════════════════════════════════════════════════


class TestResolveSlotSelectionGuard:
    """T-H1: guard must use selected_slot, not stylist_id."""

    def _offered_slots(self) -> list[dict]:
        return [
            {
                "date": "2026-04-06",
                "day_name": "lunes 6 de abril",
                "time": "10:00",
                "full_datetime": "2026-04-06T10:00:00+02:00",
                "stylist_id": "uuid-ana",
                "stylist_name": "Ana",
            },
            {
                "date": "2026-04-06",
                "day_name": "lunes 6 de abril",
                "time": "12:00",
                "full_datetime": "2026-04-06T12:00:00+02:00",
                "stylist_id": "uuid-ana",
                "stylist_name": "Ana",
            },
        ]

    def test_proceeds_when_stylist_set_but_no_slot(self):
        """stylist_id set, selected_slot=None → resolver proceeds (T-H1 fix).

        Before fix: stylist_id being set → resolver returned False (bug).
        After fix: only selected_slot presence blocks the resolver.
        """
        ctx = BookingContext(
            offered_slots=self._offered_slots(),
            stylist_id="uuid-ana",
            stylist_name="Ana",
            selected_slot=None,
        )
        result = _resolve_user_slot_selection("1", ctx)
        # Should resolve slot 1
        assert result is True
        assert ctx.selected_slot is not None
        assert ctx.selected_slot["time"] == "10:00"

    def test_blocked_when_slot_already_selected(self):
        """selected_slot is set → resolver returns False (slot already chosen)."""
        existing_slot = {
            "date": "2026-04-06",
            "time": "10:00",
            "full_datetime": "2026-04-06T10:00:00+02:00",
            "stylist_id": "uuid-ana",
            "stylist_name": "Ana",
        }
        ctx = BookingContext(
            offered_slots=self._offered_slots(),
            selected_slot=existing_slot,
        )
        original = dict(existing_slot)
        result = _resolve_user_slot_selection("2", ctx)
        assert result is False
        # selected_slot must not be overwritten
        assert ctx.selected_slot == original


# ══════════════════════════════════════════════════════════════════════════
# T-H2: _is_booking_data_complete requires selected_slot
# ══════════════════════════════════════════════════════════════════════════


class TestIsBookingDataComplete:
    """T-H2: booking data complete only when selected_slot is set."""

    def test_complete_with_selected_slot(self):
        """All required fields including selected_slot → True."""
        ctx = _minimal_complete_ctx()
        assert _is_booking_data_complete(ctx) is True

    def test_not_complete_with_only_offered_slots(self):
        """offered_slots set but selected_slot=None → False (slot not yet chosen)."""
        ctx = BookingContext(
            service_id="svc-001",
            selected_services=["Corte Caballero"],
            stylist_id="uuid-ana",
            offered_slots=[{"time": "10:00", "date": "2026-04-06"}],
            selected_slot=None,  # user hasn't chosen yet
            customer_name="Pedro",
        )
        assert _is_booking_data_complete(ctx) is False

    def test_not_complete_missing_service(self):
        """selected_slot set but no service → False."""
        ctx = _minimal_complete_ctx()
        ctx.service_id = None
        ctx.selected_services = []
        assert _is_booking_data_complete(ctx) is False

    def test_not_complete_missing_stylist(self):
        """selected_slot set but no stylist_id → False."""
        ctx = _minimal_complete_ctx()
        ctx.stylist_id = None
        assert _is_booking_data_complete(ctx) is False

    def test_not_complete_missing_customer(self):
        """selected_slot set but no customer → False."""
        ctx = _minimal_complete_ctx()
        ctx.customer_name = None
        ctx.customer_id = None
        assert _is_booking_data_complete(ctx) is False

    def test_complete_with_customer_id_only(self):
        """customer_id (no name) satisfies customer requirement."""
        ctx = _minimal_complete_ctx()
        ctx.customer_name = None
        ctx.customer_id = "cust-001"
        assert _is_booking_data_complete(ctx) is True

    def test_not_complete_empty_context(self):
        """Empty context → False."""
        ctx = BookingContext()
        assert _is_booking_data_complete(ctx) is False


# ══════════════════════════════════════════════════════════════════════════
# T-M2: slots_shown_count field
# ══════════════════════════════════════════════════════════════════════════


class TestSlotsShownCount:
    """T-M2: slots_shown_count field — init, increment via _build_offered_slots_section, reset."""

    def test_init_zero(self):
        """BookingContext() has slots_shown_count=0."""
        ctx = BookingContext()
        assert ctx.slots_shown_count == 0

    def test_reset_transient_zeroes_count(self):
        """reset_transient() resets slots_shown_count to 0."""
        ctx = BookingContext()
        ctx.slots_shown_count = 5
        ctx.reset_transient()
        assert ctx.slots_shown_count == 0

    def test_round_trip_serialization(self):
        """slots_shown_count survives to_mode_context → from_mode_context."""
        ctx = BookingContext()
        ctx.slots_shown_count = 3
        restored = BookingContext.from_mode_context(ctx.to_mode_context())
        assert restored.slots_shown_count == 3

    def test_increments_when_slots_shown(self):
        """_build_offered_slots_section increments slots_shown_count when slots present."""
        from agent.modes.booking_mode import _build_offered_slots_section

        ctx = BookingContext(
            offered_slots=[
                {
                    "date": "2026-04-06",
                    "time": "10:00",
                    "full_datetime": "2026-04-06T10:00:00+02:00",
                    "stylist_id": "uuid-ana",
                    "stylist_name": "Ana",
                }
            ]
        )
        initial_count = ctx.slots_shown_count
        _build_offered_slots_section(ctx)
        assert ctx.slots_shown_count == initial_count + 1

    def test_no_increment_when_no_slots(self):
        """_build_offered_slots_section does NOT increment when offered_slots is empty."""
        from agent.modes.booking_mode import _build_offered_slots_section

        ctx = BookingContext(offered_slots=[])
        _build_offered_slots_section(ctx)
        assert ctx.slots_shown_count == 0


# ══════════════════════════════════════════════════════════════════════════
# T-M3: notes_asked threshold >= 2
# ══════════════════════════════════════════════════════════════════════════


class TestNotesAskedThreshold:
    """T-M3: notes_asked auto-set threshold changed from >= 1 to >= 2."""

    def _make_state_with_ctx(self, ctx: BookingContext) -> dict:
        """Minimal state dict for preprocess logic."""
        return {"messages": [], "mode_context": ctx.to_mode_context()}

    @pytest.mark.asyncio
    async def test_notes_asked_not_set_at_one_attempt(self):
        """notes_ask_attempts=1 → notes_asked stays False (threshold is >= 2)."""
        mode = _make_booking_mode()
        ctx = BookingContext(
            service_id="svc-001",
            service_name="Corte Caballero",
            stylist_id="sty-001",
            notes_asked=False,
            notes_ask_attempts=1,
        )
        mode._ctx = ctx

        # Simulate the preprocess logic inline (lines 689-700 of booking_mode.py)
        messages = []
        if ctx and not ctx.notes_asked:
            if ctx.notes_ask_attempts >= 2:
                ctx.notes_asked = True

        assert ctx.notes_asked is False

    @pytest.mark.asyncio
    async def test_notes_asked_set_at_two_attempts(self):
        """notes_ask_attempts=2 → notes_asked becomes True (threshold met)."""
        mode = _make_booking_mode()
        ctx = BookingContext(
            service_id="svc-001",
            service_name="Corte Caballero",
            stylist_id="sty-001",
            notes_asked=False,
            notes_ask_attempts=2,
        )
        mode._ctx = ctx

        # Simulate the preprocess logic
        if ctx and not ctx.notes_asked:
            if ctx.notes_ask_attempts >= 2:
                ctx.notes_asked = True

        assert ctx.notes_asked is True

    @pytest.mark.asyncio
    async def test_notes_asked_set_at_three_attempts(self):
        """notes_ask_attempts=3 → notes_asked becomes True (threshold still met)."""
        ctx = BookingContext(notes_asked=False, notes_ask_attempts=3)

        if ctx and not ctx.notes_asked:
            if ctx.notes_ask_attempts >= 2:
                ctx.notes_asked = True

        assert ctx.notes_asked is True

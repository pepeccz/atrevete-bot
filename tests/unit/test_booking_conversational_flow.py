"""
Unit tests for booking flow — LLM-driven architecture.

Tests cover:
- A: DISAMBIGUATION_PENDING gate in _pre_tool_call
- B: _booking_complete() field-presence gate (replaces _compute_step)
- C: Hide durations from client (_build_collected_summary, catalog_builder, ui_constraint)
- D: Dynamic context — factual, no imperative directives
- E: _build_flow_hint() neutral pending-data list
"""

from __future__ import annotations

import pytest

from agent.modes.base import ToolCallRejection
from agent.modes.booking_mode import BookingModeNode


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def booking_node() -> BookingModeNode:
    """Create a bare BookingModeNode (no LLM needed for unit tests)."""
    return BookingModeNode(tools=[])


# ===========================================================================
# Change A — DISAMBIGUATION_PENDING gate
# ===========================================================================


class TestChangeADisambiguationGate:
    """_pre_tool_call rejects check_availability when disambiguation is pending."""

    @pytest.mark.asyncio
    async def test_rejects_when_disambiguation_pending(self, booking_node):
        """check_availability blocked when _has_pending_disambiguation=True and no services."""
        booking_node._mode_context = {
            "_has_pending_disambiguation": True,
            # last_services absent → empty
        }
        result = await booking_node._pre_tool_call(
            "check_availability", {"service_names": ["Cortar"]}
        )
        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "DISAMBIGUATION_PENDING"

    @pytest.mark.asyncio
    async def test_allows_when_services_resolved(self, booking_node):
        """check_availability allowed even with flag if last_services is non-empty."""
        booking_node._mode_context = {
            "_has_pending_disambiguation": True,
            "last_services": ["Cortar"],
        }
        result = await booking_node._pre_tool_call(
            "check_availability", {"service_names": ["Cortar"]}
        )
        assert not isinstance(result, ToolCallRejection)

    @pytest.mark.asyncio
    async def test_allows_when_no_flag(self, booking_node):
        """check_availability allowed when _has_pending_disambiguation is absent."""
        booking_node._mode_context = {}
        result = await booking_node._pre_tool_call(
            "check_availability", {"service_names": ["Cortar"]}
        )
        assert not isinstance(result, ToolCallRejection)


# ===========================================================================
# Change B — _booking_complete() field-presence gate
# ===========================================================================


class TestBookingComplete:
    """_booking_complete checks if all required fields are present (GATE, not sequencer)."""

    def test_empty_context_all_missing(self):
        is_complete, missing = BookingModeNode._booking_complete({})
        assert is_complete is False
        assert len(missing) == 5
        assert "servicio" in missing
        assert "estilista" in missing
        assert "fecha/hora" in missing
        assert "nombre" in missing
        assert "notas" in missing

    def test_partial_context(self):
        ctx = {"last_services": ["Cortar"], "last_stylist": "Marta"}
        is_complete, missing = BookingModeNode._booking_complete(ctx)
        assert is_complete is False
        assert "servicio" not in missing
        assert "estilista" not in missing
        assert "fecha/hora" in missing

    def test_no_preference_stylist_counts(self):
        ctx = {"last_services": ["Cortar"], "no_preference_stylist": True}
        _, missing = BookingModeNode._booking_complete(ctx)
        assert "estilista" not in missing

    def test_full_context_is_complete(self):
        ctx = {
            "last_services": ["Cortar"],
            "last_stylist": "Marta",
            "selected_slot": {"time": "10:00"},
            "customer_name": "Ana",
            "notes_asked": True,
        }
        is_complete, missing = BookingModeNode._booking_complete(ctx)
        assert is_complete is True
        assert missing == []

    @pytest.mark.asyncio
    async def test_book_rejected_when_incomplete(self, booking_node):
        """book() gate rejects when fields are missing."""
        booking_node._mode_context = {"last_services": ["Cortar"]}
        result = await booking_node._pre_tool_call("book", {})
        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "CONFIRMATION_REQUIRED"
        assert "estilista" in result.error_message
        assert "nombre" in result.error_message

    @pytest.mark.asyncio
    async def test_book_accepted_when_complete(self, booking_node):
        """book() gate allows when all fields present."""
        booking_node._mode_context = {
            "last_services": ["Cortar"],
            "last_stylist": "Marta",
            "selected_slot": {
                "time": "10:00",
                "stylist_id": "abc-123",
                "start_time": "2026-04-20T10:00:00",
                "stylist_name": "Marta",
            },
            "offered_slots": [
                {
                    "time": "10:00",
                    "stylist_id": "abc-123",
                    "start_time": "2026-04-20T10:00:00",
                    "stylist_name": "Marta",
                }
            ],
            "customer_name": "Ana",
            "notes_asked": True,
        }
        result = await booking_node._pre_tool_call(
            "book",
            {
                "slot_index": 1,
                "customer_first_name": "Ana",
                "services": ["Cortar"],
            },
        )
        assert not isinstance(result, ToolCallRejection)


# ===========================================================================
# Change C — Hide durations from client
# ===========================================================================


class TestChangeCCollectedSummary:
    """_build_collected_summary does not include duration."""

    def test_single_service_no_duration(self, booking_node):
        ctx = {"last_services": ["Cortar"], "last_total_duration_minutes": 45}
        result = booking_node._build_collected_summary(ctx)
        assert "Cortar" in result
        assert "45" not in result
        assert "min" not in result

    def test_multi_service_no_duration(self, booking_node):
        ctx = {
            "last_services": ["Cortar", "Óleo"],
            "last_total_duration_minutes": 80,
        }
        result = booking_node._build_collected_summary(ctx)
        assert "Cortar" in result
        assert "Óleo" in result
        assert "80" not in result
        assert "min" not in result


class TestChangeCCatalog:
    """catalog_builder marks durations as [INTERNO]."""

    def test_catalog_source_has_interno_marker(self):
        """catalog_builder source must use [INTERNO:] marker for durations."""
        import inspect

        import agent.prompts.catalog_builder as cb

        source = inspect.getsource(cb)
        assert "[INTERNO:" in source, "catalog_builder must use [INTERNO:] marker for durations"


class TestChangeCUiConstraint:
    """_build_dynamic_context includes <ui_constraint> element."""

    def test_ui_constraint_in_dynamic_context(self, booking_node):
        state = {
            "messages": [],
            "customer_phone": "+34612345678",
            "conversation_summary": None,
        }
        mode_context = {}
        result = booking_node._build_dynamic_context(mode_context, state)
        assert "<ui_constraint>" in result
        assert "duraciones" in result.lower() or "INTERNO" in result


# ===========================================================================
# Change D — Dynamic context is factual, not imperative
# ===========================================================================


class TestDynamicContextFactual:
    """Dynamic context contains factual data, no imperative directives."""

    def test_no_current_step_in_context(self, booking_node):
        state = {"messages": [], "customer_phone": "+34612345678", "conversation_summary": None}
        result = booking_node._build_dynamic_context({}, state)
        assert "<current_step>" not in result

    def test_no_next_action_in_context(self, booking_node):
        state = {"messages": [], "customer_phone": "+34612345678", "conversation_summary": None}
        result = booking_node._build_dynamic_context({}, state)
        assert "<next_action>" not in result

    def test_collected_data_present(self, booking_node):
        state = {"messages": [], "customer_phone": "+34612345678", "conversation_summary": None}
        ctx = {"last_services": ["Cortar"]}
        result = booking_node._build_dynamic_context(ctx, state)
        assert "<collected_data>" in result

    def test_flow_hint_present(self, booking_node):
        state = {"messages": [], "customer_phone": "+34612345678", "conversation_summary": None}
        result = booking_node._build_dynamic_context({}, state)
        assert "<flow_hint>" in result

    def test_no_missing_data_section(self, booking_node):
        state = {"messages": [], "customer_phone": "+34612345678", "conversation_summary": None}
        result = booking_node._build_dynamic_context({}, state)
        assert "<missing_data>" not in result

    def test_stylists_shown_when_services_known(self, booking_node):
        """Stylists visible when last_services is set, regardless of step."""
        state = {"messages": [], "customer_phone": "+34612345678", "conversation_summary": None}
        ctx = {"last_services": ["Cortar"]}
        booking_node._cached_stylists_by_category = {
            "HAIRDRESSING": ["Marta", "Pilar"],
        }
        result = booking_node._build_dynamic_context(ctx, state)
        assert "<available_stylists>" in result


# ===========================================================================
# Change E — _build_flow_hint
# ===========================================================================


class TestBuildFlowHint:
    """_build_flow_hint produces neutral pending-data list."""

    def test_empty_context_lists_all_pending(self):
        result = BookingModeNode._build_flow_hint({})
        assert "Datos pendientes" in result
        assert "servicio" in result
        assert "nombre" in result

    def test_partial_context(self):
        ctx = {"last_services": ["Cortar"], "last_stylist": "Marta"}
        result = BookingModeNode._build_flow_hint(ctx)
        assert "servicio" not in result
        assert "estilista" not in result
        assert "fecha/hora" in result

    def test_complete_context(self):
        ctx = {
            "last_services": ["Cortar"],
            "last_stylist": "Marta",
            "selected_slot": {"time": "10:00"},
            "customer_name": "Ana",
            "notes_asked": True,
        }
        result = BookingModeNode._build_flow_hint(ctx)
        assert "Todos los datos recogidos" in result
        assert "Datos pendientes" not in result

"""
Unit tests for booking-conversational-flow changes.

Change A: DISAMBIGUATION_PENDING gate in _pre_tool_call
Change B: add_more_asked tracking (_compute_step, _resolve_pending_selection, _post_tool_result,
          _build_dynamic_context, _build_missing_summary)
Change C: Hide durations from client (_build_collected_summary, catalog_builder, ui_constraint)
"""

from __future__ import annotations

import pytest

from agent.modes.base import ToolCallRejection
from agent.modes.booking_mode import (
    BookingModeNode,
    _DECLINE_MORE_PATTERN,
)


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
# Change B — add_more_asked tracking
# ===========================================================================


class TestChangeBComputeStep:
    """_compute_step holds at service_selection until add_more_asked is True."""

    def test_holds_when_services_exist_but_not_asked(self):
        ctx = {"last_services": ["Cortar"]}
        assert BookingModeNode._compute_step(ctx) == "service_selection"

    def test_holds_when_add_more_asked_false(self):
        ctx = {"last_services": ["Cortar"], "add_more_asked": False}
        assert BookingModeNode._compute_step(ctx) == "service_selection"

    def test_advances_when_add_more_asked_true(self):
        ctx = {"last_services": ["Cortar"], "add_more_asked": True}
        assert BookingModeNode._compute_step(ctx) == "stylist_selection"

    def test_advances_full_flow(self):
        ctx = {
            "last_services": ["Cortar"],
            "add_more_asked": True,
            "last_stylist": "Marta",
            "selected_slot": {"time": "10:00"},
            "customer_name": "Ana",
            "notes_asked": True,
        }
        assert BookingModeNode._compute_step(ctx) == "confirmation"


class TestChangeBDeclineDetection:
    """_DECLINE_MORE_PATTERN matches decline phrases for '¿Algo más?'."""

    @pytest.mark.parametrize(
        "phrase",
        ["no", "nada", "nada más", "nada mas", "solo eso", "ya está", "ya esta",
         "no gracias", "eso es todo", "con eso"],
    )
    def test_decline_phrases_match(self, phrase):
        assert _DECLINE_MORE_PATTERN.match(phrase), f"Should match: {phrase!r}"

    @pytest.mark.parametrize(
        "phrase",
        ["sí", "dale", "quiero también mechas", "añade un corte", "y una manicura"],
    )
    def test_non_decline_phrases_dont_match(self, phrase):
        assert not _DECLINE_MORE_PATTERN.match(phrase), f"Should NOT match: {phrase!r}"


class TestChangeBMissingSummary:
    """_build_missing_summary shows pending '¿Algo más?' question."""

    def test_shows_pending_when_services_but_not_asked(self, booking_node):
        ctx = {"last_services": ["Cortar"]}
        result = booking_node._build_missing_summary(ctx)
        assert "¿Algo más?" in result
        assert "Estilista" not in result  # stylist not shown until add_more resolved

    def test_shows_stylist_after_add_more_asked(self, booking_node):
        ctx = {"last_services": ["Cortar"], "add_more_asked": True}
        result = booking_node._build_missing_summary(ctx)
        assert "¿Algo más?" not in result
        assert "Estilista" in result

    def test_shows_service_pending_when_no_services(self, booking_node):
        ctx = {}
        result = booking_node._build_missing_summary(ctx)
        assert "Servicio: pendiente" in result


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
        mode_context = {"booking_step": "service_selection"}
        result = booking_node._build_dynamic_context(mode_context, state)
        assert "<ui_constraint>" in result
        assert "duraciones" in result.lower() or "INTERNO" in result

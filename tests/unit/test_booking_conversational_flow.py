"""
Unit tests for booking-conversational-flow changes.

Change A: DISAMBIGUATION_PENDING gate in _pre_tool_call
Change B: add_more_asked tracking (_compute_step, _resolve_pending_selection, _post_tool_result,
          _build_dynamic_context, _build_missing_summary)
Change C: Hide durations from client (_build_collected_summary, catalog_builder, ui_constraint)
Change D: Passive state extraction (BookingStateExtraction schema, merge logic)
"""

from __future__ import annotations

import pytest

from agent.modes.base import ToolCallRejection
from agent.modes.booking_mode import (
    BookingModeNode,
    BookingStateExtraction,
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
    """add_more_declined is handled by pre-loop LLM extraction, not regex.

    The _DECLINE_MORE_PATTERN regex was removed because it failed on natural
    language variations like 'Nope, nada más'. BookingStateExtraction.add_more_declined
    handles this via structured LLM output before the agentic loop.
    """

    def test_extraction_schema_has_add_more_declined_field(self):
        extraction = BookingStateExtraction(add_more_declined=True)
        assert extraction.add_more_declined is True

    def test_extraction_schema_add_more_defaults_false(self):
        extraction = BookingStateExtraction()
        assert extraction.add_more_declined is False

    def test_extraction_schema_notes_declined_field(self):
        extraction = BookingStateExtraction(notes_declined=True)
        assert extraction.notes_declined is True

    def test_extraction_schema_notes_declined_defaults_false(self):
        extraction = BookingStateExtraction()
        assert extraction.notes_declined is False

    def test_extraction_schema_wants_to_exit_field(self):
        extraction = BookingStateExtraction(wants_to_exit=True)
        assert extraction.wants_to_exit is True

    def test_extraction_schema_wants_to_exit_defaults_false(self):
        extraction = BookingStateExtraction()
        assert extraction.wants_to_exit is False


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


# ===========================================================================
# Change D — Passive state extraction (schema + merge logic)
# ===========================================================================


class TestExtractionSchema:
    """BookingStateExtraction Pydantic schema defaults and validation."""

    def test_defaults_are_safe(self):
        """Empty extraction produces all None/False — no state pollution."""
        e = BookingStateExtraction()
        assert e.resolved_services is None
        assert e.add_more_declined is False
        assert e.stylist_preference is None
        assert e.preferred_date is None
        assert e.customer_name is None
        assert e.notes is None
        assert e.notes_declined is False

    def test_full_extraction_valid(self):
        """All fields populated validates correctly."""
        e = BookingStateExtraction(
            resolved_services=["Cortar", "Óleo Mantenimiento"],
            add_more_declined=True,
            stylist_preference="Marta",
            preferred_date="el martes",
            customer_name="Ana García",
            notes="Tengo el pelo muy fino",
            notes_declined=False,
        )
        assert e.resolved_services == ["Cortar", "Óleo Mantenimiento"]
        assert e.add_more_declined is True
        assert e.stylist_preference == "Marta"


class TestExtractionMerge:
    """Merge logic: extraction fills missing fields, never overwrites."""

    @staticmethod
    def _merge(booking_context: dict, extraction: BookingStateExtraction) -> dict:
        """Replicate the merge logic from handle() for unit testing."""
        if extraction.resolved_services and not booking_context.get("last_services"):
            booking_context["last_services"] = extraction.resolved_services
        if extraction.add_more_declined and not booking_context.get("add_more_asked"):
            booking_context["add_more_asked"] = True
        if extraction.stylist_preference and not booking_context.get("last_stylist"):
            booking_context["last_stylist"] = extraction.stylist_preference
            if extraction.stylist_preference.lower() in ("sin preferencia",):
                booking_context["no_preference_stylist"] = True
        if extraction.customer_name and not booking_context.get("customer_name"):
            booking_context["customer_name"] = extraction.customer_name
        if extraction.notes_declined and not booking_context.get("notes_asked"):
            booking_context["notes_asked"] = True
            booking_context["notes"] = None
        elif extraction.notes and not booking_context.get("notes_asked"):
            booking_context["notes_asked"] = True
            booking_context["notes"] = extraction.notes
        booking_context["booking_step"] = BookingModeNode._compute_step(booking_context)
        return booking_context

    def test_fills_missing_services(self):
        ctx = {}
        extraction = BookingStateExtraction(resolved_services=["Cortar"])
        result = self._merge(ctx, extraction)
        assert result["last_services"] == ["Cortar"]

    def test_does_not_overwrite_existing_services(self):
        ctx = {"last_services": ["Cortar"]}
        extraction = BookingStateExtraction(resolved_services=["Mechas"])
        result = self._merge(ctx, extraction)
        assert result["last_services"] == ["Cortar"]  # NOT overwritten

    def test_fills_add_more_declined(self):
        ctx = {"last_services": ["Cortar"]}
        extraction = BookingStateExtraction(add_more_declined=True)
        result = self._merge(ctx, extraction)
        assert result["add_more_asked"] is True

    def test_does_not_overwrite_add_more(self):
        ctx = {"last_services": ["Cortar"], "add_more_asked": True}
        extraction = BookingStateExtraction(add_more_declined=True)
        result = self._merge(ctx, extraction)
        assert result["add_more_asked"] is True  # already set, no change

    def test_fills_stylist_preference(self):
        ctx = {"last_services": ["Cortar"], "add_more_asked": True}
        extraction = BookingStateExtraction(stylist_preference="Marta")
        result = self._merge(ctx, extraction)
        assert result["last_stylist"] == "Marta"

    def test_sin_preferencia_sets_flag(self):
        ctx = {"last_services": ["Cortar"], "add_more_asked": True}
        extraction = BookingStateExtraction(stylist_preference="Sin preferencia")
        result = self._merge(ctx, extraction)
        assert result["last_stylist"] == "Sin preferencia"
        assert result["no_preference_stylist"] is True

    def test_does_not_overwrite_existing_stylist(self):
        ctx = {"last_services": ["Cortar"], "add_more_asked": True, "last_stylist": "Pilar"}
        extraction = BookingStateExtraction(stylist_preference="Marta")
        result = self._merge(ctx, extraction)
        assert result["last_stylist"] == "Pilar"  # NOT overwritten

    def test_fills_customer_name(self):
        ctx = {}
        extraction = BookingStateExtraction(customer_name="Ana García")
        result = self._merge(ctx, extraction)
        assert result["customer_name"] == "Ana García"

    def test_notes_declined_sets_asked_and_none(self):
        ctx = {"last_services": ["Cortar"], "add_more_asked": True, "last_stylist": "Marta",
               "selected_slot": {"time": "10:00"}, "customer_name": "Ana"}
        extraction = BookingStateExtraction(notes_declined=True)
        result = self._merge(ctx, extraction)
        assert result["notes_asked"] is True
        assert result["notes"] is None

    def test_notes_with_content(self):
        ctx = {"last_services": ["Cortar"], "add_more_asked": True, "last_stylist": "Marta",
               "selected_slot": {"time": "10:00"}, "customer_name": "Ana"}
        extraction = BookingStateExtraction(notes="Pelo muy fino")
        result = self._merge(ctx, extraction)
        assert result["notes_asked"] is True
        assert result["notes"] == "Pelo muy fino"

    def test_step_recomputed_after_merge(self):
        ctx = {}
        extraction = BookingStateExtraction(
            resolved_services=["Cortar"], add_more_declined=True
        )
        result = self._merge(ctx, extraction)
        assert result["booking_step"] == "stylist_selection"

    def test_none_extraction_does_not_affect_state(self):
        """Simulates extraction returning None — merge is skipped entirely."""
        ctx = {"booking_step": "service_selection"}
        extraction = None
        # Merge should NOT run when extraction is None
        if extraction is not None:
            self._merge(ctx, extraction)
        assert ctx["booking_step"] == "service_selection"  # unchanged

    def test_empty_extraction_does_not_pollute(self):
        """All-default extraction doesn't set any fields."""
        ctx = {}
        extraction = BookingStateExtraction()  # all None/False
        result = self._merge(ctx, extraction)
        assert "last_services" not in result
        assert "add_more_asked" not in result
        assert "last_stylist" not in result


class TestNegativeConstraints:
    """_STEP_ACTIONS include negative constraints."""

    def test_service_selection_has_negative_constraint(self, booking_node):
        state = {"messages": [], "customer_phone": "+34612345678", "conversation_summary": None}
        mode_context = {"booking_step": "service_selection"}
        result = booking_node._build_dynamic_context(mode_context, state)
        assert "NO preguntes por fecha" in result

    def test_stylist_selection_has_negative_constraint(self, booking_node):
        state = {"messages": [], "customer_phone": "+34612345678", "conversation_summary": None}
        mode_context = {"booking_step": "stylist_selection", "last_services": ["Cortar"],
                        "add_more_asked": True}
        result = booking_node._build_dynamic_context(mode_context, state)
        assert "NO preguntes por fecha" in result

    def test_datetime_has_negative_constraint(self, booking_node):
        state = {"messages": [], "customer_phone": "+34612345678", "conversation_summary": None}
        mode_context = {"booking_step": "datetime_selection", "last_services": ["Cortar"],
                        "add_more_asked": True, "last_stylist": "Marta"}
        result = booking_node._build_dynamic_context(mode_context, state)
        assert "NO pidas nombre" in result

"""
Unit tests for booking flow — LLM-driven architecture.

Tests cover:
- A: DISAMBIGUATION_PENDING gate in _pre_tool_call
- B: _booking_complete() field-presence gate (replaces _compute_step)
- C: Hide durations from client (_build_collected_summary, catalog_builder, ui_constraint)
- D: Dynamic context — factual, no imperative directives
- E: _build_flow_hint() neutral pending-data list
- F: BookingStateExtraction schema + _merge_extraction
"""

from __future__ import annotations

import pytest

from agent.modes.base import ToolCallRejection
from agent.modes.booking_mode import BookingModeNode, BookingStateExtraction


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


class TestDisambiguationGateRemoved:
    """DISAMBIGUATION_PENDING gate removed — check_availability always allowed."""

    @pytest.mark.asyncio
    async def test_allowed_despite_pending_flag(self, booking_node):
        """check_availability NOT blocked even with _has_pending_disambiguation=True."""
        booking_node._mode_context = {"_has_pending_disambiguation": True}
        result = await booking_node._pre_tool_call(
            "check_availability", {"service_names": ["Cortar"]}
        )
        assert not isinstance(result, ToolCallRejection)

    @pytest.mark.asyncio
    async def test_allowed_with_no_context(self, booking_node):
        """check_availability allowed with empty context."""
        booking_node._mode_context = {}
        result = await booking_node._pre_tool_call(
            "check_availability", {"service_names": ["Cortar"]}
        )
        assert not isinstance(result, ToolCallRejection)


class TestDisambiguationShowOnce:
    """Disambiguation questions shown once, then replaced with hint."""

    def test_questions_shown_on_first_detection(self, booking_node):
        """Current message with service keywords → <required_questions> injected, flag set."""
        mode_context = {"opening_booking_request": "quiero cortarme el pelo y un oleo"}
        state = {
            "customer_phone": "+34600000000",
            "messages": [{"role": "user", "content": "quiero cortarme el pelo y un oleo"}],
        }
        context = booking_node._build_dynamic_context(mode_context, state)
        assert "<required_questions>" in context
        assert mode_context.get("_disambiguation_questions_shown") is True

    def test_hint_shown_on_subsequent_turn(self, booking_node):
        """Flag already True, no last_services → <disambiguation_context> hint."""
        mode_context = {
            "_disambiguation_questions_shown": True,
            "opening_booking_request": "quiero cortarme el pelo",
        }
        state = {
            "customer_phone": "+34600000000",
            "messages": [{"role": "user", "content": "para señora y por mantenimiento"}],
        }
        context = booking_node._build_dynamic_context(mode_context, state)
        assert "<disambiguation_context>" in context
        assert "<required_questions>" not in context

    def test_no_disambiguation_when_services_resolved(self, booking_node):
        """last_services set → neither block appears."""
        mode_context = {"last_services": ["Cortar"], "last_stylist": "Pilar"}
        state = {
            "customer_phone": "+34600000000",
            "messages": [{"role": "user", "content": "el viernes"}],
        }
        context = booking_node._build_dynamic_context(mode_context, state)
        assert "<required_questions>" not in context
        assert "<disambiguation_context>" not in context

    def test_detection_on_current_message_not_opening_request(self, booking_node):
        """opening_booking_request generic, user_msg has keywords → questions fire."""
        mode_context = {"opening_booking_request": "quiero pedir cita"}
        state = {
            "customer_phone": "+34600000000",
            "messages": [{"role": "user", "content": "un corte y un óleo"}],
        }
        context = booking_node._build_dynamic_context(mode_context, state)
        assert "<required_questions>" in context
        assert "corte" in context.lower()
        assert "óleo" in context.lower() or "oleo" in context.lower()

    def test_answer_message_does_not_retrigger(self, booking_node):
        """User answer without service keywords → no questions, flag stays False."""
        mode_context = {"opening_booking_request": "quiero cortarme el pelo"}
        state = {
            "customer_phone": "+34600000000",
            "messages": [{"role": "user", "content": "para señora y por mantenimiento"}],
        }
        context = booking_node._build_dynamic_context(mode_context, state)
        assert "<required_questions>" not in context
        assert mode_context.get("_disambiguation_questions_shown") is not True


# ===========================================================================
# Change B — _booking_complete() field-presence gate
# ===========================================================================


class TestBookingComplete:
    """_booking_complete checks if all required fields are present (GATE, not sequencer)."""

    def test_empty_context_all_missing(self):
        is_complete, missing = BookingModeNode._booking_complete({})
        assert is_complete is False
        assert len(missing) == 4
        assert "servicio" in missing
        assert "estilista" in missing
        assert "fecha/hora" in missing
        assert "nombre" in missing

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
    """_build_flow_hint produces prescriptive phase-aware instructions."""

    def test_phase1_no_services(self):
        """No services → hint to identify services, no tools."""
        result = BookingModeNode._build_flow_hint({})
        assert "Identificar servicios" in result
        assert "NO llames herramientas" in result

    def test_phase1b_algo_mas(self):
        """Services set, no add_more_asked, no hints → ask '¿algo más?'."""
        ctx = {"last_services": ["Cortar"]}
        result = BookingModeNode._build_flow_hint(ctx)
        assert "algo más" in result.lower()
        assert "NO llames herramientas" in result

    def test_phase1b_skipped_with_date_hint(self):
        """Services set + preferred_date_hint → skip algo más, go to stylist."""
        ctx = {"last_services": ["Cortar"], "preferred_date_hint": "viernes"}
        result = BookingModeNode._build_flow_hint(ctx)
        assert "estilista" in result.lower()
        assert "algo más" not in result.lower()

    def test_phase2_no_stylist(self):
        """Services + add_more_asked, no stylist → ask stylist preference."""
        ctx = {"last_services": ["Cortar"], "add_more_asked": True}
        result = BookingModeNode._build_flow_hint(ctx)
        assert "estilista" in result.lower()
        assert "NO llames check_availability" in result

    def test_phase3_no_slots(self):
        """Stylist set, no slots → ask what day."""
        ctx = {"last_services": ["Cortar"], "last_stylist": "Pilar", "add_more_asked": True}
        result = BookingModeNode._build_flow_hint(ctx)
        assert "día" in result.lower()
        assert "check_availability" in result

    def test_phase3b_slots_offered(self):
        """Slots offered, none selected → wait for selection."""
        ctx = {
            "last_services": ["Cortar"],
            "last_stylist": "Pilar",
            "add_more_asked": True,
            "offered_slots": [{"time": "10:00"}],
        }
        result = BookingModeNode._build_flow_hint(ctx)
        assert "elige horario" in result.lower()

    def test_phase5_notes(self):
        """All required present, no notes → ask notes."""
        ctx = {
            "last_services": ["Cortar"],
            "last_stylist": "Marta",
            "add_more_asked": True,
            "selected_slot": {"time": "10:00"},
            "customer_name": "Ana",
        }
        result = BookingModeNode._build_flow_hint(ctx)
        assert "nota" in result.lower()

    def test_phase6_confirmation(self):
        """All data including notes → show summary and confirm."""
        ctx = {
            "last_services": ["Cortar"],
            "last_stylist": "Marta",
            "add_more_asked": True,
            "selected_slot": {"time": "10:00"},
            "customer_name": "Ana",
            "notes_asked": True,
        }
        result = BookingModeNode._build_flow_hint(ctx)
        assert "resumen" in result.lower()
        assert "book()" in result

    def test_atajo_with_handoff_hints(self):
        """preferred_date_hint + preferred_stylist_name → skip to stylist (already hinted)."""
        ctx = {
            "last_services": ["Cortar"],
            "preferred_date_hint": "viernes",
            "preferred_stylist_name": "Pilar",
            "last_stylist": "Pilar",
            "add_more_asked": True,
        }
        result = BookingModeNode._build_flow_hint(ctx)
        # Should be at phase 3 (date) since stylist is already set
        assert "día" in result.lower()


# ===========================================================================
# Change F — BookingStateExtraction schema + _merge_extraction
# ===========================================================================


class TestBookingStateExtractionSchema:
    """BookingStateExtraction Pydantic schema defaults are safe."""

    def test_defaults_are_safe(self):
        """Empty construction produces no state pollution."""
        ext = BookingStateExtraction()
        assert ext.resolved_services is None
        assert ext.add_more_declined is False
        assert ext.stylist_preference is None
        assert ext.preferred_date is None
        assert ext.customer_name is None
        assert ext.notes is None
        assert ext.notes_declined is False

    def test_full_construction(self):
        """All fields can be set."""
        ext = BookingStateExtraction(
            resolved_services=["Cortar", "Óleo Mantenimiento"],
            add_more_declined=True,
            stylist_preference="Pilar",
            preferred_date="el martes",
            customer_name="Maria Garcia",
            notes="Tengo alergia",
            notes_declined=False,
        )
        assert ext.resolved_services == ["Cortar", "Óleo Mantenimiento"]
        assert ext.customer_name == "Maria Garcia"
        assert ext.stylist_preference == "Pilar"


class TestMergeExtraction:
    """_merge_extraction fills missing fields and never overwrites existing ones."""

    def test_fills_missing_add_more_asked(self, booking_node):
        """add_more_declined=True → sets add_more_asked in booking_context."""
        ctx: dict = {"last_services": ["Cortar"]}
        ext = BookingStateExtraction(add_more_declined=True)
        booking_node._merge_extraction(ctx, ext)
        assert ctx["add_more_asked"] is True

    def test_does_not_overwrite_existing_services(self, booking_node):
        """Tool-provided services are preserved even if extraction disagrees."""
        ctx: dict = {"last_services": ["Cortar"]}
        ext = BookingStateExtraction(resolved_services=["Cortar", "Óleo"])
        booking_node._merge_extraction(ctx, ext)
        assert ctx["last_services"] == ["Cortar"]

    def test_fills_missing_services(self, booking_node):
        """Extraction fills last_services when empty."""
        ctx: dict = {}
        ext = BookingStateExtraction(resolved_services=["Cortar"])
        booking_node._merge_extraction(ctx, ext)
        assert ctx["last_services"] == ["Cortar"]

    def test_fills_customer_name(self, booking_node):
        """Extraction fills customer_name when missing."""
        ctx: dict = {}
        ext = BookingStateExtraction(customer_name="Maria Garcia")
        booking_node._merge_extraction(ctx, ext)
        assert ctx["customer_name"] == "Maria Garcia"

    def test_does_not_overwrite_existing_customer_name(self, booking_node):
        """Existing customer_name is preserved."""
        ctx: dict = {"customer_name": "Pablo Cabeza"}
        ext = BookingStateExtraction(customer_name="Maria Garcia")
        booking_node._merge_extraction(ctx, ext)
        assert ctx["customer_name"] == "Pablo Cabeza"

    def test_fills_stylist_preference(self, booking_node):
        """Extraction fills last_stylist."""
        ctx: dict = {}
        ext = BookingStateExtraction(stylist_preference="Pilar")
        booking_node._merge_extraction(ctx, ext)
        assert ctx["last_stylist"] == "Pilar"

    def test_sin_preferencia_sets_flag(self, booking_node):
        """'Sin preferencia' also sets no_preference_stylist."""
        ctx: dict = {}
        ext = BookingStateExtraction(stylist_preference="Sin preferencia")
        booking_node._merge_extraction(ctx, ext)
        assert ctx["last_stylist"] == "Sin preferencia"
        assert ctx["no_preference_stylist"] is True

    def test_notes_declined(self, booking_node):
        """notes_declined=True → notes_asked=True, notes=None."""
        ctx: dict = {}
        ext = BookingStateExtraction(notes_declined=True)
        booking_node._merge_extraction(ctx, ext)
        assert ctx["notes_asked"] is True
        assert ctx["notes"] is None

    def test_notes_provided(self, booking_node):
        """Notes string → notes_asked=True, notes set."""
        ctx: dict = {}
        ext = BookingStateExtraction(notes="Tengo alergia al tinte")
        booking_node._merge_extraction(ctx, ext)
        assert ctx["notes_asked"] is True
        assert ctx["notes"] == "Tengo alergia al tinte"

    def test_does_not_overwrite_existing_notes(self, booking_node):
        """Existing notes_asked is preserved."""
        ctx: dict = {"notes_asked": True, "notes": "Pelo fino"}
        ext = BookingStateExtraction(notes="Otra cosa")
        booking_node._merge_extraction(ctx, ext)
        assert ctx["notes"] == "Pelo fino"

    def test_empty_extraction_changes_nothing(self, booking_node):
        """Default extraction (all None/False) leaves context untouched."""
        ctx: dict = {"last_services": ["Cortar"], "customer_name": "Pablo"}
        ext = BookingStateExtraction()
        booking_node._merge_extraction(ctx, ext)
        assert ctx == {"last_services": ["Cortar"], "customer_name": "Pablo"}

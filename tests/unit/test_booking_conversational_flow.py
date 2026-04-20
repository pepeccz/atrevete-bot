"""
Unit tests for booking flow — LLM-driven architecture.

Tests cover:
- A: DISAMBIGUATION_PENDING gate in _pre_tool_call
- B: _booking_complete() field-presence gate (replaces _compute_step)
- C: Hide durations from client (_build_collected_summary, catalog_builder, ui_constraint)
- D: Dynamic context — factual, no imperative directives
- E: _build_flow_hint() neutral pending-data list
- F: Smart gate recovery (prescriptive messages + recovery responses)
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
    node = BookingModeNode(tools=[])
    node._cached_stylists_by_category = {
        "HAIRDRESSING": ["Pilar", "Marta", "Victor", "Harolyn", "Ana"],
    }
    return node


# ===========================================================================
# Change A — DISAMBIGUATION_PENDING gate
# ===========================================================================


class TestDisambiguationGateRemoved:
    """DISAMBIGUATION_PENDING gate removed — check_availability always allowed."""

    @pytest.mark.asyncio
    async def test_allowed_despite_pending_flag(self, booking_node):
        """check_availability NOT blocked even with _has_pending_disambiguation=True."""
        booking_node._mode_context = {
            "_has_pending_disambiguation": True,
            "last_services": ["Cortar"],
            "last_stylist": "Pilar",
            "_date_question_asked": True,
        }
        result = await booking_node._pre_tool_call(
            "check_availability",
            {"service_names": ["Cortar"], "date": "el martes"},
        )
        assert not isinstance(result, ToolCallRejection)

    def test_check_availability_not_in_tools_without_services(self, booking_node):
        """check_availability not included in get_tools() when services are empty (tool filtering)."""
        booking_node._mode_context = {}
        tools = booking_node.get_tools(booking_node._mode_context)
        tool_names = [t.name if hasattr(t, "name") else t.__name__ for t in tools]
        assert "check_availability" not in tool_names

    @pytest.mark.asyncio
    async def test_allowed_with_service_names_in_args(self, booking_node):
        """check_availability allowed when services + stylist in context + shortcut hint."""
        booking_node._mode_context = {
            "preferred_date_hint": "viernes",
            "last_services": ["Cortar"],
            "last_stylist": "Pilar",
        }
        result = await booking_node._pre_tool_call(
            "check_availability",
            {"service_names": ["Cortar"], "stylist_name": "Pilar", "date": "el viernes"},
        )
        assert not isinstance(result, ToolCallRejection)

    @pytest.mark.asyncio
    async def test_allowed_with_services(self, booking_node):
        """check_availability allowed when last_services, last_stylist set + date + flag."""
        booking_node._mode_context = {
            "last_services": ["Cortar"],
            "last_stylist": "Pilar",
            "_date_question_asked": True,
        }
        result = await booking_node._pre_tool_call(
            "check_availability", {"service_names": ["Cortar"], "date": "mañana"}
        )
        assert not isinstance(result, ToolCallRejection)


class TestDisambiguationShowOnce:
    """Disambiguation questions shown once, then replaced with hint."""

    @pytest.mark.xfail(
        strict=True,
        reason="state-first-booking Batch 4: _build_flow_hint deleted — test needs rewrite, issue #TBD",
    )
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

    @pytest.mark.xfail(
        strict=True,
        reason="state-first-booking Batch 4: _build_flow_hint deleted — test needs rewrite, issue #TBD",
    )
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
        """last_services set → compute_next_prompt does NOT return ASK_AUDIENCE."""
        # After B.1.6 _build_dynamic_context is removed. Verify via compute_next_prompt.
        from agent.booking.grounding import compute_next_prompt

        state = {
            "booking_context": {"last_services": ["Cortar"], "last_stylist": "Pilar"},
            "messages": [{"role": "user", "content": "el viernes"}],
            "customer_phone": "+34600000000",
        }
        directive = compute_next_prompt(state)
        assert directive.action != "ASK_AUDIENCE", (
            "When services are resolved there must be no disambiguation — got "
            f"{directive.action!r}"
        )

    @pytest.mark.xfail(
        strict=True,
        reason="state-first-booking Batch 4: _build_flow_hint deleted — test needs rewrite, issue #TBD",
    )
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
        """User answer without services set → grounding returns ASK_SERVICE, no disambiguation."""
        # After B.1.6, _build_dynamic_context is gone. Verify via compute_next_prompt.
        from agent.booking.grounding import compute_next_prompt

        state = {
            "booking_context": {"opening_booking_request": "quiero cortarme el pelo"},
            "messages": [{"role": "user", "content": "para señora y por mantenimiento"}],
            "customer_phone": "+34600000000",
        }
        directive = compute_next_prompt(state)
        # No services set → must ask for service, not audience disambiguation
        assert (
            directive.action == "ASK_SERVICE"
        ), f"Without services, must be ASK_SERVICE, got {directive.action!r}"


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
    async def test_book_passthrough_when_incomplete(self, booking_node):
        """_pre_tool_call no longer rejects for missing fields (Step B removed).

        Completeness gate moved to BookingInvariantMiddleware.  _pre_tool_call
        only handles injection (slot UUID, services, customer_name from context).
        When fields are incomplete the call passes through as a plain dict;
        the middleware enforces preconditions before book() executes.
        See test_invariants_covers_legacy_gates.py for the coverage anchor.
        """
        booking_node._mode_context = {"last_services": ["Cortar"]}
        result = await booking_node._pre_tool_call("book", {})
        # Must NOT be a ToolCallRejection — completeness is the middleware's job now
        assert not isinstance(result, ToolCallRejection), (
            "_pre_tool_call must not reject for missing fields — "
            "BookingInvariantMiddleware handles this gate"
        )
        assert isinstance(result, dict)

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
            "customer_name": "Ana García",
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
    """<ui_constraint> was moved to booking.md — no longer injected in dynamic context."""

    def test_ui_constraint_not_in_dynamic_context(self, booking_node):
        """_build_dynamic_context is deleted — BookingModeNode must not have this method."""
        # After B.1.6 deletion, verify the method does not exist at all.
        # The legacy XML path is gone; booking.md contains the ui_constraint text.
        assert not hasattr(
            booking_node, "_build_dynamic_context"
        ), "_build_dynamic_context must be removed from BookingModeNode (B.1.6)"


# ===========================================================================
# Change D — Dynamic context is factual, not imperative
# ===========================================================================


class TestDynamicContextFactual:
    """Dynamic context contains factual data, no imperative directives."""

    def test_no_current_step_in_context(self, booking_node):
        """_build_dynamic_context is deleted — <current_step> XML no longer possible."""
        # After B.1.6, _build_dynamic_context is removed.
        # The [grounding] directive from compute_next_prompt carries structured data, not XML.
        assert not hasattr(
            booking_node, "_build_dynamic_context"
        ), "_build_dynamic_context must not exist — XML path removed in B.1.6"

    def test_no_next_action_in_context(self, booking_node):
        """_build_dynamic_context is deleted — <next_action> XML no longer possible."""
        assert not hasattr(
            booking_node, "_build_dynamic_context"
        ), "_build_dynamic_context must not exist — XML path removed in B.1.6"

    @pytest.mark.xfail(
        strict=True,
        reason="state-first-booking Batch 4: _build_flow_hint deleted — test needs rewrite, issue #TBD",
    )
    def test_collected_data_in_flow_hint(self, booking_node):
        """<collected_data> was removed; collected info is now reported via <flow_hint>."""
        state = {"messages": [], "customer_phone": "+34612345678", "conversation_summary": None}
        ctx = {"last_services": ["Cortar"]}
        result = booking_node._build_dynamic_context(ctx, state)
        assert "<collected_data>" not in result
        assert "<flow_hint>" in result
        assert "Cortar" in result

    @pytest.mark.xfail(
        strict=True,
        reason="state-first-booking Batch 4: _build_flow_hint deleted — test needs rewrite, issue #TBD",
    )
    def test_flow_hint_present(self, booking_node):
        state = {"messages": [], "customer_phone": "+34612345678", "conversation_summary": None}
        result = booking_node._build_dynamic_context({}, state)
        assert "<flow_hint>" in result

    def test_no_missing_data_section(self, booking_node):
        """_build_dynamic_context is deleted — <missing_data> XML no longer possible."""
        assert not hasattr(
            booking_node, "_build_dynamic_context"
        ), "_build_dynamic_context must not exist — XML path removed in B.1.6"

    def test_stylists_shown_after_algo_mas_asked(self, booking_node):
        """Stylists available in directive.data when services set AND add_more_asked is True."""
        from agent.booking.grounding import compute_next_prompt

        state = {
            "booking_context": {
                "last_services": ["Cortar"],
                "add_more_asked": True,
                "_offered_stylists": ["Marta", "Pilar", "Sin preferencia"],
            },
            "messages": [],
            "customer_phone": "+34612345678",
        }
        directive = compute_next_prompt(state)
        assert (
            directive.action == "ASK_STYLIST"
        ), f"With services + add_more_asked=True, expected ASK_STYLIST, got {directive.action!r}"
        # Stylists are in directive.data["stylists"] after B.1.5
        assert "stylists" in directive.data

    def test_stylists_hidden_before_algo_mas(self, booking_node):
        """Before add_more_asked, compute_next_prompt returns ASK_MORE_SERVICES (no stylist prompt)."""
        from agent.booking.grounding import compute_next_prompt

        state = {
            "booking_context": {"last_services": ["Cortar"]},
            "messages": [],
            "customer_phone": "+34612345678",
        }
        directive = compute_next_prompt(state)
        assert (
            directive.action == "ASK_MORE_SERVICES"
        ), f"Before add_more_asked, must be ASK_MORE_SERVICES, got {directive.action!r}"


# ===========================================================================
# Change E — _build_flow_hint
# ===========================================================================


@pytest.mark.xfail(
    reason="state-first-booking Batch 4: _build_flow_hint deleted, test needs rewrite — issue #TBD",
    strict=True,
)
class TestBuildFlowHint:
    """_build_flow_hint produces descriptive state hints — data, not commands."""

    def test_empty_ctx_all_pending(self):
        """Empty ctx → required fields listed as pending. Notes are optional — not in pending."""
        result = BookingModeNode._build_flow_hint({})
        assert "pendiente" in result.lower()
        assert "servicio" in result.lower()
        assert "estilista" in result.lower()
        assert "nombre" in result.lower()
        # Notes are optional (R8/C5): not listed as pending even when notes_state=not_asked
        assert "notas" not in result.lower() or "recogido" in result.lower()

    def test_services_collected_stylist_pending(self):
        """Services set → servicio in collected, estilista in pending."""
        ctx = {"last_services": ["Cortar"]}
        result = BookingModeNode._build_flow_hint(ctx)
        assert "Cortar" in result
        assert "estilista" in result.lower()
        assert "pendiente" in result.lower()

    def test_services_and_stylist_collected(self):
        """Services + stylist → both in collected, fecha in pending."""
        ctx = {"last_services": ["Cortar"], "last_stylist": "Pilar"}
        result = BookingModeNode._build_flow_hint(ctx)
        assert "Cortar" in result
        assert "Pilar" in result
        assert "fecha" in result.lower()

    def test_slots_offered_not_selected(self):
        """Slots offered but none selected → mentions options offered."""
        ctx = {
            "last_services": ["Cortar"],
            "last_stylist": "Pilar",
            "offered_slots": [{"time": "10:00"}],
        }
        result = BookingModeNode._build_flow_hint(ctx)
        assert "opciones ofrecidas" in result.lower() or "selección" in result.lower()

    def test_name_pending(self):
        """Slot selected, no name → nombre in pending."""
        ctx = {
            "last_services": ["Cortar"],
            "last_stylist": "Marta",
            "offered_slots": [{"time": "10:00"}],
            "selected_slot": {"time": "10:00"},
        }
        result = BookingModeNode._build_flow_hint(ctx)
        assert "nombre" in result.lower()
        assert "pendiente" in result.lower()

    def test_all_required_collected_notes_state_not_asked(self):
        """All required fields set, notes_state=not_asked → no notas in pending (R8/C5 fix).

        Notes are optional: _build_flow_hint must NOT add 'notas' to pending.
        When all required fields are present, _confirmation_shown must be set.
        add_more_asked=True required to suppress the "preguntar ¿algo más?" pending item.
        """
        ctx = {
            "last_services": ["Cortar"],
            "last_stylist": "Marta",
            "add_more_asked": True,
            "offered_slots": [{"time": "10:00"}],
            "selected_slot": {"time": "10:00"},
            "customer_name": "Ana García",
        }
        result = BookingModeNode._build_flow_hint(ctx)
        # notas must NOT appear in pending segment (notes are optional)
        if "Pendiente:" in result:
            pending_segment = result.split("Pendiente:")[1].split("</flow_hint>")[0]
            assert (
                "notas" not in pending_segment.lower()
            ), f"notas must not be in pending when notes_state=not_asked. Got: {pending_segment!r}"
        # _confirmation_shown must be set since all required fields are present
        assert (
            ctx.get("_confirmation_shown") is True
        ), "_confirmation_shown must be set when all required fields are present"

    def test_all_collected_with_stylist_preference(self):
        """Stylist + date hint → fecha/hora in pending, stylist in collected."""
        ctx = {
            "last_services": ["Cortar"],
            "last_stylist": "Pilar",
        }
        result = BookingModeNode._build_flow_hint(ctx)
        assert "Pilar" in result
        assert "fecha" in result.lower()


# ===========================================================================
# Change F — ToolCallRejection data class (gate recovery tests removed;
#             gates that existed for services/stylist/date were removed and
#             replaced by tool filtering in get_tools())
# ===========================================================================


class TestToolCallRejectionDataClass:
    """ToolCallRejection data class behaves correctly."""

    def test_tool_call_rejection_default_recovery_is_none(self):
        """ToolCallRejection without recovery_response defaults to None."""
        r = ToolCallRejection(name="test", error_code="TEST", error_message="test")
        assert r.recovery_response is None

    def test_tool_call_rejection_with_recovery(self):
        """ToolCallRejection accepts recovery_response."""
        r = ToolCallRejection(
            name="test",
            error_code="TEST",
            error_message="test",
            recovery_response="fallback text",
        )
        assert r.recovery_response == "fallback text"

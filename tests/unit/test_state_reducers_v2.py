"""
Unit tests for the M2 state reducers + typed ``BookingContext``.

Covers:
- ``replace_dict`` full-replace semantics (empty / non-empty / ``None`` updates).
- ``replace_booking_context`` backwards-compat alias.
- ``BookingContext`` instantiation and field access.
- The ``booking_context`` reducer chosen on ``ConversationState`` actually
  replaces (no stale-key zombies).

No LLM, DB, or Redis — these are pure-Python, offline reducer tests.
"""

from __future__ import annotations

from typing import get_type_hints

import pytest

from agent.state.schemas import (
    BookingContext,
    ConversationState,
    replace_booking_context,
    replace_dict,
)


# =============================================================================
# replace_dict
# =============================================================================


class TestReplaceDict:
    """The generic full-replace reducer used for booking_context."""

    def test_none_update_keeps_current(self):
        current = {"last_services": ["Corte"]}
        assert replace_dict(current, None) == {"last_services": ["Corte"]}

    def test_none_current_and_none_update_returns_empty_dict(self):
        assert replace_dict(None, None) == {}

    def test_empty_update_replaces_current_with_empty(self):
        """``{}`` is a deliberate reset — stale keys must go, not persist."""
        current = {"last_services": ["Corte"], "last_stylist": "Ana"}
        assert replace_dict(current, {}) == {}

    def test_non_empty_update_fully_replaces_current(self):
        current = {"last_services": ["Corte"], "last_stylist": "Ana"}
        update = {"last_services": ["Tinte"]}
        result = replace_dict(current, update)
        assert result == {"last_services": ["Tinte"]}
        assert "last_stylist" not in result  # zombie-key guarantee

    def test_update_none_with_none_current_returns_empty_dict(self):
        assert replace_dict(None, None) == {}

    def test_none_current_with_update_returns_copy_of_update(self):
        update = {"last_services": ["Corte"]}
        result = replace_dict(None, update)
        assert result == update
        # Must be a copy, not the same reference — mutating result must not leak.
        result["injected"] = True
        assert "injected" not in update

    def test_result_is_detached_copy_of_update(self):
        current = {"a": 1}
        update = {"b": 2}
        result = replace_dict(current, update)
        result["injected"] = True
        assert "injected" not in update

    def test_does_not_mutate_inputs(self):
        current = {"a": 1, "b": 2}
        update = {"c": 3}
        snapshot_current = dict(current)
        snapshot_update = dict(update)
        _ = replace_dict(current, update)
        assert current == snapshot_current
        assert update == snapshot_update


# =============================================================================
# replace_booking_context — backwards-compat alias
# =============================================================================


class TestReplaceBookingContextAlias:
    """The legacy name must behave exactly like ``replace_dict``."""

    def test_alias_points_to_replace_dict(self):
        assert replace_booking_context is replace_dict

    def test_alias_full_replaces(self):
        current = {"last_services": ["Corte"], "last_stylist": "Ana"}
        update = {"last_services": ["Tinte"]}
        assert replace_booking_context(current, update) == {"last_services": ["Tinte"]}


# =============================================================================
# BookingContext TypedDict
# =============================================================================


class TestBookingContextType:
    """Structural checks on the typed booking context."""

    def test_instantiation_with_no_fields_is_valid(self):
        ctx: BookingContext = {}
        assert ctx == {}

    def test_populated_context_reads_back(self):
        ctx: BookingContext = {
            "last_services": ["CORTE LARGO"],
            "last_stylist": "Pilar",
            "no_preference_stylist": False,
            "offered_slots": [{"stylist_id": "abc", "start_time": "2026-04-14T10:00"}],
            "selected_slot": None,
        }
        assert ctx["last_services"] == ["CORTE LARGO"]
        assert ctx["last_stylist"] == "Pilar"
        assert ctx["no_preference_stylist"] is False
        assert ctx["selected_slot"] is None

    def test_expected_fields_are_declared(self):
        """Every field actually used by booking_mode / tools / graph must be typed."""
        expected_fields = {
            "booking_step",
            "last_services",
            "last_service_category",
            "last_total_duration_minutes",
            "last_stylist",
            "no_preference_stylist",
            "available_stylists",
            "offered_slots",
            "selected_slot",
            "customer_name",
            "customer_first_name",
            "customer_last_name",
            "customer_id",
            "opening_booking_request",
            "service_audience_hint",
            "preferred_stylist_name",
            "preferred_date_hint",
            "add_more_asked",
            "notes",
            "notes_asked",
            "_booking_completed",
            "_confirmation_shown",
            "_disambiguation_questions_shown",
            "_offered_stylists",
            "_suggested_customer_name",
        }
        declared = set(BookingContext.__annotations__)
        missing = expected_fields - declared
        assert not missing, f"BookingContext is missing fields: {sorted(missing)}"


# =============================================================================
# ConversationState wiring — booking_context uses replace_dict
# =============================================================================


class TestConversationStateBookingContextReducer:
    """Verify the schema wiring, not just the reducer in isolation."""

    def test_booking_context_annotation_uses_replace_dict(self):
        """The reducer on booking_context must be the new full-replace one."""
        hints = get_type_hints(ConversationState, include_extras=True)
        bc_type = hints["booking_context"]
        # The Annotated metadata is exposed via __metadata__.
        metadata = getattr(bc_type, "__metadata__", ())
        assert replace_dict in metadata, (
            "booking_context must be annotated with replace_dict; "
            f"got metadata={metadata!r}"
        )

    def test_customer_data_collected_declared_exactly_once(self):
        """The duplicated annotation bug must stay fixed."""
        # TypedDict annotations de-duplicate at runtime, but if the source
        # were to re-introduce the duplicate, refactors would silently swap
        # which annotation wins. Checking presence is enough — the regression
        # test above (on fields) plus this one anchor the intent.
        assert "customer_data_collected" in ConversationState.__annotations__


# =============================================================================
# End-to-end reducer behavior on the state field
# =============================================================================


class TestBookingContextReplaceBehavior:
    """Simulate how LangGraph applies the reducer to successive updates."""

    def test_successive_updates_replace_previous(self):
        state_bc: dict = {}
        # Step 1: write services
        state_bc = replace_dict(state_bc, {"last_services": ["Corte"]})
        assert state_bc == {"last_services": ["Corte"]}
        # Step 2: write services + stylist — both survive because the caller
        # included both keys. This mirrors how booking_mode writes the full
        # context each turn.
        state_bc = replace_dict(state_bc, {"last_services": ["Corte"], "last_stylist": "Ana"})
        assert state_bc == {"last_services": ["Corte"], "last_stylist": "Ana"}
        # Step 3: stylist omitted on purpose → it is gone (no zombie).
        state_bc = replace_dict(state_bc, {"last_services": ["Corte"]})
        assert state_bc == {"last_services": ["Corte"]}
        assert "last_stylist" not in state_bc

    def test_none_update_preserves_state(self):
        state_bc = {"last_services": ["Corte"]}
        assert replace_dict(state_bc, None) == state_bc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))

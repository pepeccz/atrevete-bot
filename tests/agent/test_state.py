"""Tests for AgentState TypedDict, BookingContext, and reducers — Phase 1.1/1.2."""

from typing import Annotated, Literal, get_args, get_origin, get_type_hints

import pytest

from agent.state import AgentState, BookingContext, replace_dict

# ---------------------------------------------------------------------------
# replace_dict reducer
# ---------------------------------------------------------------------------


class TestReplaceDict:
    def test_both_none_returns_none(self):
        assert replace_dict(None, None) is None

    def test_update_none_returns_current(self):
        current = {"a": 1}
        assert replace_dict(current, None) == {"a": 1}

    def test_update_replaces_fully(self):
        assert replace_dict({"a": 1}, {"b": 2}) == {"b": 2}

    def test_no_merge_behavior(self):
        """replace_dict must NOT merge — old keys disappear."""
        result = replace_dict({"a": 1, "c": 3}, {"b": 2})
        assert result == {"b": 2}
        assert "a" not in result

    def test_current_none_update_dict(self):
        assert replace_dict(None, {"x": 99}) == {"x": 99}

    def test_empty_update_replaces(self):
        assert replace_dict({"a": 1}, {}) == {}


# ---------------------------------------------------------------------------
# AgentState shape
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {
    "conversation_id",
    "customer_phone",
    "user_message",
    "pending_whatsapp_name",
    "current_mode",
    "messages",
    "booking",
    "customer_id",
    "customer_name",
}


class TestAgentStateShape:
    def test_has_all_required_keys(self):
        hints = get_type_hints(AgentState, include_extras=True)
        assert REQUIRED_KEYS == set(hints.keys())

    def test_current_mode_is_literal(self):
        hints = get_type_hints(AgentState, include_extras=True)
        raw = hints["current_mode"]
        # unwrap Annotated if present
        if get_origin(raw) is Annotated:
            raw = get_args(raw)[0]
        assert get_origin(raw) is Literal
        assert set(get_args(raw)) == {"GENERAL", "BOOKING"}

    def test_messages_annotated_with_add_messages(self):
        from langgraph.graph.message import add_messages

        hints = get_type_hints(AgentState, include_extras=True)
        raw = hints["messages"]
        assert get_origin(raw) is Annotated
        args = get_args(raw)
        # second element must be add_messages
        assert args[1] is add_messages

    def test_booking_annotated_with_replace_dict(self):
        hints = get_type_hints(AgentState, include_extras=True)
        raw = hints["booking"]
        assert get_origin(raw) is Annotated
        args = get_args(raw)
        assert args[1] is replace_dict


# ---------------------------------------------------------------------------
# BookingContext shape
# ---------------------------------------------------------------------------


class TestBookingContextShape:
    def test_is_total_false(self):
        assert BookingContext.__total__ is False

    @pytest.mark.parametrize(
        "field",
        [
            "service_ids",
            "audience",
            "stylist_id",
            "date",
            "offered_slots",
            "selected_slot",
            "customer_full_name",
            "step",
        ],
    )
    def test_has_field(self, field):
        hints = get_type_hints(BookingContext)
        assert field in hints

    def test_step_literal_values(self):
        hints = get_type_hints(BookingContext)
        step_type = hints["step"]
        # step is Literal[...] directly (total=False makes the key optional, not the type)
        assert get_origin(step_type) is Literal
        expected = {
            "service",
            "audience",
            "stylist",
            "date",
            "slot",
            "name",
            "notes",
            "confirm",
            "done",
        }
        assert set(get_args(step_type)) == expected

    def test_audience_literal_values(self):
        hints = get_type_hints(BookingContext)
        audience_type = hints["audience"]
        # unwrap Optional
        args = [a for a in get_args(audience_type) if a is not type(None)]
        assert args, "audience must be Optional[Literal[...]]"
        inner = args[0]
        assert get_origin(inner) is Literal
        assert set(get_args(inner)) == {
            "adult_female",
            "adult_male",
            "child_female",
            "child_male",
            "unisex",
            "baby",
        }

    def test_audience_does_not_contain_old_values(self):
        """Phase 4.0 — DB-aligned strings must replace legacy uppercase tags."""
        hints = get_type_hints(BookingContext)
        audience_type = hints["audience"]
        args = [a for a in get_args(audience_type) if a is not type(None)]
        inner = args[0]
        allowed = set(get_args(inner))
        assert "MUJER" not in allowed
        assert "HOMBRE" not in allowed
        assert "NINO" not in allowed
        assert "BEBE" not in allowed

    # --- Phase 5.1 additions ---

    @pytest.mark.parametrize(
        "field",
        ["_escape_intent", "_notes_asked", "no_preference", "notes"],
    )
    def test_has_phase5_field(self, field):
        hints = get_type_hints(BookingContext)
        assert field in hints, f"BookingContext missing field: {field}"

    def test_escape_intent_literal_or_none(self):
        """_escape_intent must be Literal[...] | None with correct variants."""
        hints = get_type_hints(BookingContext)
        t = hints["_escape_intent"]
        # Union of Literal + None
        args = get_args(t)
        non_none = [a for a in args if a is not type(None)]
        assert len(non_none) == 1
        inner = non_none[0]
        assert get_origin(inner) is Literal
        assert set(get_args(inner)) == {
            "cancel",
            "start_over",
            "change_date",
            "change_service",
            "change_stylist",
        }

    def test_notes_asked_is_bool(self):
        hints = get_type_hints(BookingContext)
        assert hints["_notes_asked"] is bool

    def test_no_preference_is_bool(self):
        hints = get_type_hints(BookingContext)
        assert hints["no_preference"] is bool

    def test_notes_is_optional_str(self):
        hints = get_type_hints(BookingContext)
        t = hints["notes"]
        args = get_args(t)
        assert str in args
        assert type(None) in args

    def test_step_includes_notes_before_confirm(self):
        hints = get_type_hints(BookingContext)
        step_type = hints["step"]
        allowed = set(get_args(step_type))
        assert "notes" in allowed

    def test_step_done_is_last_conceptually(self):
        """'done' must be a valid step value."""
        hints = get_type_hints(BookingContext)
        step_type = hints["step"]
        assert "done" in get_args(step_type)

    def test_step_full_sequence(self):
        hints = get_type_hints(BookingContext)
        step_type = hints["step"]
        expected = {
            "service",
            "audience",
            "stylist",
            "date",
            "slot",
            "name",
            "notes",
            "confirm",
            "done",
        }
        assert set(get_args(step_type)) == expected

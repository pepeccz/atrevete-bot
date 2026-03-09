"""
Unit tests for agent/state/schemas.py — ConversationState v6.0

Coverage:
- create_initial_state() defaults
- preserve_if_none reducer behavior
- merge_dicts reducer behavior
- append_unique_list reducer behavior
- operator.add reducer (messages) behavior
- transition_mode() partial dict output

All tests are synchronous — no LLM, no DB, no Redis needed.
"""

import pytest

from agent.state.schemas import (
    ConversationState,
    append_unique_list,
    create_initial_state,
    merge_dicts,
    preserve_if_none,
    transition_mode,
)


# =============================================================================
# create_initial_state()
# =============================================================================


class TestCreateInitialState:
    """Tests for the create_initial_state() factory function."""

    def test_returns_conversation_state(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert isinstance(state, dict)

    def test_conversation_id_set(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["conversation_id"] == "conv-001"

    def test_customer_phone_set(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["customer_phone"] == "+34612345678"

    def test_current_mode_is_greeting(self):
        """Initial mode must be GREETING — that's the entry point."""
        state = create_initial_state("conv-001", "+34612345678")
        assert state["current_mode"] == "GREETING"

    def test_is_first_interaction_true(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["is_first_interaction"] is True

    def test_messages_empty_list(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["messages"] == []

    def test_mode_history_empty_list(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["mode_history"] == []

    def test_mode_context_empty_dict(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["mode_context"] == {}

    def test_draft_contexts_empty_dict(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["draft_contexts"] == {}

    def test_customer_id_none(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["customer_id"] is None

    def test_customer_name_none(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["customer_name"] is None

    def test_error_count_zero(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["error_count"] == 0

    def test_escalation_triggered_false(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["escalation_triggered"] is False

    def test_escalation_reason_none(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["escalation_reason"] is None

    def test_total_message_count_zero(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["total_message_count"] == 0

    def test_previous_mode_none(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["previous_mode"] is None

    def test_user_message_none(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["user_message"] is None

    def test_created_at_is_set(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["created_at"] is not None
        assert isinstance(state["created_at"], str)
        # ISO 8601 format
        assert "T" in state["created_at"]

    def test_retry_state_none(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["retry_state"] is None

    def test_fallback_metrics_none(self):
        state = create_initial_state("conv-001", "+34612345678")
        assert state["fallback_metrics"] is None


# =============================================================================
# preserve_if_none reducer
# =============================================================================


class TestPreserveIfNone:
    """Tests for the preserve_if_none reducer function."""

    def test_existing_value_preserved_when_update_is_none(self):
        """Core behavior: if update is None, keep current."""
        result = preserve_if_none("existing_value", None)
        assert result == "existing_value"

    def test_new_value_used_when_current_is_none(self):
        """If current is None, the new value replaces it."""
        result = preserve_if_none(None, "new_value")
        assert result == "new_value"

    def test_new_value_overwrites_current(self):
        """When update is not None, it wins."""
        result = preserve_if_none("old", "new")
        assert result == "new"

    def test_both_none_returns_none(self):
        result = preserve_if_none(None, None)
        assert result is None

    def test_preserves_dict(self):
        current = {"key": "value"}
        result = preserve_if_none(current, None)
        assert result == {"key": "value"}

    def test_preserves_list(self):
        current = [1, 2, 3]
        result = preserve_if_none(current, None)
        assert result == [1, 2, 3]

    def test_preserves_zero(self):
        """Zero is falsy but not None — should still be overwritten by update."""
        result = preserve_if_none(0, 5)
        assert result == 5

    def test_preserves_empty_string_update(self):
        """Empty string is not None — so it should overwrite."""
        result = preserve_if_none("existing", "")
        assert result == ""

    def test_false_update_overwrites(self):
        """False is not None — should overwrite current."""
        result = preserve_if_none(True, False)
        assert result is False


# =============================================================================
# merge_dicts reducer
# =============================================================================


class TestMergeDicts:
    """Tests for the merge_dicts reducer function."""

    def test_new_keys_added_to_existing(self):
        current = {"a": 1}
        update = {"b": 2}
        result = merge_dicts(current, update)
        assert result == {"a": 1, "b": 2}

    def test_existing_keys_overwritten_by_update(self):
        current = {"a": 1, "b": 2}
        update = {"b": 99}
        result = merge_dicts(current, update)
        assert result["b"] == 99
        assert result["a"] == 1

    def test_update_none_returns_current(self):
        current = {"x": 1}
        result = merge_dicts(current, None)
        assert result == {"x": 1}

    def test_current_none_returns_update(self):
        update = {"y": 2}
        result = merge_dicts(None, update)
        assert result == {"y": 2}

    def test_both_none_returns_empty_dict(self):
        result = merge_dicts(None, None)
        assert result == {}

    def test_merge_complex_values(self):
        current = {"booking_step": "service_selection", "service_name": "Corte"}
        update = {"booking_step": "stylist_selection"}
        result = merge_dicts(current, update)
        assert result["booking_step"] == "stylist_selection"
        assert result["service_name"] == "Corte"

    def test_does_not_mutate_current(self):
        current = {"a": 1}
        update = {"b": 2}
        _ = merge_dicts(current, update)
        assert current == {"a": 1}  # Original unchanged

    def test_does_not_mutate_update(self):
        current = {"a": 1}
        update = {"b": 2}
        _ = merge_dicts(current, update)
        assert update == {"b": 2}  # Original unchanged


# =============================================================================
# append_unique_list reducer
# =============================================================================


class TestAppendUniqueList:
    """Tests for the append_unique_list reducer function."""

    def test_items_added_only_once(self):
        """Core anti-duplicate guarantee."""
        current = ["GREETING"]
        update = ["GREETING"]  # Same item — must NOT be duplicated
        result = append_unique_list(current, update)
        assert result == ["GREETING"]

    def test_new_items_appended(self):
        current = ["GREETING"]
        update = ["GENERAL"]
        result = append_unique_list(current, update)
        assert "GREETING" in result
        assert "GENERAL" in result

    def test_order_preserved(self):
        current = ["GREETING", "GENERAL"]
        update = ["BOOKING"]
        result = append_unique_list(current, update)
        assert result == ["GREETING", "GENERAL", "BOOKING"]

    def test_update_none_returns_current(self):
        current = ["GREETING"]
        result = append_unique_list(current, None)
        assert result == ["GREETING"]

    def test_current_none_returns_update(self):
        update = ["GREETING"]
        result = append_unique_list(None, update)
        assert result == ["GREETING"]

    def test_both_none_returns_empty_list(self):
        result = append_unique_list(None, None)
        assert result == []

    def test_multiple_unique_items_in_update(self):
        current = ["GREETING"]
        update = ["GENERAL", "BOOKING"]
        result = append_unique_list(current, update)
        assert result == ["GREETING", "GENERAL", "BOOKING"]

    def test_duplicate_in_update_not_added(self):
        current = ["GREETING", "GENERAL"]
        update = ["GENERAL"]  # Already in current — skip
        result = append_unique_list(current, update)
        assert result.count("GENERAL") == 1


# =============================================================================
# operator.add reducer (messages)
# =============================================================================


class TestMessagesAddReducer:
    """
    Tests for the operator.add reducer used for the messages field.

    operator.add on lists is equivalent to list concatenation:
    add([msg1], [msg2]) → [msg1, msg2]
    """

    def test_messages_grow_with_each_addition(self):
        from operator import add

        initial: list = []
        msg1 = [{"role": "user", "content": "Hola"}]
        msg2 = [{"role": "assistant", "content": "¡Hola!"}]

        after_first = add(initial, msg1)
        assert len(after_first) == 1

        after_second = add(after_first, msg2)
        assert len(after_second) == 2

    def test_order_preserved(self):
        from operator import add

        msg1 = [{"role": "user", "content": "First"}]
        msg2 = [{"role": "assistant", "content": "Second"}]

        result = add(msg1, msg2)
        assert result[0]["content"] == "First"
        assert result[1]["content"] == "Second"

    def test_add_empty_list_to_existing(self):
        from operator import add

        existing = [{"role": "user", "content": "Hi"}]
        result = add(existing, [])
        assert result == existing


# =============================================================================
# transition_mode()
# =============================================================================


class TestTransitionMode:
    """Tests for the transition_mode() helper function."""

    def _make_state(
        self,
        current_mode: str = "GREETING",
        previous_mode: str | None = None,
        mode_history: list | None = None,
        mode_context: dict | None = None,
    ) -> ConversationState:
        state = create_initial_state("conv-001", "+34612345678")
        state["current_mode"] = current_mode
        state["previous_mode"] = previous_mode
        state["mode_history"] = mode_history or []
        state["mode_context"] = mode_context or {}
        return state

    def test_new_mode_set_in_result(self):
        state = self._make_state(current_mode="GREETING")
        update = transition_mode(state, "GENERAL")
        assert update["current_mode"] == "GENERAL"

    def test_previous_mode_set_to_old_mode(self):
        state = self._make_state(current_mode="GREETING")
        update = transition_mode(state, "GENERAL")
        assert update["previous_mode"] == "GREETING"

    def test_mode_history_contains_old_mode(self):
        state = self._make_state(current_mode="GREETING")
        update = transition_mode(state, "GENERAL")
        # mode_history update should be a list containing the old mode
        assert "GREETING" in update["mode_history"]

    def test_mode_context_reset_when_no_context_update(self):
        state = self._make_state(current_mode="BOOKING", mode_context={"booking_step": "slot"})
        update = transition_mode(state, "GENERAL")
        # When no context_update provided, mode_context should be reset to empty
        assert update["mode_context"] == {}

    def test_mode_context_set_when_context_update_provided(self):
        state = self._make_state(current_mode="GREETING")
        update = transition_mode(state, "BOOKING", context_update={"booking_step": "service_selection"})
        assert update["mode_context"] == {"booking_step": "service_selection"}

    def test_old_context_saved_to_draft_contexts(self):
        """When transitioning away from a mode with context, save it as a draft."""
        state = self._make_state(
            current_mode="BOOKING",
            mode_context={"booking_step": "stylist_selection", "service_name": "Corte"},
        )
        update = transition_mode(state, "GENERAL")
        # The old BOOKING context should be saved into draft_contexts["BOOKING"]
        assert "BOOKING" in update["draft_contexts"]
        assert update["draft_contexts"]["BOOKING"]["booking_step"] == "stylist_selection"

    def test_updated_at_is_set(self):
        state = self._make_state()
        update = transition_mode(state, "GENERAL")
        assert "updated_at" in update
        assert update["updated_at"] is not None

    def test_does_not_mutate_input_state(self):
        state = self._make_state(current_mode="GREETING")
        original_mode = state["current_mode"]
        _ = transition_mode(state, "GENERAL")
        assert state["current_mode"] == original_mode

    def test_same_mode_transition_no_draft_saved(self):
        """Transitioning to the same mode should not create a draft context."""
        state = self._make_state(current_mode="GENERAL", mode_context={})
        update = transition_mode(state, "GENERAL")
        # No draft_contexts entry for GENERAL since mode didn't change (or context was empty)
        assert update["draft_contexts"] == {}

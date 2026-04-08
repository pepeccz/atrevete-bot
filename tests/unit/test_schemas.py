"""
Unit tests for TASK-1: ConversationState schema extension.

Tests:
- test_create_initial_state_has_customer_memories_none
- test_conversation_state_accepts_customer_memories_dict
"""

import pytest

from agent.state.schemas import ConversationState, create_initial_state


class TestCustomerMemoriesField:
    """Tests for the customer_memories field added in TASK-1."""

    def test_create_initial_state_has_customer_memories_none(self):
        """create_initial_state() must include customer_memories=None."""
        state = create_initial_state("conv-001", "+34612345678")
        assert "customer_memories" in state
        assert state["customer_memories"] is None

    def test_conversation_state_accepts_customer_memories_dict(self):
        """ConversationState-compatible dict must accept non-None customer_memories."""
        state = create_initial_state("conv-001", "+34612345678")
        memories = {
            "visit_count": 3,
            "preferred_stylist_name": "Pilar",
            "typical_services": ["CORTE LARGO"],
        }
        state["customer_memories"] = memories
        # Verify the field exists and has the correct value
        assert state["customer_memories"] == memories
        assert state["customer_memories"]["visit_count"] == 3

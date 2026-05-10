"""T2.1 — AgentState slim-down: BookingContext, AudienceTag, replace_dict removed.

Tests written BEFORE implementation (TDD RED phase).
"""

import pytest


def test_agent_state_has_required_fields():
    """AgentState TypedDict has all expected slim fields."""
    from agent.state import AgentState

    hints = AgentState.__annotations__
    assert "conversation_id" in hints
    assert "customer_phone" in hints
    assert "user_message" in hints
    assert "pending_whatsapp_name" in hints
    assert "messages" in hints
    assert "customer_id" in hints
    assert "customer_name" in hints


def test_agent_state_no_booking_context():
    """AgentState no longer has booking field or BookingContext."""
    from agent.state import AgentState

    hints = AgentState.__annotations__
    assert "booking" not in hints, "booking field must be removed from AgentState"
    assert "current_mode" not in hints, "current_mode field must be removed from AgentState"


def test_booking_context_not_importable():
    """BookingContext class must be deleted from agent.state."""
    import agent.state as state_module

    assert not hasattr(state_module, "BookingContext"), (
        "BookingContext must be removed from agent.state"
    )


def test_audience_tag_not_importable():
    """AudienceTag type alias must be deleted from agent.state."""
    import agent.state as state_module

    assert not hasattr(state_module, "AudienceTag"), (
        "AudienceTag must be removed from agent.state"
    )


def test_replace_dict_not_importable():
    """replace_dict reducer must be deleted from agent.state."""
    import agent.state as state_module

    assert not hasattr(state_module, "replace_dict"), (
        "replace_dict must be removed from agent.state"
    )


def test_agent_state_instantiation():
    """AgentState can be constructed with the slim field set."""
    from agent.state import AgentState

    # Verify the TypedDict is constructable
    state: AgentState = {  # type: ignore[misc]
        "conversation_id": "test-123",
        "customer_phone": "+34600000000",
        "user_message": "hola",
        "pending_whatsapp_name": None,
        "messages": [],
        "customer_id": None,
        "customer_name": None,
    }
    assert state["conversation_id"] == "test-123"
    assert state["customer_id"] is None


def test_agent_state_has_customer_memories_field():
    """AgentState declares customer_memories as a NotRequired field."""
    from typing import get_type_hints
    from agent.state import AgentState

    hints = get_type_hints(AgentState, include_extras=True)
    assert "customer_memories" in hints, "customer_memories field must be declared in AgentState"


def test_agent_state_customer_memories_defaults_to_absent():
    """When not set, customer_memories is absent (NotRequired) — accessing returns KeyError."""
    from agent.state import AgentState

    state: AgentState = {  # type: ignore[misc]
        "conversation_id": "test-456",
        "customer_phone": "+34600000001",
        "user_message": None,
        "pending_whatsapp_name": None,
        "messages": [],
        "customer_id": None,
        "customer_name": None,
    }
    assert state.get("customer_memories") is None


def test_agent_state_customer_memories_can_hold_dict():
    """customer_memories can be set to a non-None dict for returning customers."""
    from agent.state import AgentState

    memories = {"visit_count": 3, "preferred_stylist_name": "Pilar", "agent_notes": "Alergia"}
    state: AgentState = {  # type: ignore[misc]
        "conversation_id": "test-789",
        "customer_phone": "+34600000002",
        "user_message": "hola",
        "pending_whatsapp_name": None,
        "messages": [],
        "customer_id": None,
        "customer_name": None,
        "customer_memories": memories,
    }
    assert state["customer_memories"] == memories
    assert state["customer_memories"]["visit_count"] == 3

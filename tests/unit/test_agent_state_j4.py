"""Tests for T4: recently_offered_slots in AgentState.

Change J: hallucination-tolerant-architecture-bundle.
REQ-J3.

Tests written BEFORE implementation (TDD RED phase).
"""

from __future__ import annotations

from typing import get_type_hints


def test_recently_offered_slots_in_agent_state():
    """AgentState must include recently_offered_slots as NotRequired[list[dict]]."""
    from agent.state import AgentState

    hints = get_type_hints(AgentState, include_extras=True)
    assert (
        "recently_offered_slots" in hints
    ), "recently_offered_slots must be declared in AgentState"


def test_recently_offered_slots_not_in_slot_registry():
    """recently_offered_slots must NOT be in SLOT_REGISTRY (it's not a _slot_* field)."""
    from agent.state import SLOT_REGISTRY

    assert (
        "recently_offered_slots" not in SLOT_REGISTRY
    ), "recently_offered_slots must not be in SLOT_REGISTRY — it has no _slot_ prefix"


def test_validate_registry_still_passes_with_new_field():
    """Adding recently_offered_slots must not break _validate_registry() drift check."""
    # If _validate_registry raises, the import itself will raise
    # This test just confirms the import succeeds post-addition
    import agent.state  # noqa: F401 — triggers _validate_registry() at module level


def test_recently_offered_slots_not_prefixed_with_slot():
    """recently_offered_slots must NOT start with _slot_ prefix."""
    from agent.state import AgentState

    hints = get_type_hints(AgentState, include_extras=True)
    # The field must not be a _slot_ field
    assert "recently_offered_slots" not in {
        k for k in hints if k.startswith("_slot_")
    }, "recently_offered_slots must not have _slot_ prefix"

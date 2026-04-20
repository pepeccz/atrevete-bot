"""Shared fixtures for tests/unit/middleware/.

Provides helpers for constructing ToolCallRequest-shaped objects used in
wrap_tool_call / awrap_tool_call tests after the AgentMiddleware migration.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def make_tool_call_request(tc: Any, state: dict, runtime: Any = None) -> SimpleNamespace:
    """Build a ToolCallRequest-shaped SimpleNamespace for wrap_tool_call tests.

    Args:
        tc: Raw tool call (MagicMock or dict with name/args/id).
        state: Current agent state dict (must be a real dict for _is_tool_call_request).
        runtime: Optional runtime context (unused by booking middlewares).

    Returns:
        SimpleNamespace with .tool_call, .state, .runtime attributes.
    """
    return SimpleNamespace(tool_call=tc, state=state, runtime=runtime)


def make_booking_state(**overrides) -> dict:
    """Return a fully-populated BOOKING mode state dict for use in tests.

    All booking_context fields are defaulted to valid values (confirmed=True,
    all required fields present). Pass overrides to test specific conditions.
    """
    bc = {
        "_booking_completed": False,
        "confirmed": True,
        "_confirmation_shown": True,
        "pending_disambiguations": [],
        "last_services": ["Corte Largo"],
        "add_more_asked": True,
        "last_stylist": "Ana",
        "stylist_id": "stylist-uuid-001",
        "no_preference_stylist": False,
        "offered_slots": [{"start": "2026-04-21T10:00:00"}],
        "selected_slot": {"start": "2026-04-21T10:00:00"},
        "customer_name": "María García",
        "notes_state": "skipped",
    }
    bc_overrides = {k: v for k, v in overrides.items() if k in bc}
    bc.update(bc_overrides)
    state = {
        "current_mode": "BOOKING",
        "booking_context": bc,
        "conversation_id": "conv-conftest-001",
        "total_message_count": 1,
    }
    state_overrides = {k: v for k, v in overrides.items() if k not in bc}
    state.update(state_overrides)
    return state

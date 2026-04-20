"""
Unit tests for _confirmation_shown flag set via BookingModeNode pre-loop.

T15 [R14, R15] — When compute_next_prompt returns SHOW_CONFIRMATION,
_confirmation_shown is set to True BEFORE the LLM call.

INSPECT GATE FINDING (Phase E1):
- BookingGroundingMiddleware.before_model() returns {"messages": [msg]} ONLY.
- booking_context uses replace_dict (full-replace), so side-channel patch
  from before_model() would wipe the entire booking_context.
- DECISION: Option 3 — Set _confirmation_shown=True in BookingModeNode.handle()
  pre-loop, using compute_next_prompt (already imported for stylist gate).
  Same pattern as affirmation/negation wiring (direct dict mutation on booking_context).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def booking_state_ready_for_confirmation():
    """State with all booking fields set, ready for SHOW_CONFIRMATION."""
    return {
        "conversation_id": "test-conf-001",
        "current_mode": "BOOKING",
        "user_message": "el lunes a las 10",
        "messages": [{"role": "user", "content": "el lunes a las 10"}],
        "booking_context": {
            "last_services": ["Corte"],
            "last_service_category": "MUJER",
            "last_stylist": "Pilar",
            "selected_slot": {"start": "2026-04-25T10:00:00", "stylist_id": "uuid-1"},
            "customer_name": "Ana",
            "add_more_asked": True,
            "_confirmation_shown": False,
            "confirmed": None,
        },
        "mode_context": {},
        "total_message_count": 5,
    }


@pytest.mark.asyncio
async def test_show_confirmation_action_sets_confirmation_shown_flag(
    booking_state_ready_for_confirmation,
):
    """T15 [R14/R15] — When compute_next_prompt returns SHOW_CONFIRMATION,
    booking_context['_confirmation_shown'] is True before the LLM call.
    """
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    state = booking_state_ready_for_confirmation

    captured_booking_context: dict | None = None

    async def fake_invoke_create_agent(**kwargs):
        nonlocal captured_booking_context
        captured_booking_context = dict(node._booking_context)
        result = MagicMock()
        result.response_text = "Aquí está tu resumen"
        result.messages = []
        return result

    from shared.booking_config import ToolChoicePolicy
    config_mock = MagicMock()
    config_mock.tool_choice_policy = ToolChoicePolicy.NEVER_FORCE

    # compute_next_prompt returns SHOW_CONFIRMATION
    show_conf_directive = MagicMock()
    show_conf_directive.action = "SHOW_CONFIRMATION"

    with (
        patch.object(node, "_load_stylists_by_category", AsyncMock(return_value={})),
        patch.object(node, "_load_service_names", AsyncMock(return_value=[])),
        patch.object(node, "_resolve_service_category", AsyncMock()),
        patch.object(node, "_resolve_customer_from_state", MagicMock()),
        patch.object(node, "_build_messages", AsyncMock(return_value=[])),
        patch.object(node, "_invoke_create_agent", fake_invoke_create_agent),
        patch("agent.modes.booking_mode.get_booking_config", AsyncMock(return_value=config_mock)),
        patch("agent.modes.booking_mode.compute_next_prompt", MagicMock(return_value=show_conf_directive)),
    ):
        try:
            await node.handle(state, intent=None)
        except Exception:
            pass

    assert captured_booking_context is not None, "LLM was never called"
    assert captured_booking_context.get("_confirmation_shown") is True, (
        f"_confirmation_shown not set before LLM call. booking_context={captured_booking_context}"
    )


@pytest.mark.asyncio
async def test_confirmation_shown_idempotent(booking_state_ready_for_confirmation):
    """T15b — If _confirmation_shown is already True, it stays True (idempotent)."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    state = booking_state_ready_for_confirmation
    # Already shown
    state["booking_context"]["_confirmation_shown"] = True

    captured_booking_context: dict | None = None

    async def fake_invoke_create_agent(**kwargs):
        nonlocal captured_booking_context
        captured_booking_context = dict(node._booking_context)
        result = MagicMock()
        result.response_text = "test"
        result.messages = []
        return result

    from shared.booking_config import ToolChoicePolicy
    config_mock = MagicMock()
    config_mock.tool_choice_policy = ToolChoicePolicy.NEVER_FORCE

    show_conf_directive = MagicMock()
    show_conf_directive.action = "SHOW_CONFIRMATION"

    with (
        patch.object(node, "_load_stylists_by_category", AsyncMock(return_value={})),
        patch.object(node, "_load_service_names", AsyncMock(return_value=[])),
        patch.object(node, "_resolve_service_category", AsyncMock()),
        patch.object(node, "_resolve_customer_from_state", MagicMock()),
        patch.object(node, "_build_messages", AsyncMock(return_value=[])),
        patch.object(node, "_invoke_create_agent", fake_invoke_create_agent),
        patch("agent.modes.booking_mode.get_booking_config", AsyncMock(return_value=config_mock)),
        patch("agent.modes.booking_mode.compute_next_prompt", MagicMock(return_value=show_conf_directive)),
    ):
        try:
            await node.handle(state, intent=None)
        except Exception:
            pass

    assert captured_booking_context is not None
    assert captured_booking_context.get("_confirmation_shown") is True

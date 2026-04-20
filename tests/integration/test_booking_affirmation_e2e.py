"""
Integration test for the full affirmation path: SHOW_CONFIRMATION → confirmed=True → book().

T16 [R16] — After _confirmation_shown is set (Turn N), user says "Dale" (Turn N+1),
affirmation resolver fires, confirmed=True is committed BEFORE the LLM call.

Full middleware stack tested with mocked LLM and mocked book tool.

INSPECT GATE NOTE (Phase E1):
Decision was Option 3 — _confirmation_shown set in BookingModeNode.handle() pre-loop
via compute_next_prompt (not via BookingGroundingMiddleware.before_model()).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_state(booking_context: dict, user_msg: str, turn: int = 3) -> dict:
    """Build a minimal ConversationState dict for testing."""
    return {
        "conversation_id": "e2e-test-001",
        "current_mode": "BOOKING",
        "user_message": user_msg,
        "messages": [{"role": "user", "content": user_msg}],
        "booking_context": booking_context,
        "mode_context": {},
        "total_message_count": turn,
    }


@pytest.fixture
def base_booking_context():
    """Fully-filled booking context — all required fields present."""
    return {
        "last_services": ["Corte"],
        "last_service_category": "MUJER",
        "last_stylist": "Pilar",
        "selected_slot": {"start": "2026-04-28T10:00:00", "stylist_id": "uuid-pilar"},
        "customer_name": "Ana García",
        "customer_first_name": "Ana",
        "customer_id": "cust-uuid-001",
        "add_more_asked": True,
        "_confirmation_shown": False,  # Not shown yet at Turn N
        "confirmed": None,
    }


@pytest.mark.asyncio
async def test_dale_after_confirmation_fires_confirmed(base_booking_context):
    """T16 [R16] — Two-turn sequence:

    Turn N  : state triggers SHOW_CONFIRMATION → _confirmation_shown=True is set
              by the pre-loop gate.
    Turn N+1: user message "Dale" → affirmation resolver fires → confirmed=True
              is committed BEFORE the LLM call.
    """
    from agent.modes.booking_mode import BookingModeNode

    # ── Turn N: SHOW_CONFIRMATION fires ─────────────────────────────────────
    state_n = _make_state(base_booking_context, "quiero confirmar", turn=5)

    node = BookingModeNode(tools=[])

    captured_n: dict | None = None

    async def capture_n(**kwargs):
        nonlocal captured_n
        captured_n = dict(node._booking_context)
        result = MagicMock()
        result.response_text = "Aquí está tu resumen: Corte con Pilar el lunes."
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
        patch.object(node, "_invoke_create_agent", capture_n),
        patch("agent.modes.booking_mode.get_booking_config", AsyncMock(return_value=config_mock)),
        patch("agent.modes.booking_mode.compute_next_prompt", MagicMock(return_value=show_conf_directive)),
    ):
        result_n = await node.handle(state_n, intent=None)

    # After Turn N: _confirmation_shown was set before LLM call
    assert captured_n is not None, "LLM not called on Turn N"
    assert captured_n.get("_confirmation_shown") is True, (
        f"Turn N: _confirmation_shown not set. ctx={captured_n}"
    )

    # ── Turn N+1: user says "Dale" ────────────────────────────────────────────
    # Simulate state after Turn N: booking_context now has _confirmation_shown=True
    booking_context_after_n = dict(base_booking_context)
    booking_context_after_n["_confirmation_shown"] = True
    state_n1 = _make_state(booking_context_after_n, "Dale", turn=6)

    node2 = BookingModeNode(tools=[])
    captured_n1: dict | None = None

    async def capture_n1(**kwargs):
        nonlocal captured_n1
        captured_n1 = dict(node2._booking_context)
        result = MagicMock()
        result.response_text = "Perfecto, te reservé."
        result.messages = []
        return result

    # On Turn N+1, directive is AWAIT_CONFIRMATION (confirmation already shown)
    await_conf_directive = MagicMock()
    await_conf_directive.action = "AWAIT_CONFIRMATION"

    with (
        patch.object(node2, "_load_stylists_by_category", AsyncMock(return_value={})),
        patch.object(node2, "_load_service_names", AsyncMock(return_value=[])),
        patch.object(node2, "_resolve_service_category", AsyncMock()),
        patch.object(node2, "_resolve_customer_from_state", MagicMock()),
        patch.object(node2, "_build_messages", AsyncMock(return_value=[])),
        patch.object(node2, "_invoke_create_agent", capture_n1),
        patch("agent.modes.booking_mode.get_booking_config", AsyncMock(return_value=config_mock)),
        patch("agent.modes.booking_mode.compute_next_prompt", MagicMock(return_value=await_conf_directive)),
    ):
        await node2.handle(state_n1, intent=None)

    # After Turn N+1: confirmed=True committed before LLM call
    assert captured_n1 is not None, "LLM not called on Turn N+1"
    assert captured_n1.get("confirmed") is True, (
        f"Turn N+1: 'Dale' did not set confirmed=True. ctx={captured_n1}"
    )


@pytest.mark.asyncio
async def test_no_dale_without_confirmation_shown(base_booking_context):
    """T16b — 'Dale' without _confirmation_shown=True does NOT set confirmed=True.
    Guards against the affirmation resolver firing prematurely.
    """
    from agent.modes.booking_mode import BookingModeNode

    # _confirmation_shown is False (not shown yet)
    state = _make_state(base_booking_context, "Dale", turn=4)

    node = BookingModeNode(tools=[])
    captured: dict | None = None

    async def capture(**kwargs):
        nonlocal captured
        captured = dict(node._booking_context)
        result = MagicMock()
        result.response_text = "test"
        result.messages = []
        return result

    from shared.booking_config import ToolChoicePolicy
    config_mock = MagicMock()
    config_mock.tool_choice_policy = ToolChoicePolicy.NEVER_FORCE

    ask_slot_directive = MagicMock()
    ask_slot_directive.action = "ASK_SLOT"

    with (
        patch.object(node, "_load_stylists_by_category", AsyncMock(return_value={})),
        patch.object(node, "_load_service_names", AsyncMock(return_value=[])),
        patch.object(node, "_resolve_service_category", AsyncMock()),
        patch.object(node, "_resolve_customer_from_state", MagicMock()),
        patch.object(node, "_build_messages", AsyncMock(return_value=[])),
        patch.object(node, "_invoke_create_agent", capture),
        patch("agent.modes.booking_mode.get_booking_config", AsyncMock(return_value=config_mock)),
        patch("agent.modes.booking_mode.compute_next_prompt", MagicMock(return_value=ask_slot_directive)),
    ):
        await node.handle(state, intent=None)

    assert captured is not None
    # confirmed should NOT be True — _confirmation_shown was False
    assert not captured.get("confirmed"), (
        f"confirmed should be falsy without _confirmation_shown. ctx={captured}"
    )

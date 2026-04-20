"""
Unit tests for stylist resolver wiring in BookingModeNode.

T13 [R12] — _offered_stylists is populated BEFORE stylist resolver gate runs.
T14 [R13] — resolver commits last_stylist to booking_context before LLM call.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def booking_state_with_pilar():
    """Minimal ConversationState with services set, no stylist, user says 'Pilar'."""
    return {
        "conversation_id": "test-conv-001",
        "current_mode": "BOOKING",
        "user_message": "Pilar",
        "messages": [{"role": "user", "content": "Pilar"}],
        "booking_context": {
            "last_services": ["Corte"],
            "last_service_category": "MUJER",
            "add_more_asked": True,
            "last_stylist": None,
            "no_preference_stylist": None,
            "_offered_stylists": None,
            "_confirmation_shown": False,
        },
        "mode_context": {},
        "total_message_count": 3,
    }


@pytest.mark.asyncio
async def test_offered_stylists_populated_before_resolver(booking_state_with_pilar):
    """T13 [R12] — _offered_stylists in booking_context is non-None after handle() setup
    phase (before LLM call), when category cache is available.
    """
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    state = booking_state_with_pilar

    # Mock async methods that require DB/Redis
    category_cache = {
        "MUJER": ["Marta", "Pilar", "Victor"],
        "HOMBRE": ["Marta", "Victor"],
    }
    service_catalog = ["Corte", "Mechas", "Tinte"]

    captured_booking_context: dict | None = None

    async def fake_invoke_create_agent(**kwargs):
        # Capture booking_context at LLM call time
        nonlocal captured_booking_context
        captured_booking_context = dict(node._booking_context)
        # Return a minimal AgenticLoopResult-like object
        result = MagicMock()
        result.response_text = "test response"
        result.messages = []
        return result

    with (
        patch.object(node, "_load_stylists_by_category", AsyncMock(return_value=category_cache)),
        patch.object(node, "_load_service_names", AsyncMock(return_value=service_catalog)),
        patch.object(node, "_resolve_service_category", AsyncMock()),
        patch.object(node, "_resolve_customer_from_state", MagicMock()),
        patch.object(node, "_build_messages", AsyncMock(return_value=[])),
        patch.object(node, "_invoke_create_agent", fake_invoke_create_agent),
        patch("agent.modes.booking_mode.get_booking_config", AsyncMock(return_value=MagicMock(
            tool_choice_policy=MagicMock(value="never_force"),
            tool_choice_policy_value=None,
        ))),
    ):
        try:
            await node.handle(state, intent=None)
        except Exception:
            pass  # We only care about state at LLM call time

    # _offered_stylists must be set BEFORE the LLM call
    assert captured_booking_context is not None, "LLM was never called"
    assert captured_booking_context.get("_offered_stylists") is not None, (
        "_offered_stylists was None at LLM call time — R12 timing requirement violated"
    )


@pytest.mark.asyncio
async def test_stylist_resolver_commits_last_stylist_before_llm_turn(booking_state_with_pilar):
    """T14 [R13] — When directive is ASK_STYLIST and user says 'Pilar',
    booking_context['last_stylist'] == 'Pilar' is set BEFORE LLM call.
    """
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    state = booking_state_with_pilar

    category_cache = {
        "MUJER": ["Marta", "Pilar", "Victor"],
    }
    service_catalog = ["Corte"]

    captured_booking_context: dict | None = None

    async def fake_invoke_create_agent(**kwargs):
        nonlocal captured_booking_context
        captured_booking_context = dict(node._booking_context)
        result = MagicMock()
        result.response_text = "test response"
        result.messages = []
        return result

    from shared.booking_config import ToolChoicePolicy
    config_mock = MagicMock()
    config_mock.tool_choice_policy = ToolChoicePolicy.NEVER_FORCE

    with (
        patch.object(node, "_load_stylists_by_category", AsyncMock(return_value=category_cache)),
        patch.object(node, "_load_service_names", AsyncMock(return_value=service_catalog)),
        patch.object(node, "_resolve_service_category", AsyncMock()),
        patch.object(node, "_resolve_customer_from_state", MagicMock()),
        patch.object(node, "_build_messages", AsyncMock(return_value=[])),
        patch.object(node, "_invoke_create_agent", fake_invoke_create_agent),
        patch("agent.modes.booking_mode.get_booking_config", AsyncMock(return_value=config_mock)),
        patch("agent.modes.booking_mode.compute_next_prompt", MagicMock(return_value=MagicMock(
            action="ASK_STYLIST"
        ))),
    ):
        try:
            await node.handle(state, intent=None)
        except Exception:
            pass

    assert captured_booking_context is not None, "LLM was never called"
    assert captured_booking_context.get("last_stylist") == "Pilar", (
        f"last_stylist not set before LLM call. booking_context={captured_booking_context}"
    )

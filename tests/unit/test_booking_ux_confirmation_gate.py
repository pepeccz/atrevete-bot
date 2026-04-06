"""
Tests for the confirmation gate in BookingModeNode.handle().

Spec: Task 5.4 — booking-ux-fixes
Scenarios:
  (a) IntentResult(intent="confirm") → confirmation_shown=True
  (b) Plain string "confirm" → NOT set (no AttributeError)
  (c) None intent + "dale" user_message → set via _is_spanish_affirmative
  (d) None intent + "no" user_message → NOT set
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agent.routing.intent_router import IntentResult


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _base_mode_context() -> dict:
    """Returns a mode_context that satisfies all gate conditions except confirmation_shown."""
    return {
        "confirmation_shown": False,
        "confirmation_summary_sent": True,
        "last_services": ["Cortar"],
        "last_stylist": "Ana",
        "offered_slots": [{"day_label": "Lunes 8", "time": "09:00"}],
    }


def _make_state(user_message: str, mode_context: dict) -> dict:
    """Minimal ConversationState for testing."""
    return {
        "user_message": user_message,
        "mode_context": mode_context,
        "messages": [],
        "total_message_count": 0,
    }


def _booking_node_with_mocked_loop():
    """Create a BookingModeNode whose _run_agentic_loop is mocked to return fast."""
    from agent.modes.booking_mode import BookingModeNode
    from agent.modes.base import AgenticLoopResult

    node = BookingModeNode(tools=[])
    # Mock out expensive operations so handle() can run without LLM/DB
    node._run_agentic_loop = AsyncMock(
        return_value=AgenticLoopResult(response_text="respuesta de prueba")
    )
    node._build_messages = AsyncMock(return_value=[])
    return node


# ──────────────────────────────────────────────────────────────────────────────
# (a) IntentResult.is_confirmation() → confirmation_shown = True
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_intent_result_confirm_sets_confirmation_shown() -> None:
    """Spec (a): IntentResult(intent='confirm') triggers confirmation gate."""
    node = _booking_node_with_mocked_loop()
    mode_context = _base_mode_context()
    state = _make_state("Sí", mode_context)

    intent = IntentResult(intent="confirm", confidence=0.9, raw_input="Sí")

    await node.handle(state, intent)  # type: ignore[arg-type]

    assert node._mode_context.get("confirmation_shown") is True


@pytest.mark.asyncio
async def test_intent_result_non_confirm_does_not_set() -> None:
    """IntentResult(intent='book') does NOT trigger the confirmation gate."""
    node = _booking_node_with_mocked_loop()
    mode_context = _base_mode_context()
    state = _make_state("quiero reservar", mode_context)

    intent = IntentResult(intent="book", confidence=0.9, raw_input="quiero reservar")

    await node.handle(state, intent)  # type: ignore[arg-type]

    assert not node._mode_context.get("confirmation_shown")


# ──────────────────────────────────────────────────────────────────────────────
# (b) Plain string "confirm" → NOT set, no AttributeError
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plain_string_confirm_does_not_set_no_error() -> None:
    """Spec (b): plain string 'confirm' as intent → no AttributeError and gate stays False."""
    node = _booking_node_with_mocked_loop()
    mode_context = _base_mode_context()
    state = _make_state("confirm", mode_context)

    # This is a plain string, not an IntentResult
    intent = "confirm"

    # Must not raise AttributeError
    await node.handle(state, intent)  # type: ignore[arg-type]

    # "confirm" as user_message does NOT match _is_spanish_affirmative
    assert not node._mode_context.get("confirmation_shown")


# ──────────────────────────────────────────────────────────────────────────────
# (c) None intent + affirmative user_message → confirmation_shown set via fallback
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_none_intent_with_dale_sets_via_affirmative_fallback() -> None:
    """Spec (c): intent=None but user says 'dale' → _is_spanish_affirmative fallback."""
    node = _booking_node_with_mocked_loop()
    mode_context = _base_mode_context()
    state = _make_state("dale", mode_context)

    await node.handle(state, None)

    assert node._mode_context.get("confirmation_shown") is True


@pytest.mark.asyncio
async def test_none_intent_with_si_sets_via_affirmative_fallback() -> None:
    """Spec (c): 'sí' with None intent also triggers the gate."""
    node = _booking_node_with_mocked_loop()
    mode_context = _base_mode_context()
    state = _make_state("sí", mode_context)

    await node.handle(state, None)

    assert node._mode_context.get("confirmation_shown") is True


# ──────────────────────────────────────────────────────────────────────────────
# (d) None intent + "no" user_message → NOT set
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_none_intent_with_no_does_not_set() -> None:
    """Spec (d): 'no' with None intent → gate stays False."""
    node = _booking_node_with_mocked_loop()
    mode_context = _base_mode_context()
    state = _make_state("no", mode_context)

    await node.handle(state, None)

    assert not node._mode_context.get("confirmation_shown")


@pytest.mark.asyncio
async def test_none_intent_with_maybe_does_not_set() -> None:
    """'quizás' is not affirmative → gate stays False."""
    node = _booking_node_with_mocked_loop()
    mode_context = _base_mode_context()
    state = _make_state("quizás", mode_context)

    await node.handle(state, None)

    assert not node._mode_context.get("confirmation_shown")

"""
Tests for greeting → booking handoff after customer-name-handling refactor.

The old name confirmation subflow has been removed. Greeting transitions to:
- GENERAL when last_intent is greet, ambiguous, or absent (default)
- BOOKING when last_intent is book (e.g., "Hola, quiero cortarme el pelo")

This avoids requiring the user to repeat their booking intent on a second turn.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.greeting_mode import GreetingMode
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


def _make_intent(intent: str = "greet", confidence: float = 0.95) -> IntentResult:
    return IntentResult(intent=intent, confidence=confidence, raw_input="hola", mode_hint="GREETING")


def _make_mode() -> GreetingMode:
    mock_llm = MagicMock()
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    mock_llm.ainvoke = AsyncMock()
    return GreetingMode(tools=[], llm_client=mock_llm)


@pytest.mark.asyncio
async def test_new_customer_always_transitions_to_general() -> None:
    """New customer greeting always goes to GENERAL, never BOOKING."""
    mode = _make_mode()
    state = create_initial_state("conv-handoff-1", "+34612345678")
    state["customer_name"] = None
    state["pending_whatsapp_name"] = "Carlos"
    state["messages"] = [
        {"role": "user", "content": "hola", "timestamp": "2026-03-18T10:00:00+01:00"}
    ]

    mock_result = {"id": "cust-123", "first_name": "Carlos"}
    with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
        mock_mc.ainvoke = AsyncMock(return_value=mock_result)
        result = await mode.handle(state, _make_intent())

    assert result["current_mode"] == "GENERAL"


@pytest.mark.asyncio
async def test_returning_customer_always_transitions_to_general() -> None:
    """Returning customer greeting always goes to GENERAL."""
    mode = _make_mode()
    state = create_initial_state("conv-handoff-2", "+34612345678")
    state["customer_name"] = "Carlos"
    state["is_first_interaction"] = False

    result = await mode.handle(state, _make_intent())

    assert result["current_mode"] == "GENERAL"


@pytest.mark.asyncio
async def test_greeting_response_never_contains_customer_name() -> None:
    """Greeting response must NEVER contain the customer's name."""
    mode = _make_mode()
    state = create_initial_state("conv-handoff-3", "+34612345678")
    state["customer_name"] = None
    state["pending_whatsapp_name"] = "María"
    state["messages"] = [
        {"role": "user", "content": "buenas", "timestamp": "2026-03-18T10:00:00+01:00"}
    ]

    mock_result = {"id": "cust-456", "first_name": "María"}
    with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
        mock_mc.ainvoke = AsyncMock(return_value=mock_result)
        result = await mode.handle(state, _make_intent())

    messages = result.get("messages", [])
    combined = " ".join(m.get("content", "") for m in messages)
    assert "María" not in combined


@pytest.mark.asyncio
async def test_greeting_with_book_intent_transitions_to_booking() -> None:
    """When mode_context has last_intent=book, greeting transitions to BOOKING."""
    mode = _make_mode()
    state = create_initial_state("conv-handoff-4", "+34612345678")
    state["customer_name"] = None
    state["pending_whatsapp_name"] = "Pepe"
    state["mode_context"] = {"last_intent": "book", "last_intent_confidence": 0.85}
    state["messages"] = [
        {"role": "user", "content": "Hola, quiero cortarme el pelo",
         "timestamp": "2026-03-18T10:00:00+01:00"}
    ]

    mock_result = {"id": "cust-789", "first_name": "Pepe"}
    with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
        mock_mc.ainvoke = AsyncMock(return_value=mock_result)
        result = await mode.handle(state, _make_intent())

    assert result["current_mode"] == "BOOKING"


@pytest.mark.asyncio
async def test_returning_customer_with_book_intent_transitions_to_booking() -> None:
    """Returning customer with booking intent goes to BOOKING after greeting."""
    mode = _make_mode()
    state = create_initial_state("conv-handoff-5", "+34612345678")
    state["customer_name"] = "Carlos"
    state["mode_context"] = {"last_intent": "book", "last_intent_confidence": 0.90}

    result = await mode.handle(state, _make_intent())

    assert result["current_mode"] == "BOOKING"

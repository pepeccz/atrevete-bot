from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.graphs.conversation_flow import router_node
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


def _make_state(*, customer_name: str | None = None, customer_id: str | None = None) -> dict:
    state = create_initial_state("conv-router-intent-gate", "+34600000001")
    state["current_mode"] = "GENERAL"
    state["customer_name"] = customer_name
    state["customer_id"] = customer_id
    state["is_first_interaction"] = customer_name is None
    state["messages"] = [
        {"role": "user", "content": "hola", "timestamp": "2026-03-17T10:00:00+01:00"}
    ]
    state["user_message"] = "hola"
    return state


def _make_router(intent: str) -> MagicMock:
    router = MagicMock()
    router.classify = AsyncMock(
        return_value=IntentResult(intent=intent, confidence=0.9, raw_input="hola", mode_hint=None)
    )
    return router


@pytest.mark.asyncio
async def test_router_unknown_customer_booking_intent_routes_to_booking() -> None:
    state = _make_state(customer_name=None, customer_id=None)

    with patch("agent.graphs.conversation_flow._get_intent_router", return_value=_make_router("book")):
        result = await router_node(state)

    assert result["current_mode"] == "BOOKING"


@pytest.mark.asyncio
async def test_router_unknown_customer_greet_intent_routes_to_greeting() -> None:
    state = _make_state(customer_name=None, customer_id=None)

    with patch("agent.graphs.conversation_flow._get_intent_router", return_value=_make_router("greet")):
        result = await router_node(state)

    assert result["current_mode"] == "GREETING"

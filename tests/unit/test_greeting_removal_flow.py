from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.graphs.conversation_flow import create_graph, router_node
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


def _make_router(intent: str) -> MagicMock:
    router = MagicMock()
    router.classify = AsyncMock(
        return_value=IntentResult(intent=intent, confidence=0.9, raw_input="hola", mode_hint=None)
    )
    return router


@pytest.mark.asyncio
async def test_preprocess_unknown_customer_with_booking_intent_does_not_seed_greeting_step() -> None:
    graph = create_graph(checkpointer=None)
    preprocess = graph.builder.nodes["preprocess"].runnable
    state = create_initial_state("conv-preprocess-booking", "+34600000005")
    state["customer_phone"] = "+34600000005"
    state["customer_name"] = None
    state["pending_whatsapp_name"] = "Ana desde WhatsApp"
    state["user_message"] = "quiero turno para manana"

    with patch("agent.graphs.conversation_flow.check_customer_exists", new=AsyncMock(return_value=(False, None))):
        result = await preprocess.ainvoke(state)

    assert result["customer_name"] is None
    assert result["customer_id"] is None
    assert result["pending_whatsapp_name"] == "Ana desde WhatsApp"
    assert "mode_context" not in result or "greeting_step" not in result["mode_context"]


@pytest.mark.asyncio
async def test_unknown_customer_pure_greet_routes_to_greeting() -> None:
    state = create_initial_state("conv-greeting-route", "+34600000006")
    state["current_mode"] = "GENERAL"
    state["customer_name"] = None
    state["customer_id"] = None
    state["messages"] = [
        {"role": "user", "content": "hola", "timestamp": "2026-03-17T10:00:00+01:00"}
    ]
    state["user_message"] = "hola"

    with patch("agent.graphs.conversation_flow._get_intent_router", return_value=_make_router("greet")):
        result = await router_node(state)

    assert result["current_mode"] == "GREETING"

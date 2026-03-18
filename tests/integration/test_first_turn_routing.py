from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.graphs.conversation_flow import create_graph
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


def _make_llm(response_text: str = "Hola") -> MagicMock:
    mock = MagicMock()
    response = MagicMock()
    response.content = response_text
    response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def _make_intent_router(intent: str, confidence: float = 0.9) -> MagicMock:
    mock = MagicMock()
    mock.classify = AsyncMock(
        return_value=IntentResult(intent=intent, confidence=confidence, raw_input="", mode_hint=None)
    )
    return mock


async def _customer_not_found(*args, **kwargs):
    return (False, None)


async def _summarize_passthrough(state):
    return {"user_message": None, "last_node": "summarize"}


@pytest.mark.asyncio
async def test_first_turn_booking_message_routes_to_booking():
    state = create_initial_state("first-turn-booking-001", "+34600000011")
    state["user_message"] = "quiero agendar"

    with (
        patch("agent.graphs.conversation_flow._get_llm_client", return_value=_make_llm()),
        patch("agent.graphs.conversation_flow.check_customer_exists", side_effect=_customer_not_found),
        patch("agent.graphs.conversation_flow.summarize_conversation", side_effect=_summarize_passthrough),
        patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router,
    ):
        mock_get_router.return_value = _make_intent_router("book")
        graph = create_graph(checkpointer=None)
        result = await graph.ainvoke(state, config={"configurable": {"thread_id": "first-turn-booking-001"}})

    assert result["current_mode"] == "BOOKING"


@pytest.mark.asyncio
async def test_first_turn_greeting_message_routes_to_greeting():
    state = create_initial_state("first-turn-greeting-001", "+34600000012")
    state["user_message"] = "hola"

    with (
        patch("agent.graphs.conversation_flow._get_llm_client", return_value=_make_llm()),
        patch("agent.graphs.conversation_flow.check_customer_exists", side_effect=_customer_not_found),
        patch("agent.graphs.conversation_flow.summarize_conversation", side_effect=_summarize_passthrough),
        patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router,
    ):
        mock_get_router.return_value = _make_intent_router("greet")
        graph = create_graph(checkpointer=None)
        result = await graph.ainvoke(state, config={"configurable": {"thread_id": "first-turn-greeting-001"}})

    # After customer-name-handling refactor, GreetingMode transitions to GENERAL immediately
    # So the final mode is GENERAL, but GREETING should appear in mode_history
    assert result["current_mode"] == "GENERAL"
    assert "GREETING" in result.get("mode_history", [])

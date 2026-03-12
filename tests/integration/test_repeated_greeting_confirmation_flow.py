from unittest.mock import AsyncMock, MagicMock, patch

from agent.graphs.conversation_flow import create_graph
from agent.state.schemas import create_initial_state


def _make_llm(response_text: str = "Hola") -> MagicMock:
    mock = MagicMock()
    response = MagicMock()
    response.content = response_text
    response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


async def _customer_not_found(*args, **kwargs):
    return (False, None)


async def _summarize_passthrough(state):
    return {"user_message": None, "last_node": "summarize"}


async def test_repeated_greeting_confirmation_resolves_once():
    initial_state = create_initial_state("greeting-confirm-001", "+34612345678")
    initial_state["pending_whatsapp_name"] = "Pepe Garcia"
    initial_state["user_message"] = "Hola"

    mock_llm = _make_llm()
    mock_customer_result = {"id": "customer-uuid-777", "first_name": "Pepe", "phone": "+34612345678"}

    with (
        patch("agent.graphs.conversation_flow._get_llm_client", return_value=mock_llm),
        patch("agent.graphs.conversation_flow.check_customer_exists", side_effect=_customer_not_found),
        patch("agent.graphs.conversation_flow.summarize_conversation", side_effect=_summarize_passthrough),
        patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router,
        patch("agent.modes.greeting_mode.manage_customer") as mock_manage_customer,
    ):
        mock_get_router.return_value.classify = AsyncMock(
            side_effect=[
                MagicMock(intent="confirm", confidence=0.99),
            ]
        )
        mock_manage_customer.ainvoke = AsyncMock(return_value=mock_customer_result)
        graph = create_graph(checkpointer=None)

        turn_one = await graph.ainvoke(initial_state, config={"configurable": {"thread_id": "greeting-confirm-001"}})

        turn_two_state = dict(turn_one)
        turn_two_state["user_message"] = "Sí"
        turn_two = await graph.ainvoke(turn_two_state, config={"configurable": {"thread_id": "greeting-confirm-001"}})

    assistant_messages = [m["content"] for m in turn_two["messages"] if m.get("role") == "assistant"]

    assert any("Puedo llamarte Pepe" in message for message in assistant_messages)
    assert any("Perfecto, Pepe" in message for message in assistant_messages)
    assert turn_two.get("customer_name") == "Pepe"
    assert turn_two.get("current_mode") == "GENERAL"

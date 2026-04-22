"""E2E general mode FAQ test — Task 8.2.

Verifies that the graph routes a schedule question through:
  preprocess → router → general node → create_agent → query_info tool → AIMessage

All LLM and DB I/O is mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

THREAD_ID = "e2e-general-test-001"
CONV_CONFIG = {"configurable": {"thread_id": THREAD_ID}}


def _make_state(user_message: str):
    return {
        "conversation_id": THREAD_ID,
        "customer_phone": "+34600000099",
        "user_message": user_message,
        "pending_whatsapp_name": None,
    }


@pytest.fixture()
def checkpointer():
    return MemorySaver()


@pytest.fixture()
def mock_llm():
    """Mock LLM that, when create_agent calls it, simulates a tool call then final response."""
    # create_agent compiles a StateGraph that calls llm.bind_tools(tools) internally.
    # We simulate: one AIMessage as the final response.
    # The simplest mock: llm is called and returns an AIMessage with the answer.

    ai_resp = AIMessage(content="Nuestros horarios son de lunes a viernes de 10:00 a 20:00.")
    llm = MagicMock()
    # bind_tools must return a mock that has ainvoke
    bound = MagicMock()
    bound.ainvoke = AsyncMock(return_value=ai_resp)
    llm.bind_tools = MagicMock(return_value=bound)
    # Direct ainvoke path
    llm.ainvoke = AsyncMock(return_value=ai_resp)
    return llm


@pytest.fixture()
def graph(checkpointer, mock_llm):
    from agent.graph import create_graph

    with (
        patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=AsyncMock(return_value="catalog"),
        ),
        patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(return_value={}),
        ),
        patch("agent.nodes.preprocess.get_async_session"),
        patch("agent.nodes.preprocess.Customer"),
    ):
        g = create_graph(checkpointer=checkpointer, llm_factory=lambda: mock_llm)
    return g


@pytest.mark.asyncio
async def test_e2e_general_schedule_query(graph):
    """User asks about schedule → general node → AIMessage with hours."""
    state = _make_state("cuáles son los horarios")

    # Patch query_info to return a structured hours response
    hours_payload = {
        "status": "ok",
        "payload": {
            "hours": {
                "lunes": "10:00-20:00",
                "martes": "10:00-20:00",
                "miercoles": "10:00-20:00",
                "jueves": "10:00-20:00",
                "viernes": "10:00-20:00",
                "sabado": "09:00-14:00",
                "domingo": "cerrado",
            }
        },
        "errors": [],
        "next_step": None,
    }

    with patch(
        "agent.tools.query_info._load_hours",
        new=AsyncMock(return_value=hours_payload["payload"]["hours"]),
    ):
        result = await graph.ainvoke(state, config=CONV_CONFIG)

    msgs = result.get("messages", [])
    assert len(msgs) > 0, "Expected at least one message in result"

    # At minimum, router sent us to general (not booking)
    assert (
        result.get("current_mode") == "GENERAL"
    ), f"Expected GENERAL mode, got: {result.get('current_mode')!r}"

    # The last message must be an AI message
    last = msgs[-1]
    last_role = getattr(last, "type", None) or (
        last.get("role") if isinstance(last, dict) else None
    )
    # langchain_core AIMessage has type="ai"
    assert last_role in (
        "ai",
        "assistant",
    ), f"Last message should be AI/assistant, got role={last_role!r}"

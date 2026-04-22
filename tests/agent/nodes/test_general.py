"""Tests for agent/nodes/general.py — Task 6.3."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage


def _import_build_general_node():
    from agent.nodes.general import build_general_node

    return build_general_node


# ---------------------------------------------------------------------------
# Factory smoke
# ---------------------------------------------------------------------------


def test_build_general_node_returns_callable():
    build_general_node = _import_build_general_node()
    mock_llm = MagicMock()
    node_fn = build_general_node(lambda: mock_llm)
    assert callable(node_fn)


def test_build_general_node_wraps_create_agent():
    """Ensure create_agent is called with query_info in tools list."""
    build_general_node = _import_build_general_node()

    with patch("agent.nodes.general.create_agent") as mock_create_agent:
        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent
        from agent.tools.query_info import query_info

        mock_llm = MagicMock()
        build_general_node(lambda: mock_llm)

        assert mock_create_agent.called
        call_kwargs = mock_create_agent.call_args
        # tools list includes query_info
        tools_arg = call_kwargs.kwargs.get("tools") or call_kwargs.args[1]
        assert query_info in tools_arg


# ---------------------------------------------------------------------------
# Node invocation: accumulates new messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_general_node_returns_new_messages_only():
    """Node returns only newly added messages (delta), not full history."""
    build_general_node = _import_build_general_node()

    existing = [HumanMessage(content="qué horarios tienen?")]
    new_ai = AIMessage(content="Estamos abiertos de martes a viernes.")

    # Simulate agent.ainvoke returning existing + new messages
    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={"messages": existing + [new_ai]})

    with patch("agent.nodes.general.create_agent", return_value=mock_agent):
        node_fn = build_general_node(lambda: MagicMock())

    state = {
        "messages": existing,
        "conversation_id": "conv-1",
        "customer_phone": "+5491100000000",
        "user_message": None,
        "current_mode": "GENERAL",
        "booking": None,
        "customer_id": None,
        "customer_name": None,
        "pending_whatsapp_name": None,
    }
    result = await node_fn(state)

    assert "messages" in result
    assert result["messages"] == [new_ai]


@pytest.mark.asyncio
async def test_general_node_passes_messages_to_agent():
    """Node passes state['messages'] to agent.ainvoke."""
    build_general_node = _import_build_general_node()

    existing = [HumanMessage(content="hola")]
    new_ai = AIMessage(content="Hola! ¿En qué te puedo ayudar?")

    mock_agent = MagicMock()
    captured_input = {}

    async def fake_ainvoke(inp, **kwargs):
        captured_input.update(inp)
        return {"messages": existing + [new_ai]}

    mock_agent.ainvoke = fake_ainvoke

    with patch("agent.nodes.general.create_agent", return_value=mock_agent):
        node_fn = build_general_node(lambda: MagicMock())

    state = {
        "messages": existing,
        "conversation_id": "conv-1",
        "customer_phone": "+5491100000000",
        "user_message": None,
        "current_mode": "GENERAL",
        "booking": None,
        "customer_id": None,
        "customer_name": None,
        "pending_whatsapp_name": None,
    }
    await node_fn(state)
    assert "messages" in captured_input
    assert captured_input["messages"] == existing


# ---------------------------------------------------------------------------
# DynamicPromptMiddleware is wired
# ---------------------------------------------------------------------------


def test_dynamic_prompt_middleware_in_create_agent_call():
    """DynamicPromptMiddleware must be passed to create_agent middleware list."""
    build_general_node = _import_build_general_node()
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    with patch("agent.nodes.general.create_agent") as mock_create_agent:
        mock_create_agent.return_value = MagicMock()
        build_general_node(lambda: MagicMock())

        call_kwargs = mock_create_agent.call_args
        middleware_arg = call_kwargs.kwargs.get("middleware") or []
        types_in_middleware = [type(m) for m in middleware_arg]
        assert DynamicPromptMiddleware in types_in_middleware


# ---------------------------------------------------------------------------
# query_info is accessible as tool
# ---------------------------------------------------------------------------


def test_query_info_tool_has_invoke():
    from agent.tools.query_info import query_info

    assert hasattr(query_info, "invoke")

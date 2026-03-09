"""
T-020: Integration smoke test for the v6.0 mode-based LangGraph.

Verifies that the graph processes a message end-to-end without crashing.
Uses mocks for: LLM, database, tools, Redis checkpointer.

The graph is tested without a real checkpointer (checkpointer=None in
create_graph()), which is supported by the implementation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.graphs.conversation_flow import create_graph
from agent.state.schemas import create_initial_state


# =============================================================================
# Mock helpers
# =============================================================================


def make_mock_llm(response_text: str = "¡Hola! Soy Maite. ¿Con quién tengo el gusto de hablar?") -> MagicMock:
    """Build a mock LLM client that returns a simple greeting response."""
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []  # No tool calls
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    return mock_llm


async def _customer_not_found(*args, **kwargs):
    """AsyncMock-compatible customer check that returns (False, None)."""
    return (False, None)


async def _summarize_noop(state):
    """AsyncMock-compatible summarize that returns empty dict."""
    return {}


# =============================================================================
# Smoke tests
# =============================================================================


class TestModeGraphSmoke:
    """
    Smoke tests for the v6.0 conversation graph.

    These tests verify the graph doesn't crash on basic input.
    They do NOT verify LLM response content (that's integration testing).
    """

    async def test_graph_processes_first_hola_message(self):
        """
        Graph must handle a 'hola' message on a new conversation without crashing.

        Patches:
        - _get_llm_client() → returns mock LLM
        - check_customer_exists() → returns (False, None) — new customer
        - summarize_conversation() → no-op
        """
        initial_state = create_initial_state("smoke-conv-001", "+34612345678")
        initial_state["user_message"] = "hola"

        mock_llm = make_mock_llm()

        with (
            patch("agent.graphs.conversation_flow._get_llm_client", return_value=mock_llm),
            patch(
                "agent.graphs.conversation_flow.check_customer_exists",
                side_effect=_customer_not_found,
            ),
            patch(
                "agent.graphs.conversation_flow.summarize_conversation",
                side_effect=_summarize_noop,
            ),
        ):
            # Graph with no checkpointer (in-memory only)
            graph = create_graph(checkpointer=None)

            config = {"configurable": {"thread_id": "smoke-conv-001"}}
            result = await graph.ainvoke(initial_state, config=config)

        # Basic assertions — graph ran to completion
        assert result is not None
        assert isinstance(result, dict)

    async def test_graph_sets_current_mode(self):
        """Graph must set a current_mode after processing."""
        initial_state = create_initial_state("smoke-conv-002", "+34612345678")
        initial_state["user_message"] = "hola"

        mock_llm = make_mock_llm()

        with (
            patch("agent.graphs.conversation_flow._get_llm_client", return_value=mock_llm),
            patch(
                "agent.graphs.conversation_flow.check_customer_exists",
                side_effect=_customer_not_found,
            ),
            patch(
                "agent.graphs.conversation_flow.summarize_conversation",
                side_effect=_summarize_noop,
            ),
        ):
            graph = create_graph(checkpointer=None)
            config = {"configurable": {"thread_id": "smoke-conv-002"}}
            result = await graph.ainvoke(initial_state, config=config)

        assert result.get("current_mode") is not None
        assert result["current_mode"] in ("GREETING", "GENERAL", "BOOKING", "ESCALATION")

    async def test_graph_adds_messages(self):
        """Graph must add at least one message to the messages list."""
        initial_state = create_initial_state("smoke-conv-003", "+34612345678")
        initial_state["user_message"] = "hola"

        mock_llm = make_mock_llm()

        with (
            patch("agent.graphs.conversation_flow._get_llm_client", return_value=mock_llm),
            patch(
                "agent.graphs.conversation_flow.check_customer_exists",
                side_effect=_customer_not_found,
            ),
            patch(
                "agent.graphs.conversation_flow.summarize_conversation",
                side_effect=_summarize_noop,
            ),
        ):
            graph = create_graph(checkpointer=None)
            config = {"configurable": {"thread_id": "smoke-conv-003"}}
            result = await graph.ainvoke(initial_state, config=config)

        messages = result.get("messages", [])
        assert len(messages) >= 1  # At minimum the user message was added

    async def test_graph_does_not_raise_on_first_interaction(self):
        """No exception should propagate from the graph on first interaction."""
        initial_state = create_initial_state("smoke-conv-004", "+34612345678")
        initial_state["user_message"] = "hola"

        mock_llm = make_mock_llm()

        with (
            patch("agent.graphs.conversation_flow._get_llm_client", return_value=mock_llm),
            patch(
                "agent.graphs.conversation_flow.check_customer_exists",
                side_effect=_customer_not_found,
            ),
            patch(
                "agent.graphs.conversation_flow.summarize_conversation",
                side_effect=_summarize_noop,
            ),
        ):
            graph = create_graph(checkpointer=None)
            config = {"configurable": {"thread_id": "smoke-conv-004"}}

            # This must not raise
            result = await graph.ainvoke(initial_state, config=config)

        assert result is not None

    async def test_graph_preprocess_node_records_user_message(self):
        """After preprocess, the user message 'hola' must be in messages."""
        initial_state = create_initial_state("smoke-conv-005", "+34612345678")
        initial_state["user_message"] = "hola"

        mock_llm = make_mock_llm()

        with (
            patch("agent.graphs.conversation_flow._get_llm_client", return_value=mock_llm),
            patch(
                "agent.graphs.conversation_flow.check_customer_exists",
                side_effect=_customer_not_found,
            ),
            patch(
                "agent.graphs.conversation_flow.summarize_conversation",
                side_effect=_summarize_noop,
            ),
        ):
            graph = create_graph(checkpointer=None)
            config = {"configurable": {"thread_id": "smoke-conv-005"}}
            result = await graph.ainvoke(initial_state, config=config)

        messages = result.get("messages", [])
        user_messages = [m for m in messages if m.get("role") == "user"]
        assert len(user_messages) >= 1
        assert user_messages[0]["content"] == "hola"

    async def test_graph_greeting_mode_for_new_customer(self):
        """New customer (no DB record) must be routed to GREETING mode."""
        initial_state = create_initial_state("smoke-conv-006", "+34612345678")
        initial_state["user_message"] = "hola"

        mock_llm = make_mock_llm()

        with (
            patch("agent.graphs.conversation_flow._get_llm_client", return_value=mock_llm),
            patch(
                "agent.graphs.conversation_flow.check_customer_exists",
                side_effect=_customer_not_found,
            ),
            patch(
                "agent.graphs.conversation_flow.summarize_conversation",
                side_effect=_summarize_noop,
            ),
        ):
            graph = create_graph(checkpointer=None)
            config = {"configurable": {"thread_id": "smoke-conv-006"}}
            result = await graph.ainvoke(initial_state, config=config)

        # New customer → must be in GREETING mode (router rules 1 and 3)
        # (is_first_interaction=True OR customer_name=None → GREETING)
        assert result.get("current_mode") == "GREETING"

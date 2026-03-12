"""
T-014: Integration smoke tests for v6.0 mode-based graph routing.

Verifies end-to-end routing through the full pipeline:
  preprocess_node → router_node → mode_dispatcher → [mode_node]

Uses mocks for: LLM, DB (check_customer_exists), tools, Redis, summarize.
No real DB or Redis connections needed.

Test Scenarios:
1. New customer (first interaction) → GREETING mode
2. Returning customer → GENERAL mode (ask_info intent)
3. Error threshold (error_count=3) → auto-escalation to ESCALATION
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.graphs.conversation_flow import create_graph, router_node
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


# ============================================================================
# Shared Mock Helpers
# ============================================================================


def _make_llm(response_text: str = "¡Hola! Soy Maite.") -> MagicMock:
    """Mock LLM that returns a text response with no tool calls."""
    mock = MagicMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def _make_intent_router(intent: str, confidence: float = 0.9) -> MagicMock:
    """Mock IntentRouter that returns the given intent."""
    mock = MagicMock()
    mock.classify = AsyncMock(
        return_value=IntentResult(
            intent=intent,
            confidence=confidence,
            raw_input="",
            mode_hint=None,
        )
    )
    return mock


async def _customer_not_found(*args, **kwargs):
    """New customer: (False, None)."""
    return (False, None)


async def _customer_found(*args, **kwargs):
    """Returning customer mock with name set."""
    mock_customer = MagicMock()
    mock_customer.id = "uuid-customer-001"
    mock_customer.first_name = "Pedro"
    return (True, mock_customer)


async def _customer_found_ana(*args, **kwargs):
    """Returning customer 'Ana' for GENERAL test."""
    mock_customer = MagicMock()
    mock_customer.id = "uuid-customer-002"
    mock_customer.first_name = "Ana"
    return (True, mock_customer)


async def _summarize_noop(state):
    """Summarize is a no-op — returns empty dict."""
    return {}


# ============================================================================
# Test 1 — New customer greeting flow
# ============================================================================


class TestNewCustomerGreetingFlow:
    """
    Test 1: New customer first interaction → GREETING mode.

    State: is_first_interaction=True, customer_name=None (new customer).
    Mock: check_customer_exists → (False, None).
    Expected: current_mode == GREETING after routing.
    """

    async def test_new_customer_routes_to_greeting(self):
        """
        New customer's first message must route to GREETING mode.

        preprocess_node detects new customer (not in DB) → no customer_name set.
        router_node sees customer_name=None → Rule 3b → GREETING.
        """
        state = create_initial_state("v6-smoke-new-001", "+34600000001")
        state["user_message"] = "hola"

        mock_llm = _make_llm()

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
            patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router,
        ):
            mock_get_router.return_value = _make_intent_router("greet")
            graph = create_graph(checkpointer=None)
            config = {"configurable": {"thread_id": "v6-smoke-new-001"}}
            result = await graph.ainvoke(state, config=config)

        assert result is not None
        assert result.get("current_mode") == "GREETING"

    async def test_new_customer_result_has_messages(self):
        """Graph must produce at least the user message in messages list."""
        state = create_initial_state("v6-smoke-new-002", "+34600000001")
        state["user_message"] = "hola"

        mock_llm = _make_llm("¡Hola! ¿Con quién hablo?")

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
            patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router,
        ):
            mock_get_router.return_value = _make_intent_router("greet")
            graph = create_graph(checkpointer=None)
            config = {"configurable": {"thread_id": "v6-smoke-new-002"}}
            result = await graph.ainvoke(state, config=config)

        messages = result.get("messages", [])
        assert any(m.get("role") == "user" for m in messages)


# ============================================================================
# Test 2 — Returning customer routes to GENERAL
# ============================================================================


class TestReturningCustomerGeneralFlow:
    """
    Test 2: Returning customer with ask_info intent → GENERAL mode.

    State: customer_name="Ana", is_first_interaction=False, error_count=0.
    Mock: IntentRouter → "ask_info", check_customer_exists → (True, Ana).
    Expected: current_mode == GENERAL after routing.
    """

    async def test_returning_customer_ask_info_routes_to_general(self):
        """
        Returning customer asking for information → GENERAL mode.

        preprocess_node finds customer in DB → customer_name="Ana".
        router_node: no escalation, no first_interaction, intent=ask_info → GENERAL.
        """
        state = create_initial_state("v6-smoke-returning-001", "+34600000002")
        state["user_message"] = "cuánto cuesta el corte"
        state["customer_name"] = "Ana"

        mock_llm = _make_llm("El corte de pelo tiene un precio...")

        with (
            patch("agent.graphs.conversation_flow._get_llm_client", return_value=mock_llm),
            patch(
                "agent.graphs.conversation_flow.check_customer_exists",
                side_effect=_customer_found_ana,
            ),
            patch(
                "agent.graphs.conversation_flow.summarize_conversation",
                side_effect=_summarize_noop,
            ),
            patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router,
        ):
            mock_get_router.return_value = _make_intent_router("ask_info")
            graph = create_graph(checkpointer=None)
            config = {"configurable": {"thread_id": "v6-smoke-returning-001"}}
            result = await graph.ainvoke(state, config=config)

        assert result is not None
        assert result.get("current_mode") == "GENERAL"

    async def test_returning_customer_router_node_alone(self):
        """
        Direct router_node unit test: returning customer + ask_info → GENERAL.
        Does not run the full graph — verifies router logic in isolation.
        """
        state = create_initial_state("v6-smoke-router-001", "+34600000002")
        state["customer_name"] = "Ana"
        state["is_first_interaction"] = False
        state["error_count"] = 0
        state["escalation_triggered"] = False
        state["messages"] = [
            {"role": "user", "content": "cuánto cuesta", "timestamp": "2026-01-01T00:00:00"}
        ]

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_intent_router("ask_info")
            result = await router_node(state)

        # ask_info when already in GENERAL → no mode change returned OR GENERAL explicitly
        returned_mode = result.get("current_mode")
        assert returned_mode is None or returned_mode == "GENERAL"


# ============================================================================
# Test 3 — Error threshold auto-escalation
# ============================================================================


class TestErrorThresholdAutoEscalation:
    """
    Test 3: error_count=3 triggers auto-escalation to ESCALATION.

    State: error_count=3, customer_name="Carlos", is_first_interaction=False.
    Expected: current_mode == ESCALATION (Rule 2 in router_node).
    """

    async def test_error_count_3_escalates_via_router_node(self):
        """
        Direct router_node call with error_count=3 → ESCALATION.
        Rule 2 short-circuits before intent classification.
        """
        state = create_initial_state("v6-smoke-error-001", "+34600000003")
        state["customer_name"] = "Carlos"
        state["is_first_interaction"] = False
        state["error_count"] = 3
        state["escalation_triggered"] = False
        state["messages"] = [
            {"role": "user", "content": "ayuda", "timestamp": "2026-01-01T00:00:00"}
        ]

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_intent_router("ask_info")
            result = await router_node(state)

        assert result["current_mode"] == "ESCALATION"
        # IntentRouter must NOT be called (Rule 2 short-circuits)
        mock_get_router.return_value.classify.assert_not_called()

    async def test_error_count_3_escalates_via_full_graph(self):
        """
        Full graph run with error_count=3 → ESCALATION mode in result.
        """
        state = create_initial_state("v6-smoke-error-002", "+34600000003")
        state["customer_name"] = "Carlos"
        state["is_first_interaction"] = False
        state["error_count"] = 3
        state["escalation_triggered"] = False
        state["user_message"] = "necesito ayuda urgente"

        mock_llm = _make_llm("Entiendo que necesitas ayuda urgente...")

        with (
            patch("agent.graphs.conversation_flow._get_llm_client", return_value=mock_llm),
            patch(
                "agent.graphs.conversation_flow.check_customer_exists",
                side_effect=_customer_found,
            ),
            patch(
                "agent.graphs.conversation_flow.summarize_conversation",
                side_effect=_summarize_noop,
            ),
            patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router,
        ):
            mock_get_router.return_value = _make_intent_router("ask_info")
            graph = create_graph(checkpointer=None)
            config = {"configurable": {"thread_id": "v6-smoke-error-002"}}
            result = await graph.ainvoke(state, config=config)

        assert result is not None
        assert result.get("current_mode") == "ESCALATION"

    async def test_error_count_above_threshold_also_escalates(self):
        """error_count > 3 also triggers auto-escalation (Rule 2)."""
        state = create_initial_state("v6-smoke-error-003", "+34600000003")
        state["customer_name"] = "Carlos"
        state["is_first_interaction"] = False
        state["error_count"] = 7
        state["escalation_triggered"] = False
        state["messages"] = [
            {"role": "user", "content": "ayuda", "timestamp": "2026-01-01T00:00:00"}
        ]

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_intent_router("ask_info")
            result = await router_node(state)

        assert result["current_mode"] == "ESCALATION"

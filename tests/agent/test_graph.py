"""Tests for create_graph factory — Task 7.1."""

from __future__ import annotations

from unittest.mock import MagicMock

from langgraph.graph.state import CompiledStateGraph

# ---------------------------------------------------------------------------
# 7.1.1  create_graph returns a CompiledStateGraph
# ---------------------------------------------------------------------------


def test_create_graph_returns_compiled_state_graph():
    """create_graph() must return a CompiledStateGraph instance."""
    from agent.graph import create_graph

    graph = create_graph()
    assert isinstance(graph, CompiledStateGraph)


# ---------------------------------------------------------------------------
# 7.1.2  Node set
# ---------------------------------------------------------------------------


def test_create_graph_node_set():
    """Graph must contain exactly preprocess, router, general, booking nodes."""
    from agent.graph import create_graph

    graph = create_graph()
    node_names = set(graph.nodes.keys())
    # LangGraph adds __start__ automatically
    expected = {"preprocess", "router", "general", "booking", "__start__"}
    assert expected.issubset(node_names), f"Missing nodes: {expected - node_names}"


# ---------------------------------------------------------------------------
# 7.1.3  Checkpointer is threaded in
# ---------------------------------------------------------------------------


def test_create_graph_with_checkpointer():
    """checkpointer kwarg must be passed through to compile()."""
    from langgraph.checkpoint.memory import MemorySaver

    from agent.graph import create_graph

    saver = MemorySaver()
    graph = create_graph(checkpointer=saver)
    assert isinstance(graph, CompiledStateGraph)
    # The checkpointer is stored on the compiled graph
    assert graph.checkpointer is saver


# ---------------------------------------------------------------------------
# 7.1.4  llm_factory is honoured
# ---------------------------------------------------------------------------


def test_create_graph_with_custom_llm_factory():
    """llm_factory kwarg must be accepted and not raise."""
    from agent.graph import create_graph

    mock_llm = MagicMock()
    # Factory callable that returns mock LLM
    graph = create_graph(llm_factory=lambda: mock_llm)
    assert isinstance(graph, CompiledStateGraph)


# ---------------------------------------------------------------------------
# 7.1.5  store kwarg is accepted (MVP: unused but must not raise)
# ---------------------------------------------------------------------------


def test_create_graph_accepts_store_kwarg():
    """store kwarg must be accepted for interface compat with main.py."""
    from agent.graph import create_graph

    graph = create_graph(store=None)
    assert isinstance(graph, CompiledStateGraph)

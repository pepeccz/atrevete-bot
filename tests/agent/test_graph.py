"""Tests for create_graph factory — adapted for create_agent rewrite."""

from __future__ import annotations

from unittest.mock import MagicMock

from langgraph.graph.state import CompiledStateGraph


def test_create_graph_returns_compiled_state_graph():
    """create_graph() must return a CompiledStateGraph instance."""
    from agent.graph import create_graph

    graph = create_graph()
    assert isinstance(graph, CompiledStateGraph)


def test_create_graph_with_checkpointer():
    """checkpointer kwarg must be passed through to compile()."""
    from langgraph.checkpoint.memory import MemorySaver

    from agent.graph import create_graph

    saver = MemorySaver()
    graph = create_graph(checkpointer=saver)
    assert isinstance(graph, CompiledStateGraph)
    assert graph.checkpointer is saver


def test_create_graph_with_custom_llm_factory():
    """llm_factory kwarg must be accepted and not raise."""
    from agent.graph import create_graph

    mock_llm = MagicMock()
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    graph = create_graph(llm_factory=lambda: mock_llm)
    assert isinstance(graph, CompiledStateGraph)


def test_create_graph_accepts_store_kwarg():
    """store kwarg must be accepted for interface compat with main.py."""
    from agent.graph import create_graph

    graph = create_graph(store=None)
    assert isinstance(graph, CompiledStateGraph)


def test_create_graph_has_ainvoke():
    """The compiled graph exposes ainvoke — required by main.py."""
    from agent.graph import create_graph

    graph = create_graph()
    assert hasattr(graph, "ainvoke"), "CompiledStateGraph must expose ainvoke"

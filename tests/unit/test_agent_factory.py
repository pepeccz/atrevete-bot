"""T2.2 / T7.1 — agent_factory: build_conversation_agent returns compiled graph.

TDD RED phase — written before agent/agent_factory.py exists.
"""

from unittest.mock import MagicMock, patch


def _fake_llm():
    """Return a minimal mock that satisfies create_agent binding."""
    mock = MagicMock()
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def test_build_conversation_agent_importable():
    """build_conversation_agent is importable from agent.agent_factory."""
    from agent.agent_factory import build_conversation_agent

    assert callable(build_conversation_agent)


def test_build_conversation_agent_returns_compiled_graph():
    """build_conversation_agent(llm_factory, checkpointer=None) returns a runnable graph."""
    from langgraph.checkpoint.memory import MemorySaver

    from agent.agent_factory import build_conversation_agent

    graph = build_conversation_agent(llm_factory=_fake_llm, checkpointer=MemorySaver())
    # LangGraph compiled graphs expose ainvoke
    assert hasattr(graph, "ainvoke"), "compiled graph must have ainvoke method"


def test_build_conversation_agent_has_five_tools():
    """The graph is built with the five canonical booking/general tools."""
    from agent.agent_factory import AGENT_TOOLS

    assert len(AGENT_TOOLS) == 5
    tool_names = {t.name for t in AGENT_TOOLS}
    assert "check_availability" in tool_names
    assert "get_next_available_options" in tool_names
    assert "book" in tool_names
    assert "manage_appointments" in tool_names
    assert "escalate" in tool_names


def test_build_conversation_agent_accepts_none_checkpointer():
    """build_conversation_agent with checkpointer=None does not raise."""
    from agent.agent_factory import build_conversation_agent

    graph = build_conversation_agent(llm_factory=_fake_llm, checkpointer=None)
    assert graph is not None


def test_build_conversation_agent_default_llm_factory():
    """build_conversation_agent with llm_factory=None uses get_llm internally."""
    from agent.agent_factory import build_conversation_agent

    with patch("agent.agent_factory.get_llm") as mock_get_llm:
        mock_llm = _fake_llm()
        mock_get_llm.return_value = mock_llm
        build_conversation_agent()
        mock_get_llm.assert_called_once()

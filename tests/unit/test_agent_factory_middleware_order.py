"""C1-RED: agent_factory must register PromptAssemblyMiddleware after DynamicPrompt and before Summarize."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _fake_llm():
    mock = MagicMock()
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def test_middleware_registration_order():
    """Factory middleware list must follow: Disclosure → CustomerResolve → AppointmentContext → DynamicPrompt → PromptAssembly → Summarize."""
    from langgraph.checkpoint.memory import MemorySaver

    with patch("agent.agent_factory.get_llm", return_value=_fake_llm()):
        # We need to inspect what middleware list is passed to create_agent
        captured: dict = {}

        def fake_create_agent(model, tools, system_prompt, middleware, checkpointer, state_schema):
            captured["middleware"] = middleware
            # Return a minimal compiled graph mock
            g = MagicMock()
            g.ainvoke = MagicMock()
            return g

        with patch("agent.agent_factory.create_agent", side_effect=fake_create_agent):
            from agent.agent_factory import build_conversation_agent
            build_conversation_agent(llm_factory=_fake_llm, checkpointer=MemorySaver())

    mw_list = captured.get("middleware", [])
    mw_types = [type(m).__name__ for m in mw_list]

    assert "DisclosureMiddleware" in mw_types
    assert "CustomerResolveMiddleware" in mw_types
    assert "AppointmentContextMiddleware" in mw_types
    assert "DynamicPromptMiddleware" in mw_types
    assert "PromptAssemblyMiddleware" in mw_types
    assert "SummarizeMiddleware" in mw_types

    idx = {name: i for i, name in enumerate(mw_types)}
    assert idx["DisclosureMiddleware"] < idx["CustomerResolveMiddleware"]
    assert idx["CustomerResolveMiddleware"] < idx["AppointmentContextMiddleware"]
    assert idx["AppointmentContextMiddleware"] < idx["DynamicPromptMiddleware"]
    assert idx["DynamicPromptMiddleware"] < idx["PromptAssemblyMiddleware"]
    assert idx["PromptAssemblyMiddleware"] < idx["SummarizeMiddleware"]

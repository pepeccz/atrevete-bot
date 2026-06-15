"""T-10 RED tests: agent_factory.py middleware stack — LLMTraceMiddleware conditional wiring.

Tests:
  - test_middleware_count_with_trace_enabled — 8 entries when flag is on
  - test_llm_trace_middleware_is_first — LLMTraceMiddleware at index 0
  - test_middleware_count_with_trace_disabled — 7 entries when flag is off
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _fake_llm():
    mock = MagicMock()
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def _build_and_capture_middleware(trace_enabled: bool) -> list:
    """Helper: build the agent with the given trace flag and return the middleware list."""
    captured: dict = {}

    def fake_create_agent(model, tools, system_prompt, middleware, checkpointer, state_schema):
        captured["middleware"] = middleware
        g = MagicMock()
        g.ainvoke = MagicMock()
        return g

    mock_settings = MagicMock()
    mock_settings.LLM_TRACE_ENABLED = trace_enabled

    with patch("agent.agent_factory.get_llm", return_value=_fake_llm()):
        with patch("agent.agent_factory.create_agent", side_effect=fake_create_agent):
            with patch("agent.agent_factory.get_settings", return_value=mock_settings):
                from agent.agent_factory import build_conversation_agent
                build_conversation_agent(llm_factory=_fake_llm)

    return captured.get("middleware", [])


def test_middleware_count_with_trace_enabled():
    """build_conversation_agent() with trace on → middleware list has 9 entries."""
    mw_list = _build_and_capture_middleware(trace_enabled=True)
    assert len(mw_list) == 9, (
        f"Expected 9 middleware entries with trace enabled, got {len(mw_list)}: "
        f"{[type(m).__name__ for m in mw_list]}"
    )


def test_llm_trace_middleware_is_first():
    """LLMTraceMiddleware is at index 0 (outermost) when trace is enabled."""
    from agent.middleware.llm_trace import LLMTraceMiddleware

    mw_list = _build_and_capture_middleware(trace_enabled=True)
    assert len(mw_list) > 0, "Middleware list must not be empty"
    assert isinstance(mw_list[0], LLMTraceMiddleware), (
        f"Expected LLMTraceMiddleware at index 0, got {type(mw_list[0]).__name__}"
    )


def test_middleware_count_with_trace_disabled():
    """build_conversation_agent() with trace off → middleware list has 8 entries (LLMTraceMiddleware absent)."""
    mw_list = _build_and_capture_middleware(trace_enabled=False)
    assert len(mw_list) == 8, (
        f"Expected 8 middleware entries with trace disabled, got {len(mw_list)}: "
        f"{[type(m).__name__ for m in mw_list]}"
    )
    mw_types = [type(m).__name__ for m in mw_list]
    assert "LLMTraceMiddleware" not in mw_types, (
        "LLMTraceMiddleware must not be present when trace is disabled"
    )

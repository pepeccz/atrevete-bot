"""Top-level graph factory — create_agent rewrite.

create_graph(checkpointer, llm_factory, store) → CompiledStateGraph

Thin wrapper that delegates to build_conversation_agent().
Keeps the original function signature so agent/main.py is untouched.
"""

from __future__ import annotations

from typing import Any


def create_graph(
    checkpointer: Any = None,
    llm_factory: Any = None,
    store: Any = None,
) -> Any:
    """Build and compile the conversation graph via create_agent.

    Args:
        checkpointer: Optional LangGraph checkpointer (AsyncRedisSaver / MemorySaver).
        llm_factory: Zero-arg callable → BaseChatModel. Defaults to get_llm().
        store: Accepted for interface compat with main.py; not used in v2.

    Returns:
        CompiledStateGraph
    """
    from agent.agent_factory import build_conversation_agent

    return build_conversation_agent(llm_factory=llm_factory, checkpointer=checkpointer)

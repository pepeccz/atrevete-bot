"""
LangGraph nodes for conversation flow - v6.0 Mode-Based Architecture.

This package contains node functions that process conversation state.

v6.0 node functions live in agent/graphs/conversation_flow.py and are
NOT re-exported from this package to avoid circular imports.

[DEPRECATED] v3.0/v5.0 legacy nodes (kept for backward compatibility only):
- conversational_agent: Old single mega-node (FSM-based, DEPRECATED in v6.0)
  → Replaced by preprocess_node + router_node + [mode]_node in conversation_flow.py
- summarize_conversation: Summarization function (still reused by v6.0 summarize_node)

The v6.0 graph nodes (preprocess_node, router_node, greeting_node, etc.)
are defined in agent/graphs/conversation_flow.py and should be imported
directly from there if needed outside the graph module.

DO NOT add conversational_agent to new graphs — it is not part of the v6.0 flow.
"""

# [DEPRECATED] Legacy mega-node — kept for test backward compatibility
# The new graph does NOT use this node. See agent/graphs/conversation_flow.py.
from agent.nodes.conversational_agent import conversational_agent

# Active: summarize_conversation is still used by v6.0 summarize_node
from agent.nodes.summarization import summarize_conversation

__all__ = [
    # [DEPRECATED] v5.0 mega-node — not used in v6.0 graph
    "conversational_agent",
    # Active: used by summarize_node in conversation_flow.py
    "summarize_conversation",
]

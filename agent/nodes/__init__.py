"""
LangGraph nodes for conversation flow - v3.0 Architecture.

This package contains node functions that process conversation state:
- conversational_agent: Single node handling all conversations (Claude + 7 tools)
- summarize_conversation: Summarization for FIFO windowing

All transactional logic (booking, availability) is handled by Claude via tools.
No explicit Tier 1/Tier 2 separation - Claude orchestrates entire flow.
"""

from agent.nodes.conversational_agent import conversational_agent
from agent.nodes.summarization import summarize_conversation

__all__ = [
    # Core conversational node
    "conversational_agent",
    # Message management
    "summarize_conversation",
]

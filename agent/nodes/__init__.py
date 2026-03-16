"""
LangGraph nodes for conversation flow - v6.0 Architecture.

This package contains node functions that process conversation state:
- summarize_conversation: Summarization for FIFO windowing

v6.0 Changes:
- REMOVED: conversational_agent (replaced by mode-based architecture)
- Modes handle all conversation logic (GreetingMode, BookingMode, GeneralMode, EscalationMode)
"""

from agent.nodes.summarization import summarize_conversation

__all__ = [
    # Message management
    "summarize_conversation",
]
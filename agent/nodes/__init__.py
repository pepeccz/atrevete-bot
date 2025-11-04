"""
LangGraph nodes for conversation flow - Hybrid Architecture.

This package contains node functions that process conversation state:
- Tier 1: conversational_agent (Claude + tools)
- Tier 2: Transactional nodes (booking, availability, payment)
"""

from agent.nodes.conversational_agent import conversational_agent
from agent.nodes.summarization import summarize_conversation
from agent.nodes.availability_nodes import check_availability
# from agent.nodes.pack_suggestion_nodes import suggest_pack, handle_pack_response  # Removed - packs functionality eliminated
from agent.nodes.booking_nodes import validate_booking_request, handle_category_choice

__all__ = [
    # Tier 1: Conversational
    "conversational_agent",
    # Message management
    "summarize_conversation",
    # Tier 2: Transactional
    "check_availability",
    # "suggest_pack",  # Removed - packs functionality eliminated
    # "handle_pack_response",  # Removed - packs functionality eliminated
    "validate_booking_request",
    "handle_category_choice",
]

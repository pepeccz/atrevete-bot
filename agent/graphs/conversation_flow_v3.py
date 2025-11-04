"""
LangGraph StateGraph for conversation flow orchestration - v3.0 Architecture.

This module defines the minimalist StateGraph for v3.0 tool-based architecture:
- Single conversational_agent node (Claude + 7 consolidated tools)
- No transactional nodes (booking delegated to BookingTransaction handler)
- Simplified state (15 fields vs 50 fields in v2)

The graph is a simple linear flow:
    process_incoming_message → conversational_agent → END

All conversation logic (FAQs, booking, availability, customer management) is handled
by Claude through tool calling. No explicit state transitions or routing logic needed.
"""

import logging
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.nodes.conversational_agent import conversational_agent
from agent.nodes.summarization import summarize_conversation
from agent.prompts import load_maite_system_prompt
from agent.state.schemas import ConversationState
from agent.state.helpers import add_message, should_summarize

# Configure logger
logger = logging.getLogger(__name__)

# Lazy-loaded system prompt cache
_MAITE_SYSTEM_PROMPT_CACHE: str | None = None


def get_maite_system_prompt() -> str:
    """
    Get Maite system prompt with lazy-loading and caching.

    Returns:
        str: The Maite system prompt content
    """
    global _MAITE_SYSTEM_PROMPT_CACHE

    if _MAITE_SYSTEM_PROMPT_CACHE is None:
        _MAITE_SYSTEM_PROMPT_CACHE = load_maite_system_prompt()
        logger.info(f"Maite system prompt loaded ({len(_MAITE_SYSTEM_PROMPT_CACHE)} characters)")

    return _MAITE_SYSTEM_PROMPT_CACHE


# For backward compatibility
MAITE_SYSTEM_PROMPT = get_maite_system_prompt


async def process_incoming_message(state: ConversationState) -> dict[str, Any]:
    """
    Process incoming user message and add it to conversation history.

    This node is the first to execute in the graph. It takes the user_message
    field (set by agent/main.py) and adds it to the messages history using
    add_message() helper, which handles FIFO windowing.

    Args:
        state: Current conversation state (with checkpoint loaded by LangGraph)

    Returns:
        Updated state with new user message added to history
    """
    user_message = state.get("user_message")
    conversation_id = state.get("conversation_id", "unknown")

    if not user_message:
        logger.warning(
            f"process_incoming_message called without user_message",
            extra={"conversation_id": conversation_id}
        )
        return {}

    logger.info(
        f"Processing incoming message for conversation {conversation_id}",
        extra={
            "conversation_id": conversation_id,
            "message_preview": user_message[:50],
            "existing_messages_count": len(state.get("messages", []))
        }
    )

    # Add user message to conversation history
    updated_state = add_message(state, "user", user_message)

    # Clear user_message field after processing
    updated_state["user_message"] = None

    return updated_state


def create_conversation_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph[ConversationState, Any, Any, Any]:
    """
    Create and compile the conversation StateGraph with v3.0 tool-based architecture.

    This function builds the minimalist LangGraph StateGraph that orchestrates
    the single-node conversation flow:

    **Architecture:**
    - Entry: process_incoming_message (adds user message to history)
    - Main: conversational_agent (Claude + 7 tools handles everything)
    - Exit: END (wait for next user message)

    **Routing:**
    - Entry → (check summarization) → conversational_agent → END

    No booking nodes, no transactional flow. Claude + tools handle all logic:
    - query_info: FAQs, business hours, services, policies
    - manage_customer / get_customer_history: Customer identification
    - check_availability: Calendar checking with natural dates
    - book: Atomic booking via BookingTransaction handler
    - offer_consultation_tool: Free consultation for indecisive customers
    - escalate_to_human: Human escalation

    Args:
        checkpointer: Optional checkpoint saver for state persistence.
                     If None, no checkpointing is performed (useful for testing).
                     For production, pass a RedisSaver instance.

    Returns:
        Compiled StateGraph ready for invocation

    Example:
        >>> from agent.state.checkpointer import get_redis_checkpointer
        >>> checkpointer = get_redis_checkpointer()
        >>> graph = create_conversation_graph(checkpointer=checkpointer)
        >>> config = {"configurable": {"thread_id": "wa-msg-123"}}
        >>> result = await graph.ainvoke(initial_state, config=config)
    """
    # Initialize StateGraph with ConversationState schema
    graph = StateGraph(ConversationState)

    # ========================================================================
    # Nodes
    # ========================================================================
    graph.add_node("process_incoming_message", process_incoming_message)
    graph.add_node("conversational_agent", conversational_agent)
    graph.add_node("summarize", summarize_conversation)

    # ========================================================================
    # Entry Point Routing
    # ========================================================================
    def route_entry(state: ConversationState) -> str:
        """
        Route from process_incoming_message to next node.

        Simple logic:
        1. Check if summarization needed → summarize
        2. Otherwise → conversational_agent

        No transactional state checks, no booking phases. Just conversation.
        """
        # Check if summarization is needed before continuing
        if should_summarize(state):
            logger.info(
                "Message limit reached, summarizing conversation",
                extra={
                    "conversation_id": state.get("conversation_id"),
                    "message_count": len(state.get("messages", []))
                }
            )
            return "summarize"

        # Default: Route to conversational agent
        return "conversational_agent"

    # Set process_incoming_message as entry point
    graph.set_entry_point("process_incoming_message")

    # Route from process_incoming_message
    graph.add_conditional_edges(
        "process_incoming_message",
        route_entry,
        {
            "conversational_agent": "conversational_agent",
            "summarize": "summarize",
        }
    )

    # ========================================================================
    # Conversational Agent Routing
    # ========================================================================
    def route_after_conversational_agent(state: ConversationState) -> str:
        """
        Route after conversational agent completes.

        In v3.0, conversational_agent handles everything via tools.
        Always end after agent responds - no transactional nodes.

        The only exception is escalation, but that's handled by setting
        escalation_triggered=True in state, not by routing to another node.
        """
        # Check if escalation was triggered
        if state.get("escalation_triggered"):
            logger.info(
                "Conversation escalated to human team",
                extra={
                    "conversation_id": state.get("conversation_id"),
                    "reason": state.get("escalation_reason")
                }
            )

        # Always end - wait for next user message
        return "end"

    graph.add_conditional_edges(
        "conversational_agent",
        route_after_conversational_agent,
        {
            "end": END,
        }
    )

    # ========================================================================
    # Summarization Routing
    # ========================================================================
    def route_after_summarization(state: ConversationState) -> str:
        """Route after summarization completes, continuing to conversational agent."""
        return "conversational_agent"

    graph.add_conditional_edges(
        "summarize",
        route_after_summarization,
        {
            "conversational_agent": "conversational_agent",
        }
    )

    # ========================================================================
    # Compile Graph
    # ========================================================================
    logger.info("Compiling v3.0 conversation graph (1 node: conversational_agent)")

    compiled_graph = graph.compile(checkpointer=checkpointer)

    logger.info("v3.0 conversation graph compiled successfully")

    return compiled_graph

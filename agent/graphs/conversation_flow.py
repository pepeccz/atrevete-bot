"""
LangGraph StateGraph for conversation flow orchestration.

This module defines the main StateGraph that orchestrates the conversational
agent workflow. In Story 1.5, this is a minimal echo bot that greets customers.
Future stories will expand this graph with additional nodes for customer
identification, booking, payment, etc.
"""

import logging
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.nodes.greeting import greet_customer
from agent.state.schemas import ConversationState

# Configure logger
logger = logging.getLogger(__name__)


def create_conversation_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph[ConversationState, Any, Any, Any]:
    """
    Create and compile the conversation StateGraph.

    This function builds the LangGraph StateGraph that orchestrates the
    conversation flow. In Story 1.5, the graph has a single node (greet_customer)
    that sends a greeting and ends. Future stories will add more nodes and
    conditional routing.

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

    # Add nodes
    graph.add_node("greet_customer", greet_customer)

    # Set entry point
    graph.set_entry_point("greet_customer")

    # Add edges
    graph.add_edge("greet_customer", END)

    # Compile graph with optional checkpointer
    compiled_graph = graph.compile(checkpointer=checkpointer)

    logger.info(
        f"Conversation graph compiled with checkpointer={'enabled' if checkpointer else 'disabled'}"
    )

    return compiled_graph

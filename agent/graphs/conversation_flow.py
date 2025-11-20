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
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import select

from agent.nodes.conversational_agent import conversational_agent
from agent.nodes.summarization import summarize_conversation
from agent.prompts import load_maite_system_prompt
from agent.state.schemas import ConversationState
from agent.state.helpers import add_message, should_summarize
from database.connection import get_async_session
from database.models import Customer

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


async def ensure_customer_exists(phone: str, whatsapp_name: str) -> UUID:
    """
    Ensure customer exists in database. Create if not found using WhatsApp name.

    This function is called at the start of every conversation to guarantee that
    the customer record exists before any booking flow begins. It uses the WhatsApp
    display name for initial customer creation and can be updated later by the agent.

    Args:
        phone: Customer phone number in E.164 format (e.g., +34623226544)
        whatsapp_name: Display name from WhatsApp (fallback: "Cliente")

    Returns:
        UUID: Customer ID (existing or newly created)

    Example:
        >>> customer_id = await ensure_customer_exists("+34612345678", "Pepe Cabeza")
        >>> # Returns existing customer_id or creates new customer with name "Pepe" "Cabeza"
    """
    async with get_async_session() as session:
        try:
            # Step 1: Check if customer exists by phone
            stmt = select(Customer).where(Customer.phone == phone)
            result = await session.execute(stmt)
            existing_customer = result.scalar_one_or_none()

            if existing_customer:
                logger.debug(
                    f"Customer already exists for phone {phone}",
                    extra={"customer_id": str(existing_customer.id), "phone": phone}
                )
                return existing_customer.id

            # Step 2: Customer doesn't exist - create new one
            # Parse WhatsApp name into first_name and last_name
            name_parts = whatsapp_name.strip().split(maxsplit=1)
            first_name = name_parts[0] if name_parts else "Cliente"
            last_name = name_parts[1] if len(name_parts) > 1 else None

            logger.info(
                f"Creating new customer for phone {phone}",
                extra={
                    "phone": phone,
                    "first_name": first_name,
                    "last_name": last_name,
                    "whatsapp_name": whatsapp_name
                }
            )

            # Step 3: Create new customer
            new_customer = Customer(
                phone=phone,
                first_name=first_name,
                last_name=last_name
            )

            session.add(new_customer)
            await session.commit()
            await session.refresh(new_customer)

            logger.info(
                f"Customer created successfully",
                extra={
                    "customer_id": str(new_customer.id),
                    "phone": phone,
                    "first_name": first_name
                }
            )

            return new_customer.id

        except Exception as e:
            logger.error(
                f"Error ensuring customer exists for phone {phone}: {e}",
                exc_info=True
            )
            await session.rollback()
            raise


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

    # Ensure customer exists in database (auto-create if first interaction)
    customer_phone = state.get("customer_phone")
    if customer_phone and not state.get("customer_id"):
        # Extract WhatsApp name from state (set by agent/main.py from Chatwoot webhook)
        whatsapp_name = state.get("customer_name", "Cliente")

        try:
            customer_id = await ensure_customer_exists(customer_phone, whatsapp_name)
            updated_state["customer_id"] = customer_id
            logger.info(
                f"Customer ensured for conversation {conversation_id}",
                extra={
                    "customer_id": str(customer_id),
                    "phone": customer_phone,
                    "whatsapp_name": whatsapp_name
                }
            )
        except Exception as e:
            logger.error(
                f"Failed to ensure customer exists for {customer_phone}: {e}",
                extra={"conversation_id": conversation_id}
            )
            # Continue processing - don't block the conversation

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
    - query_info: FAQs, business hours, services, policies (includes consultation info)
    - manage_customer / get_customer_history: Customer identification
    - check_availability / find_next_available: Calendar checking with natural dates
    - book: Atomic booking via BookingTransaction handler
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

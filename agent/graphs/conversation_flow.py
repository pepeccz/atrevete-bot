"""
LangGraph StateGraph for conversation flow orchestration - Hybrid Architecture.

This module defines the simplified StateGraph that orchestrates the hybrid
architecture with two tiers:
- Tier 1: Conversational agent (Claude + tools) handles FAQs, inquiries, identification
- Tier 2: Transactional nodes handle booking, payment, availability

Simplified from 25 nodes to 12 nodes by consolidating conversational logic
into the conversational_agent node powered by Claude.
"""

import logging
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.nodes.conversational_agent import conversational_agent
from agent.nodes.summarization import summarize_conversation
from agent.nodes.availability_nodes import check_availability
from agent.nodes.pack_suggestion_nodes import suggest_pack, handle_pack_response
from agent.nodes.booking_nodes import validate_booking_request, handle_category_choice
from agent.prompts import load_maite_system_prompt
from agent.state.schemas import ConversationState
from agent.state.helpers import should_summarize

# Configure logger
logger = logging.getLogger(__name__)

# Lazy-loaded system prompt cache (loaded on first graph creation, not at module import)
_MAITE_SYSTEM_PROMPT_CACHE: str | None = None


def get_maite_system_prompt() -> str:
    """
    Get Maite system prompt with lazy-loading and caching.

    This function loads the prompt on first call and caches it for subsequent calls,
    avoiding module-level I/O that could block async initialization.

    Returns:
        str: The Maite system prompt content
    """
    global _MAITE_SYSTEM_PROMPT_CACHE

    if _MAITE_SYSTEM_PROMPT_CACHE is None:
        _MAITE_SYSTEM_PROMPT_CACHE = load_maite_system_prompt()
        logger.info(f"Maite system prompt loaded ({len(_MAITE_SYSTEM_PROMPT_CACHE)} characters)")

    return _MAITE_SYSTEM_PROMPT_CACHE


# For backward compatibility, export as MAITE_SYSTEM_PROMPT (but it's now a function)
MAITE_SYSTEM_PROMPT = get_maite_system_prompt


# ============================================================================
# Placeholder Nodes for Future Stories
# ============================================================================


async def booking_handler(state: ConversationState) -> dict[str, Any]:
    """
    Placeholder node for booking flow (Epic 3).

    For Story 3.4: If requested_services exist, proceed to pack suggestion.
    Otherwise, show placeholder message.
    """
    from langchain_core.messages import AIMessage

    messages = list(state.get("messages", []))

    # Check if services have been extracted (for Story 3.4 testing)
    requested_services = state.get("requested_services", [])

    if not requested_services:
        # No services extracted yet - show placeholder
        messages.append(AIMessage(content="Entiendo que quieres hacer una reserva. Pronto podré ayudarte con esto. 😊"))
        logger.info(f"booking_handler placeholder called (no services)", extra={"conversation_id": state.get("conversation_id")})
    else:
        # Services extracted - proceed to pack suggestion
        logger.info(f"booking_handler: services extracted, proceeding to pack suggestion", extra={"conversation_id": state.get("conversation_id")})

    return {"messages": messages}


async def modification_handler(state: ConversationState) -> dict[str, Any]:
    """Placeholder node for modification flow (Epic 5)."""
    from langchain_core.messages import AIMessage

    messages = list(state.get("messages", []))
    messages.append(AIMessage(content="Entiendo que quieres modificar una cita. Pronto podré ayudarte con esto. 😊"))

    logger.info(f"modification_handler placeholder called", extra={"conversation_id": state.get("conversation_id")})
    return {"messages": messages}


async def cancellation_handler(state: ConversationState) -> dict[str, Any]:
    """Placeholder node for cancellation flow (Epic 5)."""
    from langchain_core.messages import AIMessage

    messages = list(state.get("messages", []))
    messages.append(AIMessage(content="Entiendo que quieres cancelar una cita. Pronto podré ayudarte con esto. 😊"))

    logger.info(f"cancellation_handler placeholder called", extra={"conversation_id": state.get("conversation_id")})
    return {"messages": messages}


async def usual_service_handler(state: ConversationState) -> dict[str, Any]:
    """Placeholder node for 'lo de siempre' handling (Epic 4)."""
    from langchain_core.messages import AIMessage

    messages = list(state.get("messages", []))
    messages.append(AIMessage(content="Entiendo que quieres tu servicio habitual. Pronto podré ayudarte con esto. 😊"))

    logger.info(f"usual_service_handler placeholder called", extra={"conversation_id": state.get("conversation_id")})
    return {"messages": messages}


async def clarification_handler(state: ConversationState) -> dict[str, Any]:
    """Placeholder node for clarification handling."""
    from langchain_core.messages import AIMessage

    messages = list(state.get("messages", []))
    messages.append(AIMessage(content="¿Podrías darme más detalles sobre lo que necesitas? 😊"))

    logger.info(f"clarification_handler placeholder called", extra={"conversation_id": state.get("conversation_id")})
    return {"messages": messages}


def create_conversation_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph[ConversationState, Any, Any, Any]:
    """
    Create and compile the conversation StateGraph with hybrid architecture.

    This function builds the simplified LangGraph StateGraph that orchestrates
    the hybrid two-tier conversation flow:

    **Tier 1: Conversational Agent (Claude + tools)**
    - Handles: FAQs, greetings, identification, service inquiries, consultation
    - Node: conversational_agent
    - Sets: booking_intent_confirmed=True when customer ready to book

    **Tier 2: Transactional Nodes**
    - Handles: Booking, payment, availability checking
    - Nodes: booking_handler, check_availability, suggest_pack, validate_booking_request

    **Simplified Routing:**
    - Entry → conversational_agent (handles all conversational flow)
    - conversational_agent → booking_handler (if booking_intent_confirmed=True)
    - conversational_agent → END (if still in conversation/inquiry mode)

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
    # Tier 1: Conversational Agent (Claude + tools)
    # ========================================================================
    graph.add_node("conversational_agent", conversational_agent)

    # ========================================================================
    # Message Management
    # ========================================================================
    graph.add_node("summarize", summarize_conversation)

    # ========================================================================
    # Tier 2: Transactional Nodes
    # ========================================================================
    # Availability checking (Story 3.3)
    graph.add_node("check_availability", check_availability)

    # Pack suggestion (Story 3.4)
    graph.add_node("suggest_pack", suggest_pack)
    graph.add_node("handle_pack_response", handle_pack_response)

    # Service category validation (Story 3.6)
    graph.add_node("validate_booking_request", validate_booking_request)
    graph.add_node("handle_category_choice", handle_category_choice)

    # Booking flow placeholder (will be expanded in future stories)
    graph.add_node("booking_handler", booking_handler)

    # ========================================================================
    # Placeholder Nodes (Future Epics)
    # ========================================================================
    graph.add_node("modification_handler", modification_handler)
    graph.add_node("cancellation_handler", cancellation_handler)
    graph.add_node("usual_service_handler", usual_service_handler)
    graph.add_node("clarification_handler", clarification_handler)

    # ========================================================================
    # Entry Point Routing - Simplified
    # ========================================================================
    def route_entry(state: ConversationState) -> str:
        """
        Simplified entry routing for hybrid architecture.

        Routing logic:
        1. Check if awaiting Tier 2 transactional responses (pack, category choice)
        2. Check if summarization needed
        3. Otherwise → conversational_agent (handles all Tier 1 logic)

        This replaces the previous 6-way routing with a single conversational entry point.
        """
        # Check if awaiting category choice (Tier 2 transactional state)
        if state.get("awaiting_category_choice"):
            return "handle_category_choice"

        # Check if awaiting pack response (Tier 2 transactional state)
        suggested_pack = state.get("suggested_pack")
        pack_id = state.get("pack_id")
        pack_declined = state.get("pack_declined")

        if suggested_pack and not pack_id and not pack_declined:
            return "handle_pack_response"

        # Check if summarization is needed before continuing
        if should_summarize(state):
            return "summarize"

        # Default: Route to conversational agent (Tier 1)
        # This handles: greetings, FAQs, identification, service inquiries, consultation
        return "conversational_agent"

    graph.set_conditional_entry_point(
        route_entry,
        {
            "conversational_agent": "conversational_agent",
            "handle_category_choice": "handle_category_choice",
            "handle_pack_response": "handle_pack_response",
            "summarize": "summarize",
        }
    )

    # ========================================================================
    # Routing After Conversational Agent - Simplified
    # ========================================================================
    def route_after_conversational_agent(state: ConversationState) -> str:
        """
        Route after conversational agent based on booking intent.

        This is the critical Tier 1 → Tier 2 transition:
        - If booking_intent_confirmed=True → booking_handler (Tier 2)
        - Otherwise → END (continue conversation, wait for user)

        Replaces previous complex intent routing with single booking intent check.
        """
        booking_intent_confirmed = state.get("booking_intent_confirmed", False)

        if booking_intent_confirmed:
            logger.info(
                "Booking intent confirmed, transitioning to Tier 2 (booking flow)",
                extra={"conversation_id": state.get("conversation_id")}
            )
            return "booking_handler"
        else:
            # Still in conversational mode - end and wait for user response
            return "end"

    graph.add_conditional_edges(
        "conversational_agent",
        route_after_conversational_agent,
        {
            "booking_handler": "booking_handler",
            "end": END,
        }
    )

    # ========================================================================
    # Summarization Routing
    # ========================================================================
    def route_after_summarization(state: ConversationState) -> str:
        """Route after summarization completes, continuing to conversational agent."""
        # After summarization, return to conversational agent
        return "conversational_agent"

    graph.add_conditional_edges(
        "summarize",
        route_after_summarization,
        {
            "conversational_agent": "conversational_agent",
        }
    )

    # ========================================================================
    # Tier 2 Transactional Flow Routing
    # ========================================================================

    # Booking handler → suggest pack (after service extraction)
    def route_after_booking_handler(state: ConversationState) -> str:
        """
        Route after booking_handler based on service extraction.

        If requested_services exist, proceed to pack suggestion.
        Otherwise, end conversation (placeholder response shown).
        """
        requested_services = state.get("requested_services", [])
        if requested_services:
            return "suggest_pack"
        else:
            return "end"

    graph.add_conditional_edges(
        "booking_handler",
        route_after_booking_handler,
        {
            "suggest_pack": "suggest_pack",
            "end": END,
        }
    )

    # Pack suggestion → handle response or validation
    def route_after_pack_suggestion(state: ConversationState) -> str:
        """
        Route after pack suggestion based on whether pack was suggested.

        If pack suggested, wait for customer response.
        If no pack, proceed to service validation (Story 3.6) before availability.
        """
        suggested_pack = state.get("suggested_pack")
        if suggested_pack:
            # Pack suggested - wait for customer response (end here, next message will trigger handle_pack_response)
            return "end"
        else:
            # No pack - proceed to service validation (Story 3.6)
            return "validate_booking_request"

    graph.add_conditional_edges(
        "suggest_pack",
        route_after_pack_suggestion,
        {
            "validate_booking_request": "validate_booking_request",
            "end": END,
        }
    )

    # Pack response → validation
    def route_after_pack_response(state: ConversationState) -> str:
        """
        Route after customer responds to pack suggestion.

        If accepted or declined, proceed to service validation (Story 3.6).
        If unclear, end and wait for clarification response.
        """
        # Check if pack was accepted or declined
        pack_id = state.get("pack_id")
        pack_declined = state.get("pack_declined")

        if pack_id or pack_declined:
            # Decision made - proceed to service validation (Story 3.6)
            return "validate_booking_request"
        else:
            # Still unclear - end and wait for clarification response
            return "end"

    graph.add_conditional_edges(
        "handle_pack_response",
        route_after_pack_response,
        {
            "validate_booking_request": "validate_booking_request",
            "end": END,
        }
    )

    # Validation → availability or category choice
    def route_after_validation(state: ConversationState) -> str:
        """
        Route after service validation based on validation result.

        If validation passed, proceed to availability checking.
        If mixed categories detected, wait for customer choice.
        """
        booking_validation_passed = state.get("booking_validation_passed", False)
        mixed_category_detected = state.get("mixed_category_detected", False)

        if booking_validation_passed:
            # Validation passed - proceed to availability
            return "check_availability"
        elif mixed_category_detected:
            # Mixed categories - wait for customer choice (end here)
            return "end"
        else:
            # Error or other issue - end
            return "end"

    graph.add_conditional_edges(
        "validate_booking_request",
        route_after_validation,
        {
            "check_availability": "check_availability",
            "end": END,
        }
    )

    # Category choice → availability
    def route_after_category_choice(state: ConversationState) -> str:
        """
        Route after customer chooses category option.

        If choice made and validation passed, proceed to availability.
        Otherwise, end and wait for clarification.
        """
        booking_validation_passed = state.get("booking_validation_passed", False)

        if booking_validation_passed:
            # Choice made, proceed to availability
            return "check_availability"
        else:
            # Waiting for clarification
            return "end"

    graph.add_conditional_edges(
        "handle_category_choice",
        route_after_category_choice,
        {
            "check_availability": "check_availability",
            "end": END,
        }
    )

    # Availability check → end (wait for customer slot selection)
    def route_after_availability_check(state: ConversationState) -> str:
        """
        Route after availability check completes.

        If slots found or alternatives suggested, wait for customer selection.
        """
        # For now, just end after showing availability
        # Future stories will add customer selection and booking confirmation
        return "end"

    graph.add_conditional_edges(
        "check_availability",
        route_after_availability_check,
        {
            "end": END,
        }
    )

    # Placeholder handlers → end
    graph.add_edge("modification_handler", END)
    graph.add_edge("cancellation_handler", END)
    graph.add_edge("usual_service_handler", END)
    graph.add_edge("clarification_handler", END)

    # Compile graph with optional checkpointer
    compiled_graph = graph.compile(checkpointer=checkpointer)

    logger.info(
        f"Hybrid architecture graph compiled with {len(graph.nodes)} nodes "
        f"(checkpointer={'enabled' if checkpointer else 'disabled'})"
    )

    return compiled_graph

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
# Pack suggestion nodes removed - packs functionality eliminated
from agent.nodes.booking_nodes import validate_booking_request, handle_category_choice
from agent.nodes.appointment_nodes import (
    handle_slot_selection,
    collect_customer_data,
    create_provisional_booking,
    generate_payment_link,
)
from agent.prompts import load_maite_system_prompt
from agent.state.schemas import ConversationState
from agent.state.helpers import add_message, should_summarize

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

    If requested_services exist, proceed to validation.
    Otherwise, show placeholder message.
    """
    # Check if services have been extracted
    requested_services = state.get("requested_services", [])

    if not requested_services:
        # No services extracted yet - show placeholder
        updated_state = add_message(state, "assistant", "Entiendo que quieres hacer una reserva. Pronto podré ayudarte con esto. 😊")
        logger.info(f"booking_handler placeholder called (no services)", extra={"conversation_id": state.get("conversation_id")})
        return updated_state
    else:
        # Services extracted - proceed directly to validation
        logger.info(f"booking_handler: services extracted, proceeding to validation", extra={"conversation_id": state.get("conversation_id")})
        return {}


async def modification_handler(state: ConversationState) -> dict[str, Any]:
    """Placeholder node for modification flow (Epic 5)."""
    logger.info(f"modification_handler placeholder called", extra={"conversation_id": state.get("conversation_id")})
    return add_message(state, "assistant", "Entiendo que quieres modificar una cita. Pronto podré ayudarte con esto. 😊")


async def cancellation_handler(state: ConversationState) -> dict[str, Any]:
    """Placeholder node for cancellation flow (Epic 5)."""
    logger.info(f"cancellation_handler placeholder called", extra={"conversation_id": state.get("conversation_id")})
    return add_message(state, "assistant", "Entiendo que quieres cancelar una cita. Pronto podré ayudarte con esto. 😊")


async def usual_service_handler(state: ConversationState) -> dict[str, Any]:
    """Placeholder node for 'lo de siempre' handling (Epic 4)."""
    logger.info(f"usual_service_handler placeholder called", extra={"conversation_id": state.get("conversation_id")})
    return add_message(state, "assistant", "Entiendo que quieres tu servicio habitual. Pronto podré ayudarte con esto. 😊")


async def clarification_handler(state: ConversationState) -> dict[str, Any]:
    """Placeholder node for clarification handling."""
    logger.info(f"clarification_handler placeholder called", extra={"conversation_id": state.get("conversation_id")})
    return add_message(state, "assistant", "¿Podrías darme más detalles sobre lo que necesitas? 😊")


async def process_incoming_message(state: ConversationState) -> dict[str, Any]:
    """
    Process incoming user message and add it to conversation history.

    This node is the first to execute in the graph. It takes the user_message
    field (set by agent/main.py) and adds it to the messages history using
    add_message() helper, which handles FIFO windowing and preserves previous messages.

    This approach ensures that:
    1. The checkpoint is loaded first by LangGraph (preserving conversation history)
    2. The new user message is appended to existing history
    3. Memory is maintained across messages

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

    # Add user message to conversation history (preserves existing messages from checkpoint)
    updated_state = add_message(state, "user", user_message)

    # Clear user_message field after processing
    updated_state["user_message"] = None

    return updated_state


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
    - Nodes: booking_handler, check_availability, validate_booking_request

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
    # Message Processing Entry Point
    # ========================================================================
    graph.add_node("process_incoming_message", process_incoming_message)

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

    # Pack suggestion removed - packs functionality eliminated

    # Service category validation (Story 3.6)
    graph.add_node("validate_booking_request", validate_booking_request)
    graph.add_node("handle_category_choice", handle_category_choice)

    # Booking flow placeholder (will be expanded in future stories)
    graph.add_node("booking_handler", booking_handler)

    # Appointment booking flow nodes (Fase 2-4)
    graph.add_node("handle_slot_selection", handle_slot_selection)
    graph.add_node("collect_customer_data", collect_customer_data)
    graph.add_node("create_provisional_booking", create_provisional_booking)
    graph.add_node("generate_payment_link", generate_payment_link)

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
        1. Check if awaiting Tier 2 transactional responses (category choice)
        2. Check if summarization needed
        3. Otherwise → conversational_agent (handles all Tier 1 logic)

        This replaces the previous 6-way routing with a single conversational entry point.
        """
        # Check if awaiting category choice (Tier 2 transactional state)
        if state.get("awaiting_category_choice"):
            return "handle_category_choice"

        # Check if summarization is needed before continuing
        if should_summarize(state):
            return "summarize"

        # Default: Route to conversational agent (Tier 1)
        # This handles: greetings, FAQs, identification, service inquiries, consultation
        return "conversational_agent"

    # Set process_incoming_message as the entry point (always runs first)
    graph.set_entry_point("process_incoming_message")

    # Route from process_incoming_message to appropriate next node
    graph.add_conditional_edges(
        "process_incoming_message",
        route_entry,
        {
            "conversational_agent": "conversational_agent",
            "handle_category_choice": "handle_category_choice",
            "summarize": "summarize",
        }
    )

    # ========================================================================
    # Routing After Conversational Agent - Simplified
    # ========================================================================
    def route_after_conversational_agent(state: ConversationState) -> str:
        """
        Route after conversational agent based on booking intent and service clarity.

        This is the critical Tier 1 → Tier 2 transition with ambiguity handling:
        - If pending_service_clarification exists → END (stay in Tier 1 for user to clarify)
        - If booking_intent_confirmed=True AND requested_services populated → booking_handler (Tier 2)
        - Otherwise → END (continue conversation, wait for user)

        Safety checks:
        1. Block Tier 2 transition if service ambiguity pending
        2. Validate that requested_services is populated when booking intent is detected
        """
        booking_intent_confirmed = state.get("booking_intent_confirmed", False)
        requested_services = state.get("requested_services", [])
        pending_service_clarification = state.get("pending_service_clarification", None)

        # Priority 1: Check for pending service clarification
        if pending_service_clarification:
            logger.info(
                "Ambiguous service detected - staying in Tier 1 for customer to clarify",
                extra={
                    "conversation_id": state.get("conversation_id"),
                    "ambiguous_query": pending_service_clarification.get("query"),
                    "num_options": len(pending_service_clarification.get("options", []))
                }
            )
            # Stay in Tier 1 - Claude must clarify with customer first
            return "end"

        # Priority 2: Check booking intent with services
        if booking_intent_confirmed:
            # Validate that requested_services is populated
            if not requested_services:
                logger.warning(
                    "Booking intent confirmed but requested_services is empty! "
                    "Staying in Tier 1 to collect services.",
                    extra={
                        "conversation_id": state.get("conversation_id"),
                        "booking_intent_confirmed": booking_intent_confirmed,
                        "requested_services_count": len(requested_services)
                    }
                )
                # Stay in Tier 1 - something went wrong with service resolution
                return "end"

            logger.info(
                "Booking intent confirmed with services, transitioning to Tier 2 (booking flow)",
                extra={
                    "conversation_id": state.get("conversation_id"),
                    "requested_services_count": len(requested_services)
                }
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

    # Booking handler → validation (after service extraction)
    def route_after_booking_handler(state: ConversationState) -> str:
        """
        Route after booking_handler based on service extraction.

        If requested_services exist, proceed directly to validation (packs removed).
        Otherwise, end conversation (placeholder response shown).
        """
        requested_services = state.get("requested_services", [])
        if requested_services:
            return "validate_booking_request"
        else:
            return "end"

    graph.add_conditional_edges(
        "booking_handler",
        route_after_booking_handler,
        {
            "validate_booking_request": "validate_booking_request",
            "end": END,
        }
    )

    # Pack suggestion and response routing removed - packs functionality eliminated

    # Validation → availability or category choice
    def route_after_validation(state: ConversationState) -> str:
        """
        Route after service validation based on validation result.

        If validation passed and date available, proceed to availability checking.
        If validation passed but awaiting date, end and wait for customer response.
        If mixed categories detected, wait for customer choice.
        """
        booking_validation_passed = state.get("booking_validation_passed", False)
        mixed_category_detected = state.get("mixed_category_detected", False)
        awaiting_date_input = state.get("awaiting_date_input", False)

        if booking_validation_passed and awaiting_date_input:
            # Validation passed but waiting for date - end and wait for customer response
            logger.info(
                "Validation passed but awaiting date input - ending to wait for customer",
                extra={"conversation_id": state.get("conversation_id")}
            )
            return "end"
        elif booking_validation_passed:
            # Validation passed and date available - proceed to availability
            logger.info(
                "Validation passed with date - proceeding to availability check",
                extra={"conversation_id": state.get("conversation_id")}
            )
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

    # Availability check → slot selection or end
    def route_after_availability_check(state: ConversationState) -> str:
        """
        Route after availability check completes.

        If slots found, proceed to slot selection.
        Otherwise END (alternatives suggested or error occurred).
        """
        available_slots = state.get("available_slots", [])

        if available_slots:
            # Slots found, proceed to slot selection
            logger.info(
                f"Routing to handle_slot_selection | "
                f"slots_count={len(available_slots)} | "
                f"conversation_id={state.get('conversation_id')}"
            )
            return "handle_slot_selection"
        else:
            # No slots found (alternatives suggested or error)
            logger.info(
                f"No available slots, ending conversation | "
                f"conversation_id={state.get('conversation_id')}"
            )
            return "end"

    graph.add_conditional_edges(
        "check_availability",
        route_after_availability_check,
        {
            "handle_slot_selection": "handle_slot_selection",
            "end": END,
        }
    )

    # Placeholder handlers → end
    graph.add_edge("modification_handler", END)
    graph.add_edge("cancellation_handler", END)
    graph.add_edge("usual_service_handler", END)
    graph.add_edge("clarification_handler", END)

    # ========================================================================
    # Booking Flow Routing (Fase 2-4)
    # ========================================================================

    # Slot selection → customer data collection or error
    def route_after_slot_selection(state: ConversationState) -> str:
        """
        Route after customer selects a slot.

        If slot selected successfully, proceed to customer data collection.
        If error or ambiguity, return to conversational agent for clarification.
        """
        booking_phase = state.get("booking_phase")
        selected_slot = state.get("selected_slot")

        if booking_phase == "customer_data" and selected_slot:
            # Slot selected successfully
            logger.info(
                f"Routing to collect_customer_data | "
                f"conversation_id={state.get('conversation_id')}"
            )
            return "collect_customer_data"
        else:
            # Error or needs clarification
            logger.info(
                f"Slot selection needs clarification, returning to conversational_agent | "
                f"conversation_id={state.get('conversation_id')}"
            )
            return "conversational_agent"

    graph.add_conditional_edges(
        "handle_slot_selection",
        route_after_slot_selection,
        {
            "collect_customer_data": "collect_customer_data",
            "conversational_agent": "conversational_agent",
        }
    )

    # Customer data collection → provisional booking or loop
    def route_after_customer_data(state: ConversationState) -> str:
        """
        Route after collecting customer data.

        If all data collected, proceed to provisional booking.
        If needs more data, loop back to collect_customer_data.
        """
        booking_phase = state.get("booking_phase")
        customer_name = state.get("customer_name")

        if booking_phase == "payment" and customer_name:
            # All data collected, proceed to booking
            logger.info(
                f"Routing to create_provisional_booking | "
                f"conversation_id={state.get('conversation_id')}"
            )
            return "create_provisional_booking"
        else:
            # Still collecting data
            logger.info(
                f"Still collecting customer data | "
                f"conversation_id={state.get('conversation_id')}"
            )
            return "collect_customer_data"

    graph.add_conditional_edges(
        "collect_customer_data",
        route_after_customer_data,
        {
            "create_provisional_booking": "create_provisional_booking",
            "collect_customer_data": "collect_customer_data",
        }
    )

    # Provisional booking → payment link or retry availability
    def route_after_provisional_booking(state: ConversationState) -> str:
        """
        Route after creating provisional booking.

        If booking created successfully, proceed to payment link generation.
        If conflict (buffer validation failed), return to availability check.
        """
        provisional_appointment_id = state.get("provisional_appointment_id")
        error_count = state.get("error_count", 0)

        if provisional_appointment_id:
            # Booking created successfully
            logger.info(
                f"Routing to generate_payment_link | "
                f"appointment_id={provisional_appointment_id} | "
                f"conversation_id={state.get('conversation_id')}"
            )
            return "generate_payment_link"
        elif error_count > 0:
            # Buffer conflict or error, retry availability
            logger.warning(
                f"Provisional booking failed, retrying availability | "
                f"conversation_id={state.get('conversation_id')}"
            )
            return "check_availability"
        else:
            # Unexpected state, end
            return "end"

    graph.add_conditional_edges(
        "create_provisional_booking",
        route_after_provisional_booking,
        {
            "generate_payment_link": "generate_payment_link",
            "check_availability": "check_availability",
            "end": END,
        }
    )

    # Payment link generation → END (wait for async webhook)
    graph.add_edge("generate_payment_link", END)

    # Compile graph with optional checkpointer
    compiled_graph = graph.compile(checkpointer=checkpointer)

    logger.info(
        f"Hybrid architecture graph compiled with {len(graph.nodes)} nodes "
        f"(checkpointer={'enabled' if checkpointer else 'disabled'})"
    )

    return compiled_graph

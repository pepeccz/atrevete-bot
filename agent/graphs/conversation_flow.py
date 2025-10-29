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
from agent.nodes.identification import confirm_name, greet_new_customer, greet_returning_customer, identify_customer
from agent.nodes.classification import (
    extract_intent,
    detect_indecision,
    offer_consultation,
    handle_consultation_response,
)
from agent.nodes.summarization import summarize_conversation
from agent.nodes.faq import answer_faq, detect_faq_intent
from agent.nodes.faq_generation import fetch_faq_context, generate_personalized_faq_response
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


async def faq_handler(state: ConversationState) -> dict[str, Any]:
    """Placeholder node for FAQ/inquiry handling (Epic 6)."""
    from langchain_core.messages import AIMessage

    messages = list(state.get("messages", []))
    messages.append(AIMessage(content="Entiendo que tienes una consulta. Pronto podré ayudarte con esto. 😊"))

    logger.info(f"faq_handler placeholder called", extra={"conversation_id": state.get("conversation_id")})
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

    # Add identification and greeting nodes
    graph.add_node("greet_customer", greet_customer)
    graph.add_node("identify_customer", identify_customer)
    graph.add_node("greet_new_customer", greet_new_customer)
    graph.add_node("confirm_name", confirm_name)

    # Add returning customer nodes (Story 2.3)
    graph.add_node("extract_intent", extract_intent)
    graph.add_node("greet_returning_customer", greet_returning_customer)

    # Add FAQ nodes (Story 2.6, enhanced with AI generation)
    graph.add_node("detect_faq_intent", detect_faq_intent)
    graph.add_node("answer_faq", answer_faq)
    graph.add_node("fetch_faq_context", fetch_faq_context)
    graph.add_node("generate_faq_response", generate_personalized_faq_response)

    # Add summarization node (Story 2.5b)
    graph.add_node("summarize", summarize_conversation)

    # Add availability checking node (Story 3.3)
    graph.add_node("check_availability", check_availability)

    # Add pack suggestion nodes (Story 3.4)
    graph.add_node("suggest_pack", suggest_pack)
    graph.add_node("handle_pack_response", handle_pack_response)

    # Add indecision detection & consultation nodes (Story 3.5)
    graph.add_node("detect_indecision", detect_indecision)
    graph.add_node("offer_consultation", offer_consultation)
    graph.add_node("handle_consultation_response", handle_consultation_response)

    # Add service category validation nodes (Story 3.6)
    graph.add_node("validate_booking_request", validate_booking_request)
    graph.add_node("handle_category_choice", handle_category_choice)

    # Add placeholder handler nodes (Story 2.3)
    graph.add_node("booking_handler", booking_handler)
    graph.add_node("modification_handler", modification_handler)
    graph.add_node("cancellation_handler", cancellation_handler)
    graph.add_node("faq_handler", faq_handler)
    graph.add_node("usual_service_handler", usual_service_handler)
    graph.add_node("clarification_handler", clarification_handler)

    # Conditional entry point based on conversation state
    def route_entry(state: ConversationState) -> str:
        """
        Route entry based on conversation state and history.

        Determines the appropriate entry point:
        - First message in conversation → greet_customer
        - Awaiting name confirmation → confirm_name
        - Awaiting consultation response → handle_consultation_response
        - Awaiting pack response → handle_pack_response
        - Awaiting category choice → handle_category_choice
        - Continuing conversation → detect_faq_intent (skip greeting)
        """
        # Check if awaiting name confirmation from new customer
        if state.get("awaiting_name_confirmation") and not state.get("customer_identified"):
            return "confirm_name"

        # Check if awaiting category choice (Story 3.6)
        # If mixed category detected and awaiting customer's choice
        if state.get("awaiting_category_choice"):
            return "handle_category_choice"

        # Check if awaiting consultation response (Story 3.5)
        # If consultation offered but not yet accepted/declined, handle response
        consultation_offered = state.get("consultation_offered")
        consultation_accepted = state.get("consultation_accepted")
        consultation_declined = state.get("consultation_declined")

        if consultation_offered and not consultation_accepted and not consultation_declined:
            return "handle_consultation_response"

        # Check if awaiting pack response (Story 3.4)
        # If pack was suggested but not yet accepted/declined, handle response
        suggested_pack = state.get("suggested_pack")
        pack_id = state.get("pack_id")
        pack_declined = state.get("pack_declined")

        if suggested_pack and not pack_id and not pack_declined:
            return "handle_pack_response"

        # Check if this is a continuation of existing conversation
        # If there are already messages (excluding system prompt), skip greeting
        messages = state.get("messages", [])
        # Filter out system messages to count only user/assistant messages
        conversation_messages = [
            msg for msg in messages
            if hasattr(msg, 'type') and msg.type in ['human', 'ai']
        ]

        # If conversation has already started (has messages), skip greeting
        if len(conversation_messages) > 0:
            return "detect_faq_intent"

        # First message - start with greeting flow
        return "greet_customer"

    graph.set_conditional_entry_point(
        route_entry,
        {
            "greet_customer": "greet_customer",
            "confirm_name": "confirm_name",
            "handle_category_choice": "handle_category_choice",
            "handle_consultation_response": "handle_consultation_response",
            "handle_pack_response": "handle_pack_response",
            "detect_faq_intent": "detect_faq_intent",
        }
    )

    # Add edges from greet_customer to identify_customer
    graph.add_edge("greet_customer", "identify_customer")

    # Conditional routing after customer identification
    def route_after_identification(state: ConversationState) -> str:
        """Route based on whether customer is returning or new, with optional summarization."""
        # Check if summarization is needed first
        if should_summarize(state):
            return "summarize"

        # Normal routing based on customer status
        if state.get("is_returning_customer"):
            # Story 2.6: Route returning customers to FAQ detection first (before intent extraction)
            return "detect_faq_intent"
        else:
            return "greet_new_customer"

    graph.add_conditional_edges(
        "identify_customer",
        route_after_identification,
        {
            "summarize": "summarize",
            "greet_new_customer": "greet_new_customer",
            "detect_faq_intent": "detect_faq_intent",
        }
    )

    # Conditional routing after greeting new customer
    def route_after_new_customer_greeting(state: ConversationState) -> str:
        """Route after greeting new customer - wait for user response or confirm name."""
        # If awaiting name confirmation, end and wait for user message
        if state.get("awaiting_name_confirmation"):
            return "end"
        # If customer already identified (shouldn't happen), end
        elif state.get("customer_identified"):
            return "end"
        else:
            # Fallback: end conversation
            return "end"

    graph.add_conditional_edges(
        "greet_new_customer",
        route_after_new_customer_greeting,
        {
            "end": END,
        }
    )

    # Conditional routing after FAQ detection (Story 2.6, enhanced with hybrid approach)
    def route_after_faq_detection(state: ConversationState) -> str:
        """
        Route based on FAQ detection and query complexity.

        Hybrid approach:
        - Simple single-FAQ queries → static answer_faq (fast)
        - Compound multi-FAQ queries → AI generation (smart)
        - No FAQ → proceed to intent extraction
        """
        if not state.get("faq_detected"):
            # No FAQ detected - proceed to intent extraction
            return "extract_intent"

        # FAQ detected - determine routing based on complexity
        complexity = state.get("query_complexity", "simple")
        detected_faq_ids = state.get("detected_faq_ids", [])

        # Simple single FAQ → use fast static response
        if complexity == "simple" and len(detected_faq_ids) == 1:
            logger.debug(
                f"Routing to static FAQ answer (simple query)",
                extra={"conversation_id": state.get("conversation_id"), "faq_id": detected_faq_ids[0]}
            )
            return "answer_faq"

        # Compound or multiple FAQs → use AI generation
        elif complexity == "compound" or len(detected_faq_ids) > 1:
            logger.debug(
                f"Routing to AI FAQ generation (compound query)",
                extra={"conversation_id": state.get("conversation_id"), "faq_ids": detected_faq_ids}
            )
            return "fetch_faq_context"

        # Fallback to static response
        else:
            logger.debug(
                f"Routing to static FAQ answer (fallback)",
                extra={"conversation_id": state.get("conversation_id")}
            )
            return "answer_faq"

    graph.add_conditional_edges(
        "detect_faq_intent",
        route_after_faq_detection,
        {
            "answer_faq": "answer_faq",
            "fetch_faq_context": "fetch_faq_context",
            "extract_intent": "extract_intent",
        }
    )

    # After fetching FAQ context, generate AI response
    graph.add_edge("fetch_faq_context", "generate_faq_response")

    # FAQ answered (both static and AI) - end conversation
    graph.add_edge("answer_faq", END)
    graph.add_edge("generate_faq_response", END)

    # Route from summarization node back to main flow (Story 2.5b)
    def route_after_summarization(state: ConversationState) -> str:
        """Route after summarization completes, continuing normal flow."""
        # After summarization, continue with normal routing logic
        if state.get("is_returning_customer"):
            return "detect_faq_intent"
        else:
            return "greet_new_customer"

    graph.add_conditional_edges(
        "summarize",
        route_after_summarization,
        {
            "detect_faq_intent": "detect_faq_intent",
            "greet_new_customer": "greet_new_customer",
        }
    )

    # Conditional routing by intent (Story 2.3)
    def route_by_intent(state: ConversationState) -> str:
        """Route to appropriate handler based on extracted intent."""
        intent = state.get("current_intent")

        routing_map = {
            "booking": "booking_handler",
            "modification": "modification_handler",
            "cancellation": "cancellation_handler",
            "inquiry": "faq_handler",
            "faq": "faq_handler",
            "usual_service": "usual_service_handler",
            "greeting_only": "greet_returning_customer",
        }

        return routing_map.get(intent, "clarification_handler")

    graph.add_conditional_edges(
        "extract_intent",
        route_by_intent,
        {
            "booking_handler": "booking_handler",
            "modification_handler": "modification_handler",
            "cancellation_handler": "cancellation_handler",
            "faq_handler": "faq_handler",
            "usual_service_handler": "usual_service_handler",
            "greet_returning_customer": "greet_returning_customer",
            "clarification_handler": "clarification_handler",
        }
    )

    # Routing after check_availability (Story 3.3)
    def route_after_availability_check(state: ConversationState) -> str:
        """
        Route after availability check completes.

        If slots found or alternatives suggested, wait for customer selection.
        If error occurred, end conversation (customer will retry).
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

    # Conditional routing from booking_handler (Story 3.4, extended for Story 3.5)
    def route_after_booking_handler(state: ConversationState) -> str:
        """
        Route after booking_handler based on service extraction.

        If requested_services exist:
        - Check for indecision first (Story 3.5)
        - If no indecision, proceed to pack suggestion
        Otherwise, end conversation (placeholder response shown).
        """
        requested_services = state.get("requested_services", [])
        if requested_services:
            # First check for indecision (Story 3.5)
            return "detect_indecision"
        else:
            return "end"

    graph.add_conditional_edges(
        "booking_handler",
        route_after_booking_handler,
        {
            "detect_indecision": "detect_indecision",
            "end": END,
        }
    )

    # Conditional routing after indecision detection (Story 3.5)
    def route_after_indecision_detection(state: ConversationState) -> str:
        """
        Route after indecision detection based on confidence level.

        If indecision detected (confidence > 0.7) → offer_consultation
        Otherwise → suggest_pack (continue normal booking flow)
        """
        indecision_detected = state.get("indecision_detected", False)
        confidence = state.get("confidence", 0.0)

        if indecision_detected and confidence > 0.7:
            return "offer_consultation"
        else:
            return "suggest_pack"

    graph.add_conditional_edges(
        "detect_indecision",
        route_after_indecision_detection,
        {
            "offer_consultation": "offer_consultation",
            "suggest_pack": "suggest_pack",
        }
    )

    # After offering consultation, wait for customer response (end)
    graph.add_edge("offer_consultation", END)

    # Conditional routing after consultation response (Story 3.5)
    def route_after_consultation_response(state: ConversationState) -> str:
        """
        Route after customer responds to consultation offer.

        If accepted → proceed to availability checking
        If declined → return to service selection (suggest_pack)
        If unclear (awaiting clarification) → end and wait
        """
        consultation_accepted = state.get("consultation_accepted", False)
        consultation_declined = state.get("consultation_declined", False)

        if consultation_accepted:
            # Proceed to availability checking for consultation booking
            return "check_availability"
        elif consultation_declined:
            # Return to normal booking flow
            return "suggest_pack"
        else:
            # Unclear response, waiting for clarification
            return "end"

    graph.add_conditional_edges(
        "handle_consultation_response",
        route_after_consultation_response,
        {
            "check_availability": "check_availability",
            "suggest_pack": "suggest_pack",
            "end": END,
        }
    )

    # Conditional routing from suggest_pack (Story 3.4, updated for Story 3.6)
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

    # Conditional routing from handle_pack_response (Story 3.4, updated for Story 3.6)
    def route_after_pack_response(state: ConversationState) -> str:
        """
        Route after customer responds to pack suggestion.

        If accepted or declined, proceed to service validation (Story 3.6).
        If unclear and needs clarification, end and wait for response.
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

    # Conditional routing after validation (Story 3.6)
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

    # Conditional routing after category choice (Story 3.6)
    def route_after_category_choice(state: ConversationState) -> str:
        """
        Route after customer chooses category option.

        If choice made and validation passed, proceed to availability.
        If escalated, end conversation.
        Otherwise, end and wait for clarification.
        """
        booking_validation_passed = state.get("booking_validation_passed", False)
        escalated = state.get("escalated", False)

        if escalated:
            # Escalated due to unclear responses
            return "end"
        elif booking_validation_passed:
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

    graph.add_edge("modification_handler", END)
    graph.add_edge("cancellation_handler", END)
    graph.add_edge("faq_handler", END)
    graph.add_edge("usual_service_handler", END)
    graph.add_edge("clarification_handler", END)
    graph.add_edge("greet_returning_customer", END)

    # Conditional routing after name confirmation
    def route_after_name_confirmation(state: ConversationState) -> str:
        """Route based on confirmation status."""
        if state.get("customer_identified"):
            # TODO: Route to intent extraction (future story)
            return "end"
        elif state.get("escalated"):
            # TODO: Route to escalation handler (future story)
            return "end"
        elif state.get("awaiting_name_confirmation"):
            # Still waiting for user response, end here
            return "end"
        else:
            # Loop back for retry only if there was a clarification attempt
            # This prevents infinite loops when there are no user messages
            if state.get("clarification_attempts", 0) > 0:
                return "end"  # Don't loop if we already tried clarifying
            return "confirm_name"

    graph.add_conditional_edges(
        "confirm_name",
        route_after_name_confirmation,
        {
            "confirm_name": "confirm_name",
            "end": END,
        }
    )

    # Compile graph with optional checkpointer
    compiled_graph = graph.compile(checkpointer=checkpointer)

    logger.info(
        f"Conversation graph compiled with checkpointer={'enabled' if checkpointer else 'disabled'}"
    )

    return compiled_graph

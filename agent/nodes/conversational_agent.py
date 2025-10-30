"""
Conversational Agent Node - Tier 1 Architecture.

This is the primary conversational node that handles all informational conversations
using Claude LLM with tool access. Part of the hybrid architecture simplification.

Handles:
- FAQs, greetings, service inquiries
- Indecision detection and consultation offering
- Pack suggestions
- Availability checking (informational only)
- Customer identification and creation

Transitions to Tier 2 (transactional flow) when:
- booking_intent_confirmed=True (customer ready to book)
"""

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.prompts import load_maite_system_prompt
from agent.state.schemas import ConversationState
from agent.tools.availability_tools import check_availability_tool
from agent.tools.booking_tools import get_services
from agent.tools.consultation_tools import offer_consultation_tool
from agent.tools.customer_tools import create_customer, get_customer_by_phone
from agent.tools.escalation_tools import escalate_to_human
from agent.tools.faq_tools import get_faqs
from agent.tools.pack_tools import suggest_pack_tool
from shared.config import get_settings

logger = logging.getLogger(__name__)


def get_llm_with_tools() -> ChatAnthropic:
    """
    Get Claude LLM instance with all available tools bound.

    Tools available (Phase 1-2 complete):
    - Customer tools: get_customer_by_phone, create_customer
    - FAQ tools: get_faqs
    - Booking tools: get_services
    - Availability tools: check_availability_tool
    - Pack tools: suggest_pack_tool
    - Consultation tools: offer_consultation_tool
    - Escalation tools: escalate_to_human

    Returns:
        ChatAnthropic instance with tools bound
    """
    settings = get_settings()

    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        api_key=settings.ANTHROPIC_API_KEY,
        temperature=0.7,  # Slightly higher for natural conversation
    )

    # Bind all tools for conversational agent
    tools = [
        # Customer management
        get_customer_by_phone,
        create_customer,
        # Information retrieval
        get_faqs,
        get_services,
        # Availability & scheduling
        check_availability_tool,
        # Value propositions
        suggest_pack_tool,
        offer_consultation_tool,
        # Escalation
        escalate_to_human,
    ]

    llm_with_tools = llm.bind_tools(tools)

    return llm_with_tools


def format_llm_messages_with_summary(state: ConversationState, system_prompt: str) -> list:
    """
    Format messages for LLM with conversation summary if needed.

    Args:
        state: Current conversation state
        system_prompt: System prompt content

    Returns:
        List of messages formatted for LLM (SystemMessage + conversation history)
    """
    messages = [SystemMessage(content=system_prompt)]

    # Add conversation summary if available
    if state.get("conversation_summary"):
        messages.append(
            SystemMessage(content=f"Previous conversation summary: {state['conversation_summary']}")
        )

    # Add recent messages from state
    for msg in state.get("messages", []):
        if msg.get("role") == "human":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg.get("role") == "ai":
            messages.append(AIMessage(content=msg["content"]))

    return messages


def detect_booking_intent(response: AIMessage) -> bool:
    """
    Detect if customer has expressed clear booking intent.

    This function analyzes the AI's response to determine if the customer
    has moved from inquiry/information gathering to actual booking intent.

    Signals that indicate booking intent:
    - "Quiero reservar [service]"
    - "Dame cita para [date]"
    - Customer confirms specific time slot
    - Customer confirms pack acceptance for booking

    NOT signals (still in inquiry phase):
    - "¿Cuánto cuesta?" (just asking price)
    - "¿Tenéis libre?" (checking availability, not confirming)
    - "¿Qué diferencia hay?" (comparing services)

    Args:
        response: AIMessage from LLM

    Returns:
        bool: True if booking intent detected, False otherwise
    """
    if not response.content:
        return False

    # Handle both string content and list content (when tool calls are present)
    if isinstance(response.content, list):
        # When tool calls are present, content is a list of content blocks
        # Extract text from text blocks only
        text_content = " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in response.content
            if block
        )
        if not text_content.strip():
            return False
        content_lower = text_content.lower()
    else:
        content_lower = response.content.lower()

    # Strong booking intent keywords
    booking_keywords = [
        "quiero reservar",
        "dame cita",
        "reserva ",
        "confirmo la cita",
        "perfecto, reserva",
        "sí, reserva",
        "vale, reserva",
        "quiero la cita",
        "quiero el pack",  # Pack acceptance with booking intent
    ]

    # Check if any booking keyword is present
    has_booking_keyword = any(keyword in content_lower for keyword in booking_keywords)

    # Additional context: Check if tool calls include booking-related tools
    # (This will be expanded when booking tools are available)
    has_booking_tool_call = False
    if hasattr(response, "tool_calls") and response.tool_calls:
        booking_tool_names = [
            "create_provisional_booking",
            "validate_booking_request",
        ]
        has_booking_tool_call = any(
            tool_call.get("name") in booking_tool_names
            for tool_call in response.tool_calls
        )

    booking_intent_confirmed = has_booking_keyword or has_booking_tool_call

    if booking_intent_confirmed:
        logger.info(f"Booking intent detected in response: {content_lower[:100]}")

    return booking_intent_confirmed


async def conversational_agent(state: ConversationState) -> dict[str, Any]:
    """
    Tier 1 conversational agent powered by Claude + tools.

    This is the main conversational node that handles all informational
    interactions using Claude's reasoning capabilities and tool access.

    Responsibilities:
    - Natural conversation management
    - Customer identification and creation
    - FAQ answering
    - Service inquiry handling
    - Indecision detection and consultation offering
    - Pack suggestion
    - Availability checking (informational)
    - Booking intent detection

    Transitions:
    - Sets booking_intent_confirmed=True when customer ready to book
    - This triggers transition to Tier 2 transactional flow

    Args:
        state: Current conversation state

    Returns:
        Dict with state updates including:
        - messages: Updated message list with AI response
        - booking_intent_confirmed: True if booking intent detected
        - customer_id: If customer identified/created
        - updated_at: Current timestamp
    """
    try:
        logger.info(
            f"Conversational agent invoked",
            extra={
                "conversation_id": state.get("conversation_id"),
                "customer_phone": state.get("customer_phone"),
                "message_count": len(state.get("messages", [])),
            }
        )

        # Load system prompt with conversational guidance
        system_prompt = load_maite_system_prompt()

        # Get LLM with tools
        llm_with_tools = get_llm_with_tools()

        # Format messages for LLM
        messages = format_llm_messages_with_summary(state, system_prompt)

        # Invoke LLM with tools
        logger.debug(f"Invoking LLM with {len(messages)} messages")
        response = await llm_with_tools.ainvoke(messages)

        # Log tool calls if any
        if hasattr(response, "tool_calls") and response.tool_calls:
            logger.info(
                f"LLM made {len(response.tool_calls)} tool calls",
                extra={
                    "tool_names": [tc.get("name") for tc in response.tool_calls],
                    "conversation_id": state.get("conversation_id"),
                }
            )

        # Detect booking intent
        booking_intent_confirmed = detect_booking_intent(response)

        # Extract content for message (handle both string and list formats)
        if isinstance(response.content, list):
            # When tool calls are present, content is a list of content blocks
            message_content = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in response.content
                if block
            ).strip()
        else:
            message_content = response.content

        # Prepare state updates
        updates = {
            "messages": state.get("messages", []) + [
                {
                    "role": "ai",
                    "content": message_content,
                    "timestamp": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(),
                }
            ],
            "booking_intent_confirmed": booking_intent_confirmed,
            "updated_at": datetime.now(ZoneInfo("Europe/Madrid")),
            "last_node": "conversational_agent",
        }

        logger.info(
            f"Conversational agent completed",
            extra={
                "conversation_id": state.get("conversation_id"),
                "booking_intent_confirmed": booking_intent_confirmed,
                "response_length": len(response.content) if response.content else 0,
            }
        )

        return updates

    except Exception as e:
        logger.error(
            f"Error in conversational_agent: {e}",
            extra={
                "conversation_id": state.get("conversation_id"),
                "error_type": type(e).__name__,
            },
            exc_info=True
        )

        # Return error state update
        return {
            "error_count": state.get("error_count", 0) + 1,
            "last_node": "conversational_agent",
            "updated_at": datetime.now(ZoneInfo("Europe/Madrid")),
            "messages": state.get("messages", []) + [
                {
                    "role": "ai",
                    "content": "Lo siento, tuve un problema. ¿Puedes repetir tu pregunta? 💕",
                    "timestamp": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(),
                }
            ],
        }

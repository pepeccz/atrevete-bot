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
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent.prompts import load_maite_system_prompt
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState
from agent.tools.availability_tools import check_availability_tool
from agent.tools.booking_tools import get_services, start_booking_flow, set_preferred_date
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
        set_preferred_date,
        # Value propositions
        suggest_pack_tool,
        offer_consultation_tool,
        # Booking flow initiation
        start_booking_flow,
        # Escalation
        escalate_to_human,
    ]

    llm_with_tools = llm.bind_tools(tools)

    return llm_with_tools


async def execute_tool_call(tool_call: dict) -> str:
    """
    Execute a single tool call and return the result as a string.

    Args:
        tool_call: Tool call dict with 'name', 'args', and 'id' keys

    Returns:
        String representation of tool result (JSON or error message)
    """
    tool_name = tool_call.get("name")
    tool_args = tool_call.get("args", {})

    logger.info(
        f"Executing tool: {tool_name}",
        extra={
            "tool_name": tool_name,
            "tool_args": tool_args,
        }
    )

    # Map tool names to their implementations
    tool_map = {
        "get_customer_by_phone": get_customer_by_phone,
        "create_customer": create_customer,
        "get_faqs": get_faqs,
        "get_services": get_services,
        "check_availability_tool": check_availability_tool,
        "set_preferred_date": set_preferred_date,
        "suggest_pack_tool": suggest_pack_tool,
        "offer_consultation_tool": offer_consultation_tool,
        "start_booking_flow": start_booking_flow,
        "escalate_to_human": escalate_to_human,
    }

    tool = tool_map.get(tool_name)

    if not tool:
        error_msg = f"Tool '{tool_name}' not found in tool map"
        logger.error(error_msg)
        return error_msg

    try:
        # Execute tool asynchronously
        result = await tool.ainvoke(tool_args)

        logger.info(
            f"Tool {tool_name} executed successfully",
            extra={
                "tool_name": tool_name,
                "result_preview": str(result)[:100],
            }
        )

        # Convert result to string (handle different result types)
        if isinstance(result, dict):
            import json
            return json.dumps(result, ensure_ascii=False, default=str)
        elif isinstance(result, list):
            import json
            return json.dumps(result, ensure_ascii=False, default=str)
        else:
            return str(result)

    except Exception as e:
        error_msg = f"Error executing tool {tool_name}: {str(e)}"
        logger.error(
            error_msg,
            extra={
                "tool_name": tool_name,
                "error_type": type(e).__name__,
            },
            exc_info=True
        )
        return error_msg


def format_llm_messages_with_summary(state: ConversationState, system_prompt: str) -> list:
    """
    Format messages for LLM with conversation summary if needed.

    Converts state messages (dict format with role: "user"/"assistant") to LangChain
    Message objects (HumanMessage/AIMessage) for Claude API compatibility.

    Args:
        state: Current conversation state
        system_prompt: System prompt content

    Returns:
        List of messages formatted for LLM (SystemMessage + conversation history)
    """
    messages = [SystemMessage(content=system_prompt)]

    # Add current date/time context so Claude knows what "today", "tomorrow", etc. mean
    now = datetime.now(ZoneInfo("Europe/Madrid"))
    day_names_es = {
        0: "lunes", 1: "martes", 2: "miércoles", 3: "jueves",
        4: "viernes", 5: "sábado", 6: "domingo"
    }
    month_names_es = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
        7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
    }
    day_name = day_names_es[now.weekday()]
    month_name = month_names_es[now.month]
    temporal_context = (
        f"CONTEXTO TEMPORAL: Hoy es {day_name}, {now.day} de {month_name} de {now.year} "
        f"a las {now.strftime('%H:%M')} (zona horaria: Europe/Madrid)"
    )
    messages.append(SystemMessage(content=temporal_context))

    # Add conversation summary if available
    if state.get("conversation_summary"):
        messages.append(
            SystemMessage(content=f"Previous conversation summary: {state['conversation_summary']}")
        )

    # Add recent messages from state (converts dict → LangChain messages)
    for msg in state.get("messages", []):
        if msg.get("role") == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg.get("role") == "assistant":
            messages.append(AIMessage(content=msg["content"]))

    return messages


def detect_booking_intent(all_tool_calls_history: list[dict]) -> bool:
    """
    Detect if customer has expressed clear booking intent through tool calls.

    This function checks if Claude called start_booking_flow() tool during
    the ReAct loop, which indicates the customer wants to proceed with a booking.

    The agent (Claude) decides when to call start_booking_flow() based on:
    - "Quiero reservar [service]"
    - "Dame cita para [date]"
    - "Perfecto, agéndame"
    - Customer confirms specific intent to book

    NOT signals (still in inquiry phase):
    - "¿Cuánto cuesta?" (just asking price)
    - "¿Tenéis libre?" (checking availability, not confirming)
    - "¿Qué diferencia hay?" (comparing services)

    Args:
        all_tool_calls_history: List of all tool calls made during ReAct loop

    Returns:
        bool: True if start_booking_flow was called, False otherwise
    """
    # Check if start_booking_flow was called in any iteration
    for tool_call in all_tool_calls_history:
        tool_name = tool_call.get("name")
        if tool_name == "start_booking_flow":
            logger.info(
                "Booking intent detected: start_booking_flow() was called by agent",
                extra={
                    "tool_args": tool_call.get("args", {}),
                }
            )
            return True

    return False


def extract_preferred_date(all_tool_calls_history: list[dict]) -> tuple[str | None, str | None]:
    """
    Extract preferred date and time from tool calls.

    This function checks if Claude called set_preferred_date() tool during
    the ReAct loop and extracts the date/time values.

    Args:
        all_tool_calls_history: List of all tool calls made during ReAct loop

    Returns:
        tuple: (preferred_date, preferred_time) or (None, None) if not set
    """
    # Check if set_preferred_date was called in any iteration
    for tool_call in all_tool_calls_history:
        tool_name = tool_call.get("name")
        if tool_name == "set_preferred_date":
            args = tool_call.get("args", {})
            preferred_date = args.get("preferred_date")
            preferred_time = args.get("preferred_time")

            logger.info(
                "Preferred date extracted from tool call",
                extra={
                    "preferred_date": preferred_date,
                    "preferred_time": preferred_time,
                }
            )
            return preferred_date, preferred_time

    return None, None


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

        # Pre-load customer data from database (ALWAYS attempt, database is source of truth)
        # This ensures Claude always has access to the customer's name for personalization
        # Priority: Database > Chatwoot webhook > Ask user
        if state.get("customer_phone"):
            try:
                from agent.tools.customer_tools import get_customer_by_phone
                from phonenumbers import parse as parse_phone, format_number, PhoneNumberFormat

                # Normalize phone to E.164 format for lookup
                phone = state.get("customer_phone")
                try:
                    parsed = parse_phone(phone, "ES")
                    normalized_phone = format_number(parsed, PhoneNumberFormat.E164)
                except Exception:
                    normalized_phone = phone

                # Query database for customer (always check, DB is source of truth)
                customer_data = await get_customer_by_phone.ainvoke({"phone": normalized_phone})

                if customer_data:
                    # Update state with customer information from database
                    customer_name = customer_data.get("first_name", "")
                    if customer_data.get("last_name"):
                        customer_name += f" {customer_data['last_name']}"

                    state["customer_name"] = customer_name
                    state["customer_id"] = customer_data.get("id")

                    logger.info(
                        f"Pre-loaded customer data from database: {customer_name}",
                        extra={
                            "conversation_id": state.get("conversation_id"),
                            "customer_id": customer_data.get("id"),
                        }
                    )
                else:
                    # Customer not in database yet
                    # Keep customer_name from Chatwoot webhook if available, otherwise None
                    logger.info(
                        f"Customer not found in database, using webhook name: {state.get('customer_name')}",
                        extra={"conversation_id": state.get("conversation_id")}
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to pre-load customer data: {e}",
                    extra={"conversation_id": state.get("conversation_id")},
                    exc_info=True
                )

        # Load system prompt with conversational guidance
        system_prompt = load_maite_system_prompt()

        # Get LLM with tools
        llm_with_tools = get_llm_with_tools()

        # Format messages for LLM
        messages = format_llm_messages_with_summary(state, system_prompt)

        # ReAct loop: Invoke LLM with tools and execute them until no more tool calls
        logger.debug(f"Starting ReAct loop with {len(messages)} messages")

        max_iterations = 5  # Prevent infinite loops
        response = None
        all_tool_calls = []  # Collect all tool calls for booking intent detection

        for iteration in range(max_iterations):
            logger.debug(f"ReAct iteration {iteration + 1}/{max_iterations}")

            # Invoke LLM
            response = await llm_with_tools.ainvoke(messages)

            # Check if LLM requested tool calls
            if not hasattr(response, "tool_calls") or not response.tool_calls:
                # No tool calls - we have the final response
                logger.info(
                    f"ReAct loop completed after {iteration + 1} iteration(s) - no more tool calls",
                    extra={"conversation_id": state.get("conversation_id")}
                )
                break

            # Log tool calls
            logger.info(
                f"LLM made {len(response.tool_calls)} tool call(s) in iteration {iteration + 1}",
                extra={
                    "tool_names": [tc.get("name") for tc in response.tool_calls],
                    "conversation_id": state.get("conversation_id"),
                    "iteration": iteration + 1,
                }
            )

            # Append AI message with tool calls to conversation
            messages.append(response)

            # Execute each tool call and append results
            for tool_call in response.tool_calls:
                # Collect tool call for booking intent detection
                all_tool_calls.append(tool_call)

                tool_result = await execute_tool_call(tool_call)

                # Append tool result as ToolMessage
                tool_message = ToolMessage(
                    content=tool_result,
                    tool_call_id=tool_call["id"]
                )
                messages.append(tool_message)

            # Continue loop to get LLM's response incorporating tool results

        # Safety check: If we maxed out iterations, still use last response
        if response is None:
            raise RuntimeError("ReAct loop completed without any LLM response")

        # Detect booking intent from all tool calls made during ReAct loop
        booking_intent_confirmed = detect_booking_intent(all_tool_calls)

        # Extract preferred date from tool calls (if set_preferred_date was called)
        preferred_date, preferred_time = extract_preferred_date(all_tool_calls)

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

        # Fallback: If message_content is empty but we had tool execution, use a default
        if not message_content or not message_content.strip():
            logger.warning(
                "Final LLM response has empty content after tool execution",
                extra={"conversation_id": state.get("conversation_id")}
            )
            message_content = "¿En qué más puedo ayudarte? 😊"

        # Add assistant message using helper (ensures FIFO windowing + total_message_count)
        updated_state = add_message(state, "assistant", message_content)

        # Prepare state updates (merge with add_message updates)
        updates = {
            **updated_state,  # Include messages and total_message_count from add_message
            "booking_intent_confirmed": booking_intent_confirmed,
            "updated_at": datetime.now(ZoneInfo("Europe/Madrid")),
            "last_node": "conversational_agent",
        }

        # Set preferred date if it was provided by customer
        if preferred_date:
            updates["requested_date"] = preferred_date
            updates["awaiting_date_input"] = False  # Clear the awaiting flag
            logger.info(
                f"Requested date set from customer response: {preferred_date}",
                extra={"conversation_id": state.get("conversation_id"), "requested_date": preferred_date}
            )

        if preferred_time:
            updates["requested_time"] = preferred_time
            logger.info(
                f"Requested time set from customer response: {preferred_time}",
                extra={"conversation_id": state.get("conversation_id"), "requested_time": preferred_time}
            )

        # Include customer data if it was loaded/updated
        if state.get("customer_name"):
            updates["customer_name"] = state["customer_name"]
        if state.get("customer_id"):
            updates["customer_id"] = state["customer_id"]

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

        # Return error state update using add_message helper
        error_state = add_message(
            state,
            "assistant",
            "Lo siento, tuve un problema. ¿Puedes repetir tu pregunta? 💕"
        )

        return {
            **error_state,
            "error_count": state.get("error_count", 0) + 1,
            "last_node": "conversational_agent",
            "updated_at": datetime.now(ZoneInfo("Europe/Madrid")),
        }

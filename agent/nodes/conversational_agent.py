"""
Conversational Agent Node - Tier 1 Architecture.

This is the primary conversational node that handles all informational conversations
using Claude LLM with tool access. Part of the hybrid architecture simplification.

Handles:
- FAQs, greetings, service inquiries
- Indecision detection and consultation offering
- Availability checking (informational only)
- Customer identification and creation

Note: Pack suggestions removed (packs functionality eliminated)

Transitions to Tier 2 (transactional flow) when:
- booking_intent_confirmed=True (customer ready to book)
"""

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent.prompts import load_maite_system_prompt, load_stylist_context
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState
from agent.tools.availability_tools import check_availability_tool
from agent.tools.booking_tools import get_services, start_booking_flow, set_preferred_date, validate_booking_date
from agent.tools.business_hours_tools import get_business_hours
from agent.tools.consultation_tools import offer_consultation_tool
from agent.tools.customer_tools import create_customer, get_customer_by_phone
from agent.tools.escalation_tools import escalate_to_human
from agent.tools.faq_tools import get_faqs
from agent.tools.policy_tools import get_payment_policies, get_cancellation_policy
# from agent.tools.pack_tools import suggest_pack_tool  # Removed - packs functionality eliminated
from shared.config import get_settings

logger = logging.getLogger(__name__)


def get_llm_with_tools() -> ChatAnthropic:
    """
    Get Claude LLM instance with all available tools bound.

    Tools available (Optimized - Dynamic Data Fetching):
    - Customer tools: get_customer_by_phone, create_customer
    - Information tools: get_faqs, get_business_hours, get_payment_policies, get_cancellation_policy
    - Booking tools: get_services, set_preferred_date, start_booking_flow
    - Availability tools: check_availability_tool
    - Consultation tools: offer_consultation_tool
    - Escalation tools: escalate_to_human

    Note: Pack tools removed (packs functionality eliminated)

    Returns:
        ChatAnthropic instance with tools bound
    """
    settings = get_settings()

    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        api_key=settings.ANTHROPIC_API_KEY,
        temperature=0.3,
    )

    # Bind all tools for conversational agent
    tools = [
        # Customer management
        get_customer_by_phone,
        create_customer,
        # Information retrieval (dynamic from DB)
        get_faqs,
        get_business_hours,
        get_payment_policies,
        get_cancellation_policy,
        get_services,
        # Availability & scheduling
        validate_booking_date,  # 🆕 Validate 3-day rule early (Tier 1)
        check_availability_tool,
        set_preferred_date,
        # Value propositions
        # suggest_pack_tool,  # Removed - packs functionality eliminated
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
        "get_business_hours": get_business_hours,
        "get_payment_policies": get_payment_policies,
        "get_cancellation_policy": get_cancellation_policy,
        "get_services": get_services,
        "validate_booking_date": validate_booking_date,  # 🆕 Early 3-day validation
        "check_availability_tool": check_availability_tool,
        "set_preferred_date": set_preferred_date,
        # "suggest_pack_tool": suggest_pack_tool,  # Removed - packs functionality eliminated
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


def format_llm_messages_with_summary(
    state: ConversationState,
    system_prompt: str,
    stylist_context: str | None = None
) -> list:
    """
    Format messages for LLM with conversation summary if needed.

    Converts state messages (dict format with role: "user"/"assistant") to LangChain
    Message objects (HumanMessage/AIMessage) for Claude API compatibility.

    Args:
        state: Current conversation state
        system_prompt: System prompt content
        stylist_context: Optional dynamic stylist team context from database

    Returns:
        List of messages formatted for LLM (SystemMessage + conversation history)
    """
    messages = [SystemMessage(content=system_prompt)]

    # Add dynamic stylist context (database source of truth)
    # Injected after system prompt, before temporal context
    if stylist_context:
        messages.append(SystemMessage(content=stylist_context))

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

    This function checks if Claude called either:
    - set_preferred_date() - explicit date setting tool
    - start_booking_flow() - booking initiation with optional date parameters

    Priority: set_preferred_date takes precedence if both are called

    Args:
        all_tool_calls_history: List of all tool calls made during ReAct loop

    Returns:
        tuple: (preferred_date, preferred_time) or (None, None) if not set
    """
    # Check for set_preferred_date first (explicit date setting - higher priority)
    for tool_call in all_tool_calls_history:
        tool_name = tool_call.get("name")
        if tool_name == "set_preferred_date":
            args = tool_call.get("args", {})
            preferred_date = args.get("preferred_date")
            preferred_time = args.get("preferred_time")

            logger.info(
                "Preferred date extracted from set_preferred_date tool",
                extra={
                    "preferred_date": preferred_date,
                    "preferred_time": preferred_time,
                }
            )
            return preferred_date, preferred_time

    # Check for start_booking_flow (booking initiation with optional date)
    for tool_call in all_tool_calls_history:
        tool_name = tool_call.get("name")
        if tool_name == "start_booking_flow":
            args = tool_call.get("args", {})
            preferred_date = args.get("preferred_date")
            preferred_time = args.get("preferred_time")

            # Only extract if date was actually provided (not None)
            if preferred_date:
                logger.info(
                    "Preferred date extracted from start_booking_flow tool",
                    extra={
                        "preferred_date": preferred_date,
                        "preferred_time": preferred_time,
                    }
                )
                return preferred_date, preferred_time

    return None, None


async def extract_requested_services(all_tool_calls_history: list[dict]) -> dict[str, Any]:
    """
    Extract and resolve service names to UUIDs from tool calls.

    This function checks if Claude called start_booking_flow() tool during
    the ReAct loop and resolves the service names to database UUIDs.

    **Ambiguity Handling:**
    - If a service name matches EXACTLY ONE service → auto-resolve to UUID
    - If a service name matches MULTIPLE services → flag as ambiguous for clarification

    Args:
        all_tool_calls_history: List of all tool calls made during ReAct loop

    Returns:
        dict with:
            - resolved_uuids: list[UUID] - Successfully resolved service UUIDs
            - ambiguous_services: dict | None - Info about ambiguous service if detected
                Structure: {
                    "query": str,  # Original query (e.g., "corte")
                    "options": [   # List of matching services
                        {"id": str, "name": str, "price_euros": float, "duration_minutes": int, "category": str}
                    ]
                }
    """
    from agent.tools.booking_tools import get_service_by_name
    from uuid import UUID

    # Find start_booking_flow tool call
    for tool_call in all_tool_calls_history:
        tool_name = tool_call.get("name")
        if tool_name == "start_booking_flow":
            args = tool_call.get("args", {})
            service_names = args.get("services", [])

            if not service_names:
                logger.warning("start_booking_flow called without services")
                return {"resolved_uuids": [], "ambiguous_services": None}

            logger.info(
                f"Resolving service names to UUIDs: {service_names}",
                extra={"service_names": service_names}
            )

            # Resolve each service name to UUID
            resolved_uuids = []
            ambiguous_services = None

            for service_name in service_names:
                try:
                    # Use fuzzy matching to find services (returns list)
                    matching_services = await get_service_by_name(service_name, fuzzy=True, limit=5)

                    if len(matching_services) == 0:
                        # No matches found
                        logger.warning(
                            f"Could not resolve service name '{service_name}' to UUID (no matches)"
                        )

                    elif len(matching_services) == 1:
                        # Unambiguous - single match found
                        service = matching_services[0]
                        resolved_uuids.append(service.id)
                        logger.info(
                            f"Resolved '{service_name}' → {service.name} (UUID: {service.id})"
                        )

                    else:
                        # Multiple matches - check if first is exact match
                        normalized_query = service_name.strip().lower()
                        first_match_name = matching_services[0].name.strip().lower()

                        if normalized_query == first_match_name:
                            # Exact match found - use it directly (ignore other fuzzy matches)
                            service = matching_services[0]
                            resolved_uuids.append(service.id)
                            logger.info(
                                f"Exact match found (ignoring {len(matching_services) - 1} other fuzzy matches): "
                                f"'{service_name}' → {service.name} (UUID: {service.id})"
                            )
                        else:
                            # True ambiguity - multiple matches without exact match
                            logger.warning(
                                f"Ambiguous service query '{service_name}': {len(matching_services)} matches found"
                            )

                            # Store ambiguity info for Claude to handle
                            ambiguous_services = {
                                "query": service_name,
                                "options": [
                                    {
                                        "id": str(s.id),
                                        "name": s.name,
                                        "price_euros": float(s.price_euros),
                                        "duration_minutes": s.duration_minutes,
                                        "category": s.category.value,
                                    }
                                    for s in matching_services
                                ]
                            }

                            logger.info(
                                f"Flagging '{service_name}' as ambiguous with {len(matching_services)} options: "
                                f"{[s.name for s in matching_services]}"
                            )

                            # Stop processing more services - handle one ambiguity at a time
                            break

                except Exception as e:
                    logger.error(
                        f"Error resolving service '{service_name}': {e}",
                        exc_info=True
                    )

            logger.info(
                f"Service resolution complete: {len(resolved_uuids)}/{len(service_names)} resolved, "
                f"ambiguous: {ambiguous_services is not None}",
                extra={
                    "requested_services": [str(uuid) for uuid in resolved_uuids],
                    "has_ambiguity": ambiguous_services is not None
                }
            )

            return {
                "resolved_uuids": resolved_uuids,
                "ambiguous_services": ambiguous_services
            }

    return {"resolved_uuids": [], "ambiguous_services": None}


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

        # Load dynamic stylist context from database (source of truth)
        stylist_context = await load_stylist_context()

        # Inject pending service clarification if ambiguity detected
        ambiguity_context = ""
        pending_clarification = state.get("pending_service_clarification")
        if pending_clarification:
            query = pending_clarification.get("query", "")
            options = pending_clarification.get("options", [])
            ambiguity_context = "\n\n## ⚠️ ACCIÓN REQUERIDA: Clarificar Servicio Ambiguo\n\n"
            ambiguity_context += f"El cliente mencionó '{query}', pero hay {len(options)} servicios que coinciden:\n\n"
            for i, opt in enumerate(options, 1):
                ambiguity_context += (
                    f"{i}. **{opt['name']}** - {opt['price_euros']}€, {opt['duration_minutes']} min "
                    f"({opt['category']})\n"
                )
            ambiguity_context += (
                "\n**DEBES presentar TODAS estas opciones al cliente de forma clara y amigable "
                "(usa emojis, lista numerada) y pedirle que elija cuál prefiere.**\n"
                "\n**Cuando responda**, llama `start_booking_flow(services=[\"nombre exacto del servicio elegido\"], ...)`\n"
            )

        # Get LLM with tools
        llm_with_tools = get_llm_with_tools()

        # Format messages for LLM (includes dynamic stylist injection + ambiguity alert)
        full_context = stylist_context + ambiguity_context
        messages = format_llm_messages_with_summary(state, system_prompt, full_context)

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

        # Extract and resolve requested services from tool calls (if start_booking_flow was called)
        service_resolution = await extract_requested_services(all_tool_calls)
        requested_services_uuids = service_resolution.get("resolved_uuids", [])
        ambiguous_services = service_resolution.get("ambiguous_services", None)

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

        # Fallback: If message_content is empty but we had tool execution, escalate to human
        if not message_content or not message_content.strip():
            logger.error(
                "Final LLM response has empty content after tool execution - escalating to human",
                extra={"conversation_id": state.get("conversation_id")}
            )
            try:
                # Call escalate_to_human to get appropriate message
                escalation_result = await escalate_to_human.ainvoke({"reason": "technical_error"})
                message_content = escalation_result.get("message", "Te conecto con el equipo 💕")
                # Mark escalation in state (will be added to updates later)
                escalation_triggered = True
                escalation_reason = "technical_error"
            except Exception as escalation_error:
                logger.error(f"Failed to escalate during empty content fallback: {escalation_error}")
                message_content = "Disculpa, he tenido un problema al procesar tu mensaje. He notificado al equipo y te atenderán lo antes posible 🌸"
                escalation_triggered = True
                escalation_reason = "technical_error"
        else:
            escalation_triggered = False
            escalation_reason = None

        # Add assistant message using helper (ensures FIFO windowing + total_message_count)
        updated_state = add_message(state, "assistant", message_content)

        # Prepare state updates (merge with add_message updates)
        updates = {
            **updated_state,  # Include messages and total_message_count from add_message
            "booking_intent_confirmed": booking_intent_confirmed,
            "updated_at": datetime.now(ZoneInfo("Europe/Madrid")),
            "last_node": "conversational_agent",
            "escalation_triggered": escalation_triggered,
            "escalation_reason": escalation_reason,
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

        # Handle service ambiguity or resolution
        if ambiguous_services:
            # Ambiguous service detected - store for Claude to clarify
            updates["pending_service_clarification"] = ambiguous_services
            logger.warning(
                f"Service ambiguity detected for '{ambiguous_services['query']}' "
                f"with {len(ambiguous_services['options'])} options",
                extra={
                    "conversation_id": state.get("conversation_id"),
                    "ambiguous_query": ambiguous_services['query'],
                    "num_options": len(ambiguous_services['options'])
                }
            )
        elif requested_services_uuids:
            # Services resolved successfully - clear any pending clarification
            updates["requested_services"] = requested_services_uuids
            updates["pending_service_clarification"] = None
            logger.info(
                f"Requested services set: {len(requested_services_uuids)} service(s) resolved",
                extra={
                    "conversation_id": state.get("conversation_id"),
                    "requested_services": [str(uuid) for uuid in requested_services_uuids]
                }
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

        # Attempt to escalate with proper message
        try:
            escalation_result = await escalate_to_human.ainvoke({"reason": "technical_error"})
            error_message = escalation_result.get("message", "Te conecto con el equipo 💕")
        except Exception as escalation_error:
            logger.error(f"Failed to escalate during error handling: {escalation_error}")
            error_message = "Disculpa, he tenido un problema al procesar tu mensaje. He notificado al equipo y te atenderán lo antes posible 🌸"

        # Return error state update using add_message helper
        error_state = add_message(state, "assistant", error_message)

        return {
            **error_state,
            "error_count": state.get("error_count", 0) + 1,
            "escalation_triggered": True,
            "escalation_reason": "technical_error",
            "last_node": "conversational_agent",
            "updated_at": datetime.now(ZoneInfo("Europe/Madrid")),
        }

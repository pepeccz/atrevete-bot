"""
Conversational Agent Node - v3.2 Architecture.

This is the single node that handles ALL conversations using GPT-4.1-mini via OpenRouter
with 8 consolidated tools. Replaces the hybrid Tier 1/Tier 2 architecture.

Model: openai/gpt-4.1-mini (cost-optimized, automatic prompt caching)

Handles everything:
- FAQs, greetings, service inquiries → query_info tool
- Customer identification → manage_customer tool
- Availability checking (single date) → check_availability tool
- Availability search (multi-date) → find_next_available tool (NEW)
- Booking → book tool (delegates to BookingTransaction)
- Escalation → escalate_to_human tool

No transitions to transactional nodes. LLM orchestrates entire conversation.
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent.prompts import load_contextual_prompt, load_stylist_context
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState
from agent.tools import (
    check_availability,
    find_next_available,
    book,
    escalate_to_human,
    get_customer_history,
    manage_customer,
    query_info,
    search_services,
)
from shared.config import get_settings

logger = logging.getLogger(__name__)


def get_llm_with_tools() -> ChatOpenAI:
    """
    Get GPT-4.1-mini LLM instance with 8 consolidated tools bound via OpenRouter.

    Model: openai/gpt-4.1-mini (cost-optimized with automatic prompt caching)
    Provider: OpenRouter API

    Tools available (v3.2 enhanced):
    1. query_info: Unified information queries (services, FAQs, hours, policies)
    2. search_services: Fuzzy search for specific services (NEW - solves 47-service overflow)
    3. manage_customer: Unified customer management (get, create, update)
    4. get_customer_history: Customer appointment history
    5. check_availability: Calendar availability with natural date parsing (single date)
    6. find_next_available: Automatic multi-date availability search
    7. book: Atomic booking via BookingTransaction handler
    8. escalate_to_human: Human escalation

    Returns:
        ChatOpenAI instance configured for OpenRouter with 8 tools bound
    """
    settings = get_settings()

    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        temperature=0.3,
        default_headers={
            "HTTP-Referer": settings.SITE_URL,
            "X-Title": settings.SITE_NAME,
        }
    )

    # Bind 8 consolidated tools for v3.1 architecture
    tools = [
        query_info,               # 1. Information queries (replaces 4 tools)
        search_services,          # 2. Service search with fuzzy matching (NEW - solves overflow)
        manage_customer,          # 3. Customer management (replaces 3 tools)
        get_customer_history,     # 4. Customer history
        check_availability,       # 5. Availability checking (single date, enhanced with natural dates)
        find_next_available,      # 6. Multi-date availability search
        book,                     # 7. Atomic booking (replaces entire booking flow)
        escalate_to_human,        # 8. Human escalation
    ]

    llm_with_tools = llm.bind_tools(tools)

    logger.info(f"GPT-4.1-mini LLM initialized with 8 consolidated tools (v3.2) via OpenRouter")

    return llm_with_tools


async def execute_tool_call(tool_call: dict, state: ConversationState) -> tuple[str, dict[str, Any]]:
    """
    Execute a single tool call with state-aware validation and return result plus state updates.

    This function implements deterministic validation to prevent duplicate tool calls
    (e.g., calling manage_customer twice) by tracking execution state.

    Args:
        tool_call: Tool call dict with 'name', 'args', and 'id' keys
        state: Current conversation state for validation

    Returns:
        Tuple of (result_string, state_updates_dict)
        - result_string: JSON or error message to send to Claude
        - state_updates_dict: Fields to update in state after tool execution
    """
    import json

    tool_name = tool_call.get("name")
    tool_args = tool_call.get("args", {})
    state_updates = {}

    logger.info(
        f"Executing tool: {tool_name}",
        extra={
            "tool_name": tool_name,
            "tool_args": tool_args,
        }
    )

    # ============================================================================
    # PRE-EXECUTION VALIDATION
    # ============================================================================

    # Prevent duplicate manage_customer calls
    if tool_name == "manage_customer":
        action = tool_args.get("action")
        if action == "create" and state.get("customer_data_collected"):
            error_result = {
                "error": "DUPLICATE_CALL",
                "message": (
                    "❌ Ya obtuviste los datos del cliente anteriormente. "
                    "NO necesitas llamar a manage_customer otra vez. "
                    f"Usa directamente el customer_id que YA TIENES: {state.get('customer_id')} "
                    "para llamar a book()."
                ),
                "customer_id": str(state.get("customer_id")),
                "instruction": "Llama a book() con este customer_id ahora."
            }
            logger.warning(
                f"Prevented duplicate manage_customer call (action={action})",
                extra={
                    "customer_id": state.get("customer_id"),
                    "customer_data_collected": state.get("customer_data_collected")
                }
            )
            return json.dumps(error_result, ensure_ascii=False, indent=2), state_updates

    # Ensure customer data is collected before booking
    if tool_name == "book":
        if not state.get("customer_data_collected"):
            error_result = {
                "error": "MISSING_CUSTOMER_DATA",
                "message": (
                    "❌ Debes obtener los datos del cliente primero. "
                    "Llama a manage_customer(action='get', phone='...') antes de llamar a book()."
                ),
                "instruction": "Llama a manage_customer(action='get') ahora."
            }
            logger.warning(
                "Prevented book() call without customer data collection",
                extra={"customer_data_collected": state.get("customer_data_collected")}
            )
            return json.dumps(error_result, ensure_ascii=False, indent=2), state_updates

    # ============================================================================
    # TOOL EXECUTION
    # ============================================================================

    # Map tool names to their implementations (8 tools)
    tool_map = {
        "query_info": query_info,
        "search_services": search_services,
        "manage_customer": manage_customer,
        "get_customer_history": get_customer_history,
        "check_availability": check_availability,
        "find_next_available": find_next_available,
        "book": book,
        "escalate_to_human": escalate_to_human,
    }

    tool = tool_map.get(tool_name)

    if not tool:
        error_msg = f"Tool '{tool_name}' not found in tool map (available: {list(tool_map.keys())})"
        logger.error(error_msg)
        return error_msg, state_updates

    try:
        # Execute tool asynchronously
        result = await tool.ainvoke(tool_args)

        # Check if tool returned an error
        if isinstance(result, dict) and result.get("error"):
            logger.error(
                f"Tool {tool_name} returned error",
                extra={
                    "tool_name": tool_name,
                    "error": result.get("error"),
                    "result_preview": str(result)[:200],
                }
            )
        else:
            logger.info(
                f"Tool {tool_name} executed successfully",
                extra={
                    "tool_name": tool_name,
                    "result_preview": str(result)[:200],
                }
            )

        # ============================================================================
        # POST-EXECUTION STATE UPDATES
        # ============================================================================

        # Track successful customer data collection
        if tool_name == "manage_customer" and isinstance(result, dict) and not result.get("error"):
            state_updates["customer_data_collected"] = True
            state_updates["customer_id"] = result.get("id")
            logger.info(
                "Customer data collected successfully",
                extra={
                    "customer_id": result.get("id"),
                    "action": tool_args.get("action")
                }
            )

            # Add explicit instruction to call book() next (prevents blank responses)
            result["NEXT_STEP_REQUIRED"] = "BOOKING"
            result["instruction"] = (
                "✅ Customer data collected. "
                f"customer_id={result.get('id')} is now available. "
                "\n\n⚠️ CRITICAL: You MUST call book() NOW with:\n"
                f"- customer_id: \"{result.get('id')}\"\n"
                "- services: [list of service names the user requested]\n"
                "- stylist_id: UUID of the stylist the user chose\n"
                "- start_time: ISO timestamp of the slot the user selected\n"
                "\n🚫 DO NOT send a blank response to the user.\n"
                "🚫 DO NOT wait for more input.\n"
                "✅ Execute book() immediately with the booking details from the conversation."
            )

        # Convert result to string for LangChain ToolMessage
        if isinstance(result, dict):
            result_str = json.dumps(result, ensure_ascii=False, indent=2)
        else:
            result_str = str(result)

        return result_str, state_updates

    except Exception as e:
        error_msg = f"Error executing tool {tool_name}: {str(e)}"
        logger.error(
            error_msg,
            extra={
                "tool_name": tool_name,
                "tool_args": tool_args,
                "error": str(e),
            },
            exc_info=True
        )
        return error_msg, state_updates


async def conversational_agent(state: ConversationState) -> dict[str, Any]:
    """
    Main conversational agent node using Claude Haiku 4.5 with 7 consolidated tools.

    This single node handles ALL conversation via Claude's reasoning + tool calling.
    No explicit state transitions, no booking phases, no transactional nodes.

    Workflow:
    1. Build LangChain message history from state
    2. Add system prompt with Maite personality + stylist context
    3. Invoke Claude LLM with tools
    4. Execute tool calls if any
    5. Get final response from Claude
    6. Update state with assistant message

    Args:
        state: Current conversation state

    Returns:
        Updated state with assistant response added
    """
    conversation_id = state.get("conversation_id", "unknown")
    messages_history = state.get("messages", [])

    logger.info(
        f"Conversational agent (v3.0) invoked",
        extra={
            "conversation_id": conversation_id,
            "messages_count": len(messages_history),
        }
    )

    # Step 1: Build LangChain message history from state
    langchain_messages = []

    # PHASE 1: CACHEABLE CONTENT (Static + Semi-static)
    # This content is stable and benefits from OpenRouter's automatic caching
    system_prompt = load_contextual_prompt(state)
    stylist_context = await load_stylist_context()

    cacheable_system_prompt = f"{system_prompt}\n\n{stylist_context}"

    # Measure prompt sizes for monitoring (v3.2 enhancement)
    cacheable_size_chars = len(cacheable_system_prompt)
    cacheable_size_tokens = cacheable_size_chars // 4  # Estimate: 4 chars ≈ 1 token

    # Add cacheable system prompt as SystemMessage
    # OpenRouter will automatically cache prompts >1024 tokens (~2500 tokens here)
    langchain_messages.append(SystemMessage(content=cacheable_system_prompt))

    logger.info(
        f"Cacheable prompt size: {cacheable_size_chars} chars (~{cacheable_size_tokens} tokens) | "
        f"Cache eligible: {cacheable_size_tokens > 256}"
    )

    # PHASE 2: DYNAMIC CONTENT (Per-request)
    # This content changes frequently and should NOT be cached
    # By separating it, we maximize cache hit rate on the static portion

    # Add temporal context (current date/time for date interpretation)
    now = datetime.now(ZoneInfo("Europe/Madrid"))
    day_names_es = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    month_names_es = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
    ]

    earliest_valid = now + timedelta(days=3)
    temporal_context = f"""CONTEXTO TEMPORAL:
Hoy es {day_names_es[now.weekday()]} {now.day} de {month_names_es[now.month-1]} de {now.year}.
Hora actual: {now.strftime('%H:%M')}

IMPORTANTE: Las reservas requieren mínimo 3 días de aviso.
Fecha más cercana válida: {day_names_es[earliest_valid.weekday()]} {earliest_valid.day} de {month_names_es[earliest_valid.month-1]}"""

    # Add customer context (phone is always available from WhatsApp)
    customer_phone = state.get("customer_phone", "Desconocido")
    customer_name = state.get("customer_name")
    customer_id = state.get("customer_id")

    customer_context = f"""DATOS DEL CLIENTE:
- Teléfono: {customer_phone}
- Nombre registrado: {customer_name if customer_name else "No disponible"}
- ID de cliente: {customer_id if customer_id else "No registrado aún"}

⚠️ CRÍTICO: El teléfono ({customer_phone}) ya está disponible del WhatsApp.
NUNCA preguntes por el teléfono. Úsalo directamente cuando necesites llamar a manage_customer."""

    # Combine dynamic contexts
    dynamic_context = f"{temporal_context}\n\n{customer_context}"

    # Measure dynamic context size
    dynamic_size_chars = len(dynamic_context)
    dynamic_size_tokens = dynamic_size_chars // 4

    # Add dynamic context as a separate HumanMessage (not cached)
    # This allows OpenRouter to cache the SystemMessage above
    langchain_messages.append(
        HumanMessage(content=f"[CONTEXTO DINÁMICO]\n{dynamic_context}")
    )

    logger.info(
        f"Dynamic context size: {dynamic_size_chars} chars (~{dynamic_size_tokens} tokens) | "
        f"NOT cached (changes per request)"
    )

    # Convert state messages to LangChain format
    for msg in messages_history:
        role = msg.get("role")
        content = msg.get("content", "")

        if role == "user":
            langchain_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            langchain_messages.append(AIMessage(content=content))
        else:
            logger.warning(
                f"Unknown message role: {role}",
                extra={"conversation_id": conversation_id}
            )

    # Step 2: Get LLM with tools
    llm_with_tools = get_llm_with_tools()

    # Log total prompt sizes and detect if booking state (v3.2 monitoring)
    total_prompt_tokens = cacheable_size_tokens + dynamic_size_tokens
    from agent.prompts import _detect_booking_state
    booking_state = _detect_booking_state(state)

    logger.info(
        f"Total prompt size: ~{total_prompt_tokens} tokens "
        f"({cacheable_size_tokens} cacheable + {dynamic_size_tokens} dynamic) | "
        f"Booking state: {booking_state}"
    )

    # Alert if prompt is unusually large (>4000 tokens = ~16KB)
    if total_prompt_tokens > 4000:
        logger.warning(
            f"⚠️ Prompt unusually large ({total_prompt_tokens} tokens, ~{total_prompt_tokens * 4} chars). "
            f"Check if contextual loading is working correctly. State: {booking_state}"
        )

    # Step 3: Invoke GPT-4.1-mini LLM with tools (first pass)
    try:
        response = await llm_with_tools.ainvoke(langchain_messages)

        logger.info(
            f"Claude response received",
            extra={
                "conversation_id": conversation_id,
                "has_tool_calls": bool(response.tool_calls),
                "tool_calls_count": len(response.tool_calls) if response.tool_calls else 0,
            }
        )

    except Exception as e:
        logger.error(
            f"Error invoking Claude LLM",
            extra={
                "conversation_id": conversation_id,
                "error": str(e),
            },
            exc_info=True
        )

        # Return error message to user
        return add_message(
            state,
            "assistant",
            "Lo siento, he tenido un problema técnico. El equipo tecnico lo solucionará lo antes posible. Una asistenta atenderá tu consulta lo antes posible."
        )

    # Step 4: Handle tool calls if any
    if response.tool_calls:
        logger.info(
            f"Executing {len(response.tool_calls)} tool call(s)",
            extra={
                "conversation_id": conversation_id,
                "tools": [tc["name"] for tc in response.tool_calls],
            }
        )

        # Add Claude's response with tool calls to message history
        langchain_messages.append(response)

        # Execute each tool call with state-aware validation
        for tool_call in response.tool_calls:
            tool_result, state_updates = await execute_tool_call(tool_call, state)

            # Apply state updates immediately
            for key, value in state_updates.items():
                state[key] = value
                logger.debug(
                    f"State updated: {key} = {value}",
                    extra={"conversation_id": conversation_id, "key": key}
                )

            # Add tool result to message history
            langchain_messages.append(
                ToolMessage(
                    content=tool_result,
                    tool_call_id=tool_call["id"]
                )
            )

        # Step 5: Get final response from Claude after tool execution
        try:
            final_response = await llm_with_tools.ainvoke(langchain_messages)

            logger.info(
                f"Claude final response received after tool execution",
                extra={
                    "conversation_id": conversation_id,
                    "response_preview": final_response.content[:100],
                }
            )

        except Exception as e:
            logger.error(
                f"Error invoking Claude LLM for final response",
                extra={
                    "conversation_id": conversation_id,
                    "error": str(e),
                },
                exc_info=True
            )

            # Return error message to user
            return add_message(
                state,
                "assistant",
                "Lo siento, he tenido un problema al procesar tu solicitud. ¿Podrías intentarlo de nuevo? 🌸"
            )

        assistant_response = final_response.content

    else:
        # No tool calls - use response content directly
        assistant_response = response.content

    # Step 6: Validate response is not blank/whitespace-only
    if not assistant_response or assistant_response.strip() == "":
        logger.error(
            f"Blank response detected from Claude",
            extra={
                "conversation_id": conversation_id,
                "response_content": repr(assistant_response),
                "had_tool_calls": bool(response.tool_calls),
            }
        )
        assistant_response = (
            "Lo siento, tuve un problema al procesar tu solicitud. "
            "¿Podrías intentarlo de nuevo? 🌸"
        )

    # Step 7: Check for escalation trigger
    # If escalate_to_human was called, mark escalation in state
    if response.tool_calls:
        for tool_call in response.tool_calls:
            if tool_call["name"] == "escalate_to_human":
                logger.info(
                    f"Escalation detected in tool calls",
                    extra={
                        "conversation_id": conversation_id,
                        "reason": tool_call["args"].get("reason"),
                    }
                )
                # Mark escalation in state
                updated_state = add_message(state, "assistant", assistant_response)
                updated_state["escalation_triggered"] = True
                updated_state["escalation_reason"] = tool_call["args"].get("reason")
                updated_state["last_node"] = "conversational_agent"
                updated_state["updated_at"] = datetime.now(ZoneInfo("Europe/Madrid"))
                return updated_state

    # Step 8: Update state with assistant response
    updated_state = add_message(state, "assistant", assistant_response)
    updated_state["last_node"] = "conversational_agent"
    updated_state["updated_at"] = datetime.now(ZoneInfo("Europe/Madrid"))

    logger.info(
        f"Conversational agent completed",
        extra={
            "conversation_id": conversation_id,
            "response_preview": assistant_response[:100],
        }
    )

    return updated_state

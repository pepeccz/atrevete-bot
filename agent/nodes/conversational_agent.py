"""
Conversational Agent Node - v4.0 FSM Hybrid Architecture.

This node integrates FSM (Finite State Machine) control with LLM intent extraction.
The FSM controls conversation flow while LLM handles NLU and response generation.

Model: openai/gpt-4.1-mini via OpenRouter (cost-optimized, automatic prompt caching)

Architecture (ADR-006):
    LLM (NLU)      → Interpreta INTENCIÓN + Genera LENGUAJE
    FSM Control    → Controla FLUJO + Valida PROGRESO + Decide TOOLS
    Tool Calls     → Ejecuta ACCIONES validadas

Flow:
1. Load FSM state from Redis
2. Extract intent using LLM (state-aware disambiguation)
3. Validate transition with FSM
4. Execute tools if FSM approves
5. Generate response based on FSM state
6. Persist FSM state

Tools available (8 consolidated):
- query_info, search_services, manage_customer, get_customer_history
- check_availability, find_next_available, book, escalate_to_human
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from agent.fsm import (
    BookingFSM,
    IntentType,
    ToolExecutionError,
    extract_intent,
    log_tool_execution,
    validate_tool_call,
)
from agent.prompts import load_contextual_prompt, load_stylist_context
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState
from agent.tools import (
    book,
    check_availability,
    escalate_to_human,
    find_next_available,
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

    logger.info("GPT-4.1-mini LLM initialized with 8 consolidated tools (v3.2) via OpenRouter")

    return llm_with_tools


async def execute_tool_call(
    tool_call: dict,
    state: ConversationState,
    fsm: BookingFSM | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Execute a single tool call with FSM-aware validation and return result plus state updates.

    This function implements FSM validation (Story 5-4) to ensure tools only execute
    when the FSM state permits. Validation includes:
    1. FSM state permission check
    2. Required data availability check
    3. Legacy state validation (customer_id, first_name for book())

    Args:
        tool_call: Tool call dict with 'name', 'args', and 'id' keys
        state: Current conversation state for validation
        fsm: Optional BookingFSM instance for FSM-aware validation

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
            "fsm_state": fsm.state.value if fsm else "no_fsm",
        }
    )

    # ============================================================================
    # FSM VALIDATION (Story 5-4)
    # ============================================================================
    if fsm is not None:
        validation = validate_tool_call(tool_name, fsm)
        if not validation.allowed:
            # Tool call rejected by FSM
            error_result = {
                "error": validation.error_code,
                "message": validation.error_message,
                "redirect": validation.redirect_message,
                "fsm_state": fsm.state.value,
                "instruction": (
                    f"⚠️ La herramienta '{tool_name}' no está disponible ahora. "
                    f"{validation.redirect_message}"
                ),
            }
            logger.warning(
                f"Tool call rejected by FSM | tool={tool_name} | state={fsm.state.value}",
                extra={
                    "tool_name": tool_name,
                    "fsm_state": fsm.state.value,
                    "error_code": validation.error_code,
                    "conversation_id": fsm.conversation_id,
                }
            )
            # Log the rejection
            log_tool_execution(tool_name, fsm, error_result, success=False, error=validation.error_code)
            return json.dumps(error_result, ensure_ascii=False, indent=2), state_updates

    # ============================================================================
    # PRE-EXECUTION VALIDATION
    # ============================================================================

    # Ensure customer exists before booking (auto-created in process_incoming_message)
    if tool_name == "book":
        customer_id = state.get("customer_id")
        if not customer_id:
            error_result = {
                "error": "MISSING_CUSTOMER_ID",
                "message": (
                    "❌ No se encontró customer_id en el estado. "
                    "El cliente debe estar registrado automáticamente en la primera interacción. "
                    "Esto es un error del sistema."
                ),
                "instruction": "Escala a humano - error de sistema."
            }
            logger.error(
                "book() called without customer_id - system error",
                extra={"customer_id": customer_id, "state_keys": list(state.keys())}
            )
            return json.dumps(error_result, ensure_ascii=False, indent=2), state_updates

        # Validate book() call includes required customer fields
        first_name = tool_args.get("first_name")
        if not first_name:
            error_result = {
                "error": "MISSING_CUSTOMER_NAME",
                "message": (
                    "❌ Debes recopilar el nombre del cliente antes de llamar a book(). "
                    "Pregunta al cliente su nombre y apellido primero (PASO 3)."
                ),
                "instruction": "Pregunta: '¿Me confirmas tu nombre y apellido para la reserva?'"
            }
            logger.warning(
                "book() called without first_name parameter",
                extra={"tool_args": tool_args}
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

        # Track successful booking creation
        if tool_name == "book" and isinstance(result, dict) and not result.get("error"):
            state_updates["appointment_created"] = True
            logger.info(
                "Appointment created successfully",
                extra={
                    "appointment_id": result.get("appointment_id"),
                    "customer_id": tool_args.get("customer_id")
                }
            )

        # Track service selection when search_services returns results
        if tool_name == "search_services" and isinstance(result, dict) and not result.get("error"):
            services_found = result.get("count", 0)
            if services_found > 0:
                state_updates["service_selected"] = True
                logger.info(
                    f"Service search successful ({services_found} results)",
                    extra={"services_count": services_found}
                )

        # Track slot selection when availability tools return results
        if tool_name in ["find_next_available", "check_availability"]:
            if isinstance(result, dict) and not result.get("error"):
                # Check if any slots were found
                slots_found = result.get("slots", [])
                if slots_found:
                    state_updates["slot_selected"] = True
                    logger.info(
                        f"Availability found ({len(slots_found)} slots)",
                        extra={"tool": tool_name, "slots_count": len(slots_found)}
                    )

        # Track customer data collection when manage_customer succeeds
        if tool_name == "manage_customer" and isinstance(result, dict) and not result.get("error"):
            # Check if customer was created or updated successfully
            if result.get("id") or result.get("success"):
                state_updates["customer_data_collected"] = True
                logger.info(
                    "Customer data collected/updated successfully",
                    extra={"customer_id": result.get("id")}
                )

        # Convert result to string for LangChain ToolMessage
        if isinstance(result, dict):
            result_str = json.dumps(result, ensure_ascii=False, indent=2)
        else:
            result_str = str(result)

        # Log successful tool execution with FSM context (Story 5-4 AC #6)
        if fsm is not None:
            log_tool_execution(tool_name, fsm, result, success=True)

        return result_str, state_updates

    except Exception as e:
        error_msg = f"Error executing tool {tool_name}: {str(e)}"
        logger.error(
            error_msg,
            extra={
                "tool_name": tool_name,
                "tool_args": tool_args,
                "error": str(e),
                "fsm_state": fsm.state.value if fsm else "no_fsm",
            },
            exc_info=True
        )

        # Log failed tool execution with FSM context (Story 5-4 AC #5, #6)
        if fsm is not None:
            log_tool_execution(tool_name, fsm, {}, success=False, error=str(e))

        return error_msg, state_updates


async def conversational_agent(state: ConversationState) -> dict[str, Any]:
    """
    Main conversational agent node with FSM hybrid architecture (v4.0).

    Integrates FSM control with LLM intent extraction:
    1. Load FSM state from Redis
    2. Extract intent using LLM (state-aware disambiguation)
    3. Validate transition with FSM
    4. Execute tools if FSM approves OR handle non-booking intents
    5. Generate response based on FSM state and transition result
    6. Persist FSM state to Redis

    Args:
        state: Current conversation state

    Returns:
        Updated state with assistant response added
    """
    conversation_id = state.get("conversation_id", "unknown")
    messages_history = state.get("messages", [])

    logger.info(
        "Conversational agent (v4.0 FSM) invoked",
        extra={
            "conversation_id": conversation_id,
            "messages_count": len(messages_history),
        }
    )

    # =========================================================================
    # STEP 0: Load FSM state from Redis
    # =========================================================================
    fsm = await BookingFSM.load(conversation_id)
    logger.info(
        f"FSM loaded | state={fsm.state.value} | collected_data={list(fsm.collected_data.keys())}",
        extra={"conversation_id": conversation_id, "fsm_state": fsm.state.value}
    )

    # =========================================================================
    # STEP 1: Extract intent using LLM (state-aware disambiguation)
    # =========================================================================
    # Get the last user message for intent extraction
    last_user_message = ""
    for msg in reversed(messages_history):
        if msg.get("role") == "user":
            last_user_message = msg.get("content", "")
            break

    if last_user_message:
        intent = await extract_intent(
            message=last_user_message,
            current_state=fsm.state,
            collected_data=fsm.collected_data,
            conversation_history=messages_history,
        )
        logger.info(
            f"Intent extracted | type={intent.type.value} | confidence={intent.confidence:.2f}",
            extra={
                "conversation_id": conversation_id,
                "intent_type": intent.type.value,
                "entities": list(intent.entities.keys()),
            }
        )
    else:
        # No user message to process - shouldn't happen but handle gracefully
        intent = None
        logger.warning(
            "No user message found for intent extraction",
            extra={"conversation_id": conversation_id}
        )

    # =========================================================================
    # STEP 2: FSM validates and handles transition
    # =========================================================================
    fsm_result = None
    fsm_context_for_llm = ""

    if intent:
        # Check if this is a non-booking intent (FAQ, GREETING, ESCALATE)
        non_booking_intents = {IntentType.FAQ, IntentType.GREETING, IntentType.ESCALATE, IntentType.UNKNOWN}

        if intent.type in non_booking_intents:
            # Non-booking intents don't affect FSM state
            logger.info(
                f"Non-booking intent ({intent.type.value}) - FSM state unchanged",
                extra={"conversation_id": conversation_id, "fsm_state": fsm.state.value}
            )
            fsm_context_for_llm = f"[FSM: {fsm.state.value}] Intent: {intent.type.value} (no transition)"
        else:
            # Booking intent - validate with FSM
            if fsm.can_transition(intent):
                fsm_result = fsm.transition(intent)
                await fsm.persist()
                logger.info(
                    f"FSM transition SUCCESS | new_state={fsm_result.new_state.value}",
                    extra={
                        "conversation_id": conversation_id,
                        "new_state": fsm_result.new_state.value,
                        "next_action": fsm_result.next_action,
                    }
                )
                fsm_context_for_llm = (
                    f"[FSM TRANSICIÓN EXITOSA] Estado: {fsm_result.new_state.value}\n"
                    f"Siguiente acción: {fsm_result.next_action}\n"
                    f"Datos recopilados: {fsm_result.collected_data}"
                )
            else:
                # Invalid transition - FSM explains what's missing
                fsm_result = fsm.transition(intent)  # This returns failure details
                logger.warning(
                    f"FSM transition REJECTED | errors={fsm_result.validation_errors}",
                    extra={
                        "conversation_id": conversation_id,
                        "errors": fsm_result.validation_errors,
                    }
                )
                fsm_context_for_llm = (
                    f"[FSM TRANSICIÓN RECHAZADA] Estado actual: {fsm.state.value}\n"
                    f"Intent intentado: {intent.type.value}\n"
                    f"Errores: {', '.join(fsm_result.validation_errors)}\n"
                    f"Guía al usuario amigablemente explicando qué falta."
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

    # Calculate earliest valid date, skipping closed days (weekends)
    # Start with 3 days minimum notice
    earliest_valid = now + timedelta(days=3)

    # Skip closed days (weekends: Saturday=5, Sunday=6)
    # If earliest_valid falls on weekend, move to next Monday
    while earliest_valid.weekday() in [5, 6]:  # 5=Saturday, 6=Sunday
        earliest_valid += timedelta(days=1)

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
- ID de cliente: {str(customer_id) if customer_id else "No registrado aún"}

⚠️ CRÍTICO: El teléfono ({customer_phone}) ya está disponible del WhatsApp.
NUNCA preguntes por el teléfono. Úsalo directamente cuando necesites llamar a manage_customer."""

    # Add FSM context for state-aware response generation
    fsm_state_context = f"""ESTADO FSM:
- Estado actual: {fsm.state.value}
- Datos recopilados: {fsm.collected_data if fsm.collected_data else "Ninguno"}
{fsm_context_for_llm if fsm_context_for_llm else ""}"""

    # Combine dynamic contexts
    dynamic_context = f"{temporal_context}\n\n{customer_context}\n\n{fsm_state_context}"

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
            "Claude response received",
            extra={
                "conversation_id": conversation_id,
                "has_tool_calls": bool(response.tool_calls),
                "tool_calls_count": len(response.tool_calls) if response.tool_calls else 0,
            }
        )

    except Exception as e:
        logger.error(
            "Error invoking Claude LLM",
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
            tool_result, state_updates = await execute_tool_call(tool_call, state, fsm)

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
                "Claude final response received after tool execution",
                extra={
                    "conversation_id": conversation_id,
                    "response_preview": final_response.content[:100],
                }
            )

        except Exception as e:
            logger.error(
                "Error invoking Claude LLM for final response",
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
            "Blank response detected from Claude",
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
    # If escalate_to_human was called, mark escalation in state and disable bot in Chatwoot
    if response.tool_calls:
        for tool_call in response.tool_calls:
            if tool_call["name"] == "escalate_to_human":
                escalation_reason = tool_call["args"].get("reason")
                logger.info(
                    "Escalation detected in tool calls",
                    extra={
                        "conversation_id": conversation_id,
                        "reason": escalation_reason,
                    }
                )

                # Disable bot in Chatwoot so human team can take over
                try:
                    from shared.chatwoot_client import ChatwootClient

                    chatwoot = ChatwootClient()
                    await chatwoot.update_conversation_attributes(
                        conversation_id=int(conversation_id),
                        attributes={"atencion_automatica": False}
                    )
                    logger.info(
                        f"Bot disabled for conversation {conversation_id} (escalated to human)",
                        extra={
                            "conversation_id": conversation_id,
                            "reason": escalation_reason,
                        }
                    )
                except Exception as e:
                    # Log error but don't block - the escalation message should still be sent
                    logger.error(
                        f"Failed to disable bot in Chatwoot for conversation {conversation_id}: {e}",
                        extra={
                            "conversation_id": conversation_id,
                            "error": str(e),
                        },
                        exc_info=True,
                    )

                # Mark escalation in state
                updated_state = add_message(state, "assistant", assistant_response)
                updated_state["escalation_triggered"] = True
                updated_state["escalation_reason"] = escalation_reason
                updated_state["last_node"] = "conversational_agent"
                updated_state["updated_at"] = datetime.now(ZoneInfo("Europe/Madrid"))
                return updated_state

    # Step 8: Detect booking confirmation from user
    # If in BOOKING_CONFIRMATION state and user gives affirmative response, mark as confirmed
    from agent.prompts import _detect_booking_state
    current_state_type = _detect_booking_state(state)

    if current_state_type == "BOOKING_CONFIRMATION":
        # Read last user message from message history (user_message field is cleared by process_incoming_message node)
        messages = state.get("messages", [])
        last_user_message = ""
        if messages:
            # Find the last message with role="user"
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    last_user_message = msg.get("content", "")

        user_message = last_user_message.lower()

        # List of affirmative keywords
        affirmative_keywords = [
            "sí", "si", "adelante", "confirmo", "perfecto", "ok", "vale", "dale",
            "correcto", "exacto", "afirmativo", "confirmar", "procede", "proceder"
        ]

        # Check if user message contains affirmative intent
        if user_message and any(keyword in user_message for keyword in affirmative_keywords):
            logger.info(
                "User confirmed booking",
                extra={
                    "conversation_id": conversation_id,
                    "user_message": user_message[:50]  # Log first 50 chars
                }
            )
            # Update state with confirmation flag BEFORE adding message
            state["booking_confirmed"] = True

    # Step 9: Update state with assistant response
    updated_state = add_message(state, "assistant", assistant_response)
    updated_state["last_node"] = "conversational_agent"
    updated_state["updated_at"] = datetime.now(ZoneInfo("Europe/Madrid"))

    logger.info(
        "Conversational agent completed",
        extra={
            "conversation_id": conversation_id,
            "response_preview": assistant_response[:100],
        }
    )

    return updated_state

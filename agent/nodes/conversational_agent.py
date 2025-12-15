"""
Conversational Agent Node - v5.0 Prescriptive FSM Architecture.

This node implements the v5.0 prescriptive architecture where:
- FSM prescribes exact tools to call (no LLM tool decisions)
- LLM handles only: (1) intent extraction (NLU), (2) response formatting (generation)
- IntentRouter separates booking (FSM-prescribed) from non-booking (LLM conversational)

Model: openai/gpt-4.1-mini via OpenRouter (cost-optimized, automatic prompt caching)

Architecture (v5.0 - ADR-013):
    LLM (NLU)          → Extract intent only
    FSM Control        → Validate transition + prescribe actions
    IntentRouter       → Route booking vs non-booking
        ├─ BookingHandler     → FSM prescribes tools (0% hallucinations)
        └─ NonBookingHandler  → LLM with safe tools (FAQs, escalate)

Flow:
1. Load FSM state from checkpoint
2. Check for auto-escalation (error_count >= threshold)
3. Extract intent using LLM (state-aware disambiguation)
4. Validate transition with FSM
5. Route via IntentRouter (NEW - replaces LLM tool binding)
6. Persist FSM state
7. Reset error_count on success

Changes from v4.0:
- REMOVED: LLM tool binding (replaced with FSM prescription)
- REMOVED: tool_validation.py (997 lines of defensive code)
- REMOVED: response_validator.py (reactive validation)
- ADDED: IntentRouter with BookingHandler + NonBookingHandler
- ADDED: Auto-escalation after consecutive errors (error_count >= 3)
- REDUCED: 1,583 lines → ~400 lines (75% reduction)
"""

import asyncio
import logging
from typing import Any

import pybreaker
from langchain_openai import ChatOpenAI

from agent.fsm import BookingFSM, BookingState
from shared.circuit_breaker import call_with_breaker, openrouter_breaker
from agent.fsm.intent_extractor import extract_intent
from agent.fsm.models import Intent, IntentType
from agent.routing import IntentRouter
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState
from shared.config import get_settings

logger = logging.getLogger(__name__)

# Auto-escalation threshold: after this many consecutive errors, escalate to human
AUTO_ESCALATION_THRESHOLD = 3


async def conversational_agent(state: ConversationState) -> dict[str, Any]:
    """
    Main conversational agent node (v5.0 prescriptive architecture).

    This is the core orchestrator that:
    1. Loads FSM state
    2. Extracts intent (LLM NLU only)
    3. Validates FSM transition
    4. Routes to appropriate handler (booking vs non-booking)
    5. Persists FSM state

    Args:
        state: Current conversation state

    Returns:
        Updated state with assistant response
    """
    settings = get_settings()
    conversation_id = state.get("conversation_id", "unknown")
    messages = state.get("messages", [])

    if not messages:
        logger.warning(f"No messages in state | conversation_id={conversation_id}")
        return state

    # Get last user message
    last_message = messages[-1]
    if last_message.get("role") != "user":
        logger.warning(
            f"Last message is not from user | conversation_id={conversation_id} | "
            f"role={last_message.get('role')}"
        )
        return state

    user_message = last_message.get("content", "")

    logger.info(
        f"Processing message | conversation_id={conversation_id} | "
        f"message_length={len(user_message)}"
    )

    # ============================================================================
    # STEP 0: Check for auto-escalation (error_count >= threshold)
    # ============================================================================
    # If too many consecutive errors have occurred, auto-escalate to human
    # This prevents the bot from getting stuck in error loops

    error_count = state.get("error_count", 0)

    if error_count >= AUTO_ESCALATION_THRESHOLD:
        logger.warning(
            f"Auto-escalating due to error_count | conversation_id={conversation_id} | "
            f"error_count={error_count} | threshold={AUTO_ESCALATION_THRESHOLD}"
        )

        # Trigger auto-escalation (fire-and-forget)
        from agent.services.escalation_service import trigger_escalation

        asyncio.create_task(
            trigger_escalation(
                reason="auto_escalation",
                conversation_id=conversation_id,
                customer_phone=state.get("customer_phone", ""),
                conversation_context=messages[-5:] if messages else [],
            )
        )

        response_text = (
            "Disculpa, estoy teniendo dificultades tecnicas. "
            "Te paso con un companero humano que te ayudara enseguida."
        )

        # Reset error count and set escalation flags
        state["error_count"] = 0
        state["escalation_triggered"] = True
        state["escalation_reason"] = "auto_escalation"

        return add_message(state, "assistant", response_text)

    # ============================================================================
    # STEP 1: Load FSM from checkpoint (ADR-011: single source of truth)
    # ============================================================================

    fsm_state_dict = state.get("fsm_state")
    if fsm_state_dict:
        fsm = BookingFSM.from_dict(conversation_id, fsm_state_dict)
        logger.info(
            f"FSM loaded | conversation_id={conversation_id} | "
            f"state={fsm.state.value} | "
            f"has_data={bool(fsm.collected_data)}"
        )
    else:
        # First message - initialize FSM
        fsm = BookingFSM(conversation_id)
        logger.info(f"FSM initialized | conversation_id={conversation_id}")

    # Inject customer_id from ConversationState into FSM collected_data
    # customer_id is set in process_incoming_message via ensure_customer_exists()
    if state.get("customer_id"):
        fsm._collected_data["customer_id"] = state["customer_id"]
        logger.debug(
            f"Injected customer_id into FSM | conversation_id={conversation_id} | "
            f"customer_id={state['customer_id']}"
        )

    # ============================================================================
    # STEP 2: Extract intent (LLM NLU only - no tool decisions)
    # ============================================================================

    try:
        intent = await extract_intent(
            message=user_message,
            current_state=fsm.state,
            collected_data=fsm.collected_data,
            conversation_history=messages,
        )

        logger.info(
            f"Intent extracted | conversation_id={conversation_id} | "
            f"type={intent.type.value} | "
            f"entities={list(intent.entities.keys())} | "
            f"confidence={intent.confidence:.2f}"
        )

        # Store cleaned service_query when starting a booking
        # Uses LLM-extracted keywords (e.g., "mechas" from "Holaaa quiero hacerme las mechas")
        # Falls back to user_message if LLM didn't extract service_query
        if intent.type == IntentType.START_BOOKING:
            # Prefer LLM-cleaned query, fallback to raw message
            service_query = intent.service_query or user_message
            fsm._collected_data["service_query"] = service_query
            logger.info(
                f"Stored service_query | conversation_id={conversation_id} | "
                f"query={service_query[:50]}... | source={'llm' if intent.service_query else 'fallback'}"
            )

    except (ValueError, KeyError) as e:
        # Intent parsing error (expected - malformed data, missing fields)
        logger.warning(
            f"Intent parsing failed | conversation_id={conversation_id} | error={str(e)}"
        )
        # Fallback: treat as unknown intent
        intent = Intent(type=IntentType.UNKNOWN, raw_message=user_message)
    except AttributeError as e:
        # Configuration error (unexpected - LLM client misconfigured)
        logger.error(
            f"Intent extraction configuration error | conversation_id={conversation_id} | "
            f"error={str(e)}",
            exc_info=True,
        )
        raise  # Re-raise to surface configuration issues
    except Exception as e:
        # Unexpected error (network, LLM service down, etc.)
        logger.critical(
            f"Intent extraction crashed | conversation_id={conversation_id} | error={str(e)}",
            exc_info=True,
        )
        raise  # Don't silently continue on unexpected errors

    # ============================================================================
    # STEP 2b: Check name_confirmation_pending BEFORE any routing (v6.1 FIX)
    # ============================================================================
    # If user hasn't confirmed their name yet, route to NonBookingHandler
    # regardless of what intent they expressed (name confirmation has priority)

    name_confirmation_pending = state.get("name_confirmation_pending", False)
    if name_confirmation_pending:
        logger.info(
            f"Name confirmation pending - routing to NonBookingHandler | "
            f"conversation_id={conversation_id} | "
            f"original_intent={intent.type.value}"
        )

        # Create LLM client for NonBookingHandler
        llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY,
            temperature=0.3,
            request_timeout=30.0,
            max_retries=2,
        )

        # Import handler here to avoid circular imports
        from agent.routing.non_booking_handler import NonBookingHandler

        # Route to name confirmation handler
        handler = NonBookingHandler(state, llm, fsm)
        response_text, state_updates = await handler._handle_name_confirmation(intent)

        # Apply state updates from handler
        if state_updates:
            for key, value in state_updates.items():
                state[key] = value
            logger.debug(
                f"Name confirmation state updates applied | "
                f"conversation_id={conversation_id} | "
                f"updates={list(state_updates.keys())}"
            )

        # Persist FSM state (unchanged for name confirmation)
        state["fsm_state"] = fsm.to_dict()

        return add_message(state, "assistant", response_text)

    # ============================================================================
    # STEP 3: FSM validates and executes transition (BOOKING INTENTS ONLY)
    # ============================================================================

    # Validate intent type is a valid IntentType enum member
    if not isinstance(intent.type, IntentType):
        logger.error(
            f"Invalid intent type | conversation_id={conversation_id} | "
            f"type={type(intent.type)} | value={intent.type}"
        )
        # Fallback: treat as unknown intent
        intent = Intent(type=IntentType.UNKNOWN, raw_message=user_message)

    is_booking_intent = intent.type in IntentRouter.BOOKING_INTENTS

    if is_booking_intent:
        # Only validate FSM transition for booking intents
        try:
            result = await fsm.transition(intent)

            if result.success:
                logger.info(
                    f"FSM transition successful | conversation_id={conversation_id} | "
                    f"old_state={fsm.state.value} | "
                    f"new_state={result.new_state.value} | "
                    f"intent={intent.type.value}"
                )
            else:
                logger.warning(
                    f"FSM transition failed | conversation_id={conversation_id} | "
                    f"state={fsm.state.value} | "
                    f"intent={intent.type.value} | "
                    f"errors={result.validation_errors}"
                )

                # Transition rejected - generate helpful error message
                error_message = _generate_transition_error_message(fsm, intent, result)

                # Persist FSM (unchanged)
                state["fsm_state"] = fsm.to_dict()

                return add_message(state, "assistant", error_message)

        except ValueError as e:
            # Validation error (expected - invalid state transition, missing data)
            logger.warning(
                f"FSM validation error | conversation_id={conversation_id} | error={str(e)}"
            )

            # Generate helpful validation error message
            error_message = (
                f"Disculpa, no puedo procesar eso ahora: {str(e)}. "
                "¿Podrías intentarlo de nuevo?"
            )

            # Persist FSM (unchanged)
            state["fsm_state"] = fsm.to_dict()

            return add_message(state, "assistant", error_message)

        except AttributeError as e:
            # Configuration error (unexpected - FSM misconfigured, missing attributes)
            logger.error(
                f"FSM configuration error | conversation_id={conversation_id} | error={str(e)}",
                exc_info=True,
            )
            raise  # Re-raise to surface configuration issues

        except Exception as e:
            # Unexpected error (database down, network issues, etc.)
            logger.critical(
                f"FSM transition crashed | conversation_id={conversation_id} | error={str(e)}",
                exc_info=True,
            )
            raise  # Don't silently continue on unexpected errors
    else:
        # Non-booking intent - skip FSM transition, go directly to routing
        logger.info(
            f"Non-booking intent detected | conversation_id={conversation_id} | "
            f"intent={intent.type.value} | skipping FSM transition"
        )

    # ============================================================================
    # STEP 4: Route intent to appropriate handler (v5.0 NEW ARCHITECTURE)
    # ============================================================================
    # This replaces the old LLM tool binding with FSM-prescribed actions

    try:
        # Create LLM client for response generation
        llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY,
            temperature=0.3,  # Creative but controlled
            request_timeout=30.0,  # 30s timeout for conversation
            max_retries=2,  # Retry 2x on transient failures
        )

        # Route to appropriate handler (wrapped with circuit breaker)
        # BookingHandler: FSM prescribes tools (prescriptive)
        # NonBookingHandler: LLM decides from safe tools (conversational)
        # Circuit breaker protects against OpenRouter outages
        response_text, state_updates = await call_with_breaker(
            openrouter_breaker,
            IntentRouter.route,
            intent=intent,
            fsm=fsm,
            state=state,
            llm=llm,
        )

        # Apply state updates from handler (e.g., pending_decline state)
        if state_updates:
            for key, value in state_updates.items():
                state[key] = value
            logger.debug(
                f"State updates applied | conversation_id={conversation_id} | "
                f"updates={list(state_updates.keys())}"
            )

        logger.info(
            f"Response generated | conversation_id={conversation_id} | "
            f"length={len(response_text)} | "
            f"fsm_state={fsm.state.value}"
        )

    except pybreaker.CircuitBreakerError:
        # Circuit is OPEN - OpenRouter is down, fail fast and escalate
        logger.error(
            f"OpenRouter circuit breaker OPEN | conversation_id={conversation_id} | "
            f"escalating to human"
        )

        # Trigger escalation (fire-and-forget)
        from agent.services.escalation_service import trigger_escalation

        asyncio.create_task(
            trigger_escalation(
                reason="technical_error",
                conversation_id=conversation_id,
                customer_phone=state.get("customer_phone", ""),
                conversation_context=messages[-5:] if messages else [],
            )
        )

        response_text = (
            "Disculpa, estoy teniendo problemas tecnicos en este momento. "
            "Te paso con un companero humano que te ayudara enseguida."
        )
        # Mark for escalation so Chatwoot can route to human agent
        state["escalated"] = True
        state["escalation_triggered"] = True
        state["escalation_reason"] = "technical_error"
        # Increment error count for tracking
        state["error_count"] = error_count + 1

    except (ValueError, KeyError) as e:
        # Handler execution error (expected - invalid tool args, missing data)
        logger.warning(
            f"Handler execution error | conversation_id={conversation_id} | error={str(e)}"
        )

        # Fallback response
        response_text = _generate_fallback_response(fsm)
        # Increment error count for potential auto-escalation
        state["error_count"] = error_count + 1

    except AttributeError as e:
        # Configuration error (unexpected - LLM/handler misconfigured)
        logger.error(
            f"Response generation configuration error | conversation_id={conversation_id} | "
            f"error={str(e)}",
            exc_info=True,
        )

        # Fallback response for configuration errors (don't crash user session)
        response_text = _generate_fallback_response(fsm)
        # Increment error count for potential auto-escalation
        state["error_count"] = error_count + 1

    except Exception as e:
        # Unexpected error (network, database, tool execution failure)
        logger.critical(
            f"Response generation crashed | conversation_id={conversation_id} | "
            f"error={str(e)} | intent={intent.type.value}",
            exc_info=True,
        )

        # Fallback response (avoid crashing the conversation)
        response_text = _generate_fallback_response(fsm)
        # Increment error count for potential auto-escalation
        state["error_count"] = error_count + 1

    # ============================================================================
    # STEP 5: Reset error count on successful response
    # ============================================================================
    # Only reset if we didn't encounter an error in this iteration
    # (error handlers already increment error_count, so if it's unchanged, reset it)

    if state.get("error_count", 0) == error_count:
        # No error occurred in this iteration - reset error count
        state["error_count"] = 0

    # ============================================================================
    # STEP 6: Persist FSM state to checkpoint
    # ============================================================================

    state["fsm_state"] = fsm.to_dict()

    logger.info(
        f"FSM persisted | conversation_id={conversation_id} | "
        f"state={fsm.state.value} | "
        f"data_fields={list(fsm.collected_data.keys())} | "
        f"error_count={state.get('error_count', 0)}"
    )

    # ============================================================================
    # STEP 7: Return updated state with response
    # ============================================================================

    return add_message(state, "assistant", response_text)


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================


def _generate_transition_error_message(fsm: BookingFSM, intent, result) -> str:
    """
    Generate helpful error message when FSM transition fails.

    Args:
        fsm: Current FSM instance
        intent: User intent that was rejected
        result: FSM transition result with validation errors

    Returns:
        User-friendly error message
    """
    # Get current state
    state = fsm.state

    # Common error scenarios
    if intent.type == IntentType.CONFIRM_SERVICES and state == BookingState.SERVICE_SELECTION:
        if not fsm.collected_data.get("services"):
            return (
                "Para continuar, primero necesito saber qué servicio te gustaría. "
                "¿Me puedes decir qué servicio necesitas?"
            )

    if intent.type == IntentType.SELECT_SLOT and state == BookingState.SLOT_SELECTION:
        if not fsm.collected_data.get("slot"):
            return (
                "Necesito que elijas un horario de los disponibles. "
                "¿Cuál de los horarios que te mostré prefieres?"
            )

    # Generic helpful message
    validation_errors = ", ".join(result.validation_errors) if result.validation_errors else "datos incompletos"

    return (
        f"Disculpa, no puedo procesar eso ahora. "
        f"Estamos en el paso de {state.value}. "
        f"¿Podrías proporcionarme la información necesaria? ({validation_errors})"
    )


def _generate_fallback_response(fsm: BookingFSM) -> str:
    """
    Generate generic fallback response when everything else fails.

    Args:
        fsm: Current FSM instance

    Returns:
        Generic helpful message based on FSM state
    """
    state = fsm.state

    fallback_messages = {
        BookingState.IDLE: (
            "¡Hola! Soy Maite, tu asistente de la Peluquería Atrévete. "
            "¿En qué puedo ayudarte? Puedo ayudarte a reservar una cita, "
            "consultar servicios, horarios, o responder tus preguntas."
        ),
        BookingState.SERVICE_SELECTION: (
            "¿Qué servicio te gustaría? Puedo mostrarte nuestros servicios disponibles."
        ),
        BookingState.STYLIST_SELECTION: (
            "¿Con qué estilista prefieres tu cita? Puedo mostrarte nuestros estilistas disponibles."
        ),
        BookingState.SLOT_SELECTION: (
            "¿Para qué día y hora te gustaría la cita? Puedo mostrarte horarios disponibles."
        ),
        BookingState.CUSTOMER_DATA: (
            "¿A qué nombre y apellidos agendo la reserva?"
        ),
        BookingState.CONFIRMATION: (
            "¿Confirmas la reserva con los datos que tenemos?"
        ),
        BookingState.BOOKED: (
            "Tu cita ha sido confirmada. ¿Hay algo más en lo que pueda ayudarte?"
        ),
    }

    return fallback_messages.get(
        state,
        "Disculpa, ha ocurrido un error. ¿Podrías intentarlo de nuevo?"
    )

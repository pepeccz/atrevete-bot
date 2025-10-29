"""
Intent classification nodes for LangGraph conversation flow.

This module contains nodes for:
- Extracting customer intent from messages using Claude
- Classifying intent into routing categories
- Detecting indecision patterns in customer messages (Story 3.5)
- Offering free consultation for indecisive customers (Story 3.5)
"""

import logging
from typing import Any, Literal
from uuid import UUID

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

from agent.state.helpers import add_message, format_llm_messages_with_summary
from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)

def get_llm() -> ChatAnthropic:
    """
    Get or initialize Claude LLM for intent classification.

    Factory function to enable dependency injection for testing.
    """
    return ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0)


async def extract_intent(state: ConversationState, llm: ChatAnthropic | None = None) -> dict[str, Any]:
    """
    Extract customer intent from message using Claude LLM.

    Analyzes the most recent customer message and classifies intent into one of:
    - booking: Nueva cita
    - modification: Cambiar cita existente
    - cancellation: Cancelar cita
    - inquiry: Pregunta general
    - faq: Pregunta frecuente
    - greeting_only: Solo saludo sin solicitud
    - usual_service: "Lo de siempre"

    Args:
        state: Current conversation state with messages
        llm: Optional ChatAnthropic instance for testing (uses get_llm() if None)

    Returns:
        dict: State updates with current_intent and optional greeting message
    """
    # Use provided LLM or get default instance
    if llm is None:
        llm = get_llm()

    conversation_id = state.get("conversation_id")
    messages = state.get("messages", [])
    customer_name = state.get("customer_name", "")

    try:
        # Extract first name for personalized messages
        first_name = customer_name.split()[0] if customer_name else "Cliente"

        # If no messages, default to greeting_only
        if not messages:
            logger.info(
                f"No messages found, defaulting to greeting_only intent",
                extra={"conversation_id": conversation_id}
            )
            return {"current_intent": "greeting_only"}

        # Extract most recent user message
        user_messages = [msg for msg in messages if isinstance(msg, HumanMessage)]
        if not user_messages:
            logger.warning(
                f"No user messages found in state",
                extra={"conversation_id": conversation_id}
            )
            return {"current_intent": "greeting_only"}

        latest_user_message = user_messages[-1].content

        logger.info(
            f"Extracting intent from user message",
            extra={"conversation_id": conversation_id, "message_preview": latest_user_message[:50]}
        )

        # Use Claude to classify intent
        classification_prompt = f"""Analiza el mensaje del cliente y clasifica su intención en una de:
- booking: nueva cita
- modification: cambiar cita existente
- cancellation: cancelar cita
- inquiry: pregunta general
- faq: pregunta frecuente
- greeting_only: solo saludo sin solicitud clara
- usual_service: "lo de siempre" o solicitud de servicio habitual

Mensaje: "{latest_user_message}"

Devuelve SOLO el intent como texto, sin puntuación ni explicaciones."""

        # Format messages with conversation summary if present
        llm_messages = format_llm_messages_with_summary(state, classification_prompt)
        llm_response = await llm.ainvoke(llm_messages)
        intent = llm_response.content.strip().lower()

        # Normalize intent (remove any punctuation or whitespace)
        intent = intent.replace(".", "").replace(",", "").strip()

        logger.info(
            f"Intent classified: {intent}",
            extra={"conversation_id": conversation_id, "intent": intent}
        )

        # Handle greeting_only intent - generate personalized greeting
        if intent == "greeting_only":
            greeting_text = f"¡Hola, {first_name}! Soy Maite 🌸. ¿En qué puedo ayudarte hoy?"
            updated_state = add_message(state, "assistant", greeting_text)

            logger.info(
                f"Generated greeting_only response",
                extra={"conversation_id": conversation_id}
            )

            return {
                "current_intent": intent,
                "messages": updated_state["messages"],
                "updated_at": updated_state["updated_at"],
            }

        # Handle non-greeting intents - add acknowledgment message
        else:
            acknowledgment_text = f"¡Hola de nuevo, {first_name}! 😊"
            updated_state = add_message(state, "assistant", acknowledgment_text)

            logger.info(
                f"Generated acknowledgment for {intent} intent",
                extra={"conversation_id": conversation_id, "intent": intent}
            )

            return {
                "current_intent": intent,
                "messages": updated_state["messages"],
                "updated_at": updated_state["updated_at"],
            }

    except Exception as e:
        logger.error(
            f"Error in extract_intent: {e}",
            extra={"conversation_id": conversation_id},
            exc_info=True
        )
        return {
            "current_intent": "inquiry",  # Default to inquiry on error
            "error_count": state.get("error_count", 0) + 1,
        }


# ============================================================================
# Indecision Detection & Consultation Offering (Story 3.5)
# ============================================================================


class IndecisionClassification(BaseModel):
    """
    Pydantic model for structured indecision detection output.

    Used with Claude's structured output API to analyze customer messages
    for indecision patterns when comparing or inquiring about services.
    """
    is_indecisive: bool = Field(
        description="Whether customer is indecisive about service choice"
    )
    confidence: float = Field(
        description="Confidence score 0.0-1.0 for indecision classification"
    )
    indecision_type: Literal["service_choice", "treatment_comparison", "price_comparison", "none"] = Field(
        description="Type of indecision detected"
    )
    detected_services: list[str] = Field(
        default_factory=list,
        description="Services customer is comparing or asking about"
    )


async def detect_indecision(
    state: ConversationState,
    llm: ChatAnthropic | None = None
) -> dict[str, Any]:
    """
    Detect indecision patterns in customer message using Claude structured output.

    Analyzes customer message for signs of uncertainty about service selection,
    such as comparing services, asking for recommendations, or expressing doubts.

    Indecision patterns include:
    - "¿cuál recomiendas?" / "cual me recomiendas"
    - "no sé si..." / "no se cual elegir"
    - "¿qué diferencia hay?" / "diferencias entre"
    - "no estoy seguro/a" / "tengo dudas"
    - "¿cuál es mejor?" / "que es mejor para mi"

    Args:
        state: Current conversation state with customer messages
        llm: Optional ChatAnthropic instance for testing (uses get_llm() if None)

    Returns:
        dict: State updates with indecision detection results:
            - indecision_detected: bool (True if confidence > 0.7)
            - confidence: float (0.0-1.0)
            - indecision_type: str
            - detected_services: list[str]

    Example:
        >>> state = {"messages": [...], "conversation_id": "123"}
        >>> result = await detect_indecision(state)
        >>> result["indecision_detected"]  # True or False
        >>> result["confidence"]  # 0.85
    """
    # Use provided LLM or get default instance
    if llm is None:
        llm = get_llm()

    conversation_id = state.get("conversation_id")
    customer_id = state.get("customer_id")
    messages = state.get("messages", [])

    try:
        # Extract most recent user message
        user_messages = [msg for msg in messages if isinstance(msg, HumanMessage)]
        if not user_messages:
            logger.debug(
                f"No user messages found for indecision detection",
                extra={"conversation_id": conversation_id}
            )
            return {
                "indecision_detected": False,
                "confidence": 0.0,
                "indecision_type": "none",
                "detected_services": []
            }

        latest_user_message = user_messages[-1].content

        logger.info(
            f"Analyzing message for indecision patterns",
            extra={
                "conversation_id": conversation_id,
                "customer_id": str(customer_id) if customer_id else None,
                "message_preview": latest_user_message[:50]
            }
        )

        # Build indecision detection prompt
        indecision_prompt = f"""Analiza el siguiente mensaje del cliente para detectar indecisión sobre la elección de servicios de peluquería o estética.

Mensaje del cliente: "{latest_user_message}"

PATRONES DE INDECISIÓN EXPLÍCITA (alta confianza):
- "¿cuál recomiendas?" / "cual me recomiendas"
- "no sé si..." / "no se cual elegir"
- "¿qué diferencia hay?" / "diferencias entre"
- "no estoy seguro/a" / "tengo dudas"
- "¿cuál es mejor?" / "que es mejor para mi"

PATRONES DE INDECISIÓN IMPLÍCITA (confianza media-alta):
- Comparar múltiples servicios sin elegir uno
- Preguntar detalles sobre diferencias entre servicios
- Expresar preocupación sobre adecuación del servicio
- Solicitar recomendaciones basadas en tipo de cabello/piel

NO ES INDECISIÓN (confianza baja):
- Solicitud clara de un servicio específico: "quiero mechas"
- Preguntas de precio únicamente: "¿cuánto cuesta?"
- Consultas sobre horarios: "¿abrís los sábados?"
- Reserva directa: "reserve corte para el viernes"
- Gestión de cita existente: "tengo cita mañana"

Clasifica el mensaje y proporciona:
1. is_indecisive: true si detectas indecisión, false si no
2. confidence: puntuación 0.0-1.0 (>0.7 para indecisión clara)
3. indecision_type: tipo de indecisión o "none"
4. detected_services: lista de servicios mencionados o comparados"""

        # Get structured output from Claude
        structured_llm = llm.with_structured_output(IndecisionClassification)
        classification = await structured_llm.ainvoke([HumanMessage(content=indecision_prompt)])

        # Log detection results
        if classification.is_indecisive and classification.confidence > 0.7:
            logger.info(
                f"Indecision detected: type={classification.indecision_type}, confidence={classification.confidence}",
                extra={
                    "conversation_id": conversation_id,
                    "customer_id": str(customer_id) if customer_id else None,
                    "indecision_type": classification.indecision_type,
                    "confidence": classification.confidence,
                    "detected_services": classification.detected_services
                }
            )
        else:
            logger.debug(
                f"No indecision detected: confidence={classification.confidence}",
                extra={
                    "conversation_id": conversation_id,
                    "customer_id": str(customer_id) if customer_id else None,
                    "confidence": classification.confidence
                }
            )

        # Return state updates
        return {
            "indecision_detected": classification.is_indecisive and classification.confidence > 0.7,
            "confidence": classification.confidence,
            "indecision_type": classification.indecision_type,
            "detected_services": classification.detected_services,
        }

    except Exception as e:
        logger.exception(
            f"Error in detect_indecision: {e}",
            extra={
                "conversation_id": conversation_id,
                "customer_id": str(customer_id) if customer_id else None
            }
        )
        # Return safe defaults on error
        return {
            "indecision_detected": False,
            "confidence": 0.0,
            "indecision_type": "none",
            "detected_services": [],
            "error_count": state.get("error_count", 0) + 1,
        }


async def offer_consultation(state: ConversationState) -> dict[str, Any]:
    """
    Offer free consultation when indecision is detected.

    Retrieves the "CONSULTA GRATUITA" service from database and generates
    a personalized consultation offer message based on the type of indecision
    detected (service choice, treatment comparison, price comparison).

    Response format follows Scenario 8:
    "¿Quieres que reserve una **consulta gratuita de 15 minutos** antes del
    servicio para que mi compañera te asesore en persona sobre cuál se adapta
    mejor a {personalization}?"

    Personalization varies by indecision_type:
    - service_choice → "tus necesidades"
    - treatment_comparison → "tu cabello" or "tu piel"
    - price_comparison → "tu presupuesto"

    Args:
        state: Current conversation state with indecision detection results

    Returns:
        dict: State updates with consultation offer:
            - consultation_offered: bool (True if offer presented)
            - consultation_service_id: UUID (consultation service ID)
            - bot_response: str (formatted consultation offer message)
            - messages: updated messages with consultation offer appended

    Example:
        >>> state = {"indecision_detected": True, "indecision_type": "treatment_comparison"}
        >>> result = await offer_consultation(state)
        >>> result["consultation_offered"]  # True
        >>> result["bot_response"]  # Contains consultation offer
    """
    from agent.tools.booking_tools import get_service_by_name

    conversation_id = state.get("conversation_id")
    customer_id = state.get("customer_id")
    indecision_type = state.get("indecision_type", "service_choice")
    detected_services = state.get("detected_services", [])

    try:
        logger.info(
            f"Offering consultation for indecision",
            extra={
                "conversation_id": conversation_id,
                "customer_id": str(customer_id) if customer_id else None,
                "indecision_type": indecision_type
            }
        )

        # Query CONSULTA GRATUITA service (exact match, case-insensitive)
        consultation = await get_service_by_name("CONSULTA GRATUITA", fuzzy=False)

        if consultation is None:
            logger.error(
                "CONSULTA GRATUITA service not found in database",
                extra={"conversation_id": conversation_id}
            )
            # Fallback: proceed with normal service selection
            return {
                "consultation_offered": False,
                "error_count": state.get("error_count", 0) + 1,
            }

        # Verify consultation service properties
        if consultation.duration_minutes != 15 or consultation.price_euros != 0 or consultation.requires_advance_payment:
            logger.warning(
                f"CONSULTA GRATUITA service has unexpected properties: duration={consultation.duration_minutes}, price={consultation.price_euros}, requires_payment={consultation.requires_advance_payment}",
                extra={"conversation_id": conversation_id}
            )

        # Personalize consultation offer based on indecision type
        personalizations = {
            "service_choice": "tus necesidades",
            "treatment_comparison": "tu cabello" if "Hairdressing" in str(consultation.category) else "tu piel",
            "price_comparison": "tu presupuesto",
            "none": "tus necesidades"  # Fallback
        }

        personalization = personalizations.get(indecision_type, "tus necesidades")

        # Build consultation offer message (following Scenario 8 format)
        consultation_message = (
            f"¿Quieres que reserve una **consulta gratuita de 15 minutos** "
            f"antes del servicio para que mi compañera te asesore en persona "
            f"sobre cuál se adapta mejor a {personalization}? 🌸"
        )

        # Add message to state
        updated_state = add_message(state, "assistant", consultation_message)

        logger.info(
            f"Consultation offered: service_id={consultation.id}",
            extra={
                "conversation_id": conversation_id,
                "customer_id": str(customer_id) if customer_id else None,
                "consultation_service_id": str(consultation.id),
                "detected_services": detected_services
            }
        )

        return {
            "consultation_offered": True,
            "consultation_service_id": consultation.id,
            "bot_response": consultation_message,
            "messages": updated_state["messages"],
            "updated_at": updated_state["updated_at"],
        }

    except Exception as e:
        logger.exception(
            f"Error in offer_consultation: {e}",
            extra={
                "conversation_id": conversation_id,
                "customer_id": str(customer_id) if customer_id else None
            }
        )
        # Return safe defaults on error
        return {
            "consultation_offered": False,
            "error_count": state.get("error_count", 0) + 1,
        }


class ConsultationResponseClassification(BaseModel):
    """
    Pydantic model for structured consultation response classification.

    Used to classify customer response to consultation offer as accept, decline, or unclear.
    """
    response_type: Literal["accept", "decline", "unclear"] = Field(
        description="Customer response to consultation offer"
    )
    confidence: float = Field(
        description="Confidence score 0.0-1.0 for classification"
    )


async def handle_consultation_response(
    state: ConversationState,
    llm: ChatAnthropic | None = None
) -> dict[str, Any]:
    """
    Handle customer response to consultation offer (accept, decline, or unclear).

    Analyzes customer message to determine if they accept or decline the consultation
    offer, or if their response is unclear and needs clarification.

    Acceptance patterns:
    - "Sí, prefiero la consulta primero" (from Scenario 8)
    - "Sí", "vale", "perfecto", "ok"
    - "Quiero la consulta", "acepto"
    - "Me gustaría asesoramiento"

    Decline patterns:
    - "No", "no gracias"
    - "Prefiero decidirme ahora", "ya sé cuál quiero"
    - "Solo quiero reservar {servicio}"
    - "No necesito consulta"

    If accepted:
    - Sets consultation_accepted=True
    - Sets requested_services=[consultation_service_id]
    - Sets skip_payment_flow=True (consultation is free)
    - Proceeds to availability checking

    If declined:
    - Sets consultation_declined=True
    - Re-presents service options
    - Returns to service selection flow

    If unclear:
    - Asks clarification (max 1 attempt)
    - If still unclear after clarification → assumes decline

    Args:
        state: Current conversation state with consultation offer and customer response
        llm: Optional ChatAnthropic instance for testing (uses get_llm() if None)

    Returns:
        dict: State updates based on customer response:
            - consultation_accepted: bool (if accepted)
            - consultation_declined: bool (if declined)
            - requested_services: list[UUID] (if accepted)
            - skip_payment_flow: bool (if accepted)
            - current_intent: str (updated to "booking" if accepted)
            - messages: updated with appropriate response

    Example:
        >>> state = {"consultation_offered": True, "messages": [...]}
        >>> result = await handle_consultation_response(state)
        >>> result["consultation_accepted"]  # True/False
    """
    # Use provided LLM or get default instance
    if llm is None:
        llm = get_llm()

    conversation_id = state.get("conversation_id")
    customer_id = state.get("customer_id")
    messages = state.get("messages", [])
    consultation_service_id = state.get("consultation_service_id")
    detected_services = state.get("detected_services", [])
    clarification_attempts = state.get("clarification_attempts", 0)

    try:
        # Extract most recent user message
        user_messages = [msg for msg in messages if isinstance(msg, HumanMessage)]
        if not user_messages:
            logger.warning(
                f"No user messages found for consultation response handling",
                extra={"conversation_id": conversation_id}
            )
            return {}

        latest_user_message = user_messages[-1].content

        logger.info(
            f"Analyzing consultation response",
            extra={
                "conversation_id": conversation_id,
                "customer_id": str(customer_id) if customer_id else None,
                "message_preview": latest_user_message[:50]
            }
        )

        # Build classification prompt
        classification_prompt = f"""Analiza la respuesta del cliente a la oferta de consulta gratuita.

Mensaje del cliente: "{latest_user_message}"

PATRONES DE ACEPTACIÓN:
- "Sí, prefiero la consulta primero"
- "Sí", "vale", "perfecto", "ok", "de acuerdo"
- "Quiero la consulta", "acepto", "me interesa"
- "Me gustaría asesoramiento", "sí, necesito consejo"

PATRONES DE RECHAZO:
- "No", "no gracias"
- "Prefiero decidirme ahora", "ya sé cuál quiero"
- "Solo quiero reservar [servicio]"
- "No necesito consulta"

RESPUESTAS POCO CLARAS:
- Preguntas sobre la consulta: "¿Es obligatoria?", "¿Cuánto cuesta?"
- Cambio de tema sin responder directamente
- Respuesta ambigua

Clasifica la respuesta como:
- "accept": el cliente acepta la consulta
- "decline": el cliente rechaza la consulta
- "unclear": la respuesta no es clara

Proporciona también una puntuación de confianza (0.0-1.0)."""

        # Get structured output from Claude
        structured_llm = llm.with_structured_output(ConsultationResponseClassification)
        classification = await structured_llm.ainvoke([HumanMessage(content=classification_prompt)])

        logger.info(
            f"Consultation response classified: {classification.response_type}, confidence={classification.confidence}",
            extra={
                "conversation_id": conversation_id,
                "customer_id": str(customer_id) if customer_id else None,
                "response_type": classification.response_type,
                "confidence": classification.confidence
            }
        )

        # Handle ACCEPT
        if classification.response_type == "accept" and classification.confidence > 0.7:
            logger.info(
                f"Consultation accepted by customer",
                extra={
                    "conversation_id": conversation_id,
                    "customer_id": str(customer_id) if customer_id else None,
                    "consultation_service_id": str(consultation_service_id) if consultation_service_id else None
                }
            )

            # Set state for consultation booking
            return {
                "consultation_accepted": True,
                "requested_services": [consultation_service_id] if consultation_service_id else [],
                "skip_payment_flow": True,  # Consultation is free
                "current_intent": "booking",
            }

        # Handle DECLINE
        elif classification.response_type == "decline" and classification.confidence > 0.7:
            logger.info(
                f"Consultation declined by customer",
                extra={
                    "conversation_id": conversation_id,
                    "customer_id": str(customer_id) if customer_id else None
                }
            )

            # Build response re-presenting service options
            services_text = ", ".join(detected_services) if detected_services else "los servicios disponibles"
            decline_message = (
                f"Entendido 😊. Puedo ayudarte a elegir entre {services_text}. "
                f"¿Cuál prefieres que reserve?"
            )

            updated_state = add_message(state, "assistant", decline_message)

            return {
                "consultation_declined": True,
                "messages": updated_state["messages"],
                "updated_at": updated_state["updated_at"],
            }

        # Handle UNCLEAR
        else:
            # Check if we've already tried clarifying
            if clarification_attempts >= 1:
                # Max clarification attempts reached - assume decline
                logger.info(
                    f"Max clarification attempts reached for consultation response, assuming decline",
                    extra={"conversation_id": conversation_id}
                )

                decline_message = (
                    f"Entendido 😊. Puedo ayudarte a elegir entre los servicios disponibles. "
                    f"¿Cuál prefieres que reserve?"
                )

                updated_state = add_message(state, "assistant", decline_message)

                return {
                    "consultation_declined": True,
                    "clarification_attempts": clarification_attempts + 1,
                    "messages": updated_state["messages"],
                    "updated_at": updated_state["updated_at"],
                }

            # First unclear response - ask for clarification
            logger.info(
                f"Consultation response unclear, asking for clarification",
                extra={"conversation_id": conversation_id}
            )

            clarification_message = (
                "¿Prefieres reservar la consulta gratuita o ya tienes claro qué servicio quieres? 😊"
            )

            updated_state = add_message(state, "assistant", clarification_message)

            return {
                "clarification_attempts": clarification_attempts + 1,
                "messages": updated_state["messages"],
                "updated_at": updated_state["updated_at"],
            }

    except Exception as e:
        logger.exception(
            f"Error in handle_consultation_response: {e}",
            extra={
                "conversation_id": conversation_id,
                "customer_id": str(customer_id) if customer_id else None
            }
        )
        # Return safe defaults on error - assume decline
        return {
            "consultation_declined": True,
            "error_count": state.get("error_count", 0) + 1,
        }


async def check_recent_consultation(state: ConversationState) -> dict[str, Any]:
    """
    Check if customer has a recent consultation and reference it in booking flow.

    Edge case handler for customers who completed a consultation and return later
    to book the recommended service. If consultation exists within last 7 days,
    references it in the response to provide continuity.

    Args:
        state: Current conversation state with customer history

    Returns:
        dict: State updates with consultation reference if applicable

    Example:
        >>> state = {"customer_history": [...], "previous_consultation_date": datetime(...)}
        >>> result = await check_recent_consultation(state)
        >>> result.get("bot_response")  # May include consultation reference
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    conversation_id = state.get("conversation_id")
    customer_id = state.get("customer_id")
    customer_name = state.get("customer_name", "")
    customer_history = state.get("customer_history", [])
    previous_consultation_date = state.get("previous_consultation_date")

    try:
        # Extract first name for personalized messages
        first_name = customer_name.split()[0] if customer_name else "Cliente"

        # Check if customer has recent consultation (within last 7 days)
        if previous_consultation_date:
            now = datetime.now(ZoneInfo("Europe/Madrid"))
            days_since_consultation = (now - previous_consultation_date).days

            if days_since_consultation <= 7:
                # Recent consultation found
                logger.info(
                    f"Recent consultation found for customer (days_ago={days_since_consultation})",
                    extra={
                        "conversation_id": conversation_id,
                        "customer_id": str(customer_id) if customer_id else None,
                        "previous_consultation_date": previous_consultation_date.isoformat()
                    }
                )

                # Build message referencing consultation
                # Note: This is a placeholder - actual stylist name and recommended service
                # would come from appointment history in customer_history
                consultation_ref_message = (
                    f"Genial, {first_name}. Después de tu consulta con nuestra estilista, "
                    f"¿quieres que reserve el servicio que te recomendó? 😊"
                )

                updated_state = add_message(state, "assistant", consultation_ref_message)

                return {
                    "bot_response": consultation_ref_message,
                    "messages": updated_state["messages"],
                    "updated_at": updated_state["updated_at"],
                }

        # No recent consultation or consultation too old
        return {}

    except Exception as e:
        logger.exception(
            f"Error in check_recent_consultation: {e}",
            extra={
                "conversation_id": conversation_id,
                "customer_id": str(customer_id) if customer_id else None
            }
        )
        return {
            "error_count": state.get("error_count", 0) + 1,
        }

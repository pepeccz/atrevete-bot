"""
FAQ detection and answering nodes for LangGraph conversation flow.

This module contains nodes for:
- Detecting if customer message is an FAQ using Claude classification
- Retrieving FAQ answers from database
- Formatting responses with Maite's tone and proactive follow-up
"""

import logging
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from sqlalchemy import select

from agent.state.helpers import add_message
from agent.state.schemas import ConversationState
from database.connection import get_async_session
from database.models import Policy

logger = logging.getLogger(__name__)

def get_llm() -> ChatAnthropic:
    """
    Get or initialize Claude LLM for FAQ classification.

    Factory function to enable dependency injection for testing.
    """
    return ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0)


async def detect_faq_intent(state: ConversationState, llm: ChatAnthropic | None = None) -> dict[str, Any]:
    """
    Detect if customer message contains one or more FAQs using Claude classification.

    Analyzes the most recent customer message and determines if it matches
    one or more of the 5 core FAQ categories: hours, parking, address,
    cancellation_policy, payment_info. Can detect compound queries like
    "Where are you located and what time do you open?".

    Args:
        state: Current conversation state with messages
        llm: Optional ChatAnthropic instance for testing (uses get_llm() if None)

    Returns:
        dict: State updates with faq_detected, detected_faq_ids (list), and query_complexity
    """
    # Use provided LLM or get default instance
    if llm is None:
        llm = get_llm()

    conversation_id = state.get("conversation_id")
    messages = state.get("messages", [])

    try:
        # Extract most recent user message
        user_messages = [msg for msg in messages if isinstance(msg, HumanMessage)]
        if not user_messages:
            logger.debug(
                f"No user messages found for FAQ detection",
                extra={"conversation_id": conversation_id}
            )
            return {"faq_detected": False, "detected_faq_ids": []}

        latest_user_message = user_messages[-1].content

        logger.debug(
            f"Detecting FAQ intent from user message",
            extra={"conversation_id": conversation_id, "message_preview": latest_user_message[:50]}
        )

        # Claude classification prompt for multi-FAQ detection
        classification_prompt = f"""Analiza el siguiente mensaje del cliente y determina si contiene una o más preguntas frecuentes (FAQ).

Mensaje: {latest_user_message}

Categorías de FAQ disponibles:
- hours: Horarios de apertura/cierre
- parking: Información sobre estacionamiento
- address: Ubicación o dirección del salón
- cancellation_policy: Política de cancelación y reembolsos
- payment_info: Información sobre pagos y anticipos

Instrucciones:
- Identifica TODAS las categorías de FAQ presentes en el mensaje
- Si el mensaje contiene múltiples preguntas FAQ, lista todas
- Si no es una FAQ, responde con una lista vacía

Responde SOLO con un array JSON de faq_ids. Ejemplos:
- ["hours"] para una sola pregunta sobre horarios
- ["address", "hours"] para preguntas compuestas sobre ubicación y horarios
- [] si no es una FAQ

Respuesta (solo el array JSON):"""

        response = await llm.ainvoke([{"role": "user", "content": classification_prompt}])
        response_content = response.content.strip()

        # Parse JSON response
        import json
        try:
            faq_ids = json.loads(response_content)
            if not isinstance(faq_ids, list):
                logger.warning(
                    f"Claude returned non-list response: {response_content}",
                    extra={"conversation_id": conversation_id}
                )
                return {"faq_detected": False, "detected_faq_ids": []}
        except json.JSONDecodeError:
            logger.warning(
                f"Failed to parse Claude JSON response: {response_content}",
                extra={"conversation_id": conversation_id}
            )
            return {"faq_detected": False, "detected_faq_ids": []}

        # Valid FAQ categories
        valid_faq_ids = ["hours", "parking", "address", "cancellation_policy", "payment_info"]

        # Filter to only valid FAQ IDs
        filtered_faq_ids = [faq_id for faq_id in faq_ids if faq_id in valid_faq_ids]

        # Check if any FAQs detected
        if not filtered_faq_ids:
            logger.debug(
                f"No FAQ detected",
                extra={"conversation_id": conversation_id}
            )
            return {
                "faq_detected": False,
                "detected_faq_ids": [],
                "query_complexity": "none",
            }

        # Classify query complexity
        if len(filtered_faq_ids) == 1:
            complexity = "simple"
        else:
            complexity = "compound"

        logger.info(
            f"FAQ(s) detected: {filtered_faq_ids}",
            extra={
                "conversation_id": conversation_id,
                "faq_ids": filtered_faq_ids,
                "complexity": complexity
            }
        )

        return {
            "faq_detected": True,
            "detected_faq_ids": filtered_faq_ids,
            "query_complexity": complexity,
            # Keep backward compatibility with single FAQ ID
            "detected_faq_id": filtered_faq_ids[0] if filtered_faq_ids else None,
        }

    except Exception as e:
        logger.error(
            f"Error in detect_faq_intent: {e}",
            extra={"conversation_id": conversation_id},
            exc_info=True
        )
        return {
            "faq_detected": False,
            "detected_faq_ids": [],
            "query_complexity": "none",
            "error_count": state.get("error_count", 0) + 1,
        }


async def answer_faq(state: ConversationState) -> dict[str, Any]:
    """
    Retrieve FAQ answer from database and format response with Maite's tone.

    Retrieves the FAQ answer from the policies table, formats it with Maite's
    warm tone, adds proactive follow-up question, and optionally includes
    Google Maps link for location FAQs.

    Args:
        state: Current conversation state with detected_faq_id

    Returns:
        dict: State updates with answer message appended
    """
    conversation_id = state.get("conversation_id")
    customer_id = state.get("customer_id")
    detected_faq_id = state.get("detected_faq_id")

    try:
        if not detected_faq_id:
            logger.error(
                f"answer_faq called without detected_faq_id",
                extra={"conversation_id": conversation_id}
            )
            return {
                "faq_detected": False,
                "error": "No FAQ ID provided",
            }

        # Query database for FAQ
        faq_key = f"faq:{detected_faq_id}"
        async for session in get_async_session():
            result = await session.execute(
                select(Policy).where(Policy.key == faq_key)
            )
            faq_policy = result.scalar_one_or_none()

        # FAQ not found in database
        if not faq_policy:
            logger.error(
                f"FAQ not found in database",
                extra={"conversation_id": conversation_id, "faq_id": detected_faq_id, "faq_key": faq_key}
            )
            # Fallback to generic helpful message
            fallback_message = "Lo siento, tuve un problema al buscar esa información. ¿Puedo ayudarte con algo más? 😊"
            updated_state = add_message(state, "assistant", fallback_message)

            return {
                "faq_detected": False,
                "error": "FAQ not found",
                "messages": updated_state["messages"],
                "updated_at": updated_state["updated_at"],
            }

        # Extract FAQ data from JSONB
        faq_data = faq_policy.value
        answer_text = faq_data.get("answer", "")
        requires_location_link = faq_data.get("requires_location_link", False)
        category = faq_data.get("category", "general")

        # Add Google Maps link for location FAQs
        if requires_location_link:
            answer_text += "\n\n📍 Google Maps: https://maps.google.com/?q=Atrévete+Peluquería+La+Línea"

        # Add proactive follow-up question
        answer_text += "\n\n¿Hay algo más en lo que pueda ayudarte? 😊"

        # Append answer to state messages
        updated_state = add_message(state, "assistant", answer_text)

        logger.info(
            "FAQ answered",
            extra={
                "conversation_id": conversation_id,
                "customer_id": customer_id,
                "faq_id": detected_faq_id,
                "category": category,
            }
        )

        return {
            "messages": updated_state["messages"],
            "current_intent": "faq",
            "faq_answered": True,
            "updated_at": updated_state["updated_at"],
        }

    except Exception as e:
        logger.error(
            f"Error in answer_faq: {e}",
            extra={"conversation_id": conversation_id, "faq_id": detected_faq_id},
            exc_info=True
        )

        # Fallback message for unexpected errors
        fallback_message = "Lo siento, tuve un problema al buscar esa información. ¿Puedo ayudarte con algo más? 😊"
        updated_state = add_message(state, "assistant", fallback_message)

        return {
            "faq_detected": False,
            "error": str(e),
            "messages": updated_state["messages"],
            "updated_at": updated_state["updated_at"],
            "error_count": state.get("error_count", 0) + 1,
        }

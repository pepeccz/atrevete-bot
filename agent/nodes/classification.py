"""
Intent classification nodes for LangGraph conversation flow.

This module contains nodes for:
- Extracting customer intent from messages using Claude
- Classifying intent into routing categories
"""

import logging
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage

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

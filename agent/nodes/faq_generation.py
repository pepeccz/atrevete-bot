"""
FAQ AI generation nodes for personalized responses.

This module contains nodes for:
- Fetching FAQ context from database for multiple FAQs
- Generating personalized AI responses using Claude
- Adapting tone to customer's communication style
- Fallback to static responses if AI generation fails
"""

import json
import logging
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select

from agent.nodes.faq import answer_faq, get_llm
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState
from database.connection import get_async_session
from database.models import Policy

logger = logging.getLogger(__name__)


async def fetch_faq_context(state: ConversationState) -> dict[str, Any]:
    """
    Fetch FAQ data from database for all detected FAQ IDs.

    Retrieves FAQ information from the policies table and stores it in
    state for use by AI generation node.

    Args:
        state: Current conversation state with detected_faq_ids

    Returns:
        dict: State updates with faq_context populated
    """
    conversation_id = state.get("conversation_id")
    detected_faq_ids = state.get("detected_faq_ids", [])

    try:
        if not detected_faq_ids:
            logger.warning(
                f"fetch_faq_context called without detected_faq_ids",
                extra={"conversation_id": conversation_id}
            )
            return {"faq_context": []}

        faq_context = []

        # Query database for each FAQ
        async for session in get_async_session():
            for faq_id in detected_faq_ids:
                faq_key = f"faq:{faq_id}"
                result = await session.execute(
                    select(Policy).where(Policy.key == faq_key)
                )
                faq_policy = result.scalar_one_or_none()

                if faq_policy:
                    faq_data = faq_policy.value
                    faq_context.append({
                        "faq_id": faq_id,
                        "answer": faq_data.get("answer", ""),
                        "category": faq_data.get("category", "general"),
                        "requires_location_link": faq_data.get("requires_location_link", False),
                    })
                    logger.debug(
                        f"Fetched FAQ context: {faq_id}",
                        extra={"conversation_id": conversation_id, "faq_id": faq_id}
                    )
                else:
                    logger.warning(
                        f"FAQ not found in database: {faq_id}",
                        extra={"conversation_id": conversation_id, "faq_id": faq_id}
                    )

        logger.info(
            f"Fetched {len(faq_context)} FAQ contexts",
            extra={
                "conversation_id": conversation_id,
                "faq_ids": detected_faq_ids,
                "fetched_count": len(faq_context)
            }
        )

        return {"faq_context": faq_context}

    except Exception as e:
        logger.error(
            f"Error in fetch_faq_context: {e}",
            extra={"conversation_id": conversation_id, "faq_ids": detected_faq_ids},
            exc_info=True
        )
        return {
            "faq_context": [],
            "error_count": state.get("error_count", 0) + 1,
        }


async def generate_personalized_faq_response(
    state: ConversationState,
    llm: ChatAnthropic | None = None
) -> dict[str, Any]:
    """
    Generate personalized FAQ response using Claude AI.

    Uses Claude to generate a natural, context-aware response that:
    - Answers ALL detected FAQs in a single cohesive response
    - Adapts tone to customer's communication style (formal/informal)
    - Includes relevant context like Google Maps links
    - Maintains Maite's warm personality

    Falls back to static answer_faq() if generation fails.

    Args:
        state: Current conversation state with faq_context and messages
        llm: Optional ChatAnthropic instance for testing

    Returns:
        dict: State updates with generated response message
    """
    # Use provided LLM or get default instance
    if llm is None:
        llm = get_llm()

    conversation_id = state.get("conversation_id")
    customer_name = state.get("customer_name")
    messages = state.get("messages", [])
    faq_context = state.get("faq_context", [])
    detected_faq_ids = state.get("detected_faq_ids", [])

    try:
        # Validate we have FAQ context
        if not faq_context:
            logger.warning(
                f"No FAQ context available for generation, falling back to static response",
                extra={"conversation_id": conversation_id}
            )
            # Fallback to static answer_faq
            return await answer_faq(state)

        # Extract latest customer message
        user_messages = [msg for msg in messages if isinstance(msg, HumanMessage)]
        if not user_messages:
            logger.warning(
                f"No user messages found for FAQ generation",
                extra={"conversation_id": conversation_id}
            )
            return await answer_faq(state)

        latest_user_message = user_messages[-1].content

        # Detect customer's tone (formal vs informal)
        customer_tone = "informal" if any(
            marker in latest_user_message.lower()
            for marker in ["gracias", "vale", "ok", "genial", "perfecto", "tío", "tía"]
        ) else "formal"

        # Build FAQ knowledge base for prompt
        faq_knowledge = []
        for faq in faq_context:
            faq_info = f"""
FAQ ID: {faq['faq_id']}
Categoría: {faq['category']}
Respuesta base: {faq['answer']}
Requiere enlace de ubicación: {'Sí' if faq['requires_location_link'] else 'No'}
"""
            faq_knowledge.append(faq_info.strip())

        faq_knowledge_text = "\n\n".join(faq_knowledge)

        # Build generation prompt
        system_prompt = """Eres Maite, la asistente virtual del salón de belleza Atrévete en La Línea de la Concepción.

Tu personalidad:
- Cálida, cercana y profesional
- Usas "tú" (nunca "usted")
- Incluyes emojis de forma natural pero sin exceso (🌸 😊 ✨)
- Eres concisa pero completa

Tu tarea es responder a preguntas frecuentes (FAQs) de forma personalizada y natural."""

        # Build personalization instruction
        personalization_instruction = ""
        if customer_name and customer_name.strip():
            personalization_instruction = f'\n6. IMPORTANTE: Saluda al cliente por su nombre ({customer_name}) al inicio de la respuesta, por ejemplo: "¡Hola {customer_name}! 🌸"'

        user_prompt = f"""El cliente ha preguntado:
"{latest_user_message}"

Información disponible para responder:
{faq_knowledge_text}

Instrucciones:
1. Responde a TODAS las preguntas del mensaje en una sola respuesta cohesionada
2. Usa un tono {customer_tone} pero siempre cálido
3. Si se requiere enlace de ubicación, incluye: https://maps.google.com/?q=Atrévete+Peluquería+La+Línea
4. Máximo 150 palabras
5. Termina con: "¿Hay algo más en lo que pueda ayudarte? 😊"{personalization_instruction}

Genera una respuesta natural que responda a todas las preguntas:"""

        # Generate response with Claude
        logger.debug(
            f"Generating AI FAQ response",
            extra={
                "conversation_id": conversation_id,
                "faq_ids": detected_faq_ids,
                "customer_tone": customer_tone
            }
        )

        response = await llm.ainvoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ])

        generated_answer = response.content.strip()

        # Validate response
        if not generated_answer or len(generated_answer) < 20:
            logger.warning(
                f"Generated response too short or empty, falling back to static",
                extra={"conversation_id": conversation_id, "response_length": len(generated_answer)}
            )
            return await answer_faq(state)

        # Check for maximum length (safety check)
        word_count = len(generated_answer.split())
        if word_count > 200:
            logger.warning(
                f"Generated response exceeded word limit: {word_count} words",
                extra={"conversation_id": conversation_id, "word_count": word_count}
            )
            # Truncate to last complete sentence within limit
            sentences = generated_answer.split('. ')
            truncated = []
            current_word_count = 0
            for sentence in sentences:
                sentence_words = len(sentence.split())
                if current_word_count + sentence_words <= 180:
                    truncated.append(sentence)
                    current_word_count += sentence_words
                else:
                    break
            generated_answer = '. '.join(truncated)
            if not generated_answer.endswith('.'):
                generated_answer += '.'
            generated_answer += "\n\n¿Hay algo más en lo que pueda ayudarte? 😊"

        # Add generated response to state
        updated_state = add_message(state, "assistant", generated_answer)

        logger.info(
            f"Generated personalized FAQ response",
            extra={
                "conversation_id": conversation_id,
                "faq_ids": detected_faq_ids,
                "response_word_count": len(generated_answer.split()),
                "customer_tone": customer_tone
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
            f"Error in generate_personalized_faq_response: {e}",
            extra={"conversation_id": conversation_id, "faq_ids": detected_faq_ids},
            exc_info=True
        )

        # Fallback to static answer_faq
        logger.info(
            f"Falling back to static FAQ answer due to generation error",
            extra={"conversation_id": conversation_id}
        )
        return await answer_faq(state)

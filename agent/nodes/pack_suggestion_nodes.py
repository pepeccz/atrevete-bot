"""
Pack suggestion nodes for LangGraph conversation flow.

This module implements intelligent pack suggestion logic that:
- Queries packs containing requested services
- Calculates savings and selects the best pack when multiple options exist
- Formats transparent pricing comparisons
- Handles customer acceptance/decline responses
- Respects customer choice without pressure tactics

Design follows Story 3.4 requirements with transparent pricing and
genuine value proposition focus.
"""

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage

from agent.prompts import load_maite_system_prompt
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState
from agent.tools.booking_tools import (
    calculate_total,
    get_pack_by_id,
    get_packs_containing_service,
    get_packs_for_multiple_services,
    get_service_by_name,
)
from database.models import Pack, Service
from shared.config import get_settings

logger = logging.getLogger(__name__)

# Initialize Claude model for response classification
def get_llm() -> ChatAnthropic:
    """Get LLM instance for pack response classification."""
    settings = get_settings()
    return ChatAnthropic(
        model="claude-sonnet-4-20250514",
        api_key=settings.ANTHROPIC_API_KEY,
        temperature=0,
    )


def analyze_pack_type(pack: Pack, requested_service_ids: list[UUID]) -> str:
    """
    Determine if pack is a savings opportunity or an upgrade.

    This function analyzes the relationship between requested services
    and pack contents to determine how to present the pack to the customer.

    Args:
        pack: Pack object from database
        requested_service_ids: List of service UUIDs customer actually requested

    Returns:
        str: One of:
            - "savings": Pack contains exactly requested services (cheaper bundle)
            - "upgrade": Pack includes additional services (value-add proposition)
            - "partial": Pack doesn't include all requested services (don't suggest)

    Examples:
        >>> # Customer asked for "corte"
        >>> analyze_pack_type(mechas_corte_pack, [corte_id])
        "upgrade"  # Pack has more than requested

        >>> # Customer asked for "mechas y corte"
        >>> analyze_pack_type(mechas_corte_pack, [mechas_id, corte_id])
        "savings"  # Pack has exactly what requested

        >>> # Customer asked for "mechas, corte y color"
        >>> analyze_pack_type(mechas_corte_pack, [mechas_id, corte_id, color_id])
        "partial"  # Pack missing "color"
    """
    requested_set = set(requested_service_ids)
    pack_set = set(pack.included_service_ids)

    if pack_set == requested_set:
        # Pack contains exactly what customer requested
        return "savings"
    elif requested_set.issubset(pack_set):
        # Pack contains requested services + additional services
        return "upgrade"
    else:
        # Pack is missing some requested services or has different services
        return "partial"


def calculate_pack_savings(pack: Pack, service_ids: list[UUID], individual_total: Decimal) -> dict:
    """
    Calculate savings for a specific pack compared to individual services.

    Args:
        pack: Pack object to evaluate
        service_ids: List of service UUIDs for comparison
        individual_total: Total price of individual services

    Returns:
        Dictionary with:
        - pack: Pack object
        - individual_total: Decimal (total price of services separately)
        - pack_price: Decimal (pack price)
        - savings_amount: Decimal (individual_total - pack_price)
        - savings_percentage: float (savings as percentage)
        - duration: int (pack duration in minutes)
    """
    pack_price = pack.price_euros
    savings_amount = individual_total - pack_price
    savings_percentage = float((savings_amount / individual_total) * 100) if individual_total > 0 else 0.0

    return {
        "pack": pack,
        "individual_total": individual_total,
        "pack_price": pack_price,
        "savings_amount": savings_amount,
        "savings_percentage": savings_percentage,
        "duration": pack.duration_minutes,
    }


def select_best_pack(packs: list[Pack], service_ids: list[UUID], individual_total: Decimal) -> dict | None:
    """
    Select the best pack from multiple options using savings-based algorithm.

    Filters out "partial" packs that don't include all requested services.
    For remaining packs, selects based on:
    1. Pack type preference (savings > upgrade)
    2. Highest savings percentage
    3. Tie-breaker: Shorter duration (faster service)

    Args:
        packs: List of Pack objects to evaluate
        service_ids: List of service UUIDs for savings calculation
        individual_total: Total price of individual services

    Returns:
        Dictionary with savings info and pack_type for best pack, or None if no valid packs
    """
    if not packs:
        return None

    # Filter out partial packs (missing requested services)
    valid_packs = []
    for pack in packs:
        pack_type = analyze_pack_type(pack, service_ids)
        if pack_type != "partial":
            valid_packs.append((pack, pack_type))
        else:
            logger.debug(
                f"Filtering out partial pack: {pack.name} "
                f"(missing some requested services)"
            )

    if not valid_packs:
        logger.info("No valid packs found (all were partial matches)")
        return None

    # Calculate savings for valid packs
    pack_savings = []
    for pack, pack_type in valid_packs:
        savings_info = calculate_pack_savings(pack, service_ids, individual_total)
        savings_info["pack_type"] = pack_type  # Add pack_type to result
        pack_savings.append(savings_info)

    # Sort by:
    # 1. Pack type (savings=0 first, upgrade=1 second)
    # 2. Savings percentage (descending)
    # 3. Duration (ascending)
    pack_savings.sort(
        key=lambda x: (
            0 if x["pack_type"] == "savings" else 1,  # Prefer savings packs
            -x["savings_percentage"],  # Higher savings better
            x["duration"]  # Shorter duration better
        )
    )

    # Select top pack
    best_pack = pack_savings[0]

    logger.info(
        f"Selected best pack: {best_pack['pack'].name} "
        f"(type={best_pack['pack_type']}, "
        f"{best_pack['savings_percentage']:.1f}% savings, {best_pack['duration']}min)"
    )

    return best_pack


async def generate_pack_suggestion_with_llm(
    suggested_pack: dict,
    service_names: list[str],
    individual_service_info: str,
    customer_name: str | None = None,
) -> str:
    """
    Generate natural pack suggestion using LLM with Maite's system prompt.

    Uses Claude to create a warm, conversational pack suggestion that maintains
    Maite's personality while presenting transparent pricing information.

    Args:
        suggested_pack: Dictionary with pack and savings info
        service_names: List of service names requested
        individual_service_info: String describing individual service pricing/duration
        customer_name: Customer's name for personalization (optional)

    Returns:
        Natural pack suggestion message in Maite's tone

    Raises:
        Falls back to template format if LLM generation fails
    """
    try:
        pack = suggested_pack["pack"]
        pack_price = suggested_pack["pack_price"]
        savings_amount = suggested_pack["savings_amount"]
        duration = suggested_pack["duration"]
        pack_type = suggested_pack.get("pack_type", "savings")  # Default to savings for backward compatibility
        pack_name = pack.name.lower()

        # Load Maite's system prompt
        system_prompt = load_maite_system_prompt()

        # Determine messaging strategy based on pack type
        if pack_type == "savings":
            # Real savings - customer requested all these services
            pack_description = f"""PACK DISPONIBLE (AHORRO REAL):
- Nombre: {pack_name}
- Precio: {pack_price}€
- Duración: {duration} minutos
- Ahorro: {savings_amount}€ (contiene exactamente lo que pidió, pero más barato)

Tu tarea:
1. Presenta primero la información de los servicios individuales
2. Menciona el pack como alternativa más económica
3. Destaca el AHORRO REAL de {savings_amount}€ de forma transparente
4. Pregunta si quiere que le reserves el pack
5. Usa tu tono cálido y emojis con naturalidad (😊 ✨ 💕)
6. Normaliza los nombres (usa minúsculas: "mechas" no "MECHAS")
7. Máximo 3-4 líneas"""

        else:  # upgrade
            # Upgrade - pack includes additional services not requested
            # Get extra services included in pack
            from database.models import Service as ServiceModel
            requested_ids = set(suggested_pack.get("requested_service_ids", []))
            pack_ids = set(pack.included_service_ids)
            extra_ids = pack_ids - requested_ids

            pack_description = f"""PACK DISPONIBLE (VALOR AÑADIDO):
- Nombre: {pack_name}
- Precio: {pack_price}€
- Duración: {duration} minutos
- Incluye servicios adicionales que el cliente NO pidió

Tu tarea:
1. Presenta primero la información de los servicios que pidió
2. Menciona el pack como opción de VALOR AÑADIDO (incluye servicios extra)
3. NO MENCIONES "ahorro" (sería confuso, no pidió todos los servicios del pack)
4. Presenta el pack como: "Por {pack_price}€ también te podemos hacer {pack_name}"
5. Pregunta si le interesa el pack completo o solo lo que pidió
6. Usa tu tono cálido y emojis con naturalidad (😊 ✨ 💕)
7. Normaliza los nombres (usa minúsculas)
8. Máximo 3-4 líneas"""

        # Create generation prompt
        generation_prompt = f"""El cliente ha preguntado por estos servicios: {", ".join(service_names)}

INFORMACIÓN DE SERVICIOS INDIVIDUALES:
{individual_service_info}

{pack_description}

Genera SOLO el mensaje, sin explicaciones adicionales."""

        # Initialize LLM with higher temperature for naturalness
        settings = get_settings()
        llm = ChatAnthropic(
            model="claude-sonnet-4-20250514",
            api_key=settings.ANTHROPIC_API_KEY,
            temperature=0.3,  # Slightly creative but consistent
        )

        # Generate response
        from langchain_core.messages import SystemMessage
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=generation_prompt)
        ])

        generated_message = response.content.strip()

        logger.debug(
            f"LLM-generated pack suggestion: {generated_message[:100]}..."
        )

        return generated_message

    except Exception as e:
        logger.warning(
            f"LLM pack suggestion generation failed, falling back to template: {e}"
        )
        # Fallback to template format
        return format_pack_suggestion(suggested_pack, service_names, individual_service_info)


def format_pack_suggestion(
    suggested_pack: dict,
    service_names: list[str],
    individual_service_info: str
) -> str:
    """
    Format transparent pack suggestion response in Maite's tone (TEMPLATE FALLBACK).

    Follows Scenario 1 format with explicit pricing and savings.
    Used as fallback when LLM generation fails.

    Args:
        suggested_pack: Dictionary with pack and savings info
        service_names: List of service names requested
        individual_service_info: String describing individual service pricing/duration

    Returns:
        Formatted suggestion message in Spanish
    """
    pack = suggested_pack["pack"]
    pack_price = suggested_pack["pack_price"]
    savings_amount = suggested_pack["savings_amount"]
    duration = suggested_pack["duration"]

    # Format pack name (lowercase) and service names
    pack_name = pack.name.lower()
    # Normalize service names to lowercase
    normalized_info = individual_service_info.replace("MECHAS", "mechas").replace("Corte de pelo", "corte de pelo")

    # Build transparent pricing message with emoji
    message = (
        f"{normalized_info}, **pero también contamos con** {pack_name} "
        f"**por {pack_price}€**, que dura {duration} minutos aproximadamente "
        f"**y con el que además ahorras {savings_amount}€** 😊. ¿Quieres que te reserve ese pack?"
    )

    return message


async def suggest_pack(state: ConversationState) -> dict[str, Any]:
    """
    Suggest best money-saving pack for requested services.

    This node:
    1. Queries packs containing requested services
    2. If multiple packs exist, selects the one with highest savings
    3. Formats transparent comparison with individual pricing
    4. Updates state with pack suggestion

    Args:
        state: Current conversation state with requested_services

    Returns:
        Updated state with:
        - matching_packs: List of all matching packs
        - suggested_pack: Selected pack with savings info (or None)
        - individual_service_total: Total price of services separately
        - bot_response: Formatted pack suggestion message (or None)
    """
    conversation_id = state.get("conversation_id", "")
    requested_services = state.get("requested_services", [])

    logger.info(
        f"suggest_pack node started | conversation_id={conversation_id} | "
        f"requested_services={requested_services}"
    )

    # Validate requested_services
    if not requested_services:
        logger.warning(f"No requested_services in state | conversation_id={conversation_id}")
        return {
            "matching_packs": [],
            "suggested_pack": None,
            "bot_response": None,
        }

    try:
        # Determine if single or multiple services requested
        if len(requested_services) == 1:
            # Single service - query packs containing this service
            service_id = requested_services[0]
            packs = await get_packs_containing_service(service_id)
            logger.debug(
                f"Single service query: found {len(packs)} packs | "
                f"conversation_id={conversation_id}"
            )
        else:
            # Multiple services - query packs with exact match
            packs = await get_packs_for_multiple_services(requested_services)
            logger.debug(
                f"Multiple service query: found {len(packs)} packs | "
                f"conversation_id={conversation_id}"
            )

        # No packs found - skip suggestion
        if not packs:
            logger.info(
                f"No packs found for services {requested_services} | "
                f"conversation_id={conversation_id}"
            )
            return {
                "matching_packs": [],
                "suggested_pack": None,
                "bot_response": None,
            }

        # Calculate individual service total
        total_info = await calculate_total(requested_services)
        individual_total = total_info["total_price"]
        services = total_info["services"]

        logger.debug(
            f"Individual service total: {individual_total}€ | "
            f"conversation_id={conversation_id}"
        )

        # Select best pack
        suggested_pack = select_best_pack(packs, requested_services, individual_total)

        if not suggested_pack:
            logger.warning(
                f"No pack selected despite {len(packs)} packs found | "
                f"conversation_id={conversation_id}"
            )
            return {
                "matching_packs": [str(p.id) for p in packs],  # Serialize to UUID strings
                "suggested_pack": None,
                "bot_response": None,
            }

        # Format individual service info
        # For single service: "Las mechas tienen un precio de 60€ y una duración de 120 minutos"
        # For multiple services: show combined info
        if len(services) == 1:
            service = services[0]
            individual_service_info = (
                f"{service.name} tiene un precio de {service.price_euros}€ "
                f"y una duración de {service.duration_minutes} minutos"
            )
        else:
            service_names_str = " y ".join([s.name for s in services])
            individual_service_info = (
                f"{service_names_str} tienen un precio total de {individual_total}€ "
                f"y una duración de {total_info['total_duration']} minutos"
            )

        # Generate pack suggestion message using LLM with Maite's tone
        service_names = [s.name for s in services]
        customer_name = state.get("customer_name")
        bot_response = await generate_pack_suggestion_with_llm(
            suggested_pack,
            service_names,
            individual_service_info,
            customer_name
        )

        logger.info(
            f"Pack suggested: {suggested_pack['pack'].name} | "
            f"savings={suggested_pack['savings_amount']}€ ({suggested_pack['savings_percentage']:.1f}%) | "
            f"conversation_id={conversation_id}"
        )

        # Add bot response using helper (ensures FIFO windowing + total_message_count)
        updated_state = add_message(state, "assistant", bot_response)

        # Convert suggested_pack to serializable format (Pack object → dict)
        serializable_suggested_pack = {
            "pack_id": str(suggested_pack["pack"].id),
            "pack_name": suggested_pack["pack"].name,
            "pack_price": float(suggested_pack["pack_price"]),
            "savings_amount": float(suggested_pack["savings_amount"]),
            "savings_percentage": suggested_pack["savings_percentage"],
            "duration": suggested_pack["duration"],
            "individual_total": float(suggested_pack["individual_total"]),
        }

        return {
            **updated_state,  # Include messages and total_message_count from add_message
            "matching_packs": [str(p.id) for p in packs],  # Serialize to UUID strings
            "suggested_pack": serializable_suggested_pack,  # Serializable dict
            "individual_service_total": float(individual_total),  # Decimal → float
            "bot_response": bot_response,
        }

    except Exception as e:
        logger.exception(
            f"Error in suggest_pack node | conversation_id={conversation_id}: {e}"
        )
        return {
            "matching_packs": [],
            "suggested_pack": None,
            "bot_response": None,
            "error_count": state.get("error_count", 0) + 1,
        }


async def detect_topic_change(
    latest_message: str,
    pending_context: str,
    pack_name: str | None = None
) -> dict[str, Any]:
    """
    Detect if customer's message is about the pending question or a new topic.

    Uses LLM to perform two-stage classification:
    1. Is this response about the pending context? (yes/no)
    2. If no, what type of new intent is it? (faq/inquiry/booking/other)

    Args:
        latest_message: Customer's latest message
        pending_context: What bot is waiting for (e.g., "pack_suggestion", "consultation_offer")
        pack_name: Optional pack name for context

    Returns:
        Dictionary with:
        - is_topic_change: bool (True if customer changed topic)
        - new_intent_type: str | None ("faq", "inquiry", "booking", or None)
        - confidence: float (0.0-1.0)

    Examples:
        >>> await detect_topic_change("sí, el pack", "pack_suggestion", "mechas + corte")
        {"is_topic_change": False, "new_intent_type": None, "confidence": 0.95}

        >>> await detect_topic_change("¿a qué hora abrís?", "pack_suggestion", "mechas + corte")
        {"is_topic_change": True, "new_intent_type": "faq", "confidence": 0.90}

        >>> await detect_topic_change("¿qué incluye el pack?", "pack_suggestion", "mechas + corte")
        {"is_topic_change": False, "new_intent_type": None, "confidence": 0.85}
    """
    try:
        llm = get_llm()

        # Build context-specific prompt
        context_description = {
            "pack_suggestion": f"si quiere el pack{f' de {pack_name}' if pack_name else ''} o prefiere el servicio individual",
            "consultation_offer": "si quiere reservar una consulta gratuita",
            "category_choice": "qué categoría de servicios prefiere (peluquería o estética)",
            "name_confirmation": "confirmar su nombre",
        }.get(pending_context, "responder a una pregunta pendiente")

        detection_prompt = f"""Analiza si el cliente está respondiendo a la pregunta pendiente o cambiando de tema.

CONTEXTO: El bot está esperando que el cliente responda {context_description}.

MENSAJE DEL CLIENTE: "{latest_message}"

CLASIFICACIÓN:

Paso 1: ¿El mensaje está relacionado con la pregunta pendiente?
- SÍ si: acepta, declina, pide más información sobre la oferta, o pregunta relacionada
  Ejemplos: "sí", "no gracias", "¿qué incluye el pack?", "prefiero solo mechas"
- NO si: pregunta sobre otra cosa (horarios, precios de otros servicios, nueva reserva, ubicación)
  Ejemplos: "¿a qué hora abrís?", "¿cuánto cuesta un corte?", "quiero cancelar mi cita"

Paso 2: Si NO está relacionado, ¿qué tipo de pregunta nueva es?
- "faq": Pregunta sobre horarios, ubicación, políticas, información general
- "inquiry": Pregunta sobre precios/características de otros servicios
- "booking": Nueva solicitud de reserva
- "other": Otro tipo de mensaje

Responde SOLO con este formato JSON:
{{"is_topic_change": true/false, "new_intent_type": "faq/inquiry/booking/other" o null, "confidence": 0.0-1.0}}"""

        response = await llm.ainvoke([HumanMessage(content=detection_prompt)])
        response_text = response.content.strip()

        # Parse JSON response
        import json
        if "```" in response_text:
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        result = json.loads(response_text)

        logger.info(
            f"Topic change detection: is_change={result.get('is_topic_change')}, "
            f"new_intent={result.get('new_intent_type')}, confidence={result.get('confidence', 0)}"
        )

        return result

    except Exception as e:
        logger.warning(f"Topic change detection failed: {e}, assuming no topic change")
        return {"is_topic_change": False, "new_intent_type": None, "confidence": 0.0}


async def handle_pack_response(state: ConversationState) -> dict[str, Any]:
    """
    Handle customer's response to pack suggestion with topic change detection.

    Two-stage processing:
    1. Detect if response is about pack or new topic
    2. If about pack: classify as accept/decline/unclear
       If new topic: clear awaiting state and flag for re-routing

    Classifies pack responses as:
    - accept: Customer wants the pack
    - decline: Customer prefers individual service
    - unclear: Ambiguous response requiring clarification

    Args:
        state: Current conversation state with suggested_pack and latest message

    Returns:
        Updated state with:
        - pack_id: UUID (if accepted)
        - requested_services: Updated to pack services (if accepted)
        - pack_declined: bool (if declined)
        - bot_response: Confirmation or clarification message
        - topic_changed_during_pack_response: bool (if topic change detected)
        - new_user_message: str (original message for re-routing)
    """
    conversation_id = state.get("conversation_id", "")
    messages = state.get("messages", [])
    suggested_pack = state.get("suggested_pack")

    logger.info(f"handle_pack_response node started | conversation_id={conversation_id}")

    # Validate state
    if not suggested_pack:
        logger.warning(f"No suggested_pack in state | conversation_id={conversation_id}")
        return {}

    if not messages:
        logger.warning(f"No messages in state | conversation_id={conversation_id}")
        return {}

    # Get latest customer message
    latest_message = None
    for msg in reversed(messages):
        if hasattr(msg, 'type') and msg.type == 'human':
            latest_message = msg.content
            break

    if not latest_message:
        logger.warning(f"No customer message found | conversation_id={conversation_id}")
        return {}

    try:
        # STEP 1: Detect if customer changed topic
        pack_name = suggested_pack.get("pack_name", "").lower()
        topic_change_result = await detect_topic_change(
            latest_message,
            "pack_suggestion",
            pack_name
        )

        # Handle topic change - clear awaiting state and flag for re-routing
        if topic_change_result.get("is_topic_change", False):
            new_intent_type = topic_change_result.get("new_intent_type")

            logger.info(
                f"Topic change detected during pack response | "
                f"new_intent={new_intent_type} | conversation_id={conversation_id}"
            )

            # Clear pack awaiting state by marking as declined
            # This prevents infinite loop in entry routing
            return {
                "pack_declined": True,  # Clear awaiting state
                "topic_changed_during_pack_response": True,  # Flag for routing
                "new_intent_type": new_intent_type,  # Type of new question
                "suggested_pack": None,  # Clear suggestion
            }

        # STEP 2: Not a topic change - classify pack response (accept/decline/unclear)
        llm = get_llm()
        classification_prompt = f"""Classify the customer's response to a pack suggestion.

Customer response: "{latest_message}"

Classify as ONE of:
- "accept": Customer wants the pack (patterns: "sí", "el pack", "acepto", "vale", "perfecto", "ok", "quiero el pack")
- "decline": Customer prefers individual service (patterns: "no", "solo [servicio]", "no gracias", "prefiero")
- "unclear": Ambiguous response or question

Return ONLY the classification word (accept/decline/unclear)."""

        classification_response = await llm.ainvoke([
            HumanMessage(content=classification_prompt)
        ])

        classification = classification_response.content.strip().lower()

        logger.debug(
            f"Pack response classified as: {classification} | "
            f"conversation_id={conversation_id}"
        )

        # Handle acceptance
        if classification == "accept":
            # Query pack from DB using pack_id (suggested_pack is now serializable dict)
            pack_id = UUID(suggested_pack["pack_id"])
            pack = await get_pack_by_id(pack_id)

            if not pack:
                logger.error(f"Pack not found: {pack_id} | conversation_id={conversation_id}")
                return {
                    "error": "pack_not_found",
                    "bot_response": "Lo siento, hubo un error. ¿Podrías intentarlo de nuevo? 😊",
                }

            pack_services = pack.included_service_ids

            logger.info(
                f"Pack accepted: pack_id={pack_id} | "
                f"conversation_id={conversation_id}"
            )

            # Build confirmation message
            customer_name = state.get("customer_name", "")
            confirmation_message = f"¡Perfecto, {customer_name}! 😊 Te reservo el pack de {pack.name.lower()}."

            # Add confirmation message using helper (ensures FIFO windowing + total_message_count)
            updated_state = add_message(state, "assistant", confirmation_message)

            return {
                **updated_state,  # Include messages and total_message_count
                "pack_id": pack_id,
                "requested_services": pack_services,
                "total_price": pack.price_euros,
                "total_duration": pack.duration_minutes,
                "bot_response": confirmation_message,
            }

        # Handle decline
        elif classification == "decline":
            logger.info(
                f"Pack declined | conversation_id={conversation_id}"
            )

            # Build acknowledgment message
            customer_name = state.get("customer_name", "")
            # Get original requested service names
            original_services = state.get("requested_services", [])

            # For now, use generic message (service extraction will be in future story)
            decline_message = f"Entendido, {customer_name} 😊. Te reservo el servicio entonces."

            # Add decline message using helper (ensures FIFO windowing + total_message_count)
            updated_state = add_message(state, "assistant", decline_message)

            return {
                **updated_state,  # Include messages and total_message_count
                "pack_declined": True,
                "bot_response": decline_message,
            }

        # Handle unclear response
        else:
            logger.info(
                f"Unclear pack response, requesting clarification | "
                f"conversation_id={conversation_id}"
            )

            # Use pack_name from serialized suggested_pack (no DB query needed)
            pack_name = suggested_pack["pack_name"].lower()
            clarification_message = (
                f"¿Prefieres el pack de {pack_name} o solo el servicio individual? 😊"
            )

            # Increment clarification attempts
            clarification_attempts = state.get("clarification_attempts", 0) + 1

            # If this is the second clarification attempt, assume decline
            if clarification_attempts >= 2:
                logger.info(
                    f"Max clarification attempts reached, assuming decline | "
                    f"conversation_id={conversation_id}"
                )
                return {
                    "pack_declined": True,
                    "clarification_attempts": clarification_attempts,
                }

            # Add clarification message using helper (ensures FIFO windowing + total_message_count)
            updated_state = add_message(state, "assistant", clarification_message)

            return {
                **updated_state,  # Include messages and total_message_count
                "bot_response": clarification_message,
                "clarification_attempts": clarification_attempts,
            }

    except Exception as e:
        logger.exception(
            f"Error in handle_pack_response node | conversation_id={conversation_id}: {e}"
        )
        return {
            "error_count": state.get("error_count", 0) + 1,
        }

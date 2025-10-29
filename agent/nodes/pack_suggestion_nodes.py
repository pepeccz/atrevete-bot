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
from agent.state.schemas import ConversationState
from agent.tools.booking_tools import (
    calculate_total,
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

    Selection criteria (in order):
    1. Highest savings percentage
    2. Tie-breaker: Shorter duration (faster service)

    Args:
        packs: List of Pack objects to evaluate
        service_ids: List of service UUIDs for savings calculation
        individual_total: Total price of individual services

    Returns:
        Dictionary with savings info for best pack, or None if no packs
    """
    if not packs:
        return None

    # Calculate savings for all packs
    pack_savings = [
        calculate_pack_savings(pack, service_ids, individual_total)
        for pack in packs
    ]

    # Sort by savings_percentage (descending), then by duration (ascending)
    pack_savings.sort(key=lambda x: (-x["savings_percentage"], x["duration"]))

    # Select top pack
    best_pack = pack_savings[0]

    logger.info(
        f"Selected best pack: {best_pack['pack'].name} "
        f"({best_pack['savings_percentage']:.1f}% savings, {best_pack['duration']}min)"
    )

    return best_pack


def format_pack_suggestion(
    suggested_pack: dict,
    service_names: list[str],
    individual_service_info: str
) -> str:
    """
    Format transparent pack suggestion response in Maite's tone.

    Follows Scenario 1 format with explicit pricing and savings.

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

    # Format pack name (capitalize first letter)
    pack_name = pack.name.lower()

    # Build transparent pricing message
    message = (
        f"{individual_service_info}, **pero también contamos con** {pack_name} "
        f"**por {pack_price}€**, que dura {duration} minutos aproximadamente "
        f"**y con el que además ahorras {savings_amount}€**. ¿Quieres que te reserve ese pack?"
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
                "matching_packs": packs,
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

        # Format pack suggestion message
        service_names = [s.name for s in services]
        bot_response = format_pack_suggestion(
            suggested_pack,
            service_names,
            individual_service_info
        )

        logger.info(
            f"Pack suggested: {suggested_pack['pack'].name} | "
            f"savings={suggested_pack['savings_amount']}€ ({suggested_pack['savings_percentage']:.1f}%) | "
            f"conversation_id={conversation_id}"
        )

        # Append bot response to messages
        messages = list(state.get("messages", []))
        messages.append(AIMessage(content=bot_response))

        return {
            "matching_packs": packs,
            "suggested_pack": suggested_pack,
            "individual_service_total": individual_total,
            "bot_response": bot_response,
            "messages": messages,
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


async def handle_pack_response(state: ConversationState) -> dict[str, Any]:
    """
    Handle customer's response to pack suggestion.

    Classifies response as:
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
        # Use Claude to classify response
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
            pack = suggested_pack["pack"]
            pack_id = pack.id
            pack_services = pack.included_service_ids

            logger.info(
                f"Pack accepted: pack_id={pack_id} | "
                f"conversation_id={conversation_id}"
            )

            # Build confirmation message
            customer_name = state.get("customer_name", "")
            confirmation_message = f"¡Perfecto, {customer_name}! 😊 Te reservo el pack de {pack.name.lower()}."

            # Append confirmation to messages
            updated_messages = list(messages)
            updated_messages.append(AIMessage(content=confirmation_message))

            return {
                "pack_id": pack_id,
                "requested_services": pack_services,
                "total_price": pack.price_euros,
                "total_duration": pack.duration_minutes,
                "bot_response": confirmation_message,
                "messages": updated_messages,
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

            # Append acknowledgment to messages
            updated_messages = list(messages)
            updated_messages.append(AIMessage(content=decline_message))

            return {
                "pack_declined": True,
                "bot_response": decline_message,
                "messages": updated_messages,
            }

        # Handle unclear response
        else:
            logger.info(
                f"Unclear pack response, requesting clarification | "
                f"conversation_id={conversation_id}"
            )

            pack = suggested_pack["pack"]
            clarification_message = (
                f"¿Prefieres el pack de {pack.name.lower()} o solo el servicio individual? 😊"
            )

            # Append clarification to messages
            updated_messages = list(messages)
            updated_messages.append(AIMessage(content=clarification_message))

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

            return {
                "bot_response": clarification_message,
                "messages": updated_messages,
                "clarification_attempts": clarification_attempts,
            }

    except Exception as e:
        logger.exception(
            f"Error in handle_pack_response node | conversation_id={conversation_id}: {e}"
        )
        return {
            "error_count": state.get("error_count", 0) + 1,
        }

"""
Booking validation nodes for LangGraph conversation flow.

This module implements service category validation nodes for the booking flow.
Prevents mixing Hairdressing and Aesthetics services in a single booking.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from agent.state.schemas import ConversationState
from agent.tools.booking_tools import validate_service_combination
from database.connection import get_async_session
from database.models import Service, ServiceCategory

# Configure logger
logger = logging.getLogger(__name__)

# Initialize Claude for classification via OpenRouter
from shared.config import get_settings
settings = get_settings()

llm = ChatOpenAI(
    model="anthropic/claude-haiku-4.5",
    api_key=settings.OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
    temperature=0,
    default_headers={
        "HTTP-Referer": settings.SITE_URL,
        "X-Title": settings.SITE_NAME,
    }
)


class CategoryChoiceClassification(BaseModel):
    """Classification for customer's category choice after mixed category detection."""

    choice: str = Field(
        description="Customer's choice: book_separately, choose_hairdressing, choose_aesthetics, cancel, or unclear"
    )
    confidence: float = Field(description="Confidence score 0.0-1.0")


async def _get_service_names_str(service_ids: list, session) -> str:
    """
    Helper function to get comma-separated service names from service IDs.

    Args:
        service_ids: List of service UUIDs
        session: Database session

    Returns:
        Comma-separated string of service names
    """
    from sqlalchemy import select

    stmt = select(Service).where(Service.id.in_(service_ids))
    result = await session.execute(stmt)
    service_names = [s.name for s in result.scalars().all()]
    return ", ".join(service_names)


async def validate_booking_request(state: ConversationState) -> dict[str, Any]:
    """
    Validate that requested services can be booked together.

    Checks:
    - Services are from same category (Hairdressing or Aesthetics)
    - If mixed → offers alternatives (book separately or choose one)

    Args:
        state: Current conversation state with requested_services

    Returns:
        Updated state with validation result and bot response
    """
    conversation_id = state.get("conversation_id", "unknown")
    customer_id = state.get("customer_id")
    customer_name = state.get("customer_name", "")
    requested_services = state.get("requested_services", [])

    try:
        logger.info(
            f"Validating booking request: conversation_id={conversation_id}, services={len(requested_services)}"
        )

        # Get database session and validate service combination
        async for session in get_async_session():
            validation = await validate_service_combination(requested_services, session)

            # If validation passed, check if we have requested_date
            if validation["valid"]:
                logger.info(
                    f"Booking validation passed: conversation_id={conversation_id}, customer_id={customer_id}"
                )

                # Check if requested_date is set
                requested_date = state.get("requested_date")

                if not requested_date:
                    # No date provided - ask for it
                    logger.info(
                        f"Validation passed but no requested_date - asking customer for date | conversation_id={conversation_id}"
                    )

                    # Get service names for context
                    service_names = await _get_service_names_str(requested_services, session)

                    message = f"Perfecto, {customer_name} 😊. ¿Qué día prefieres para {service_names}?"

                    from agent.state.helpers import add_message
                    updated_state = add_message(state, "assistant", message)

                    return {
                        **updated_state,
                        "booking_validation_passed": True,
                        "awaiting_date_input": True,
                        "updated_at": datetime.now(UTC),
                        "last_node": "validate_booking_request",
                    }

                # Date is available - proceed to availability check
                return {
                    **state,
                    "booking_validation_passed": True,
                    "awaiting_date_input": False,
                    "updated_at": datetime.now(UTC),
                    "last_node": "validate_booking_request",
                }

            # If mixed categories detected, generate helpful alternatives message
            if validation["reason"] == "mixed_categories":
                services_by_cat = validation["services_by_category"]

                # Extract service names by category
                hairdressing_services = []
                aesthetics_services = []

                for category, services in services_by_cat.items():
                    service_names = [s.name for s in services]
                    if category == ServiceCategory.HAIRDRESSING:
                        hairdressing_services = service_names
                    elif category == ServiceCategory.AESTHETICS:
                        aesthetics_services = service_names

                # Format service lists for message
                hairdressing_str = ", ".join(hairdressing_services)
                aesthetics_str = ", ".join(aesthetics_services)

                # Generate Maite's empathetic message with alternatives
                message = f"""Lo siento, {customer_name} 💕, pero no podemos hacer servicios de **peluquería** y **estética** en la misma cita porque trabajamos con profesionales especializados en cada área.

Tienes dos opciones:
1️⃣ **Reservar ambos servicios por separado**: Primero {hairdressing_str} y luego {aesthetics_str}
2️⃣ **Elegir solo uno**: ¿Prefieres {hairdressing_str} o {aesthetics_str}?

¿Cómo prefieres proceder? 😊"""

                # Log mixed category detection
                logger.warning(
                    f"Mixed category booking detected: customer_id={customer_id}, "
                    f"hairdressing={hairdressing_services}, aesthetics={aesthetics_services}",
                    extra={
                        "conversation_id": conversation_id,
                        "customer_id": customer_id,
                        "hairdressing": hairdressing_services,
                        "aesthetics": aesthetics_services,
                    },
                )

                return {
                    **state,
                    "booking_validation_passed": False,
                    "mixed_category_detected": True,
                    "awaiting_category_choice": True,
                    "services_by_category": {
                        "HAIRDRESSING": [s.id for s in services_by_cat.get(ServiceCategory.HAIRDRESSING, [])],
                        "AESTHETICS": [s.id for s in services_by_cat.get(ServiceCategory.AESTHETICS, [])],
                    },
                    "bot_response": message,
                    "updated_at": datetime.now(UTC),
                    "last_node": "validate_booking_request",
                }

            # If validation error, return fallback message
            logger.error(
                f"Validation error: conversation_id={conversation_id}, reason={validation['reason']}"
            )
            return {
                **state,
                "booking_validation_passed": False,
                "error_count": state.get("error_count", 0) + 1,
                "bot_response": f"Disculpa, {customer_name} 💕, he tenido un problema técnico. ¿Podrías repetirme qué servicios quieres reservar?",
                "updated_at": datetime.now(UTC),
                "last_node": "validate_booking_request",
            }

    except Exception as e:
        logger.exception(
            f"Error in validate_booking_request: conversation_id={conversation_id}, error={e}"
        )
        return {
            **state,
            "booking_validation_passed": False,
            "error_count": state.get("error_count", 0) + 1,
            "bot_response": f"Disculpa, {customer_name} 💕, he tenido un problema técnico. ¿Podrías repetirme qué servicios quieres reservar?",
            "updated_at": datetime.now(UTC),
            "last_node": "validate_booking_request",
        }


async def handle_category_choice(state: ConversationState) -> dict[str, Any]:
    """
    Process customer's choice after mixed category detection.

    Options:
    - Book services separately (create multiple booking flows)
    - Choose one category (filter requested_services)
    - Cancel request

    Args:
        state: Current conversation state with customer response

    Returns:
        Updated state with filtered services or multiple booking tracking
    """
    conversation_id = state.get("conversation_id", "unknown")
    customer_id = state.get("customer_id")
    customer_name = state.get("customer_name", "")
    messages = state.get("messages", [])
    services_by_category = state.get("services_by_category", {})
    clarification_attempts = state.get("clarification_attempts", 0)

    try:
        # Extract customer's latest message
        if not messages:
            logger.error(f"No messages found in state: conversation_id={conversation_id}")
            return {
                **state,
                "error_count": state.get("error_count", 0) + 1,
                "updated_at": datetime.now(UTC),
                "last_node": "handle_category_choice",
            }

        customer_message = messages[-1]["content"]

        logger.info(
            f"Processing category choice: conversation_id={conversation_id}, message='{customer_message}'"
        )

        # Use Claude to classify customer's response
        structured_llm = llm.with_structured_output(CategoryChoiceClassification)

        classification_prompt = f"""Classify customer response to mixed category alternatives:
Customer message: "{customer_message}"

Options offered:
1) Book separately (two separate appointments)
2) Choose one category only

Detect:
- book_separately: "por separado", "dos citas", "primero uno y luego otro", "ambos pero en diferentes días", "ambos"
- choose_hairdressing: "solo corte", "prefiero peluquería", "olvida la estética", "opción 2 peluquería"
- choose_aesthetics: "solo manicura", "prefiero estética", "olvida el corte", "opción 2 estética"
- cancel: "déjalo", "mejor no", "cancela", "olvídalo"
- unclear: ambiguous response or unrelated topic

Return your classification with confidence score."""

        try:
            classification = await structured_llm.ainvoke(classification_prompt)
            choice = classification.choice
            confidence = classification.confidence
        except Exception as e:
            logger.exception(
                f"Claude classification error: conversation_id={conversation_id}, error={e}"
            )
            # Retry with direct question
            choice = "unclear"
            confidence = 0.0

        logger.info(
            f"Category choice classified: conversation_id={conversation_id}, choice={choice}, confidence={confidence}",
            extra={
                "conversation_id": conversation_id,
                "customer_id": customer_id,
                "choice": choice,
                "confidence": confidence,
            },
        )

        # Process based on choice
        if choice == "book_separately":
            # Create two separate booking contexts
            hairdressing_services = services_by_category.get("HAIRDRESSING", [])
            aesthetics_services = services_by_category.get("AESTHETICS", [])

            pending_bookings = [
                {
                    "booking_id": 1,
                    "category": "HAIRDRESSING",
                    "service_ids": hairdressing_services,
                    "status": "pending",
                },
                {
                    "booking_id": 2,
                    "category": "AESTHETICS",
                    "service_ids": aesthetics_services,
                    "status": "pending",
                },
            ]

            # Get first category service names for message
            async for session in get_async_session():
                first_services_str = await _get_service_names_str(hairdressing_services, session)

            response = f"Perfecto 😊. Vamos a reservar primero {first_services_str}. ¿Qué día prefieres?"

            return {
                **state,
                "pending_bookings": pending_bookings,
                "current_booking_index": 0,
                "is_multi_booking_flow": True,
                "requested_services": hairdressing_services,  # Start with first category
                "mixed_category_detected": False,
                "awaiting_category_choice": False,
                "booking_validation_passed": True,
                "bot_response": response,
                "updated_at": datetime.now(UTC),
                "last_node": "handle_category_choice",
            }

        elif choice == "choose_hairdressing":
            # Filter to only Hairdressing services
            hairdressing_services = services_by_category.get("HAIRDRESSING", [])

            async for session in get_async_session():
                services_str = await _get_service_names_str(hairdressing_services, session)

            response = f"Entendido. Vamos a reservar {services_str}. ¿Qué día prefieres?"

            return {
                **state,
                "requested_services": hairdressing_services,
                "mixed_category_detected": False,
                "awaiting_category_choice": False,
                "booking_validation_passed": True,
                "bot_response": response,
                "updated_at": datetime.now(UTC),
                "last_node": "handle_category_choice",
            }

        elif choice == "choose_aesthetics":
            # Filter to only Aesthetics services
            aesthetics_services = services_by_category.get("AESTHETICS", [])

            async for session in get_async_session():
                services_str = await _get_service_names_str(aesthetics_services, session)

            response = f"Perfecto. Vamos a reservar {services_str}. ¿Qué día prefieres?"

            return {
                **state,
                "requested_services": aesthetics_services,
                "mixed_category_detected": False,
                "awaiting_category_choice": False,
                "booking_validation_passed": True,
                "bot_response": response,
                "updated_at": datetime.now(UTC),
                "last_node": "handle_category_choice",
            }

        elif choice == "cancel":
            # Clear requested services and return to normal flow
            response = "Entendido 😊. ¿Hay algo más en lo que pueda ayudarte?"

            return {
                **state,
                "requested_services": [],
                "mixed_category_detected": False,
                "awaiting_category_choice": False,
                "bot_response": response,
                "updated_at": datetime.now(UTC),
                "last_node": "handle_category_choice",
            }

        else:  # unclear
            # Increment clarification attempts
            new_attempts = clarification_attempts + 1

            # If less than 2 attempts, ask for clarification
            if new_attempts < 2:
                response = "No estoy segura de entender 😊. ¿Quieres reservar ambos servicios por separado (opción 1️⃣) o elegir solo uno (opción 2️⃣)?"

                return {
                    **state,
                    "clarification_attempts": new_attempts,
                    "bot_response": response,
                    "updated_at": datetime.now(UTC),
                    "last_node": "handle_category_choice",
                }
            else:
                # Escalate after 2 unclear attempts
                logger.warning(
                    f"Category choice escalation: customer_id={customer_id}, attempts={new_attempts}",
                    extra={
                        "conversation_id": conversation_id,
                        "customer_id": customer_id,
                        "attempts": new_attempts,
                    },
                )

                return {
                    **state,
                    "escalated": True,
                    "escalation_reason": "unclear_category_choice_after_multiple_attempts",
                    "updated_at": datetime.now(UTC),
                    "last_node": "handle_category_choice",
                }

    except Exception as e:
        logger.exception(
            f"Error in handle_category_choice: conversation_id={conversation_id}, error={e}"
        )
        return {
            **state,
            "error_count": state.get("error_count", 0) + 1,
            "bot_response": f"Disculpa, {customer_name} 💕, he tenido un problema. ¿Podrías repetir tu elección?",
            "updated_at": datetime.now(UTC),
            "last_node": "handle_category_choice",
        }

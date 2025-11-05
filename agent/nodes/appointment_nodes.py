"""
Appointment booking nodes for Fases 2-4 of the booking flow.

This module implements the transactional booking nodes:
- Fase 2: Slot selection (handle_slot_selection)
- Fase 3: Customer data collection (collect_customer_data)
- Fase 4: Provisional booking + payment (create_provisional_booking, generate_payment_link)

All nodes integrate with the hybrid architecture (Tier 2 transactional flow).
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from sqlalchemy import select

from agent.state.helpers import add_message
from agent.state.schemas import ConversationState
from agent.tools.booking_tools import calculate_total
# get_pack_by_id removed - packs functionality eliminated
from agent.validators.booking_validators import validate_buffer_between_appointments
from database.connection import get_async_session
from database.models import Appointment, AppointmentStatus, Customer, Payment, PaymentStatus, Stylist
from shared.config import get_settings

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Europe/Madrid")

settings = get_settings()

# Initialize Claude for classification via OpenRouter
llm = ChatOpenAI(
    model="anthropic/claude-3.5-sonnet-20241022",
    api_key=settings.OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
    temperature=0,
    default_headers={
        "HTTP-Referer": settings.SITE_URL,
        "X-Title": settings.SITE_NAME,
    }
)


# ============================================================================
# Pydantic Schemas for Claude Classification
# ============================================================================


class SlotSelectionClassification(BaseModel):
    """Classification for customer's slot selection response."""

    choice: str = Field(
        description="Customer's choice: slot_number (e.g. '1', '2'), time (e.g. '15:00'), "
        "stylist_name, any_slot, more_options, or unclear"
    )
    selected_index: int | None = Field(
        description="Index of selected slot (0-based) if choice is slot_number"
    )
    confidence: float = Field(description="Confidence score 0.0-1.0")


class CustomerDataClassification(BaseModel):
    """Classification for customer data response."""

    has_name: bool = Field(description="Whether customer provided full name")
    name: str | None = Field(description="Extracted full name if provided")
    has_notes: bool = Field(description="Whether customer provided notes/preferences")
    notes: str | None = Field(description="Extracted notes if provided")
    declined_notes: bool = Field(
        description="Whether customer explicitly declined to provide notes (said 'no', 'nada', etc.)"
    )


# ============================================================================
# Fase 2: Slot Selection
# ============================================================================


async def handle_slot_selection(state: ConversationState) -> dict[str, Any]:
    """
    Process customer's selection of an available slot (Fase 2 completion).

    This node is called after check_availability presents 2-3 slots to the customer.
    Uses Claude to classify the customer's response and extract their slot choice.

    Args:
        state: Current conversation state with:
            - prioritized_slots: List of 2-3 available slots
            - messages[-1]: Customer's response message

    Returns:
        Updated state with:
        - selected_slot: {"time": "15:00", "stylist_id": "...", "stylist_name": "...", "date": "..."}
        - selected_stylist_id: UUID of selected stylist
        - booking_phase: "customer_data" (progresses to Fase 3)
        - bot_response: Confirmation message or clarification request

    Example:
        Customer: "15:00 con Marta" / "El primero" / "Opción 2"
        → Selects slot, progresses to customer_data phase
    """
    conversation_id = state.get("conversation_id", "unknown")
    customer_name = state.get("customer_name", "")
    prioritized_slots = state.get("prioritized_slots", [])
    requested_date = state.get("requested_date")
    messages = state.get("messages", [])

    try:
        logger.info(
            f"Processing slot selection | conversation_id={conversation_id} | "
            f"num_slots={len(prioritized_slots)}"
        )

        # Validate inputs
        if not prioritized_slots:
            logger.error(
                f"handle_slot_selection called with no prioritized_slots | "
                f"conversation_id={conversation_id}"
            )
            return {
                **state,
                "bot_response": "Disculpa, parece que hubo un error. ¿Podrías repetir qué día prefieres?",
                "error_count": state.get("error_count", 0) + 1,
                "updated_at": datetime.now(UTC),
                "last_node": "handle_slot_selection",
            }

        if not messages or not messages[-1].get("content"):
            logger.error(
                f"handle_slot_selection called with no customer message | "
                f"conversation_id={conversation_id}"
            )
            return {
                **state,
                "bot_response": "No recibí tu respuesta. ¿Cuál horario prefieres?",
                "error_count": state.get("error_count", 0) + 1,
                "updated_at": datetime.now(UTC),
                "last_node": "handle_slot_selection",
            }

        customer_message = messages[-1]["content"]

        # Format slots for Claude classification
        slots_description = "\n".join([
            f"Opción {i+1}: {slot['time']} con {slot['stylist_name']}"
            for i, slot in enumerate(prioritized_slots)
        ])

        # Use Claude to classify customer's selection
        structured_llm = llm.with_structured_output(SlotSelectionClassification)

        classification_prompt = f"""Classify customer's slot selection response.

Available slots:
{slots_description}

Customer message: "{customer_message}"

Detect customer's choice:
- slot_number: "Opción 1", "El primero", "La 2", "Número 3"
- time: "15:00", "A las 3", "Por la tarde"
- stylist_name: "Con Marta", "Prefiero a Pilar"
- any_slot: "Cualquiera", "El que sea", "Me da igual"
- more_options: "Más opciones", "Tienes otros?", "Otro día"
- unclear: Ambiguous or unrelated

Return choice type and selected_index (0-based) if applicable."""

        try:
            classification = await structured_llm.ainvoke(classification_prompt)
            choice = classification.choice
            selected_index = classification.selected_index
            confidence = classification.confidence
        except Exception as e:
            logger.exception(
                f"Claude classification error in slot selection | "
                f"conversation_id={conversation_id}: {e}"
            )
            choice = "unclear"
            selected_index = None
            confidence = 0.0

        logger.info(
            f"Slot selection classified | choice={choice} | "
            f"index={selected_index} | confidence={confidence} | "
            f"conversation_id={conversation_id}"
        )

        # Process based on choice
        if choice == "slot_number" and selected_index is not None:
            # Customer selected by index
            if 0 <= selected_index < len(prioritized_slots):
                selected_slot = prioritized_slots[selected_index]
                selected_slot["date"] = requested_date  # Add date to slot

                stylist_id = UUID(selected_slot["stylist_id"])
                stylist_name = selected_slot["stylist_name"]
                time = selected_slot["time"]

                # 🎯 OPTIMIZACIÓN 3: Respuesta más cálida y personal
                response = f"¡Genial! 🎉 Te reservo para el *{requested_date}* a las *{time}* con {stylist_name}."

                return {
                    **state,
                    "selected_slot": selected_slot,
                    "selected_stylist_id": stylist_id,
                    "booking_phase": "customer_data",
                    "bot_response": response,
                    "updated_at": datetime.now(UTC),
                    "last_node": "handle_slot_selection",
                }

        elif choice == "any_slot":
            # Customer accepts any slot - select first one
            selected_slot = prioritized_slots[0]
            selected_slot["date"] = requested_date

            stylist_id = UUID(selected_slot["stylist_id"])
            stylist_name = selected_slot["stylist_name"]
            time = selected_slot["time"]

            # 🎯 OPTIMIZACIÓN 3: Respuesta más cálida y personal
            response = f"¡Perfecto! 🎉 Te reservo para el *{requested_date}* a las *{time}* con {stylist_name}."

            return {
                **state,
                "selected_slot": selected_slot,
                "selected_stylist_id": stylist_id,
                "booking_phase": "customer_data",
                "bot_response": response,
                "updated_at": datetime.now(UTC),
                "last_node": "handle_slot_selection",
            }

        elif choice == "more_options":
            # Customer wants more options - TODO: implement showing more slots
            response = (
                "Esos son los horarios más cercanos disponibles 😊. "
                "¿Alguno de esos te funciona? Si no, puedo buscar en otra fecha."
            )
            return {
                **state,
                "bot_response": response,
                "updated_at": datetime.now(UTC),
                "last_node": "handle_slot_selection",
            }

        else:
            # Unclear - ask for clarification
            clarification_attempts = state.get("clarification_attempts", 0) + 1

            if clarification_attempts < 2:
                response = (
                    f"No estoy segura de cuál horario prefieres 😊. "
                    f"¿Podrías decirme el número de opción (1, 2, etc.) o el horario exacto?"
                )
                return {
                    **state,
                    "clarification_attempts": clarification_attempts,
                    "bot_response": response,
                    "updated_at": datetime.now(UTC),
                    "last_node": "handle_slot_selection",
                }
            else:
                # Too many unclear attempts - escalate
                logger.warning(
                    f"Slot selection escalation after {clarification_attempts} unclear attempts | "
                    f"conversation_id={conversation_id}"
                )
                return {
                    **state,
                    "escalated": True,
                    "escalation_reason": "unclear_slot_selection_after_multiple_attempts",
                    "updated_at": datetime.now(UTC),
                    "last_node": "handle_slot_selection",
                }

    except Exception as e:
        logger.exception(
            f"Error in handle_slot_selection | conversation_id={conversation_id}: {e}"
        )
        return {
            **state,
            "error_count": state.get("error_count", 0) + 1,
            "bot_response": f"Disculpa, {customer_name} 💕, he tenido un problema técnico. ¿Podrías repetir cuál horario prefieres?",
            "updated_at": datetime.now(UTC),
            "last_node": "handle_slot_selection",
        }


# ============================================================================
# Fase 3: Customer Data Collection
# ============================================================================


async def collect_customer_data(state: ConversationState) -> dict[str, Any]:
    """
    Collect or confirm customer data for booking (Fase 3).

    For returning customers:
    - Displays registered name and asks for confirmation
    - Allows customer to update their name if needed

    For new customers:
    - Requests full name

    For all customers:
    - Requests optional notes (allergies, preferences, etc.)

    Args:
        state: Current conversation state with customer_id, customer_name

    Returns:
        Updated state with:
        - customer_name: Confirmed/updated name
        - customer_notes: Optional notes from customer
        - awaiting_customer_name: True if waiting for name input
        - awaiting_customer_notes: True if waiting for notes input
        - booking_phase: "payment" when data collection complete
        - bot_response: Question or acknowledgment

    State Machine:
        1. Initial call: Ask for name confirmation (returning) or name (new)
        2. After name: Ask for notes
        3. After notes: Progress to payment phase
    """
    conversation_id = state.get("conversation_id", "unknown")
    customer_id = state.get("customer_id")
    customer_name = state.get("customer_name")
    is_returning_customer = state.get("is_returning_customer", False)
    messages = state.get("messages", [])
    awaiting_customer_name = state.get("awaiting_customer_name", False)
    awaiting_customer_notes = state.get("awaiting_customer_notes", False)

    try:
        logger.info(
            f"Collecting customer data | conversation_id={conversation_id} | "
            f"customer_id={customer_id} | is_returning={is_returning_customer} | "
            f"awaiting_name={awaiting_customer_name} | awaiting_notes={awaiting_customer_notes}"
        )

        # State 1: Initial call - Ask for name confirmation/input
        if not awaiting_customer_name and not awaiting_customer_notes:
            if is_returning_customer and customer_name:
                # 🎯 OPTIMIZACIÓN 1: Saltar confirmación para clientes recurrentes
                # Skip name confirmation - go directly to notes
                response = (
                    f"¿Hay algo que debamos saber antes de tu cita, {customer_name}? "
                    f"(alergias, preferencias, etc.) Si no, puedes responder 'no' o 'nada'."
                )
                return {
                    **state,
                    "awaiting_customer_notes": True,  # Skip name, go to notes
                    "bot_response": response,
                    "updated_at": datetime.now(UTC),
                    "last_node": "collect_customer_data",
                }
            else:
                # New customer - request name AND notes in one message
                # 🎯 OPTIMIZACIÓN 2: Consolidar recolección de datos
                response = (
                    "Para finalizar, necesito tu nombre completo y, si tienes alguna alergia o preferencia especial, "
                    "por favor indícamelo también 😊. Ejemplo: 'María García, sin alergias'"
                )
                return {
                    **state,
                    "awaiting_customer_name": True,
                    "awaiting_customer_notes": True,  # Ask for both at once
                    "bot_response": response,
                    "updated_at": datetime.now(UTC),
                    "last_node": "collect_customer_data",
                }

        # State 2: Processing name response (consolidated with notes if both requested)
        if awaiting_customer_name:
            if not messages or not messages[-1].get("content"):
                logger.error(
                    f"collect_customer_data awaiting name but no message | "
                    f"conversation_id={conversation_id}"
                )
                return {
                    **state,
                    "bot_response": "No recibí tu respuesta. ¿Podrías confirmar tu nombre?",
                    "updated_at": datetime.now(UTC),
                    "last_node": "collect_customer_data",
                }

            customer_message = messages[-1]["content"]

            # Use Claude to extract name AND notes (consolidated)
            structured_llm = llm.with_structured_output(CustomerDataClassification)

            # 🎯 OPTIMIZACIÓN 2: Prompt consolidado que extrae nombre Y notas
            consolidated_prompt = f"""Extract customer name and notes from message.

Current name: "{customer_name or 'ninguno'}"
Customer message: "{customer_message}"

Detect:
- has_name: Whether customer provided a full name (first + last)
- name: Extract full name if provided
- has_notes: Whether customer provided notes/preferences
- notes: Extract notes if provided
- declined_notes: Whether customer said "sin alergias", "nada", "no"

Examples:
- "María García, sin alergias" → has_name=True, name="María García", declined_notes=True
- "Juan Pérez, alérgico al tinte" → has_name=True, name="Juan Pérez", has_notes=True, notes="alérgico al tinte"
- "Sí" → has_name=False (confirmation), declined_notes=False
"""

            try:
                classification = await structured_llm.ainvoke(consolidated_prompt)
                has_name = classification.has_name
                extracted_name = classification.name
                has_notes = classification.has_notes
                extracted_notes = classification.notes
                declined_notes = classification.declined_notes
            except Exception as e:
                logger.exception(
                    f"Claude classification error in consolidated extraction | "
                    f"conversation_id={conversation_id}: {e}"
                )
                has_name = False
                extracted_name = None
                has_notes = False
                extracted_notes = None
                declined_notes = False

            # Process name
            if has_name and extracted_name:
                new_customer_name = extracted_name

                # Update customer in database
                if customer_id:
                    async for session in get_async_session():
                        stmt = select(Customer).where(Customer.id == customer_id)
                        result = await session.execute(stmt)
                        customer = result.scalar_one_or_none()

                        if customer:
                            # Extract first and last name (simple split)
                            name_parts = new_customer_name.strip().split()
                            customer.first_name = name_parts[0] if name_parts else ""
                            customer.last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

                            await session.commit()
                            logger.info(
                                f"Customer name updated | customer_id={customer_id} | "
                                f"new_name={new_customer_name}"
                            )

                # 🎯 OPTIMIZACIÓN 2: Si también pedimos notas y las proporcionaron, completar fase
                if awaiting_customer_notes and (has_notes or declined_notes):
                    customer_notes = extracted_notes if has_notes else None

                    logger.info(
                        f"Consolidated data collection complete | name={new_customer_name} | "
                        f"has_notes={has_notes} | conversation_id={conversation_id}"
                    )

                    # Data collection complete - progress to payment
                    return {
                        **state,
                        "customer_name": new_customer_name,
                        "customer_notes": customer_notes,
                        "awaiting_customer_name": False,
                        "awaiting_customer_notes": False,
                        "booking_phase": "payment",
                        "updated_at": datetime.now(UTC),
                        "last_node": "collect_customer_data",
                    }
                else:
                    # Still need notes - ask for them
                    response = (
                        f"Perfecto, {new_customer_name} 😊. "
                        f"¿Hay algo que debamos saber antes de tu cita? (alergias, preferencias, etc.) "
                        f"Si no, puedes responder 'no' o 'nada'."
                    )

                    return {
                        **state,
                        "customer_name": new_customer_name,
                        "awaiting_customer_name": False,
                        "awaiting_customer_notes": True,
                        "bot_response": response,
                        "updated_at": datetime.now(UTC),
                        "last_node": "collect_customer_data",
                    }
            else:
                # No name provided (confirmation) - ask for notes if needed
                response = (
                    f"¿Hay algo que debamos saber antes de tu cita? (alergias, preferencias, etc.) "
                    f"Si no, puedes responder 'no' o 'nada'."
                )

                return {
                    **state,
                    "awaiting_customer_name": False,
                    "awaiting_customer_notes": True,
                    "bot_response": response,
                    "updated_at": datetime.now(UTC),
                    "last_node": "collect_customer_data",
                }

        # State 3: Processing notes response
        if awaiting_customer_notes:
            if not messages or not messages[-1].get("content"):
                logger.error(
                    f"collect_customer_data awaiting notes but no message | "
                    f"conversation_id={conversation_id}"
                )
                return {
                    **state,
                    "bot_response": "No recibí tu respuesta. ¿Hay algo que debamos saber antes de tu cita?",
                    "updated_at": datetime.now(UTC),
                    "last_node": "collect_customer_data",
                }

            customer_message = messages[-1]["content"]

            # Use Claude to extract notes
            structured_llm = llm.with_structured_output(CustomerDataClassification)

            notes_prompt = f"""Extract customer notes/preferences.

Customer message: "{customer_message}"

Detect:
- has_notes: Whether customer provided actual notes/preferences
- notes: Extract notes if provided
- declined_notes: Whether customer said no/nothing (e.g. "no", "nada", "ninguno")

Examples:
- "Soy alérgica al tinte" → has_notes=True, notes="Soy alérgica al tinte"
- "No" → declined_notes=True, has_notes=False
- "Nada especial" → declined_notes=True, has_notes=False
"""

            try:
                classification = await structured_llm.ainvoke(notes_prompt)
                has_notes = classification.has_notes
                extracted_notes = classification.notes
                declined_notes = classification.declined_notes
            except Exception as e:
                logger.exception(
                    f"Claude classification error in notes extraction | "
                    f"conversation_id={conversation_id}: {e}"
                )
                has_notes = False
                extracted_notes = None
                declined_notes = False

            # Store notes (or None if declined)
            customer_notes = extracted_notes if has_notes else None

            logger.info(
                f"Customer notes collected | has_notes={has_notes} | "
                f"declined={declined_notes} | conversation_id={conversation_id}"
            )

            # Data collection complete - progress to payment phase
            # Don't send a message here - let create_provisional_booking handle the flow
            return {
                **state,
                "customer_notes": customer_notes,
                "awaiting_customer_notes": False,
                "booking_phase": "payment",
                "updated_at": datetime.now(UTC),
                "last_node": "collect_customer_data",
            }

    except Exception as e:
        logger.exception(
            f"Error in collect_customer_data | conversation_id={conversation_id}: {e}"
        )
        return {
            **state,
            "error_count": state.get("error_count", 0) + 1,
            "bot_response": "Disculpa 💕, he tenido un problema técnico. ¿Podrías repetir tu respuesta?",
            "updated_at": datetime.now(UTC),
            "last_node": "collect_customer_data",
        }


# ============================================================================
# Fase 4: Provisional Booking Creation
# ============================================================================


async def create_provisional_booking(state: ConversationState) -> dict[str, Any]:
    """
    Create provisional appointment in database and Google Calendar (Fase 4 - part 1).

    Steps:
    1. Validate buffer with existing appointments (10 minutes)
    2. Calculate total price and deposit amount (20%)
    3. Create Appointment in database (status=PROVISIONAL)
    4. Create event in Google Calendar (yellow color, PROVISIONAL title)
    5. Set payment timeout (10 minutes from now)

    Args:
        state: Current conversation state with:
            - selected_slot: Chosen time slot
            - requested_services: List of service UUIDs
            - pack_id: Optional pack ID
            - customer_id: Customer UUID
            - customer_notes: Optional customer notes

    Returns:
        Updated state with:
        - provisional_appointment_id: Created appointment UUID
        - total_price: Total cost (Decimal)
        - advance_payment_amount: 20% deposit (Decimal)
        - payment_timeout_at: Expiration datetime
        - bot_response: Error message if validation fails

    Raises:
        No exceptions - returns error in bot_response if fails
    """
    conversation_id = state.get("conversation_id", "unknown")
    customer_id = state.get("customer_id")
    customer_name = state.get("customer_name", "Cliente")
    customer_phone = state.get("customer_phone", "")
    customer_notes = state.get("customer_notes")
    selected_slot = state.get("selected_slot")
    requested_services = state.get("requested_services", [])
    # pack_id = state.get("pack_id")  # Removed - packs functionality eliminated

    try:
        logger.info(
            f"Creating provisional booking | conversation_id={conversation_id} | "
            f"customer_id={customer_id} | selected_slot={selected_slot}"
        )

        # Validate inputs
        if not customer_id:
            logger.error(
                f"create_provisional_booking called without customer_id | "
                f"conversation_id={conversation_id}"
            )
            return {
                **state,
                "bot_response": "Disculpa 💕, necesito que te identifiques primero.",
                "error_count": state.get("error_count", 0) + 1,
                "updated_at": datetime.now(UTC),
                "last_node": "create_provisional_booking",
            }

        if not selected_slot:
            logger.error(
                f"create_provisional_booking called without selected_slot | "
                f"conversation_id={conversation_id}"
            )
            return {
                **state,
                "bot_response": "Disculpa 💕, necesito que selecciones un horario primero.",
                "error_count": state.get("error_count", 0) + 1,
                "updated_at": datetime.now(UTC),
                "last_node": "create_provisional_booking",
            }

        if not requested_services:
            logger.error(
                f"create_provisional_booking called without services | "
                f"conversation_id={conversation_id}"
            )
            return {
                **state,
                "bot_response": "Disculpa 💕, necesito que selecciones servicios primero.",
                "error_count": state.get("error_count", 0) + 1,
                "updated_at": datetime.now(UTC),
                "last_node": "create_provisional_booking",
            }

        # Extract slot details
        stylist_id = UUID(selected_slot["stylist_id"])
        date_str = selected_slot["date"]  # YYYY-MM-DD
        time_str = selected_slot["time"]  # HH:MM

        # Parse datetime
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TIMEZONE)
        hour, minute = map(int, time_str.split(":"))
        start_time = date_obj.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # Calculate price and duration from individual services
        total_data = await calculate_total(requested_services)
        total_price = total_data["total_price"]
        duration_minutes = total_data["total_duration"]
        service_ids_to_use = requested_services

        # Calculate deposit (20%)
        advance_payment_amount = total_price * Decimal("0.20")

        logger.info(
            f"Booking financials | total_price={total_price}€ | "
            f"deposit={advance_payment_amount}€ | duration={duration_minutes}min | "
            f"conversation_id={conversation_id}"
        )

        # Validate buffer with existing appointments
        buffer_validation = await validate_buffer_between_appointments(
            stylist_id=stylist_id,
            start_time=start_time,
            duration_minutes=duration_minutes,
            buffer_minutes=10,
            conversation_id=conversation_id
        )

        if not buffer_validation["valid"]:
            reason = buffer_validation.get("reason", "Conflicto de horario")
            logger.warning(
                f"Buffer validation failed | reason={reason} | "
                f"conversation_id={conversation_id}"
            )

            response = (
                f"Lo siento, {customer_name} 😔, ese horario ya no está disponible. "
                f"{reason}. ¿Quieres que busque otra opción?"
            )

            return {
                **state,
                "bot_response": response,
                "updated_at": datetime.now(UTC),
                "last_node": "create_provisional_booking",
            }

        # Create Appointment in database
        appointment_id = uuid4()
        payment_timeout = datetime.now(TIMEZONE) + timedelta(minutes=int(settings.BOOKING_PAYMENT_TIMEOUT_MINUTES or 10))

        async for session in get_async_session():
            appointment = Appointment(
                id=appointment_id,
                customer_id=customer_id,
                stylist_id=stylist_id,
                service_ids=service_ids_to_use,
                # pack_id removed - packs functionality eliminated
                start_time=start_time,
                duration_minutes=duration_minutes,
                total_price=total_price,
                advance_payment_amount=advance_payment_amount,
                status=AppointmentStatus.PROVISIONAL,
                customer_notes=customer_notes,
                metadata_={
                    "conversation_id": conversation_id,
                    "payment_timeout_at": payment_timeout.isoformat(),
                    "customer_phone": customer_phone
                }
            )

            session.add(appointment)
            await session.commit()

            logger.info(
                f"Provisional appointment created | appointment_id={appointment_id} | "
                f"timeout={payment_timeout} | conversation_id={conversation_id}"
            )

        # Create Google Calendar event (PROVISIONAL)
        from agent.tools.calendar_tools import create_calendar_event

        # Get service names for calendar event
        async for session in get_async_session():
            from database.models import Service
            stmt = select(Service).where(Service.id.in_(service_ids_to_use))
            result = await session.execute(stmt)
            services = list(result.scalars().all())
            service_names = ", ".join([s.name for s in services])

        calendar_result = await create_calendar_event(
            stylist_id=str(stylist_id),
            start_time=start_time.isoformat(),
            duration_minutes=duration_minutes,
            customer_name=customer_name,
            service_names=service_names,
            status="provisional",
            appointment_id=str(appointment_id),
            customer_id=str(customer_id),
            conversation_id=conversation_id
        )

        if not calendar_result.get("success"):
            logger.error(
                f"Failed to create calendar event | error={calendar_result.get('error')} | "
                f"conversation_id={conversation_id}"
            )
            # Continue anyway - appointment is in DB
            # TODO: Consider rolling back appointment or flagging for manual calendar creation

        logger.info(
            f"Provisional booking created successfully | appointment_id={appointment_id} | "
            f"calendar_event_id={calendar_result.get('event_id')} | "
            f"conversation_id={conversation_id}"
        )

        return {
            **state,
            "provisional_appointment_id": appointment_id,
            "total_price": total_price,
            "advance_payment_amount": advance_payment_amount,
            "payment_timeout_at": payment_timeout,
            "updated_at": datetime.now(UTC),
            "last_node": "create_provisional_booking",
        }

    except Exception as e:
        logger.exception(
            f"Error in create_provisional_booking | conversation_id={conversation_id}: {e}"
        )
        return {
            **state,
            "error_count": state.get("error_count", 0) + 1,
            "bot_response": f"Disculpa, {customer_name} 💕, he tenido un problema técnico al crear la reserva. Por favor, inténtalo de nuevo.",
            "updated_at": datetime.now(UTC),
            "last_node": "create_provisional_booking",
        }


# ============================================================================
# Fase 4: Payment Link Generation
# ============================================================================


async def generate_payment_link(state: ConversationState) -> dict[str, Any]:
    """
    Generate Stripe payment link and send to customer (Fase 4 - part 2).

    If total_price = 0€ (e.g., free consultation), skips payment entirely
    and confirms appointment directly.

    Otherwise:
    1. Creates Stripe Payment Link for deposit amount
    2. Stores payment_link_url in state
    3. Sends payment link to customer with timeout warning
    4. Ends flow (payment processing happens async via webhook)

    Args:
        state: Current conversation state with:
            - provisional_appointment_id: Created appointment UUID
            - total_price: Total cost
            - advance_payment_amount: Deposit amount (20%)
            - payment_timeout_at: Expiration time

    Returns:
        Updated state with:
        - payment_link_url: Stripe payment link URL
        - bot_response: Message with payment link and timeout
        - skip_payment_flow: True if price = 0€

    Note:
        After this node, the graph should END. Payment confirmation happens
        asynchronously via Stripe webhook → payment_processor.
    """
    conversation_id = state.get("conversation_id", "unknown")
    customer_name = state.get("customer_name", "Cliente")
    provisional_appointment_id = state.get("provisional_appointment_id")
    total_price = state.get("total_price", Decimal("0.00"))
    advance_payment_amount = state.get("advance_payment_amount", Decimal("0.00"))
    payment_timeout_at = state.get("payment_timeout_at")

    try:
        logger.info(
            f"Generating payment link | conversation_id={conversation_id} | "
            f"appointment_id={provisional_appointment_id} | "
            f"total={total_price}€ | deposit={advance_payment_amount}€"
        )

        # Check if payment is required
        if total_price == 0:
            logger.info(
                f"Free appointment detected | skipping payment | "
                f"conversation_id={conversation_id}"
            )

            # Update appointment to CONFIRMED directly (no payment needed)
            async for session in get_async_session():
                stmt = select(Appointment).where(Appointment.id == provisional_appointment_id)
                result = await session.execute(stmt)
                appointment = result.scalar_one_or_none()

                if appointment:
                    appointment.status = AppointmentStatus.CONFIRMED
                    await session.commit()

                    logger.info(
                        f"Free appointment confirmed directly | "
                        f"appointment_id={provisional_appointment_id}"
                    )

                    # Update Google Calendar event to CONFIRMED (green color)
                    from agent.tools.calendar_tools import create_calendar_event, get_stylist_by_id
                    from database.models import Service

                    # Get service names
                    stmt = select(Service).where(Service.id.in_(appointment.service_ids))
                    result = await session.execute(stmt)
                    services = list(result.scalars().all())
                    service_names = ", ".join([s.name for s in services])

                    # Get calendar event ID from metadata (if exists)
                    # For simplicity, create new confirmed event
                    # TODO: Update existing event instead of creating new one

                    stylist = await get_stylist_by_id(appointment.stylist_id)

                    response = add_message(
                        state,
                        "assistant",
                        f"✅ ¡Tu cita ha sido confirmada!\n\n"
                        f"📅 Resumen:\n"
                        f"- Fecha: {appointment.start_time.strftime('%d/%m/%Y')}\n"
                        f"- Hora: {appointment.start_time.strftime('%H:%M')}\n"
                        f"- Asistenta: {stylist.name if stylist else 'N/A'}\n"
                        f"- Servicios: {service_names}\n"
                        f"- Costo: 0€ (servicio gratuito)\n\n"
                        f"¡Nos vemos pronto en Atrévete! 💇‍♀️"
                    )

                    return {
                        **response,
                        "skip_payment_flow": True,
                        "updated_at": datetime.now(UTC),
                        "last_node": "generate_payment_link",
                    }

        # Payment required - generate Stripe Payment Link
        from shared.stripe_client import create_payment_link_for_appointment
        from database.models import Service

        # Calculate timeout in minutes
        timeout_minutes = int(settings.BOOKING_PAYMENT_TIMEOUT_MINUTES or 10)

        # Get appointment details for payment link description
        async for session in get_async_session():
            stmt = select(Appointment).where(Appointment.id == provisional_appointment_id)
            result = await session.execute(stmt)
            appointment = result.scalar_one_or_none()

            if not appointment:
                raise ValueError(f"Appointment {provisional_appointment_id} not found")

            # Get service names for description
            stmt = select(Service).where(Service.id.in_(appointment.service_ids))
            result = await session.execute(stmt)
            services = list(result.scalars().all())
            service_names = ", ".join([s.name for s in services])

            # Get customer details
            customer_id = state.get("customer_id")
            customer_email = state.get("customer_email")  # If available

            # Create payment link via Stripe API
            try:
                payment_link_data = await create_payment_link_for_appointment(
                    appointment_id=str(provisional_appointment_id),
                    customer_id=str(customer_id),
                    conversation_id=conversation_id,
                    amount_euros=advance_payment_amount,
                    description=f"{service_names} - Atrévete Peluquería",
                    customer_email=customer_email,
                    customer_name=customer_name,
                )

                payment_link_url = payment_link_data["url"]
                payment_link_id = payment_link_data["id"]

                # Store payment_link_id in appointment for later deactivation
                appointment.stripe_payment_link_id = payment_link_id
                await session.commit()

                logger.info(
                    f"Payment link generated successfully | url={payment_link_url} | "
                    f"link_id={payment_link_id} | conversation_id={conversation_id}"
                )

            except Exception as stripe_error:
                logger.error(
                    f"Stripe API error generating payment link | "
                    f"appointment_id={provisional_appointment_id}: {stripe_error}"
                )
                # Re-raise to trigger escalation in outer exception handler
                raise

            break  # Exit async for loop

        # Format message with payment link
        response_message = (
            f"Perfecto, {customer_name}, tu cita está casi lista 😊.\n\n"
            f"Para confirmarla, necesito que pagues el anticipo de {advance_payment_amount}€ "
            f"(20% del total de {total_price}€).\n\n"
            f"Enlace de pago: {payment_link_url}\n\n"
            f"⏱️ Una vez procesado el pago, tu cita quedará confirmada automáticamente. "
            f"Tienes {timeout_minutes} minutos para completar el pago."
        )

        updated_state = add_message(state, "assistant", response_message)

        return {
            **updated_state,
            "payment_link_url": payment_link_url,
            "updated_at": datetime.now(UTC),
            "last_node": "generate_payment_link",
        }

    except Exception as e:
        logger.exception(
            f"Error in generate_payment_link | conversation_id={conversation_id}: {e}"
        )
        return {
            **state,
            "error_count": state.get("error_count", 0) + 1,
            "bot_response": (
                f"Disculpa, {customer_name} 💕, he tenido un problema al generar el enlace de pago. "
                f"Voy a conectarte con el equipo para que te ayuden personalmente."
            ),
            "escalated": True,
            "escalation_reason": "payment_link_generation_error",
            "updated_at": datetime.now(UTC),
            "last_node": "generate_payment_link",
        }

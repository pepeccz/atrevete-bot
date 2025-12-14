"""
Appointment confirmation service - Handles customer confirmation responses.

This service processes customer responses to 48h confirmation requests:
- CONFIRM_APPOINTMENT: Customer confirms they will attend
- DECLINE_APPOINTMENT: Customer says they can't attend

Architecture:
- Called from conversational_agent when confirmation intent is detected
- Updates appointment status in database
- Updates/deletes Google Calendar events
- Creates admin panel notifications
- Returns response data for LLM or template response
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from database.connection import get_async_session
from database.models import (
    Appointment,
    AppointmentStatus,
    Customer,
    Notification,
    NotificationType,
    Service,
)
from agent.fsm.models import IntentType
from agent.services.gcal_push_service import (
    update_gcal_event_status,
    delete_gcal_event,
)

logger = logging.getLogger(__name__)

MADRID_TZ = ZoneInfo("Europe/Madrid")

# Keywords for multi-appointment confirmation/cancellation
CONFIRM_ALL_KEYWORDS = {
    "todas", "ambas", "las dos", "las tres", "las 2", "las 3",
    "si todas", "sí todas", "confirmo todas", "confirmo ambas",
    "confirmar todas", "confirmar ambas", "las confirmo", "confirmalas",
}
CANCEL_ALL_KEYWORDS = {
    "cancelar todas", "cancela todas", "cancelo todas", "ninguna",
    "no a todas", "cancelar ambas", "cancelo ambas", "cancelalas",
}
# Keywords for specific selection by number
NUMBER_SELECTION_PATTERNS = {
    "1": 1, "la 1": 1, "la primera": 1, "primera": 1, "uno": 1, "la uno": 1,
    "2": 2, "la 2": 2, "la segunda": 2, "segunda": 2, "dos": 2, "la dos": 2,
    "3": 3, "la 3": 3, "la tercera": 3, "tercera": 3, "tres": 3, "la tres": 3,
    "4": 4, "la 4": 4, "la cuarta": 4, "cuarta": 4, "cuatro": 4, "la cuatro": 4,
}

# Spanish weekday and month names for date formatting
WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
]


def format_date_spanish(dt: datetime) -> str:
    """Format datetime to Spanish date string."""
    return f"{WEEKDAYS_ES[dt.weekday()]} {dt.day} de {MONTHS_ES[dt.month - 1]}"


def detect_multi_selection(message: str) -> tuple[bool, bool, Optional[int]]:
    """
    Detect if user wants to confirm/cancel all appointments or a specific one.

    Args:
        message: User's message text

    Returns:
        Tuple of (is_all, is_cancel, selection_number):
        - is_all=True, is_cancel=False: Confirm ALL appointments
        - is_all=True, is_cancel=True: Cancel ALL appointments
        - is_all=False, selection_number=N: Confirm/cancel specific appointment N
        - is_all=False, selection_number=None: No multi-selection detected
    """
    msg_lower = message.lower().strip()

    # IMPORTANT: Check cancel keywords FIRST (they are more specific and contain "todas")
    # If we check confirm first, "cancelar todas" would match "todas" and incorrectly confirm
    if any(kw in msg_lower for kw in CANCEL_ALL_KEYWORDS):
        return (True, True, None)

    # Check for "confirm all" keywords
    if any(kw in msg_lower for kw in CONFIRM_ALL_KEYWORDS):
        return (True, False, None)

    # Check for specific number selection
    for pattern, number in NUMBER_SELECTION_PATTERNS.items():
        if msg_lower == pattern or msg_lower.startswith(f"{pattern} "):
            return (False, False, number)

    return (False, False, None)


@dataclass
class ConfirmationResult:
    """
    Result of processing a confirmation response.

    Attributes:
        success: Whether the operation succeeded
        appointment_id: UUID of the appointment (if found, for single appointment)
        appointment_ids: List of UUIDs (for multiple appointments processed)
        response_type: "template" for simple responses, "llm" for complex ones
        response_text: Pre-generated response text (if response_type is "template")
        appointment_date: Formatted date string for the appointment
        appointment_time: Time string (HH:MM) for the appointment
        stylist_name: Name of the stylist
        service_names: Comma-separated service names
        error_message: Error message if success is False
        multiple_processed: Number of appointments processed (for batch operations)
    """
    success: bool
    appointment_id: Optional[UUID] = None
    appointment_ids: Optional[list[UUID]] = None
    response_type: str = "template"
    response_text: Optional[str] = None
    appointment_date: Optional[str] = None
    appointment_time: Optional[str] = None
    stylist_name: Optional[str] = None
    service_names: Optional[str] = None
    error_message: Optional[str] = None
    multiple_processed: int = 0


async def get_pending_confirmations(customer_id: UUID) -> list[Appointment]:
    """
    Get ALL appointments awaiting confirmation for a customer.

    Finds PENDING appointments where confirmation_sent_at IS NOT NULL,
    ordered by start_time (soonest first).

    Args:
        customer_id: UUID of the customer

    Returns:
        List of Appointment objects (empty list if none found)
    """
    try:
        async with get_async_session() as session:
            result = await session.execute(
                select(Appointment)
                .options(
                    selectinload(Appointment.customer),
                    selectinload(Appointment.stylist),
                )
                .where(
                    and_(
                        Appointment.customer_id == customer_id,
                        Appointment.status == AppointmentStatus.PENDING,
                        Appointment.confirmation_sent_at.is_not(None),
                    )
                )
                .order_by(Appointment.start_time.asc())
            )
            return list(result.scalars().all())

    except Exception as e:
        logger.error(f"Error fetching pending confirmations for customer {customer_id}: {e}")
        return []


async def get_pending_confirmation(customer_id: UUID) -> Optional[Appointment]:
    """
    Get the appointment awaiting confirmation for a customer.

    DEPRECATED: Use get_pending_confirmations() to handle multiple appointments.
    This function is kept for backwards compatibility.

    Args:
        customer_id: UUID of the customer

    Returns:
        First appointment if found, None otherwise
    """
    appointments = await get_pending_confirmations(customer_id)
    return appointments[0] if appointments else None


async def get_customer_by_phone(phone_number: str) -> Optional[Customer]:
    """
    Get customer by phone number.

    Args:
        phone_number: E.164 formatted phone number

    Returns:
        Customer object if found, None otherwise
    """
    try:
        async with get_async_session() as session:
            result = await session.execute(
                select(Customer).where(Customer.phone == phone_number)
            )
            return result.scalars().first()

    except Exception as e:
        logger.error(f"Error fetching customer by phone {phone_number}: {e}")
        return None


async def has_pending_confirmation(customer_phone: str) -> bool:
    """
    Check if customer has a pending appointment awaiting confirmation.

    This is a quick check used by intent detection to determine if
    a simple "sí" or "no" should be interpreted as confirmation response.

    Args:
        customer_phone: E.164 formatted phone number

    Returns:
        True if customer has pending appointment awaiting confirmation
    """
    customer = await get_customer_by_phone(customer_phone)
    if not customer:
        return False

    appointment = await get_pending_confirmation(customer.id)
    return appointment is not None


def _build_appointment_list(appointments: list[Appointment]) -> str:
    """
    Build a formatted list of appointments for user display.

    Args:
        appointments: List of Appointment objects

    Returns:
        Formatted string with numbered appointment list
    """
    appt_list = []
    for i, appt in enumerate(appointments, 1):
        appt_time = appt.start_time.astimezone(MADRID_TZ)
        fecha = format_date_spanish(appt_time)
        hora = appt_time.strftime("%H:%M")
        stylist = appt.stylist.name if appt.stylist else "tu estilista"
        appt_list.append(f"{i}. {fecha} a las {hora} con {stylist}")
    return "\n".join(appt_list)


async def _get_service_names(service_ids: list[UUID]) -> str:
    """Get comma-separated service names from service IDs."""
    try:
        async with get_async_session() as session:
            services_result = await session.execute(
                select(Service).where(Service.id.in_(service_ids))
            )
            services = list(services_result.scalars().all())
            return ", ".join([s.name for s in services])
    except Exception:
        return "servicios"


async def _process_single_appointment(
    customer: Customer,
    appointment: Appointment,
    intent_type: IntentType,
    message_text: str,
    now: datetime,
) -> ConfirmationResult:
    """
    Process confirmation/cancellation for a single appointment.

    Args:
        customer: Customer object
        appointment: Appointment to process
        intent_type: CONFIRM_APPOINTMENT or DECLINE_APPOINTMENT
        message_text: Original user message (for response type detection)
        now: Current timestamp

    Returns:
        ConfirmationResult with outcome
    """
    # Get service names
    service_names = await _get_service_names(appointment.service_ids)

    # Format dates
    appt_time = appointment.start_time.astimezone(MADRID_TZ)
    fecha = format_date_spanish(appt_time)
    hora = appt_time.strftime("%H:%M")

    # Get stylist name
    stylist_name = appointment.stylist.name if appointment.stylist else "tu estilista"

    # Determine if response should use template or LLM
    simple_confirm_words = {"sí", "si", "confirmo", "ok", "de acuerdo", "vale", "perfecto"}
    simple_decline_words = {"no", "no puedo", "cancela", "cancelar", "anula", "anular"}
    message_lower = message_text.lower().strip()

    is_simple_message = (
        message_lower in simple_confirm_words
        or message_lower in simple_decline_words
        or len(message_text.split()) <= 3
    )

    try:
        async with get_async_session() as session:
            # Re-fetch appointment in this session for updates
            appt_result = await session.execute(
                select(Appointment)
                .options(selectinload(Appointment.stylist))
                .where(Appointment.id == appointment.id)
            )
            appt = appt_result.scalars().first()

            if not appt:
                return ConfirmationResult(
                    success=False,
                    error_message="Error interno. Por favor, intenta de nuevo.",
                )

            if intent_type == IntentType.CONFIRM_APPOINTMENT:
                # Update appointment status
                appt.status = AppointmentStatus.CONFIRMED
                await session.commit()

                # Update Google Calendar (yellow -> green)
                if appt.google_calendar_event_id:
                    try:
                        await update_gcal_event_status(
                            stylist_id=appt.stylist_id,
                            event_id=appt.google_calendar_event_id,
                            new_status="confirmed",
                            customer_name=customer.first_name or appt.first_name,
                            service_names=service_names,
                        )
                    except Exception as gcal_error:
                        logger.warning(
                            f"GCal update failed for appointment {appt.id} "
                            f"(DB already committed to CONFIRMED): {gcal_error}"
                        )

                # Create admin notification
                notification = Notification(
                    type=NotificationType.CONFIRMATION_RECEIVED,
                    title=f"{customer.first_name or appt.first_name} confirmó su cita",
                    message=f"Cita del {fecha} a las {hora} confirmada.",
                    entity_type="appointment",
                    entity_id=appt.id,
                )
                session.add(notification)
                await session.commit()

                logger.info(f"Appointment {appt.id} confirmed by customer {customer.id}")

                # Build response
                if is_simple_message:
                    response_text = (
                        f"¡Perfecto! Tu cita del {fecha} a las {hora} "
                        f"con {stylist_name} está confirmada. Te enviaremos un recordatorio 2 horas antes 😊 "
                        f"¡Te esperamos!"
                    )
                else:
                    response_text = None

                return ConfirmationResult(
                    success=True,
                    appointment_id=appt.id,
                    response_type="template" if is_simple_message else "llm",
                    response_text=response_text,
                    appointment_date=fecha,
                    appointment_time=hora,
                    stylist_name=stylist_name,
                    service_names=service_names,
                )

            elif intent_type == IntentType.DECLINE_APPOINTMENT:
                # Update appointment status
                appt.status = AppointmentStatus.CANCELLED
                appt.cancelled_at = now
                await session.commit()

                # Delete Google Calendar event
                if appt.google_calendar_event_id:
                    try:
                        await delete_gcal_event(
                            stylist_id=appt.stylist_id,
                            event_id=appt.google_calendar_event_id,
                        )
                    except Exception as gcal_error:
                        logger.warning(
                            f"GCal delete failed for appointment {appt.id} "
                            f"(DB already committed to CANCELLED): {gcal_error}"
                        )

                # Create admin notification
                notification = Notification(
                    type=NotificationType.APPOINTMENT_CANCELLED,
                    title=f"{customer.first_name or appt.first_name} canceló su cita",
                    message=f"Cita del {fecha} a las {hora} cancelada por el cliente.",
                    entity_type="appointment",
                    entity_id=appt.id,
                )
                session.add(notification)
                await session.commit()

                logger.info(f"Appointment {appt.id} cancelled by customer {customer.id}")

                # Build response
                if is_simple_message:
                    response_text = (
                        f"Tu cita del {fecha} a las {hora} ha sido cancelada. "
                        f"Si deseas reservar para otra fecha, solo dímelo. "
                        f"¡Hasta pronto!"
                    )
                else:
                    response_text = None

                return ConfirmationResult(
                    success=True,
                    appointment_id=appt.id,
                    response_type="template" if is_simple_message else "llm",
                    response_text=response_text,
                    appointment_date=fecha,
                    appointment_time=hora,
                    stylist_name=stylist_name,
                    service_names=service_names,
                )

            else:
                return ConfirmationResult(
                    success=False,
                    error_message="No entendí tu respuesta. Por favor, responde SÍ o NO.",
                )

    except Exception as e:
        logger.exception(f"Error processing single appointment confirmation: {e}")
        return ConfirmationResult(
            success=False,
            error_message="Ocurrió un error. Por favor, intenta de nuevo.",
        )


async def _process_all_appointments(
    customer: Customer,
    appointments: list[Appointment],
    intent_type: IntentType,
    now: datetime,
) -> ConfirmationResult:
    """
    Process confirmation/cancellation for ALL pending appointments.

    Args:
        customer: Customer object
        appointments: List of appointments to process
        intent_type: CONFIRM_APPOINTMENT or DECLINE_APPOINTMENT
        now: Current timestamp

    Returns:
        ConfirmationResult with outcome for all appointments
    """
    processed_ids = []
    processed_details = []
    errors = []

    is_confirm = intent_type == IntentType.CONFIRM_APPOINTMENT

    try:
        async with get_async_session() as session:
            for appointment in appointments:
                try:
                    # Re-fetch appointment in this session
                    appt_result = await session.execute(
                        select(Appointment)
                        .options(selectinload(Appointment.stylist))
                        .where(Appointment.id == appointment.id)
                    )
                    appt = appt_result.scalars().first()

                    if not appt:
                        errors.append(f"Cita no encontrada: {appointment.id}")
                        continue

                    # Format for response
                    appt_time = appt.start_time.astimezone(MADRID_TZ)
                    fecha = format_date_spanish(appt_time)
                    hora = appt_time.strftime("%H:%M")
                    stylist_name = appt.stylist.name if appt.stylist else "tu estilista"

                    if is_confirm:
                        appt.status = AppointmentStatus.CONFIRMED
                    else:
                        appt.status = AppointmentStatus.CANCELLED
                        appt.cancelled_at = now

                    await session.commit()

                    # Update/Delete Google Calendar
                    if appt.google_calendar_event_id:
                        try:
                            if is_confirm:
                                service_names = await _get_service_names(appt.service_ids)
                                await update_gcal_event_status(
                                    stylist_id=appt.stylist_id,
                                    event_id=appt.google_calendar_event_id,
                                    new_status="confirmed",
                                    customer_name=customer.first_name or appt.first_name,
                                    service_names=service_names,
                                )
                            else:
                                await delete_gcal_event(
                                    stylist_id=appt.stylist_id,
                                    event_id=appt.google_calendar_event_id,
                                )
                        except Exception as gcal_error:
                            logger.warning(f"GCal operation failed for {appt.id}: {gcal_error}")

                    # Create notification
                    if is_confirm:
                        notification = Notification(
                            type=NotificationType.CONFIRMATION_RECEIVED,
                            title=f"{customer.first_name or appt.first_name} confirmó su cita",
                            message=f"Cita del {fecha} a las {hora} confirmada.",
                            entity_type="appointment",
                            entity_id=appt.id,
                        )
                    else:
                        notification = Notification(
                            type=NotificationType.APPOINTMENT_CANCELLED,
                            title=f"{customer.first_name or appt.first_name} canceló su cita",
                            message=f"Cita del {fecha} a las {hora} cancelada por el cliente.",
                            entity_type="appointment",
                            entity_id=appt.id,
                        )
                    session.add(notification)
                    await session.commit()

                    processed_ids.append(appt.id)
                    processed_details.append(f"• {fecha} a las {hora} con {stylist_name}")

                    logger.info(
                        f"Appointment {appt.id} {'confirmed' if is_confirm else 'cancelled'} "
                        f"by customer {customer.id}"
                    )

                except Exception as appt_error:
                    logger.error(f"Error processing appointment {appointment.id}: {appt_error}")
                    errors.append(str(appointment.id))

        if not processed_ids:
            return ConfirmationResult(
                success=False,
                error_message="No se pudo procesar ninguna cita. Por favor, intenta de nuevo.",
            )

        # Build response
        action_word = "confirmadas" if is_confirm else "canceladas"
        details_str = "\n".join(processed_details)

        if is_confirm:
            response_text = (
                f"¡Perfecto! Tus {len(processed_ids)} citas han sido {action_word}:\n\n"
                f"{details_str}\n\n"
                f"¡Te esperamos!"
            )
        else:
            response_text = (
                f"Tus {len(processed_ids)} citas han sido {action_word}:\n\n"
                f"{details_str}\n\n"
                f"Si deseas reservar nuevas citas, solo dímelo. ¡Hasta pronto!"
            )

        return ConfirmationResult(
            success=True,
            appointment_ids=processed_ids,
            response_type="template",
            response_text=response_text,
            multiple_processed=len(processed_ids),
        )

    except Exception as e:
        logger.exception(f"Error processing all appointments: {e}")
        return ConfirmationResult(
            success=False,
            error_message="Ocurrió un error. Por favor, intenta de nuevo.",
        )


async def handle_confirmation_response(
    customer_phone: str,
    intent_type: IntentType,
    message_text: str,
) -> ConfirmationResult:
    """
    Process a customer's confirmation response.

    Args:
        customer_phone: E.164 formatted phone number
        intent_type: CONFIRM_APPOINTMENT or DECLINE_APPOINTMENT
        message_text: Original message text from customer

    Returns:
        ConfirmationResult with outcome and response data

    Logic:
        - CONFIRM_APPOINTMENT: Update status to CONFIRMED, update GCal
        - DECLINE_APPOINTMENT: Update status to CANCELLED, delete GCal event
        - Creates admin notification in both cases
        - Returns template response if message is simple, LLM flag if complex
    """
    now = datetime.now(MADRID_TZ)

    # Get customer
    customer = await get_customer_by_phone(customer_phone)
    if not customer:
        logger.warning(f"Customer not found for phone {customer_phone}")
        return ConfirmationResult(
            success=False,
            error_message="No encontramos tu perfil. Por favor, contacta con nosotros.",
        )

    # Get ALL pending appointments
    pending_appointments = await get_pending_confirmations(customer.id)
    if not pending_appointments:
        logger.info(f"No pending confirmation found for customer {customer.id}")
        return ConfirmationResult(
            success=False,
            error_message="No tienes ninguna cita pendiente de confirmación.",
        )

    # Check for multiple pending appointments
    if len(pending_appointments) > 1:
        # Check if user specified multi-selection (e.g., "todas", "1", "la primera")
        is_all, is_cancel_all, selection_number = detect_multi_selection(message_text)

        if is_all:
            # User wants to confirm/cancel ALL appointments
            action_type = IntentType.DECLINE_APPOINTMENT if is_cancel_all else intent_type
            return await _process_all_appointments(
                customer=customer,
                appointments=pending_appointments,
                intent_type=action_type,
                now=now,
            )

        if selection_number is not None:
            # User selected a specific appointment by number
            if selection_number < 1 or selection_number > len(pending_appointments):
                # Invalid number, show list again
                appt_list = _build_appointment_list(pending_appointments)
                return ConfirmationResult(
                    success=False,
                    error_message=(
                        f"El número {selection_number} no es válido. "
                        f"Tienes {len(pending_appointments)} citas:\n\n{appt_list}\n\n"
                        f"Responde con un número del 1 al {len(pending_appointments)}."
                    ),
                )
            # Process the selected appointment
            selected_appointment = pending_appointments[selection_number - 1]
            return await _process_single_appointment(
                customer=customer,
                appointment=selected_appointment,
                intent_type=intent_type,
                message_text=message_text,
                now=now,
            )

        # No multi-selection detected, show improved guide
        appt_list = _build_appointment_list(pending_appointments)
        logger.info(f"Customer {customer.id} has {len(pending_appointments)} pending confirmations")
        return ConfirmationResult(
            success=False,
            error_message=(
                f"Tienes {len(pending_appointments)} citas pendientes:\n\n"
                f"{appt_list}\n\n"
                f"¿Cuál quieres gestionar?\n"
                f"• *TODAS* - para confirmar todas\n"
                f"• *1*, *2*... - para una cita específica\n"
                f"• *CANCELAR TODAS* - para cancelar todas"
            ),
        )

    # Single appointment - use helper function
    return await _process_single_appointment(
        customer=customer,
        appointment=pending_appointments[0],
        intent_type=intent_type,
        message_text=message_text,
        now=now,
    )

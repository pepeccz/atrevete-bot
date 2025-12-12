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

# Spanish weekday and month names for date formatting
WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
]


def format_date_spanish(dt: datetime) -> str:
    """Format datetime to Spanish date string."""
    return f"{WEEKDAYS_ES[dt.weekday()]} {dt.day} de {MONTHS_ES[dt.month - 1]}"


@dataclass
class ConfirmationResult:
    """
    Result of processing a confirmation response.

    Attributes:
        success: Whether the operation succeeded
        appointment_id: UUID of the appointment (if found)
        response_type: "template" for simple responses, "llm" for complex ones
        response_text: Pre-generated response text (if response_type is "template")
        appointment_date: Formatted date string for the appointment
        appointment_time: Time string (HH:MM) for the appointment
        stylist_name: Name of the stylist
        service_names: Comma-separated service names
        error_message: Error message if success is False
    """
    success: bool
    appointment_id: Optional[UUID] = None
    response_type: str = "template"
    response_text: Optional[str] = None
    appointment_date: Optional[str] = None
    appointment_time: Optional[str] = None
    stylist_name: Optional[str] = None
    service_names: Optional[str] = None
    error_message: Optional[str] = None


async def get_pending_confirmation(customer_id: UUID) -> Optional[Appointment]:
    """
    Get the appointment awaiting confirmation for a customer.

    Finds PENDING appointments where confirmation_sent_at IS NOT NULL,
    ordered by start_time (soonest first).

    Args:
        customer_id: UUID of the customer

    Returns:
        Appointment object if found, None otherwise
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
                .limit(1)
            )
            return result.scalars().first()

    except Exception as e:
        logger.error(f"Error fetching pending confirmation for customer {customer_id}: {e}")
        return None


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

    # Get pending appointment
    appointment = await get_pending_confirmation(customer.id)
    if not appointment:
        logger.info(f"No pending confirmation found for customer {customer.id}")
        return ConfirmationResult(
            success=False,
            error_message="No tienes ninguna cita pendiente de confirmación.",
        )

    # Get service names
    try:
        async with get_async_session() as session:
            services_result = await session.execute(
                select(Service).where(Service.id.in_(appointment.service_ids))
            )
            services = list(services_result.scalars().all())
            service_names = ", ".join([s.name for s in services])
    except Exception:
        service_names = "servicios"

    # Format dates
    appt_time = appointment.start_time.astimezone(MADRID_TZ)
    fecha = format_date_spanish(appt_time)
    hora = appt_time.strftime("%H:%M")

    # Get stylist name
    stylist_name = appointment.stylist.name if appointment.stylist else "tu estilista"

    # Determine if response should use template or LLM
    # Simple messages get template, complex messages get LLM
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
                    await update_gcal_event_status(
                        stylist_id=appt.stylist_id,
                        event_id=appt.google_calendar_event_id,
                        new_status="confirmed",
                        customer_name=customer.name or appt.first_name,
                        service_names=service_names,
                    )

                # Create admin notification
                notification = Notification(
                    type=NotificationType.CONFIRMATION_RECEIVED,
                    title=f"{customer.name or appt.first_name} confirmó su cita",
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
                        f"con {stylist_name} está confirmada. "
                        f"¡Te esperamos!"
                    )
                else:
                    response_text = None  # Let LLM generate response

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
                    await delete_gcal_event(
                        stylist_id=appt.stylist_id,
                        event_id=appt.google_calendar_event_id,
                    )

                # Create admin notification
                notification = Notification(
                    type=NotificationType.APPOINTMENT_CANCELLED,
                    title=f"{customer.name or appt.first_name} canceló su cita",
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
                    response_text = None  # Let LLM generate response

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
        logger.exception(f"Error handling confirmation response: {e}")
        return ConfirmationResult(
            success=False,
            error_message="Ocurrió un error. Por favor, intenta de nuevo.",
        )

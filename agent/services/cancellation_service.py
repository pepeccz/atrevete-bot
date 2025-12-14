"""
Appointment cancellation service - Handles customer-initiated cancellations.

This service processes customer requests to cancel their appointments:
- INITIATE_CANCELLATION: Start cancellation flow, show appointments
- SELECT_CANCELLATION: User selects which appointment to cancel
- CONFIRM_CANCELLATION: User confirms cancellation
- ABORT_CANCELLATION: User aborts cancellation flow
- INSIST_CANCELLATION: User insists despite window restriction -> escalate

Architecture:
- Called from NonBookingHandler when cancellation intent is detected
- Validates cancellation window (configurable, default 48h before)
- Updates appointment status in database
- Deletes Google Calendar events (fire-and-forget)
- Creates admin panel notifications
- Returns response data for template response
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
from agent.services.gcal_push_service import delete_gcal_event
from shared.settings_service import get_settings_service

logger = logging.getLogger(__name__)

MADRID_TZ = ZoneInfo("Europe/Madrid")

# Spanish weekday and month names for date formatting
WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
]

# Keywords for number selection (to select which appointment to cancel)
NUMBER_SELECTION_PATTERNS = {
    "1": 1, "la 1": 1, "la primera": 1, "primera": 1, "uno": 1, "la uno": 1,
    "2": 2, "la 2": 2, "la segunda": 2, "segunda": 2, "dos": 2, "la dos": 2,
    "3": 3, "la 3": 3, "la tercera": 3, "tercera": 3, "tres": 3, "la tres": 3,
    "4": 4, "la 4": 4, "la cuarta": 4, "cuarta": 4, "cuatro": 4, "la cuatro": 4,
    "5": 5, "la 5": 5, "la quinta": 5, "quinta": 5, "cinco": 5, "la cinco": 5,
}


def format_date_spanish(dt: datetime) -> str:
    """Format datetime to Spanish date string."""
    return f"{WEEKDAYS_ES[dt.weekday()]} {dt.day} de {MONTHS_ES[dt.month - 1]}"


def detect_number_selection(message: str) -> Optional[int]:
    """
    Detect if user selected a specific appointment by number.

    Args:
        message: User's message text

    Returns:
        Selected number (1-based) or None if no selection detected
    """
    msg_lower = message.lower().strip()
    for pattern, number in NUMBER_SELECTION_PATTERNS.items():
        if msg_lower == pattern or msg_lower.startswith(f"{pattern} "):
            return number
    return None


@dataclass
class CancellationResult:
    """
    Result of processing a cancellation request.

    Attributes:
        success: Whether the operation succeeded
        appointment_id: UUID of the appointment (if single selection)
        response_type: "template" for simple responses, "llm" for complex ones
        response_text: Pre-generated response text
        error_message: Error message if success is False
        within_window: True if cancellation blocked due to time window
        multiple_appointments: True if customer has multiple appointments to choose from
        appointment_list: Formatted list of appointments for selection
        hours_until_appointment: Hours remaining until appointment (for window messages)
    """
    success: bool
    appointment_id: Optional[UUID] = None
    response_type: str = "template"
    response_text: Optional[str] = None
    error_message: Optional[str] = None
    within_window: bool = False
    multiple_appointments: bool = False
    appointment_list: Optional[str] = None
    hours_until_appointment: Optional[int] = None


async def get_cancellation_window_hours() -> int:
    """
    Get configurable cancellation window from database settings.

    Returns:
        Number of hours before appointment that cancellation is allowed.
        Default: 48 hours
    """
    try:
        settings_service = await get_settings_service()
        return await settings_service.get("cancellation_window_hours", 48)
    except Exception as e:
        logger.warning(f"Could not load cancellation_window_hours setting: {e}. Using default 48h.")
        return 48


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


async def get_cancellable_appointments(customer_id: UUID) -> list[Appointment]:
    """
    Get all future appointments that could potentially be cancelled.

    Returns PENDING or CONFIRMED appointments in the future.
    Does NOT filter by cancellation window - that's done at cancellation time.

    Args:
        customer_id: UUID of the customer

    Returns:
        List of Appointment objects, ordered by start_time (soonest first)
    """
    now = datetime.now(MADRID_TZ)

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
                        Appointment.status.in_([
                            AppointmentStatus.PENDING,
                            AppointmentStatus.CONFIRMED,
                        ]),
                        Appointment.start_time > now,
                    )
                )
                .order_by(Appointment.start_time.asc())
            )
            return list(result.scalars().all())
    except Exception as e:
        logger.error(f"Error fetching cancellable appointments for customer {customer_id}: {e}")
        return []


async def check_cancellation_allowed(appointment: Appointment) -> tuple[bool, int]:
    """
    Check if appointment can be cancelled based on time window.

    Args:
        appointment: Appointment to check

    Returns:
        Tuple of (is_allowed, hours_until_appointment)
    """
    window_hours = await get_cancellation_window_hours()
    now = datetime.now(MADRID_TZ)
    appt_time = appointment.start_time.astimezone(MADRID_TZ)

    hours_until = (appt_time - now).total_seconds() / 3600

    return (hours_until >= window_hours, int(hours_until))


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


async def initiate_cancellation_flow(customer_phone: str) -> CancellationResult:
    """
    Start the cancellation flow for a customer.

    - If customer has 0 appointments -> error message
    - If customer has 1 appointment -> show it and ask confirmation
    - If customer has 2+ appointments -> show list and ask selection

    Args:
        customer_phone: E.164 formatted phone number

    Returns:
        CancellationResult with appropriate response
    """
    # Get customer
    customer = await get_customer_by_phone(customer_phone)
    if not customer:
        logger.warning(f"Cancellation attempted for unknown phone: {customer_phone}")
        return CancellationResult(
            success=False,
            error_message="No encontramos tu perfil. Por favor, contacta con nosotros.",
        )

    # Get cancellable appointments
    appointments = await get_cancellable_appointments(customer.id)

    if not appointments:
        return CancellationResult(
            success=False,
            error_message="No tienes citas futuras para cancelar.",
        )

    if len(appointments) == 1:
        # Single appointment - ask for confirmation directly
        appt = appointments[0]
        appt_time = appt.start_time.astimezone(MADRID_TZ)
        fecha = format_date_spanish(appt_time)
        hora = appt_time.strftime("%H:%M")
        stylist_name = appt.stylist.name if appt.stylist else "tu estilista"

        # Check if within window
        is_allowed, hours_until = await check_cancellation_allowed(appt)

        if not is_allowed:
            window_hours = await get_cancellation_window_hours()
            return CancellationResult(
                success=False,
                within_window=True,
                appointment_id=appt.id,
                hours_until_appointment=hours_until,
                error_message=(
                    f"Tu cita del {fecha} a las {hora} es en {hours_until} horas. "
                    f"Solo puedes cancelar con al menos {window_hours} horas de antelación. "
                    f"Si realmente necesitas cancelar, puedo conectarte con el equipo. "
                    f"¿Quieres que te conecte?"
                ),
            )

        # Get service names for display
        service_names = await _get_service_names(appt.service_ids)

        return CancellationResult(
            success=True,
            appointment_id=appt.id,
            response_type="template",
            response_text=(
                f"Tienes una cita el {fecha} a las {hora} con {stylist_name} "
                f"({service_names}).\n\n"
                f"¿Estás seguro/a de que quieres cancelarla?"
            ),
        )

    # Multiple appointments - show list
    appt_list = _build_appointment_list(appointments)

    return CancellationResult(
        success=True,
        multiple_appointments=True,
        appointment_list=appt_list,
        response_type="template",
        response_text=(
            f"Tienes {len(appointments)} citas futuras:\n\n"
            f"{appt_list}\n\n"
            f"¿Cuál quieres cancelar? Responde con el número."
        ),
    )


async def select_appointment_for_cancellation(
    customer_phone: str,
    selection_number: int,
) -> CancellationResult:
    """
    Handle user selection of which appointment to cancel.

    Args:
        customer_phone: E.164 formatted phone number
        selection_number: 1-based index of selected appointment

    Returns:
        CancellationResult asking for confirmation or error
    """
    customer = await get_customer_by_phone(customer_phone)
    if not customer:
        return CancellationResult(
            success=False,
            error_message="No encontramos tu perfil. Por favor, contacta con nosotros.",
        )

    appointments = await get_cancellable_appointments(customer.id)

    if not appointments:
        return CancellationResult(
            success=False,
            error_message="No tienes citas futuras para cancelar.",
        )

    # Validate selection number
    if selection_number < 1 or selection_number > len(appointments):
        return CancellationResult(
            success=False,
            error_message=f"Ese número no es válido. Por favor, elige un número del 1 al {len(appointments)}.",
        )

    # Get selected appointment (convert to 0-based index)
    appt = appointments[selection_number - 1]
    appt_time = appt.start_time.astimezone(MADRID_TZ)
    fecha = format_date_spanish(appt_time)
    hora = appt_time.strftime("%H:%M")
    stylist_name = appt.stylist.name if appt.stylist else "tu estilista"

    # Check if within window
    is_allowed, hours_until = await check_cancellation_allowed(appt)

    if not is_allowed:
        window_hours = await get_cancellation_window_hours()
        return CancellationResult(
            success=False,
            within_window=True,
            appointment_id=appt.id,
            hours_until_appointment=hours_until,
            error_message=(
                f"Esa cita del {fecha} a las {hora} es en {hours_until} horas. "
                f"Solo puedes cancelar con al menos {window_hours} horas de antelación. "
                f"Si realmente necesitas cancelar, puedo conectarte con el equipo. "
                f"¿Quieres que te conecte?"
            ),
        )

    # Get service names for display
    service_names = await _get_service_names(appt.service_ids)

    return CancellationResult(
        success=True,
        appointment_id=appt.id,
        response_type="template",
        response_text=(
            f"¿Estás seguro/a de que quieres cancelar tu cita del {fecha} "
            f"a las {hora} con {stylist_name} ({service_names})?"
        ),
    )


async def execute_cancellation(
    appointment_id: UUID,
    reason: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> CancellationResult:
    """
    Execute appointment cancellation.

    1. Update DB status to CANCELLED
    2. Set cancelled_at and cancellation_reason
    3. Delete Google Calendar event (fire-and-forget)
    4. Create admin notification
    5. Return result for response generation

    Args:
        appointment_id: UUID of appointment to cancel
        reason: Optional cancellation reason from customer
        conversation_id: Optional conversation ID for logging

    Returns:
        CancellationResult with success/error status
    """
    now = datetime.now(MADRID_TZ)

    try:
        async with get_async_session() as session:
            # Fetch appointment with relations
            result = await session.execute(
                select(Appointment)
                .options(
                    selectinload(Appointment.customer),
                    selectinload(Appointment.stylist),
                )
                .where(Appointment.id == appointment_id)
            )
            appointment = result.scalars().first()

            if not appointment:
                return CancellationResult(
                    success=False,
                    error_message="No se encontró la cita. Por favor, intenta de nuevo.",
                )

            # Check if already cancelled
            if appointment.status == AppointmentStatus.CANCELLED:
                return CancellationResult(
                    success=False,
                    error_message="Esta cita ya fue cancelada anteriormente.",
                )

            # Re-check window (in case time passed since selection)
            is_allowed, hours_until = await check_cancellation_allowed(appointment)
            if not is_allowed:
                window_hours = await get_cancellation_window_hours()
                appt_time = appointment.start_time.astimezone(MADRID_TZ)
                fecha = format_date_spanish(appt_time)
                hora = appt_time.strftime("%H:%M")
                return CancellationResult(
                    success=False,
                    within_window=True,
                    hours_until_appointment=hours_until,
                    error_message=(
                        f"Tu cita del {fecha} a las {hora} es en {hours_until} horas. "
                        f"Ya no puedes cancelar por este medio (mínimo {window_hours}h de antelación). "
                        f"Por favor, contacta directamente con el equipo."
                    ),
                )

            # Format for response before update
            appt_time = appointment.start_time.astimezone(MADRID_TZ)
            fecha = format_date_spanish(appt_time)
            hora = appt_time.strftime("%H:%M")
            stylist_name = appointment.stylist.name if appointment.stylist else "tu estilista"
            customer_name = appointment.customer.first_name or appointment.first_name or "Cliente"

            # Get service names
            service_names = await _get_service_names(appointment.service_ids)

            # Update appointment
            appointment.status = AppointmentStatus.CANCELLED
            appointment.cancelled_at = now
            appointment.cancellation_reason = reason

            await session.commit()

            logger.info(
                f"Appointment {appointment.id} cancelled by customer | "
                f"reason={reason or 'not provided'} | conversation_id={conversation_id}"
            )

            # Delete Google Calendar event (fire-and-forget)
            if appointment.google_calendar_event_id:
                try:
                    await delete_gcal_event(
                        stylist_id=appointment.stylist_id,
                        event_id=appointment.google_calendar_event_id,
                    )
                    logger.info(f"GCal event deleted for cancelled appointment {appointment.id}")
                except Exception as e:
                    logger.warning(
                        f"GCal delete failed for appointment {appointment.id} "
                        f"(DB already committed to CANCELLED): {e}"
                    )

            # Create admin notification
            notification = Notification(
                type=NotificationType.APPOINTMENT_CANCELLED,
                title=f"{customer_name} canceló su cita",
                message=(
                    f"Cita del {fecha} a las {hora} con {stylist_name} ({service_names}) "
                    f"cancelada por el cliente"
                    + (f". Motivo: {reason}" if reason else "")
                ),
                entity_type="appointment",
                entity_id=appointment.id,
            )
            session.add(notification)
            await session.commit()

            return CancellationResult(
                success=True,
                appointment_id=appointment.id,
                response_type="template",
                response_text=(
                    f"Tu cita del {fecha} a las {hora} con {stylist_name} "
                    f"ha sido cancelada.\n\n"
                    f"¿Te gustaría reservar una nueva cita para otra fecha?"
                ),
            )

    except Exception as e:
        logger.exception(f"Error cancelling appointment {appointment_id}: {e}")
        return CancellationResult(
            success=False,
            error_message="Ha ocurrido un error al cancelar la cita. Por favor, intenta de nuevo.",
        )


async def handle_cancellation_response(
    customer_phone: str,
    intent_type: str,
    message_text: str,
    pending_appointment_id: Optional[str] = None,
    cancellation_appointments: Optional[list[dict]] = None,
) -> CancellationResult:
    """
    Main entry point for handling cancellation-related intents.

    Dispatches to appropriate handler based on intent type and state.

    Args:
        customer_phone: E.164 formatted phone number
        intent_type: Type of cancellation intent
        message_text: Original user message
        pending_appointment_id: ID of appointment pending cancellation (from state)
        cancellation_appointments: List of appointments shown to user (from state)

    Returns:
        CancellationResult with appropriate response
    """
    from agent.fsm.models import IntentType

    logger.info(
        f"Handling cancellation | intent={intent_type} | phone={customer_phone} | "
        f"pending_id={pending_appointment_id}"
    )

    # Convert string to IntentType if needed
    if isinstance(intent_type, str):
        try:
            intent_type = IntentType(intent_type)
        except ValueError:
            logger.warning(f"Unknown intent type: {intent_type}")
            return CancellationResult(
                success=False,
                error_message="Ha ocurrido un error. Por favor, intenta de nuevo.",
            )

    if intent_type == IntentType.INITIATE_CANCELLATION:
        return await initiate_cancellation_flow(customer_phone)

    elif intent_type == IntentType.SELECT_CANCELLATION:
        # User selected a specific appointment by number
        selection = detect_number_selection(message_text)
        if selection:
            return await select_appointment_for_cancellation(customer_phone, selection)
        else:
            return CancellationResult(
                success=False,
                error_message="No entendí qué cita quieres cancelar. Por favor, responde con el número (1, 2, 3...).",
            )

    elif intent_type == IntentType.CONFIRM_CANCELLATION:
        # User confirmed cancellation
        if pending_appointment_id:
            try:
                appt_uuid = UUID(pending_appointment_id)
                # Extract reason if user provided one
                reason = None
                if len(message_text.split()) > 3:
                    # User provided more than just "sí" - might contain reason
                    reason = message_text
                return await execute_cancellation(appt_uuid, reason=reason)
            except ValueError:
                logger.error(f"Invalid appointment UUID: {pending_appointment_id}")
                return CancellationResult(
                    success=False,
                    error_message="Ha ocurrido un error. Por favor, intenta de nuevo.",
                )
        else:
            # No pending appointment - might be single appointment flow
            customer = await get_customer_by_phone(customer_phone)
            if customer:
                appointments = await get_cancellable_appointments(customer.id)
                if len(appointments) == 1:
                    return await execute_cancellation(appointments[0].id)
            return CancellationResult(
                success=False,
                error_message="No hay ninguna cita seleccionada para cancelar. ¿Qué cita quieres cancelar?",
            )

    elif intent_type == IntentType.ABORT_CANCELLATION:
        return CancellationResult(
            success=True,
            response_type="template",
            response_text="Entendido, no cancelaré ninguna cita. ¿En qué más puedo ayudarte?",
        )

    elif intent_type == IntentType.INSIST_CANCELLATION:
        # User insists despite window restriction -> return signal to escalate
        return CancellationResult(
            success=False,
            within_window=True,
            error_message="ESCALATE",  # Signal to handler to escalate
        )

    else:
        logger.warning(f"Unexpected intent type in cancellation handler: {intent_type}")
        return CancellationResult(
            success=False,
            error_message="No entendí tu respuesta. ¿Quieres cancelar una cita?",
        )

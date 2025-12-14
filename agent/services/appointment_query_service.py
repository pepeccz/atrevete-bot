"""
Appointment query service - Handles customer appointment lookup requests.

This service processes customer requests to view their upcoming appointments:
- CHECK_MY_APPOINTMENTS: User wants to see their scheduled appointments

Architecture:
- Called from NonBookingHandler when appointment query intent is detected
- Returns formatted list of upcoming appointments
- No state management (single request-response)
- Read-only operation (no database modifications)
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
    Service,
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
class AppointmentQueryResult:
    """
    Result of processing an appointment query request.

    Attributes:
        success: Whether the operation succeeded
        has_appointments: True if customer has upcoming appointments
        response_text: Pre-generated response text
        appointment_count: Number of appointments found
        error_message: Error message if success is False
    """
    success: bool
    has_appointments: bool = False
    response_text: str = ""
    appointment_count: int = 0
    error_message: Optional[str] = None


async def _get_customer_by_phone(phone_number: str) -> Optional[Customer]:
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


async def _get_upcoming_appointments(customer_id: UUID, limit: int = 5) -> list[Appointment]:
    """
    Get upcoming appointments for a customer.

    Returns PENDING or CONFIRMED appointments in the future.

    Args:
        customer_id: UUID of the customer
        limit: Maximum number of appointments to return (default 5)

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
                .limit(limit)
            )
            return list(result.scalars().all())
    except Exception as e:
        logger.error(f"Error fetching upcoming appointments for customer {customer_id}: {e}")
        return []


async def _get_service_names(service_ids: list[UUID]) -> str:
    """Get comma-separated service names from service IDs."""
    if not service_ids:
        return "servicios"
    try:
        async with get_async_session() as session:
            services_result = await session.execute(
                select(Service).where(Service.id.in_(service_ids))
            )
            services = list(services_result.scalars().all())
            if services:
                return " + ".join([s.name for s in services])
            return "servicios"
    except Exception:
        return "servicios"


def _format_appointments_list(appointments: list[Appointment]) -> str:
    """
    Build a formatted list of appointments for user display.

    Format:
    1. Viernes 20 de diciembre a las 10:00 con María (Corte + Tinte)
    2. Lunes 23 de diciembre a las 16:00 con Ana (Manicura)

    Args:
        appointments: List of Appointment objects (must have stylist loaded)

    Returns:
        Formatted string with numbered appointment list
    """
    lines = []
    for i, appt in enumerate(appointments, 1):
        appt_time = appt.start_time.astimezone(MADRID_TZ)
        fecha = format_date_spanish(appt_time)
        hora = appt_time.strftime("%H:%M")
        stylist = appt.stylist.name if appt.stylist else "tu estilista"
        lines.append(f"{i}. {fecha.capitalize()} a las {hora} con {stylist}")
    return "\n".join(lines)


async def get_upcoming_appointments(customer_phone: str, limit: int = 5) -> AppointmentQueryResult:
    """
    Get upcoming appointments for a customer by phone number.

    This is the main entry point for the appointment query feature.

    Args:
        customer_phone: E.164 formatted phone number
        limit: Maximum number of appointments to return (default 5)

    Returns:
        AppointmentQueryResult with formatted response
    """
    logger.info(f"Querying appointments for phone: {customer_phone}")

    # Get customer
    customer = await _get_customer_by_phone(customer_phone)
    if not customer:
        logger.warning(f"Appointment query for unknown phone: {customer_phone}")
        return AppointmentQueryResult(
            success=True,
            has_appointments=False,
            response_text="No tienes citas programadas en este momento. ¿Te gustaría reservar una?",
        )

    # Get appointments
    try:
        appointments = await _get_upcoming_appointments(customer.id, limit)
    except Exception as e:
        logger.error(f"Error fetching appointments: {e}")
        return AppointmentQueryResult(
            success=False,
            error_message=(
                "Lo siento, no he podido consultar tus citas en este momento. "
                "¿Quieres que te conecte con el equipo para ayudarte?"
            ),
        )

    if not appointments:
        return AppointmentQueryResult(
            success=True,
            has_appointments=False,
            response_text="No tienes citas programadas en este momento. ¿Te gustaría reservar una?",
        )

    # Format appointments list
    appt_list = _format_appointments_list(appointments)

    # Build response based on count
    if len(appointments) == 1:
        appt = appointments[0]
        appt_time = appt.start_time.astimezone(MADRID_TZ)
        fecha = format_date_spanish(appt_time)
        hora = appt_time.strftime("%H:%M")
        stylist_name = appt.stylist.name if appt.stylist else "tu estilista"

        response = (
            f"Tienes una cita el {fecha} a las {hora} con {stylist_name}.\n\n"
            f"¿Necesitas algo más?"
        )
    else:
        response = (
            f"Tienes {len(appointments)} citas próximas:\n\n"
            f"{appt_list}\n\n"
            f"¿Necesitas algo más?"
        )

    logger.info(f"Found {len(appointments)} appointments for customer {customer.id}")

    return AppointmentQueryResult(
        success=True,
        has_appointments=True,
        response_text=response,
        appointment_count=len(appointments),
    )

"""
Transaction Validators for Booking Business Rules.

Validators that check business constraints before atomic transactions execute.
Used by BookingTransaction to ensure bookings meet all requirements.
"""

import logging
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_async_session
from database.models import Appointment, AppointmentStatus, Service, ServiceCategory

logger = logging.getLogger(__name__)

MADRID_TZ = ZoneInfo("Europe/Madrid")

# Minimum days in advance required for booking
# Business rule: Bookings must be made at least 3 days in advance
MINIMUM_DAYS = 3


async def validate_category_consistency(service_ids: list[UUID]) -> dict:
    """
    Validate that all services belong to the same category.

    Business rule: Cannot mix Peluquería + Estética services in same booking.
    This is enforced because:
    - Different categories may have different stylists
    - Different booking flows/requirements
    - Salon operational constraints

    Args:
        service_ids: List of Service UUIDs to validate

    Returns:
        dict with validation result:
            {
                "valid": bool,
                "error_code": str | None,  # "CATEGORY_MISMATCH" if invalid
                "error_message": str | None,
                "categories_found": list[str]  # List of category names found
            }

    Example:
        Valid (all Peluquería):
        >>> await validate_category_consistency([uuid1, uuid2, uuid3])
        {"valid": True, "error_code": None, "error_message": None, "categories_found": ["Peluquería"]}

        Invalid (mix):
        >>> await validate_category_consistency([uuid_pelo, uuid_estetica])
        {
            "valid": False,
            "error_code": "CATEGORY_MISMATCH",
            "error_message": "No se pueden mezclar servicios de Peluquería y Estética...",
            "categories_found": ["Peluquería", "Estética"]
        }
    """
    if not service_ids:
        return {
            "valid": True,
            "error_code": None,
            "error_message": None,
            "categories_found": []
        }

    async with get_async_session() as session:
        try:
            # Fetch all services
            stmt = select(Service).where(Service.id.in_(service_ids))
            result = await session.execute(stmt)
            services = result.scalars().all()

            # Extract unique categories
            categories = set(service.category for service in services)
            category_names = [cat.value for cat in categories]

            if len(categories) > 1:
                # Mix detected
                logger.warning(
                    f"Category mismatch detected: {category_names}",
                    extra={"service_ids": [str(sid) for sid in service_ids]}
                )

                return {
                    "valid": False,
                    "error_code": "CATEGORY_MISMATCH",
                    "error_message": (
                        f"Lo siento, no puedo agendar servicios de diferentes categorías "
                        f"({', '.join(category_names)}) en la misma cita. "
                        f"Por favor, elige servicios de una sola categoría."
                    ),
                    "categories_found": category_names
                }

            logger.info(
                f"Category validation passed: all services are {category_names[0]}",
                extra={"category": category_names[0]}
            )

            return {
                "valid": True,
                "error_code": None,
                "error_message": None,
                "categories_found": category_names
            }

        except Exception as e:
            logger.error(f"Database error during category validation: {e}", exc_info=True)
            raise


async def validate_slot_availability(
    stylist_id: UUID,
    start_time: datetime,
    duration_minutes: int,
    session: AsyncSession
) -> dict:
    """
    Validate that a slot is available with 10-minute buffer.

    Checks for conflicts with existing appointments:
    - Slot overlaps with another appointment
    - Slot is within 10 minutes before/after another appointment (buffer)

    Args:
        stylist_id: Stylist UUID
        start_time: Proposed start time (timezone-aware)
        duration_minutes: Duration including 10-min buffer
        session: SQLAlchemy async session (must be in active transaction)

    Returns:
        dict with validation result:
            {
                "available": bool,
                "error_code": str | None,  # "SLOT_TAKEN" or "BUFFER_CONFLICT"
                "error_message": str | None,
                "conflicting_appointment_id": UUID | None
            }

    Example:
        Available:
        >>> await validate_slot_availability(stylist_uuid, datetime(...), 90, session)
        {"available": True, "error_code": None, ...}

        Conflict:
        >>> await validate_slot_availability(stylist_uuid, datetime(...), 90, session)
        {
            "available": False,
            "error_code": "SLOT_TAKEN",
            "error_message": "El horario ya está ocupado...",
            "conflicting_appointment_id": UUID("...")
        }

    Notes:
        - Uses SELECT FOR UPDATE to lock rows and prevent race conditions
        - duration_minutes should already include 10-min buffer
        - Only checks appointments with status in ('provisional', 'confirmed')
    """
    end_time = start_time + timedelta(minutes=duration_minutes)

    # Query for overlapping appointments with row lock
    # Note: We calculate appointment end_time dynamically since it's not a column
    # Formula: start_time + (duration_minutes || ' minutes')::interval
    stmt = (
        select(Appointment)
        .where(Appointment.stylist_id == stylist_id)
        .where(Appointment.status.in_([AppointmentStatus.PENDING.value, AppointmentStatus.CONFIRMED.value]))
        # Check for overlap: existing appointment overlaps with [start_time, end_time]
        # Appointment starts before our end_time
        .where(Appointment.start_time < end_time)
        # Appointment ends after our start_time (calculated dynamically)
        # Note: Use bindparams() for proper SQLAlchemy 2.0 text() comparison
        .where(text("start_time + (duration_minutes || ' minutes')::interval > :start_time").bindparams(start_time=start_time))
        .with_for_update()  # Row lock to prevent concurrent bookings
    )

    result = await session.execute(stmt)
    conflicting_appointments = list(result.scalars().all())

    # All appointments returned by the query are conflicts
    # (both 'pending' and 'confirmed' status)
    # Note: Payment system removed Nov 10, 2025 - all appointments auto-confirm

    if conflicting_appointments:
        conflict = conflicting_appointments[0]
        logger.warning(
            f"Slot conflict detected: {start_time} - {end_time}",
            extra={
                "stylist_id": str(stylist_id),
                "conflicting_appointment_id": str(conflict.id),
                "conflict_start": conflict.start_time.isoformat(),
                "conflict_end": conflict.end_time.isoformat()
            }
        )

        return {
            "available": False,
            "error_code": "SLOT_TAKEN",
            "error_message": (
                "El horario seleccionado ya está ocupado. "
                "Por favor, elige otro horario de los disponibles."
            ),
            "conflicting_appointment_id": conflict.id
        }

    logger.info(
        f"Slot available: {start_time} - {end_time}",
        extra={"stylist_id": str(stylist_id)}
    )

    return {
        "available": True,
        "error_code": None,
        "error_message": None,
        "conflicting_appointment_id": None
    }


async def validate_3_day_rule(requested_date: datetime) -> dict:
    """
    Validate that booking meets 3-day minimum notice requirement.

    Business rule: Bookings must be made at least 3 days in advance.
    This gives the salon sufficient time to:
    - Prepare materials/products
    - Schedule stylists
    - Handle cancellations/modifications

    Args:
        requested_date: Requested appointment date (timezone-aware)

    Returns:
        dict with validation result:
            {
                "valid": bool,
                "error_code": str | None,  # "DATE_TOO_SOON" if invalid
                "error_message": str | None,
                "days_until_appointment": int,
                "minimum_required_days": int
            }

    Example:
        Valid (> 3 days):
        >>> await validate_3_day_rule(datetime(2025, 11, 15))  # Today is Nov 4
        {"valid": True, "error_code": None, "days_until_appointment": 11, ...}

        Invalid (< 3 days):
        >>> await validate_3_day_rule(datetime(2025, 11, 6))  # Today is Nov 4
        {
            "valid": False,
            "error_code": "DATE_TOO_SOON",
            "error_message": "Las citas deben agendarse con al menos 3 días de anticipación...",
            "days_until_appointment": 2,
            "minimum_required_days": 3
        }

    Notes:
        - Uses Europe/Madrid timezone
        - Compares dates at midnight (ignores time)
        - 3-day rule is strict (< 3 days = invalid)
    """
    # Get current date at midnight in Madrid timezone
    now = datetime.now(MADRID_TZ).replace(hour=0, minute=0, second=0, microsecond=0)

    # Ensure requested_date is timezone-aware and at midnight
    if requested_date.tzinfo is None:
        requested_date = requested_date.replace(tzinfo=MADRID_TZ)
    requested_date_midnight = requested_date.replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    # Calculate days until appointment
    days_until = (requested_date_midnight - now).days

    if days_until < MINIMUM_DAYS:
        logger.warning(
            f"3-day rule violation: {days_until} days until appointment (min: {MINIMUM_DAYS})",
            extra={
                "requested_date": requested_date.isoformat(),
                "days_until": days_until
            }
        )

        return {
            "valid": False,
            "error_code": "DATE_TOO_SOON",
            "error_message": (
                f"Las citas deben agendarse con al menos {MINIMUM_DAYS} días de anticipación. "
                f"La fecha solicitada es en {days_until} día(s). "
                f"Por favor, elige una fecha a partir del {(now + timedelta(days=MINIMUM_DAYS)).strftime('%d/%m/%Y')}."
            ),
            "days_until_appointment": days_until,
            "minimum_required_days": MINIMUM_DAYS
        }

    logger.info(
        f"3-day rule passed: {days_until} days until appointment",
        extra={"requested_date": requested_date.isoformat()}
    )

    return {
        "valid": True,
        "error_code": None,
        "error_message": None,
        "days_until_appointment": days_until,
        "minimum_required_days": MINIMUM_DAYS
    }


async def validate_appointment_limit(customer_id: UUID) -> dict:
    """
    Validate that customer has not exceeded maximum pending appointments limit.

    Business rule: Customers can only have N pending/confirmed future appointments
    at any time (default: 3). This prevents abuse and ensures fair access.

    Counts appointments where:
    - customer_id matches (appointments FOR the customer)
    - OR booked_by_customer_id matches (appointments MADE BY customer for others)
    - AND start_time > NOW() (future appointments only)
    - AND status IN ('pending', 'confirmed')

    Args:
        customer_id: Customer UUID to check

    Returns:
        dict with validation result:
            {
                "valid": bool,
                "error_code": str | None,  # "APPOINTMENT_LIMIT_EXCEEDED" if invalid
                "error_message": str | None,
                "current_count": int,
                "max_allowed": int
            }

    Example:
        Valid (under limit):
        >>> await validate_appointment_limit(customer_uuid)
        {"valid": True, "error_code": None, "current_count": 2, "max_allowed": 3}

        Invalid (at limit):
        >>> await validate_appointment_limit(customer_uuid)
        {
            "valid": False,
            "error_code": "APPOINTMENT_LIMIT_EXCEEDED",
            "error_message": "Ya tienes 3 citas programadas...",
            "current_count": 3,
            "max_allowed": 3
        }
    """
    # Import here to avoid circular imports
    from shared.settings_service import get_settings_service

    # Get configurable limit from settings
    settings_service = await get_settings_service()
    max_appointments = await settings_service.get("max_pending_appointments_per_customer", 3)

    async with get_async_session() as session:
        try:
            # Count future pending/confirmed appointments for this customer
            # Includes: appointments FOR the customer OR appointments MADE BY the customer
            now = datetime.now(MADRID_TZ)

            stmt = select(func.count()).select_from(Appointment).where(
                or_(
                    Appointment.customer_id == customer_id,
                    Appointment.booked_by_customer_id == customer_id
                ),
                Appointment.start_time > now,
                Appointment.status.in_([
                    AppointmentStatus.PENDING.value,
                    AppointmentStatus.CONFIRMED.value
                ])
            )

            result = await session.execute(stmt)
            current_count = result.scalar() or 0

            if current_count >= max_appointments:
                logger.warning(
                    f"Appointment limit exceeded: customer has {current_count} appointments (max: {max_appointments})",
                    extra={
                        "customer_id": str(customer_id),
                        "current_count": current_count,
                        "max_allowed": max_appointments
                    }
                )

                return {
                    "valid": False,
                    "error_code": "APPOINTMENT_LIMIT_EXCEEDED",
                    "error_message": (
                        f"Ya tienes {current_count} citas programadas. "
                        f"Puedes cancelar una existente o esperar a que se complete para agendar otra."
                    ),
                    "current_count": current_count,
                    "max_allowed": max_appointments
                }

            logger.info(
                f"Appointment limit check passed: {current_count}/{max_appointments}",
                extra={
                    "customer_id": str(customer_id),
                    "current_count": current_count
                }
            )

            return {
                "valid": True,
                "error_code": None,
                "error_message": None,
                "current_count": current_count,
                "max_allowed": max_appointments
            }

        except Exception as e:
            logger.error(f"Database error during appointment limit validation: {e}", exc_info=True)
            raise

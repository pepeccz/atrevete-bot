"""
Booking Transaction Handler for v4.1 DB-First Architecture.

This module implements the booking transaction with DB-first calendar architecture:
- Business rule validation (3-day rule, category consistency, slot availability)
- Database persistence with SERIALIZABLE isolation (source of truth)
- Google Calendar push AFTER commit (fire-and-forget, non-blocking)

Key architectural change (v4.1):
- Database is committed FIRST (source of truth)
- Google Calendar is push-only mirror (fire-and-forget)
- Calendar push failures don't roll back the booking

The BookingTransaction.execute() method is the single entry point for creating appointments.
It's called by the book() tool in agent/tools/booking_tools.py.
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from agent.services.gcal_push_service import push_appointment_to_gcal
from agent.utils.calendar_link import generate_google_calendar_link
from agent.validators.transaction_validators import (
    validate_3_day_rule,
    validate_category_consistency,
    validate_slot_availability,
)
from database.connection import get_async_session
from database.models import Appointment, AppointmentStatus, Customer, Notification, NotificationType, Service, Stylist
from shared.config import get_settings

logger = logging.getLogger(__name__)

# Buffer between appointments (set to 0 - exact service duration)
BUFFER_MINUTES = 0


class BookingTransaction:
    """
    Atomic transaction handler for creating appointments.

    This class encapsulates the complete booking flow:
    1. Validate business rules (3-day, category, slot availability)
    2. Calculate total duration
    3. Create Google Calendar event
    4. Create database appointment record (auto-confirmed)
    5. Rollback everything if any step fails

    All operations use SERIALIZABLE isolation to prevent race conditions.
    """

    @staticmethod
    async def execute(
        customer_id: UUID,
        service_ids: list[UUID],
        stylist_id: UUID,
        start_time: datetime,
        first_name: str,
        last_name: str | None,
        notes: str | None,
        conversation_id: str | None = None
    ) -> dict[str, Any]:
        """
        Execute atomic booking transaction.

        This is the single entry point for creating appointments. Performs all validation,
        calendar event creation, and database persistence in a single atomic transaction.

        Args:
            customer_id: Customer UUID
            service_ids: List of Service UUIDs
            stylist_id: Stylist UUID
            start_time: Appointment start time (timezone-aware)
            first_name: Customer's first name for this appointment
            last_name: Customer's last name (optional)
            notes: Appointment-specific notes (optional)

        Returns:
            Dict with booking result. Structure:

            Success:
                {
                    "success": True,
                    "appointment_id": str,
                    "google_calendar_event_id": str,
                    "start_time": str,
                    "end_time": str,
                    "duration_minutes": int,
                    "customer_id": str,
                    "stylist_id": str,
                    "service_ids": list[str],
                    "status": "confirmed"
                }

            Failure:
                {
                    "success": False,
                    "error_code": str,
                    "error_message": str,
                    "details": dict
                }

        Example:
            >>> result = await BookingTransaction.execute(
            ...     customer_id=UUID("..."),
            ...     service_ids=[UUID("..."), UUID("...")],
            ...     stylist_id=UUID("..."),
            ...     start_time=datetime(2025, 11, 8, 10, 0, tzinfo=MADRID_TZ)
            ... )
            >>> if result["success"]:
            ...     appointment_id = result["appointment_id"]
        """
        trace_id = f"{customer_id}_{start_time.isoformat()}"
        logger.info(
            f"[{trace_id}] Starting booking transaction",
            extra={
                "customer_id": str(customer_id),
                "service_count": len(service_ids),
                "stylist_id": str(stylist_id),
                "start_time": start_time.isoformat()
            }
        )

        try:
            # Step 1: Validate 3-day rule
            validation_3day = await validate_3_day_rule(start_time)
            if not validation_3day["valid"]:
                logger.warning(
                    f"[{trace_id}] 3-day rule validation failed",
                    extra={"days_until": validation_3day["days_until_appointment"]}
                )
                return {
                    "success": False,
                    "error_code": validation_3day["error_code"],
                    "error_message": validation_3day["error_message"],
                    "details": {
                        "days_until_appointment": validation_3day["days_until_appointment"],
                        "minimum_required_days": validation_3day["minimum_required_days"]
                    }
                }

            # Step 2: Validate category consistency
            validation_category = await validate_category_consistency(service_ids)
            if not validation_category["valid"]:
                logger.warning(
                    f"[{trace_id}] Category consistency validation failed",
                    extra={"categories": validation_category["categories_found"]}
                )
                return {
                    "success": False,
                    "error_code": validation_category["error_code"],
                    "error_message": validation_category["error_message"],
                    "details": {
                        "categories_found": validation_category["categories_found"]
                    }
                }

            # Step 3: Start database transaction with SERIALIZABLE isolation
            async with get_async_session() as session:
                try:
                    # Set SERIALIZABLE isolation for this transaction
                    await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))

                    # Step 3a: Fetch services and calculate totals
                    stmt = select(Service).where(Service.id.in_(service_ids))
                    result = await session.execute(stmt)
                    services = list(result.scalars().all())

                    if len(services) != len(service_ids):
                        found_ids = {s.id for s in services}
                        missing_ids = set(service_ids) - found_ids
                        logger.error(
                            f"[{trace_id}] Service IDs not found: {missing_ids}"
                        )
                        return {
                            "success": False,
                            "error_code": "INVALID_SERVICE_IDS",
                            "error_message": "Uno o más servicios no fueron encontrados",
                            "details": {"missing_service_ids": [str(sid) for sid in missing_ids]}
                        }

                    total_duration = sum(s.duration_minutes for s in services)
                    duration_with_buffer = total_duration + BUFFER_MINUTES

                    # Step 3b: Fetch stylist for name
                    stmt = select(Stylist).where(Stylist.id == stylist_id)
                    result = await session.execute(stmt)
                    stylist = result.scalar_one_or_none()

                    if not stylist:
                        logger.error(f"[{trace_id}] Stylist not found: {stylist_id}")
                        return {
                            "success": False,
                            "error_code": "STYLIST_NOT_FOUND",
                            "error_message": "Estilista no encontrado",
                            "details": {"stylist_id": str(stylist_id)}
                        }

                    # Step 3c: Validate slot availability with row lock
                    validation_slot = await validate_slot_availability(
                        stylist_id=stylist_id,
                        start_time=start_time,
                        duration_minutes=duration_with_buffer,
                        session=session
                    )

                    if not validation_slot["available"]:
                        logger.warning(
                            f"[{trace_id}] Slot availability validation failed",
                            extra={"conflict_id": str(validation_slot.get("conflicting_appointment_id"))}
                        )
                        await session.rollback()
                        return {
                            "success": False,
                            "error_code": validation_slot["error_code"],
                            "error_message": validation_slot["error_message"],
                            "details": {
                                "conflicting_appointment_id": str(validation_slot["conflicting_appointment_id"])
                                if validation_slot.get("conflicting_appointment_id")
                                else None
                            }
                        }

                    # Step 4: Create database appointment record with PENDING status
                    # (DB first, Calendar second for proper rollback)
                    end_time = start_time + timedelta(minutes=total_duration)

                    new_appointment = Appointment(
                        customer_id=customer_id,
                        stylist_id=stylist_id,
                        service_ids=service_ids,
                        start_time=start_time,
                        duration_minutes=total_duration,
                        status=AppointmentStatus.PENDING,  # Start as PENDING (awaiting 48h confirmation)
                        first_name=first_name,
                        last_name=last_name,
                        notes=notes
                    )

                    session.add(new_appointment)
                    await session.flush()  # Flush to get ID, but don't commit yet

                    logger.info(
                        f"[{trace_id}] Appointment record created in DB (PENDING status)",
                        extra={
                            "appointment_id": str(new_appointment.id),
                            "duration_minutes": total_duration
                        }
                    )

                    # Update customer's chatwoot_conversation_id if provided
                    if conversation_id:
                        customer_stmt = select(Customer).where(Customer.id == customer_id)
                        customer_result = await session.execute(customer_stmt)
                        customer = customer_result.scalar_one_or_none()

                        if customer and not customer.chatwoot_conversation_id:
                            customer.chatwoot_conversation_id = conversation_id
                            logger.info(
                                f"[{trace_id}] Updated customer chatwoot_conversation_id",
                                extra={"conversation_id": conversation_id}
                            )

                    # Step 5: Commit transaction FIRST (DB is source of truth - DB-first architecture)
                    # Google Calendar push happens AFTER commit as fire-and-forget
                    await session.commit()
                    await session.refresh(new_appointment)

                    logger.info(
                        f"[{trace_id}] Appointment committed to database (DB-first)",
                        extra={
                            "appointment_id": str(new_appointment.id),
                            "status": "PENDING"
                        }
                    )

                    # Step 6: Push to Google Calendar (fire-and-forget, non-blocking)
                    # Push failures are logged but don't affect the booking
                    service_names = ", ".join(s.name for s in services)

                    # Get customer phone for Google Calendar title
                    phone_stmt = select(Customer.phone).where(Customer.id == customer_id)
                    phone_result = await session.execute(phone_stmt)
                    customer_phone = phone_result.scalar_one_or_none()

                    logger.info(
                        f"[{trace_id}] Pushing to Google Calendar with emoji 🟡 (fire-and-forget)",
                        extra={
                            "customer_name": first_name,
                            "services": service_names,
                            "duration": total_duration,
                            "phone": customer_phone
                        }
                    )

                    # DB-first: Push is fire-and-forget, failures don't roll back booking
                    google_event_id = await push_appointment_to_gcal(
                        appointment_id=new_appointment.id,
                        stylist_id=stylist_id,
                        customer_name=first_name,
                        service_names=service_names,
                        start_time=start_time,
                        duration_minutes=total_duration,
                        status="pending",  # Yellow emoji 🟡
                        customer_phone=customer_phone,
                    )

                    if google_event_id:
                        logger.info(
                            f"[{trace_id}] Google Calendar event created successfully 🟡",
                            extra={"google_event_id": google_event_id}
                        )
                    else:
                        # Log warning but don't fail - booking is already committed
                        logger.warning(
                            f"[{trace_id}] Google Calendar push failed (booking still valid)",
                            extra={"appointment_id": str(new_appointment.id)}
                        )

                    logger.info(
                        f"[{trace_id}] Appointment created successfully with Calendar event 🟡",
                        extra={
                            "appointment_id": str(new_appointment.id),
                            "google_event_id": google_event_id,
                            "status": "PENDING"
                        }
                    )

                    # Format friendly date and time for confirmation message
                    # Example: "viernes 22 de noviembre a las 10:00"
                    day_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
                    month_names = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
                                   "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

                    weekday = day_names[start_time.weekday()]
                    day = start_time.day
                    month = month_names[start_time.month - 1]
                    time_str = start_time.strftime("%H:%M")

                    friendly_date = f"{weekday} {day} de {month} a las {time_str}"

                    # Build confirmation message
                    confirmation_message = (
                        f"¡Cita registrada! 📝 Te enviaremos un mensaje de confirmación 48 horas antes de tu cita.\n\n"
                        f"📅 Fecha: {friendly_date}\n"
                        f"💇 Estilista: {stylist.name}\n"
                        f"✨ Servicios: {service_names}"
                    )

                    # Generate Google Calendar link for customer
                    settings = get_settings()
                    calendar_link = generate_google_calendar_link(
                        title="Cita en Peluquería Atrévete",
                        start_time=start_time,
                        end_time=end_time,
                        description=f"Servicios: {service_names}\nEstilista: {stylist.name}",
                        location=settings.SALON_ADDRESS,
                    )

                    # Create notification for admin panel
                    try:
                        notification = Notification(
                            type=NotificationType.APPOINTMENT_CREATED,
                            title="Nueva cita desde WhatsApp",
                            message=f"{first_name} ha reservado {service_names} para el {friendly_date}",
                            entity_type="appointment",
                            entity_id=new_appointment.id,
                        )
                        session.add(notification)
                        await session.commit()
                        logger.info(
                            f"[{trace_id}] Notification created for admin panel",
                            extra={"notification_type": "APPOINTMENT_CREATED"}
                        )
                    except Exception as notif_error:
                        logger.warning(
                            f"[{trace_id}] Failed to create notification: {notif_error}"
                        )

                    # Return success
                    return {
                        "success": True,
                        "appointment_id": str(new_appointment.id),
                        "google_calendar_event_id": google_event_id,
                        "start_time": start_time.isoformat(),
                        "end_time": end_time.isoformat(),
                        "duration_minutes": total_duration,
                        "customer_id": str(customer_id),
                        "customer_name": first_name,
                        "stylist_id": str(stylist_id),
                        "stylist_name": stylist.name,
                        "service_ids": [str(sid) for sid in service_ids],
                        "service_names": service_names,
                        "status": "pending",  # Status is PENDING until 48h confirmation
                        "message": confirmation_message,  # AC5: User-friendly confirmation message
                        "friendly_date": friendly_date,  # For FSM template
                        "calendar_link": calendar_link,  # Google Calendar "Add Event" URL
                        "salon_address": settings.SALON_ADDRESS,  # Salon address for template
                    }

                except IntegrityError as e:
                    logger.error(
                        f"[{trace_id}] Database integrity error",
                        extra={"error": str(e)},
                        exc_info=True
                    )
                    await session.rollback()

                    # Try to delete calendar event (cleanup on rollback)
                    if 'google_event_id' in locals():
                        try:
                            from agent.tools.calendar_tools import delete_calendar_event
                            await delete_calendar_event(
                                stylist_id=str(stylist_id),
                                event_id=google_event_id,
                                conversation_id=trace_id
                            )
                            logger.info(f"[{trace_id}] Cleaned up calendar event on rollback")
                        except Exception as cleanup_error:
                            logger.warning(
                                f"[{trace_id}] Failed to cleanup calendar event",
                                extra={"error": str(cleanup_error)}
                            )

                    return {
                        "success": False,
                        "error_code": "DATABASE_INTEGRITY_ERROR",
                        "error_message": "Error de integridad en la base de datos",
                        "details": {"error": str(e)}
                    }

                except SQLAlchemyError as e:
                    logger.error(
                        f"[{trace_id}] Database error",
                        extra={"error": str(e)},
                        exc_info=True
                    )
                    await session.rollback()

                    # Try to delete calendar event (cleanup on rollback)
                    if 'google_event_id' in locals():
                        try:
                            from agent.tools.calendar_tools import delete_calendar_event
                            await delete_calendar_event(
                                stylist_id=str(stylist_id),
                                event_id=google_event_id,
                                conversation_id=trace_id
                            )
                            logger.info(f"[{trace_id}] Cleaned up calendar event on rollback")
                        except Exception as cleanup_error:
                            logger.warning(
                                f"[{trace_id}] Failed to cleanup calendar event",
                                extra={"error": str(cleanup_error)}
                            )

                    return {
                        "success": False,
                        "error_code": "DATABASE_ERROR",
                        "error_message": "Error al crear la reserva en la base de datos",
                        "details": {"error": str(e)}
                    }

                finally:
                    # Exit async for loop
                    pass

        except Exception as e:
            logger.error(
                f"[{trace_id}] Unexpected error in booking transaction",
                extra={"error": str(e)},
                exc_info=True
            )
            return {
                "success": False,
                "error_code": "BOOKING_TRANSACTION_ERROR",
                "error_message": "Error inesperado al procesar la reserva",
                "details": {"error": str(e)}
            }

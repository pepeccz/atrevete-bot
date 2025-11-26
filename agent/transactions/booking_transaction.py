"""
Booking Transaction Handler for v3.0 Architecture.

This module implements the atomic booking transaction that creates appointments with:
- Business rule validation (3-day rule, category consistency, slot availability)
- Google Calendar event creation
- Database persistence with SERIALIZABLE isolation
- Complete rollback on any failure

The BookingTransaction.execute() method is the single entry point for creating appointments.
It's called by the book() tool in agent/tools/booking_tools.py.
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from agent.tools.calendar_tools import create_calendar_event
from agent.validators.transaction_validators import (
    validate_3_day_rule,
    validate_category_consistency,
    validate_slot_availability,
)
from database.connection import get_async_session
from database.models import Appointment, AppointmentStatus, Service, Stylist

logger = logging.getLogger(__name__)

# 10-minute buffer between appointments for cleanup/preparation
BUFFER_MINUTES = 10


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
                        from database.models import Customer
                        customer_stmt = select(Customer).where(Customer.id == customer_id)
                        customer_result = await session.execute(customer_stmt)
                        customer = customer_result.scalar_one_or_none()

                        if customer and not customer.chatwoot_conversation_id:
                            customer.chatwoot_conversation_id = conversation_id
                            logger.info(
                                f"[{trace_id}] Updated customer chatwoot_conversation_id",
                                extra={"conversation_id": conversation_id}
                            )

                    # Step 5: Create Google Calendar event with emoji 🟡
                    service_names = ", ".join(s.name for s in services)

                    logger.info(
                        f"[{trace_id}] Creating Google Calendar event with emoji 🟡",
                        extra={
                            "customer_name": first_name,
                            "services": service_names,
                            "duration": duration_with_buffer
                        }
                    )

                    calendar_result = await create_calendar_event(
                        stylist_id=str(stylist_id),
                        start_time=start_time.isoformat(),
                        duration_minutes=duration_with_buffer,
                        customer_name=first_name,  # Use first_name only for emoji format
                        service_names=service_names,
                        status="pending",  # Use pending status for emoji 🟡
                        customer_id=str(customer_id),
                        conversation_id=trace_id
                    )

                    if not calendar_result.get("success"):
                        logger.error(
                            f"[{trace_id}] Failed to create Google Calendar event",
                            extra={"error": calendar_result.get("error")}
                        )
                        # Rollback is automatic when exiting context manager without commit
                        return {
                            "success": False,
                            "error_code": "CALENDAR_EVENT_FAILED",
                            "error_message": "No pudimos completar tu reserva. Por favor, intenta de nuevo o contacta con el salón.",
                            "details": {"calendar_error": calendar_result.get("error")}
                        }

                    google_event_id = calendar_result["event_id"]

                    # Step 6: Save google_calendar_event_id to appointment
                    new_appointment.google_calendar_event_id = google_event_id

                    # Step 7: Commit transaction (if we reach here, both DB and Calendar succeeded)
                    await session.commit()
                    await session.refresh(new_appointment)

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
                        f"¡Cita confirmada! 🎉 Te enviaremos un mensaje 48 horas antes para confirmar tu asistencia.\n\n"
                        f"📅 Fecha: {friendly_date}\n"
                        f"💇 Estilista: {stylist.name}\n"
                        f"✨ Servicios: {service_names}"
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
                        "message": confirmation_message  # AC5: User-friendly confirmation message
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

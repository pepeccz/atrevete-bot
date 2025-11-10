"""
Booking Transaction Handler for v3.0 Architecture.

This module implements the atomic booking transaction that creates appointments with:
- Business rule validation (3-day rule, category consistency, slot availability)
- Google Calendar event creation
- Database persistence with SERIALIZABLE isolation
- Auto-confirmation (no payment system)
- Complete rollback on any failure

The BookingTransaction.execute() method is the single entry point for creating appointments.
It's called by the book() tool in agent/tools/booking_tools.py.
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
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
        start_time: datetime
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
            async for session in get_async_session():
                try:
                    # Set SERIALIZABLE isolation for this transaction
                    await session.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")

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

                    # Step 4: Create Google Calendar event
                    service_names = ", ".join(s.name for s in services)

                    # Get customer name from database
                    from database.models import Customer
                    stmt = select(Customer).where(Customer.id == customer_id)
                    result = await session.execute(stmt)
                    customer = result.scalar_one_or_none()

                    if not customer:
                        logger.error(f"[{trace_id}] Customer not found: {customer_id}")
                        await session.rollback()
                        return {
                            "success": False,
                            "error_code": "CUSTOMER_NOT_FOUND",
                            "error_message": "Cliente no encontrado",
                            "details": {"customer_id": str(customer_id)}
                        }

                    customer_name = f"{customer.first_name} {customer.last_name or ''}".strip()

                    logger.info(
                        f"[{trace_id}] Creating Google Calendar event",
                        extra={
                            "customer_name": customer_name,
                            "services": service_names,
                            "duration": duration_with_buffer
                        }
                    )

                    calendar_result = await create_calendar_event(
                        stylist_id=str(stylist_id),
                        start_time=start_time.isoformat(),
                        duration_minutes=duration_with_buffer,
                        customer_name=customer_name,
                        service_names=service_names,
                        status="provisional",  # Always start as provisional
                        customer_id=str(customer_id),
                        conversation_id=trace_id
                    )

                    if not calendar_result.get("success"):
                        logger.error(
                            f"[{trace_id}] Failed to create Google Calendar event",
                            extra={"error": calendar_result.get("error")}
                        )
                        await session.rollback()
                        return {
                            "success": False,
                            "error_code": "CALENDAR_EVENT_FAILED",
                            "error_message": "Error al crear el evento en el calendario",
                            "details": {"calendar_error": calendar_result.get("error")}
                        }

                    google_event_id = calendar_result["event_id"]
                    logger.info(
                        f"[{trace_id}] Google Calendar event created",
                        extra={"event_id": google_event_id}
                    )

                    # Step 5: Create database appointment record (auto-confirmed)
                    end_time = start_time + timedelta(minutes=total_duration)

                    new_appointment = Appointment(
                        customer_id=customer_id,
                        stylist_id=stylist_id,
                        service_ids=service_ids,
                        start_time=start_time,
                        duration_minutes=total_duration,
                        status=AppointmentStatus.CONFIRMED,  # Auto-confirm all appointments
                        google_calendar_event_id=google_event_id,
                    )

                    session.add(new_appointment)
                    await session.commit()
                    await session.refresh(new_appointment)

                    logger.info(
                        f"[{trace_id}] Appointment created and auto-confirmed",
                        extra={
                            "appointment_id": str(new_appointment.id),
                            "google_event_id": google_event_id,
                            "duration_minutes": total_duration
                        }
                    )

                    # Update calendar event to confirmed (green)
                    try:
                        from agent.tools.calendar_tools import update_calendar_event_status
                        await update_calendar_event_status(
                            stylist_id=str(stylist_id),
                            event_id=google_event_id,
                            status="confirmed"
                        )
                    except Exception as calendar_error:
                        logger.warning(
                            f"[{trace_id}] Failed to update calendar event to confirmed",
                            extra={"error": str(calendar_error)}
                        )

                    logger.info(
                        f"[{trace_id}] Appointment fully confirmed",
                        extra={"appointment_id": str(new_appointment.id)}
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
                        "customer_name": customer_name,
                        "stylist_id": str(stylist_id),
                        "stylist_name": stylist.name,
                        "service_ids": [str(sid) for sid in service_ids],
                        "service_names": service_names,
                        "status": "confirmed"
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
                    break

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

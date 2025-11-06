"""
Booking Expiration Worker - Expires provisional bookings that haven't been paid.

This worker runs periodically (every 1 minute) to identify and expire
provisional bookings that have exceeded their payment timeout.

Flow:
1. Query appointments with status=PROVISIONAL and expired payment_timeout_at
2. Update appointment status: PROVISIONAL → EXPIRED
3. Delete Google Calendar event (free the slot)
4. Deactivate Stripe Payment Link (prevent late payments)
5. Notify customer via Chatwoot with timeout message and retry offer

Configuration:
- Run interval: 1 minute (configurable via BOOKING_EXPIRATION_CHECK_INTERVAL_SECONDS)
- Payment timeout: 10 minutes (configured in appointment metadata)
"""

import asyncio
import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_async_session
from database.models import Appointment, AppointmentStatus
from shared.config import get_settings
from shared.stripe_client import deactivate_payment_link
from agent.tools.calendar_tools import delete_calendar_event, get_stylist_by_id
from agent.tools.notification_tools import ChatwootClient

logger = logging.getLogger(__name__)
settings = get_settings()

# Check interval in seconds (default: 60 seconds = 1 minute)
CHECK_INTERVAL_SECONDS = int(
    getattr(settings, "BOOKING_EXPIRATION_CHECK_INTERVAL_SECONDS", 60)
)


async def expire_provisional_bookings() -> int:
    """
    Find and expire provisional bookings that have exceeded payment timeout.

    Returns:
        int: Number of bookings expired in this run

    Process:
        1. Query PROVISIONAL appointments with expired timeout
        2. For each expired booking:
           - Update status to EXPIRED
           - Delete Google Calendar event
           - Deactivate Stripe Payment Link
           - Notify customer via Chatwoot
    """
    expired_count = 0

    try:
        async for session in get_async_session():
            # Query expired provisional appointments
            # payment_timeout_at is stored in metadata as ISO timestamp
            now = datetime.utcnow()

            stmt = select(Appointment).where(
                and_(
                    Appointment.status == AppointmentStatus.PROVISIONAL,
                    # Using raw SQL to compare JSONB timestamp with current time
                    # metadata->>'payment_timeout_at' < NOW()
                )
            )

            result = await session.execute(stmt)
            appointments = list(result.scalars().all())

            # Filter expired appointments in Python (since metadata JSONB comparison is complex)
            expired_appointments = []
            for appointment in appointments:
                metadata = appointment.metadata or {}
                timeout_str = metadata.get("payment_timeout_at")

                if timeout_str:
                    try:
                        timeout_dt = datetime.fromisoformat(timeout_str.replace("Z", "+00:00"))
                        if timeout_dt < now:
                            expired_appointments.append(appointment)
                    except (ValueError, AttributeError) as e:
                        logger.warning(
                            f"Invalid payment_timeout_at format in appointment {appointment.id}: "
                            f"{timeout_str} | error: {e}"
                        )

            logger.info(
                f"Found {len(expired_appointments)} expired provisional bookings "
                f"(out of {len(appointments)} provisional)"
            )

            # Process each expired booking
            for appointment in expired_appointments:
                try:
                    await expire_single_booking(session, appointment)
                    expired_count += 1

                except Exception as e:
                    logger.error(
                        f"Error expiring booking {appointment.id}: {e}",
                        exc_info=True
                    )
                    # Continue with next booking

            # Commit all updates
            await session.commit()

            break  # Exit async for loop

        logger.info(f"Expiration run completed | expired_count={expired_count}")
        return expired_count

    except Exception as e:
        logger.exception(f"Error in expire_provisional_bookings: {e}")
        return expired_count


async def expire_single_booking(
    session: AsyncSession,
    appointment: Appointment
) -> None:
    """
    Expire a single provisional booking.

    Args:
        session: Active database session
        appointment: Appointment to expire

    Process:
        1. Update appointment status to EXPIRED
        2. Delete Google Calendar event
        3. Deactivate Stripe Payment Link
        4. Notify customer via Chatwoot
    """
    appointment_id = appointment.id
    conversation_id = appointment.metadata.get("conversation_id", "unknown")

    logger.info(
        f"Expiring provisional booking | appointment_id={appointment_id} | "
        f"conversation_id={conversation_id}"
    )

    # 1. Update appointment status
    appointment.status = "expired"
    # Note: session.commit() will be called by caller

    # 2. Delete Google Calendar event (free the slot)
    if appointment.google_calendar_event_id:
        try:
            stylist = await get_stylist_by_id(appointment.stylist_id)
            if stylist and stylist.google_calendar_id:
                result = await delete_calendar_event(
                    stylist_id=str(appointment.stylist_id),
                    event_id=appointment.google_calendar_event_id,
                    conversation_id=conversation_id,
                )

                if result.get("success"):
                    logger.info(
                        f"Calendar event deleted for expired booking | "
                        f"event_id={appointment.google_calendar_event_id} | "
                        f"appointment_id={appointment_id}"
                    )
                else:
                    logger.warning(
                        f"Failed to delete calendar event for expired booking | "
                        f"event_id={appointment.google_calendar_event_id} | "
                        f"error={result.get('error')}"
                    )
            else:
                logger.warning(
                    f"Stylist or calendar_id not found for appointment | "
                    f"stylist_id={appointment.stylist_id}"
                )

        except Exception as calendar_error:
            logger.error(
                f"Error deleting calendar event for expired booking | "
                f"appointment_id={appointment_id}: {calendar_error}"
            )

    # 3. Deactivate Stripe Payment Link (prevent late payments)
    if appointment.stripe_payment_link_id:
        try:
            success = await deactivate_payment_link(appointment.stripe_payment_link_id)

            if success:
                logger.info(
                    f"Payment link deactivated for expired booking | "
                    f"link_id={appointment.stripe_payment_link_id} | "
                    f"appointment_id={appointment_id}"
                )
            else:
                logger.warning(
                    f"Failed to deactivate payment link for expired booking | "
                    f"link_id={appointment.stripe_payment_link_id}"
                )

        except Exception as stripe_error:
            logger.error(
                f"Error deactivating payment link for expired booking | "
                f"appointment_id={appointment_id}: {stripe_error}"
            )

    # 4. Notify customer via Chatwoot
    if conversation_id and conversation_id != "unknown":
        try:
            # Get customer name from metadata or use generic greeting
            customer_name = appointment.metadata.get("customer_name", "Cliente")
            customer_phone = appointment.metadata.get("customer_phone", "")

            timeout_message = (
                f"Lo siento, {customer_name} 💕, no recibí la confirmación de tu pago "
                f"en el tiempo establecido (10 minutos). La reserva ha sido cancelada "
                f"para liberar el horario.\n\n"
                f"Si aún deseas agendar esta cita, puedo ayudarte a reintentar el proceso. "
                f"¿Deseas volver a intentarlo?"
            )

            # Use ChatwootClient to send message
            chatwoot_client = ChatwootClient()
            await chatwoot_client.send_message(
                customer_phone=customer_phone,
                message=timeout_message,
                customer_name=customer_name,
                conversation_id=int(conversation_id),
            )

            logger.info(
                f"Timeout notification sent via Chatwoot | "
                f"conversation_id={conversation_id} | "
                f"appointment_id={appointment_id}"
            )

        except Exception as chatwoot_error:
            logger.error(
                f"Error sending timeout notification via Chatwoot | "
                f"appointment_id={appointment_id}: {chatwoot_error}"
            )


async def run_expiration_worker():
    """
    Main worker loop - runs expiration check every CHECK_INTERVAL_SECONDS.

    Continuously monitors for expired provisional bookings and processes them.
    Runs until interrupted.
    """
    logger.info("Booking expiration worker starting...")
    logger.info(f"Check interval: {CHECK_INTERVAL_SECONDS} seconds")

    try:
        while True:
            try:
                # Run expiration check
                expired_count = await expire_provisional_bookings()

                logger.debug(
                    f"Expiration check completed | expired_count={expired_count}"
                )

            except Exception as e:
                logger.exception(f"Error in expiration check cycle: {e}")

            # Wait before next check
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    except asyncio.CancelledError:
        logger.info("Booking expiration worker shutting down...")
    except Exception as e:
        logger.exception(f"Fatal error in expiration worker: {e}")
        raise


if __name__ == "__main__":
    """Run expiration worker as standalone service."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("Starting booking expiration worker...")

    try:
        asyncio.run(run_expiration_worker())
    except KeyboardInterrupt:
        logger.info("Booking expiration worker stopped by user")
    except Exception as e:
        logger.exception(f"Booking expiration worker crashed: {e}")
        raise

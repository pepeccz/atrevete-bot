"""
Payment Processor Worker - Processes Stripe webhook events for booking confirmation.

This worker subscribes to the Redis `payment_events` channel and processes
payment-related webhooks from Stripe to confirm provisional bookings.

Webhook Events Processed:
- checkout.session.completed: Confirms provisional booking when payment succeeds
- checkout.session.expired: Marks booking as expired (backup to expiration worker)

Flow:
1. Listen to Redis `payment_events` channel
2. Extract appointment_id from event metadata
3. Update appointment status: PROVISIONAL → CONFIRMED
4. Update Google Calendar event color: yellow → green
5. Insert Payment record in database
6. Notify customer via Chatwoot with confirmation details
"""

import asyncio
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_async_session
from database.models import Appointment, AppointmentStatus, PaymentStatus, Payment, Service
from shared.config import get_settings
from shared.redis_client import get_redis_client
from agent.tools.calendar_tools import update_calendar_event_color, get_stylist_by_id
from agent.tools.notification_tools import ChatwootClient

logger = logging.getLogger(__name__)
settings = get_settings()


async def process_payment_success(event_data: dict[str, Any]) -> None:
    """
    Process successful payment from Stripe checkout.session.completed webhook.

    Args:
        event_data: Stripe event data with checkout session details

    Flow:
        1. Extract appointment_id from metadata
        2. Query and validate appointment (must be PROVISIONAL)
        3. Update appointment to CONFIRMED
        4. Update Google Calendar event (yellow → green)
        5. Insert Payment record
        6. Send confirmation message via Chatwoot
    """
    try:
        # Extract data from Stripe event
        session = event_data.get("data", {}).get("object", {})
        metadata = session.get("metadata", {})
        appointment_id_str = metadata.get("appointment_id")
        conversation_id = metadata.get("conversation_id", "unknown")

        if not appointment_id_str:
            logger.error(
                f"Payment success event missing appointment_id in metadata | "
                f"event_id={event_data.get('id')}"
            )
            return

        appointment_id = UUID(appointment_id_str)
        payment_intent_id = session.get("payment_intent")
        amount_paid = Decimal(session.get("amount_total", 0)) / 100  # Convert cents to euros

        logger.info(
            f"Processing payment success | appointment_id={appointment_id} | "
            f"payment_intent={payment_intent_id} | amount={amount_paid}€"
        )

        # Query appointment
        async for db_session in get_async_session():
            stmt = select(Appointment).where(Appointment.id == appointment_id)
            result = await db_session.execute(stmt)
            appointment = result.scalar_one_or_none()

            if not appointment:
                logger.error(
                    f"Appointment not found for payment | appointment_id={appointment_id}"
                )
                return

            # Validate appointment is PROVISIONAL
            if appointment.status != AppointmentStatus.PROVISIONAL:
                logger.warning(
                    f"Appointment is not PROVISIONAL, skipping confirmation | "
                    f"appointment_id={appointment_id} | status={appointment.status}"
                )
                return

            # Update appointment status
            appointment.status = AppointmentStatus.CONFIRMED
            appointment.payment_status = PaymentStatus.CONFIRMED
            appointment.stripe_payment_id = payment_intent_id

            await db_session.commit()
            await db_session.refresh(appointment)

            logger.info(
                f"Appointment confirmed | appointment_id={appointment_id} | "
                f"status={appointment.status.value}"
            )

            # Update Google Calendar event color (yellow → green)
            try:
                if appointment.google_calendar_event_id:
                    stylist = await get_stylist_by_id(appointment.stylist_id)
                    if stylist and stylist.google_calendar_id:
                        await update_calendar_event_color(
                            calendar_id=stylist.google_calendar_id,
                            event_id=appointment.google_calendar_event_id,
                            color_id="9",  # Green = confirmed
                        )
                        logger.info(
                            f"Calendar event updated to green | "
                            f"event_id={appointment.google_calendar_event_id}"
                        )
                    else:
                        logger.warning(
                            f"Stylist or calendar_id not found for appointment | "
                            f"stylist_id={appointment.stylist_id}"
                        )
                else:
                    logger.warning(
                        f"No Google Calendar event_id found for appointment | "
                        f"appointment_id={appointment_id}"
                    )
            except Exception as calendar_error:
                # Log but don't fail payment confirmation
                logger.error(
                    f"Error updating calendar event color | "
                    f"appointment_id={appointment_id}: {calendar_error}"
                )

            # Insert Payment record
            try:
                payment = Payment(
                    appointment_id=appointment.id,
                    stripe_payment_intent_id=payment_intent_id,
                    stripe_checkout_session_id=session.get("id"),
                    amount=amount_paid,
                    status=PaymentStatus.CONFIRMED,
                    stripe_metadata={
                        "checkout_session_id": session.get("id"),
                        "customer_email": session.get("customer_details", {}).get("email"),
                    },
                )
                db_session.add(payment)
                await db_session.commit()

                logger.info(
                    f"Payment record created | payment_id={payment.id} | "
                    f"amount={amount_paid}€"
                )
            except Exception as payment_error:
                logger.error(
                    f"Error creating payment record | "
                    f"appointment_id={appointment_id}: {payment_error}"
                )

            # Send confirmation message via Chatwoot
            try:
                # Get service names
                stmt = select(Service).where(Service.id.in_(appointment.service_ids))
                result = await db_session.execute(stmt)
                services = list(result.scalars().all())
                service_names = ", ".join([s.name for s in services])

                # Get stylist name
                stylist = await get_stylist_by_id(appointment.stylist_id)
                stylist_name = stylist.name if stylist else "N/A"

                # Calculate pending balance
                pending_balance = appointment.total_price - appointment.advance_payment_amount

                # Get customer info from metadata
                customer_phone = appointment.metadata.get("customer_phone", "")
                customer_name = appointment.metadata.get("customer_name", "Cliente")

                # Format confirmation message
                confirmation_message = (
                    f"✅ ¡Tu cita ha sido confirmada!\n\n"
                    f"📅 Resumen de tu cita:\n"
                    f"- Fecha: {appointment.start_time.strftime('%A, %d/%m/%Y')}\n"
                    f"- Hora: {appointment.start_time.strftime('%H:%M')} - "
                    f"{(appointment.start_time.hour * 60 + appointment.start_time.minute + appointment.duration_minutes) // 60:02d}:"
                    f"{(appointment.start_time.hour * 60 + appointment.start_time.minute + appointment.duration_minutes) % 60:02d}\n"
                    f"- Asistenta: {stylist_name}\n"
                    f"- Servicios: {service_names}\n"
                    f"- Duración: {appointment.duration_minutes} minutos\n"
                    f"- Costo total: {appointment.total_price}€\n\n"
                    f"💶 Información de pago:\n"
                    f"- Anticipo pagado: {appointment.advance_payment_amount}€ ✓\n"
                    f"- Saldo pendiente: {pending_balance}€ (a pagar en el salón)\n\n"
                    f"⚠️ Política de cancelación:\n"
                    f"Para modificar o cancelar tu cita, debes hacerlo con al menos 24 horas de antelación.\n\n"
                    f"📍 Ubicación: C/ Mayor 123, Madrid\n\n"
                    f"¡Nos vemos pronto en Atrévete! 💇‍♀️"
                )

                # Use ChatwootClient to send message
                chatwoot_client = ChatwootClient()
                await chatwoot_client.send_message(
                    customer_phone=customer_phone,
                    message=confirmation_message,
                    customer_name=customer_name,
                    conversation_id=int(conversation_id) if conversation_id != "unknown" else None,
                )

                logger.info(
                    f"Confirmation message sent via Chatwoot | "
                    f"conversation_id={conversation_id} | "
                    f"appointment_id={appointment_id}"
                )

            except Exception as chatwoot_error:
                logger.error(
                    f"Error sending confirmation message via Chatwoot | "
                    f"appointment_id={appointment_id}: {chatwoot_error}"
                )

            break  # Exit async for loop

    except Exception as e:
        logger.exception(f"Error processing payment success: {e}")


async def process_payment_expired(event_data: dict[str, Any]) -> None:
    """
    Process expired checkout session from Stripe checkout.session.expired webhook.

    This is a backup to the expiration worker. Marks appointment as EXPIRED.

    Args:
        event_data: Stripe event data with expired checkout session details
    """
    try:
        session = event_data.get("data", {}).get("object", {})
        metadata = session.get("metadata", {})
        appointment_id_str = metadata.get("appointment_id")

        if not appointment_id_str:
            logger.error(
                f"Payment expired event missing appointment_id in metadata | "
                f"event_id={event_data.get('id')}"
            )
            return

        appointment_id = UUID(appointment_id_str)

        logger.info(
            f"Processing payment expiration | appointment_id={appointment_id}"
        )

        # Query and update appointment
        async for db_session in get_async_session():
            stmt = select(Appointment).where(Appointment.id == appointment_id)
            result = await db_session.execute(stmt)
            appointment = result.scalar_one_or_none()

            if not appointment:
                logger.error(
                    f"Appointment not found for expired payment | "
                    f"appointment_id={appointment_id}"
                )
                return

            # Only update if still PROVISIONAL
            if appointment.status == AppointmentStatus.PROVISIONAL:
                appointment.status = AppointmentStatus.EXPIRED
                await db_session.commit()

                logger.info(
                    f"Appointment marked as EXPIRED via Stripe webhook | "
                    f"appointment_id={appointment_id}"
                )

            break  # Exit async for loop

    except Exception as e:
        logger.exception(f"Error processing payment expiration: {e}")


async def run_payment_processor():
    """
    Main worker loop - subscribes to Redis payment_events channel.

    Processes Stripe webhook events for payment confirmation and expiration.
    Runs continuously until interrupted.
    """
    redis_client = get_redis_client()
    pubsub = redis_client.pubsub()

    logger.info("Payment processor worker starting...")
    logger.info("Subscribing to Redis channel: payment_events")

    await pubsub.subscribe("payment_events")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    # Parse event data
                    event_data = json.loads(message["data"])
                    event_type = event_data.get("type")

                    logger.info(
                        f"Received payment event | type={event_type} | "
                        f"event_id={event_data.get('id')}"
                    )

                    # Route to appropriate handler
                    if event_type == "checkout.session.completed":
                        await process_payment_success(event_data)
                    elif event_type == "checkout.session.expired":
                        await process_payment_expired(event_data)
                    else:
                        logger.warning(
                            f"Unhandled payment event type: {event_type}"
                        )

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode payment event JSON: {e}")
                except Exception as e:
                    logger.exception(f"Error processing payment event: {e}")

    except asyncio.CancelledError:
        logger.info("Payment processor worker shutting down...")
        await pubsub.unsubscribe("payment_events")
        await pubsub.close()
    except Exception as e:
        logger.exception(f"Fatal error in payment processor worker: {e}")
        raise


if __name__ == "__main__":
    """Run payment processor as standalone worker."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("Starting payment processor worker...")

    try:
        asyncio.run(run_payment_processor())
    except KeyboardInterrupt:
        logger.info("Payment processor worker stopped by user")
    except Exception as e:
        logger.exception(f"Payment processor worker crashed: {e}")
        raise

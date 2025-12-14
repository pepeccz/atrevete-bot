"""
Appointment confirmation worker - Manages the confirmation and reminder lifecycle.

This worker handles three scheduled jobs:
1. send_confirmations (10:00 AM daily): Send 48h confirmation templates
2. process_auto_cancellations (10:00 AM daily): Auto-cancel unconfirmed appointments
3. send_reminders (hourly): Send 2h reminders for confirmed appointments

Architecture:
    - Runs daily jobs at 10:00 AM Europe/Madrid
    - Uses WhatsApp templates via Chatwoot API for messages outside 24h window
    - Updates Google Calendar events (status, color, emoji)
    - Creates admin panel notifications for visibility
    - Implements health check monitoring
"""

import asyncio
import json
import logging
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, and_, update
from sqlalchemy.orm import selectinload

from database.connection import get_async_session
from database.models import (
    Appointment,
    AppointmentStatus,
    Customer,
    Notification,
    NotificationType,
    Service,
    Stylist,
)
from shared.chatwoot_client import ChatwootClient
from shared.config import get_settings
from shared.settings_service import get_settings_service
from agent.services.gcal_push_service import (
    update_gcal_event_status,
    delete_gcal_event,
)

# Configure logger
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_requested = False


async def get_dynamic_settings() -> dict[str, Any]:
    """
    Load dynamic settings from database.

    Falls back to environment variables if database is unavailable.

    Returns:
        Dict with setting values keyed by setting name.
    """
    try:
        settings_service = await get_settings_service()
        return {
            # Confirmation settings
            "confirmation_hours_before": await settings_service.get("confirmation_hours_before", 48),
            "auto_cancel_hours_before": await settings_service.get("auto_cancel_hours_before", 24),
            "reminder_hours_before": await settings_service.get("reminder_hours_before", 2),
            "confirmation_template_name": await settings_service.get(
                "confirmation_template_name", "appointment_confirmation_48h"
            ),
            "auto_cancel_template_name": await settings_service.get(
                "auto_cancel_template_name", "appointment_auto_cancelled"
            ),
            "reminder_template_name": await settings_service.get(
                "reminder_template_name", "appointment_reminder_2h"
            ),
            # Job times (require restart)
            "confirmation_job_time": await settings_service.get("confirmation_job_time", "10:00"),
            "auto_cancel_job_time": await settings_service.get("auto_cancel_job_time", "10:00"),
            "reminder_job_interval": await settings_service.get("reminder_job_interval", "hourly"),
        }
    except Exception as e:
        logger.warning(f"Failed to load dynamic settings from DB, using env vars: {e}")
        env_settings = get_settings()
        return {
            "confirmation_hours_before": env_settings.CONFIRMATION_HOURS_BEFORE,
            "auto_cancel_hours_before": env_settings.AUTO_CANCEL_HOURS_BEFORE,
            "reminder_hours_before": env_settings.REMINDER_HOURS_BEFORE,
            "confirmation_template_name": env_settings.CONFIRMATION_TEMPLATE_NAME,
            "auto_cancel_template_name": env_settings.AUTO_CANCEL_TEMPLATE_NAME,
            "reminder_template_name": env_settings.REMINDER_TEMPLATE_NAME,
            "confirmation_job_time": "10:00",
            "auto_cancel_job_time": "10:00",
            "reminder_job_interval": "hourly",
        }

# Timezone for all datetime operations
MADRID_TZ = ZoneInfo("Europe/Madrid")

# Spanish weekday and month names for date formatting
WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
]


def signal_handler(signum: int, frame: Any) -> None:
    """
    Handle SIGTERM/SIGINT for graceful shutdown.
    """
    global shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_requested = True


# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


def format_date_spanish(dt: datetime) -> str:
    """
    Format datetime to Spanish date string.

    Args:
        dt: Datetime to format

    Returns:
        Formatted string like "lunes 15 de diciembre"
    """
    return f"{WEEKDAYS_ES[dt.weekday()]} {dt.day} de {MONTHS_ES[dt.month - 1]}"


def format_datetime_spanish(dt: datetime) -> str:
    """
    Format datetime to Spanish date and time string.

    Args:
        dt: Datetime to format

    Returns:
        Formatted string like "lunes 15 de diciembre a las 10:00"
    """
    return f"{format_date_spanish(dt)} a las {dt.strftime('%H:%M')}"


async def get_services_by_ids(session, service_ids: list[UUID]) -> list[Service]:
    """
    Get services by their IDs.

    Args:
        session: Database session
        service_ids: List of service UUIDs

    Returns:
        List of Service objects
    """
    result = await session.execute(
        select(Service).where(Service.id.in_(service_ids))
    )
    return list(result.scalars().all())


async def create_notification(
    session,
    notification_type: NotificationType,
    title: str,
    message: str,
    entity_id: UUID | None = None,
) -> None:
    """
    Create an admin panel notification.

    Args:
        session: Database session
        notification_type: Type of notification
        title: Notification title
        message: Notification message
        entity_id: Related entity ID (e.g., appointment ID)
    """
    notification = Notification(
        type=notification_type,
        title=title,
        message=message,
        entity_type="appointment" if entity_id else None,
        entity_id=entity_id,
    )
    session.add(notification)
    logger.debug(f"Created notification: {notification_type.value} - {title}")


# =============================================================================
# Job 1: Send Confirmation Requests (48h before)
# =============================================================================

async def send_confirmations() -> None:
    """
    Send confirmation request templates to appointments N hours away.

    Query: PENDING appointments where confirmation_sent_at IS NULL
           and start_time is within the confirmation window.

    For each appointment:
    1. Build template parameters from appointment data
    2. Send WhatsApp template via Chatwoot
    3. Update confirmation_sent_at timestamp
    4. Create admin notification
    """
    # Load dynamic settings from database
    dynamic_settings = await get_dynamic_settings()
    confirmation_hours = dynamic_settings["confirmation_hours_before"]

    now = datetime.now(MADRID_TZ)
    start_time = datetime.now(MADRID_TZ)

    logger.info(f"Starting send_confirmations job at {now.isoformat()}")

    confirmations_sent = 0
    errors = 0

    try:
        async with get_async_session() as session:
            # Query appointments that need confirmation
            # Use dynamic hours with 1h buffer on each side
            window_start = now + timedelta(hours=confirmation_hours - 1)
            window_end = now + timedelta(hours=confirmation_hours + 1)

            result = await session.execute(
                select(Appointment)
                .options(
                    selectinload(Appointment.customer),
                    selectinload(Appointment.stylist),
                )
                .where(
                    and_(
                        Appointment.status == AppointmentStatus.PENDING,
                        Appointment.confirmation_sent_at.is_(None),
                        Appointment.start_time >= window_start,
                        Appointment.start_time <= window_end,
                    )
                )
            )
            appointments = list(result.scalars().all())

            if not appointments:
                logger.info("No appointments need confirmation")
                return

            logger.info(f"Found {len(appointments)} appointments to send confirmations")

            # Initialize Chatwoot client
            chatwoot = ChatwootClient()

            for appointment in appointments:
                try:
                    # Get service names
                    services = await get_services_by_ids(session, appointment.service_ids)
                    service_names = ", ".join([s.name for s in services])

                    # Format dates
                    appt_time = appointment.start_time.astimezone(MADRID_TZ)
                    fecha = format_date_spanish(appt_time)
                    hora = appt_time.strftime("%H:%M")

                    # Calculate deadline for auto-cancel
                    auto_cancel_hours = dynamic_settings["auto_cancel_hours_before"]
                    deadline = appt_time - timedelta(hours=auto_cancel_hours)
                    deadline_str = format_datetime_spanish(deadline)

                    # Get customer name
                    customer_name = (
                        appointment.customer.first_name
                        or appointment.first_name
                        or "Cliente"
                    )

                    # Build template parameters
                    body_params = {
                        "1": customer_name,
                        "2": fecha,
                        "3": hora,
                        "4": appointment.stylist.name,
                        "5": service_names,
                        "6": deadline_str,
                    }

                    # Mark confirmation_sent_at BEFORE sending (intent-to-send)
                    # This prevents duplicate sends if the job runs again before next cycle
                    appointment.confirmation_sent_at = now
                    await session.commit()

                    # Send template message
                    template_name = dynamic_settings["confirmation_template_name"]
                    # Use existing conversation_id from customer if available
                    conv_id = None
                    if appointment.customer.chatwoot_conversation_id:
                        try:
                            conv_id = int(appointment.customer.chatwoot_conversation_id)
                        except (ValueError, TypeError):
                            pass
                    success = await chatwoot.send_template_message(
                        customer_phone=appointment.customer.phone,
                        template_name=template_name,
                        body_params=body_params,
                        customer_name=customer_name,
                        conversation_id=conv_id,
                        fallback_content=(
                            f"Recordatorio de cita: {fecha} a las {hora} "
                            f"con {appointment.stylist.name}. "
                            f"Responde SÍ para confirmar o NO para cancelar."
                        ),
                    )

                    if success:
                        # Create success notification
                        await create_notification(
                            session,
                            NotificationType.CONFIRMATION_SENT,
                            f"Confirmación enviada a {customer_name}",
                            f"Se ha enviado solicitud de confirmación para la cita "
                            f"del {fecha} a las {hora}",
                            entity_id=appointment.id,
                        )
                        await session.commit()

                        confirmations_sent += 1
                        logger.info(
                            f"Sent confirmation to {appointment.customer.phone} "
                            f"for appointment {appointment.id}"
                        )
                    else:
                        # Mark as failed (confirmation_sent_at already set, won't retry)
                        appointment.notification_failed = True
                        await session.commit()

                        await create_notification(
                            session,
                            NotificationType.CONFIRMATION_FAILED,
                            f"Error enviando confirmación a {customer_name}",
                            f"No se pudo enviar la confirmación para la cita "
                            f"del {fecha} a las {hora}. Revisar manualmente.",
                            entity_id=appointment.id,
                        )
                        await session.commit()

                        errors += 1
                        logger.error(
                            f"Failed to send confirmation to {appointment.customer.phone}"
                        )

                except Exception as e:
                    errors += 1
                    logger.error(
                        f"Error processing confirmation for appointment {appointment.id}: {e}",
                        exc_info=True,
                    )
                    await session.rollback()

    except Exception as e:
        logger.exception(f"Critical error in send_confirmations: {e}")
        errors += 1

    # Log summary
    duration = (datetime.now(MADRID_TZ) - start_time).total_seconds()
    logger.info(
        f"Completed send_confirmations in {duration:.2f}s: "
        f"sent={confirmations_sent}, errors={errors}"
    )

    # Update health check
    await update_health_check(
        job_name="send_confirmations",
        last_run=datetime.now(MADRID_TZ),
        status="healthy" if errors == 0 else "unhealthy",
        processed=confirmations_sent,
        errors=errors,
    )


# =============================================================================
# Job 2: Process Auto-Cancellations (24h before, no confirmation)
# =============================================================================

async def process_auto_cancellations() -> None:
    """
    Auto-cancel PENDING appointments within N hours that haven't been confirmed.

    Query: PENDING appointments where confirmation_sent_at IS NOT NULL
           and start_time is within the auto-cancel window.

    For each appointment:
    1. Update status to CANCELLED
    2. Set cancelled_at timestamp
    3. Delete Google Calendar event
    4. Send cancellation template to customer
    5. Create admin notification
    """
    # Load dynamic settings from database
    dynamic_settings = await get_dynamic_settings()
    auto_cancel_hours = dynamic_settings["auto_cancel_hours_before"]

    now = datetime.now(MADRID_TZ)
    start_time = datetime.now(MADRID_TZ)

    logger.info(f"Starting process_auto_cancellations job at {now.isoformat()}")

    cancellations = 0
    errors = 0

    try:
        async with get_async_session() as session:
            # Query unconfirmed appointments within auto-cancel window
            deadline = now + timedelta(hours=auto_cancel_hours)

            result = await session.execute(
                select(Appointment)
                .options(
                    selectinload(Appointment.customer),
                    selectinload(Appointment.stylist),
                )
                .where(
                    and_(
                        Appointment.status == AppointmentStatus.PENDING,
                        Appointment.confirmation_sent_at.is_not(None),
                        Appointment.start_time <= deadline,
                        Appointment.start_time > now,  # Strictly greater - don't cancel appointments in progress
                    )
                )
            )
            appointments = list(result.scalars().all())

            if not appointments:
                logger.info("No appointments to auto-cancel")
                return

            logger.info(f"Found {len(appointments)} appointments to auto-cancel")

            # Initialize Chatwoot client
            chatwoot = ChatwootClient()

            for appointment in appointments:
                try:
                    # Get service names
                    services = await get_services_by_ids(session, appointment.service_ids)
                    service_names = ", ".join([s.name for s in services])

                    # Format dates
                    appt_time = appointment.start_time.astimezone(MADRID_TZ)
                    fecha = format_date_spanish(appt_time)
                    hora = appt_time.strftime("%H:%M")

                    # Get customer name
                    customer_name = (
                        appointment.customer.first_name
                        or appointment.first_name
                        or "Cliente"
                    )

                    # Update appointment status
                    appointment.status = AppointmentStatus.CANCELLED
                    appointment.cancelled_at = now
                    await session.commit()

                    # Delete Google Calendar event
                    if appointment.google_calendar_event_id:
                        await delete_gcal_event(
                            stylist_id=appointment.stylist_id,
                            event_id=appointment.google_calendar_event_id,
                        )

                    # Send cancellation template
                    body_params = {
                        "1": customer_name,
                        "2": fecha,
                        "3": hora,
                    }

                    template_name = dynamic_settings["auto_cancel_template_name"]
                    # Use existing conversation_id from customer if available
                    conv_id = None
                    if appointment.customer.chatwoot_conversation_id:
                        try:
                            conv_id = int(appointment.customer.chatwoot_conversation_id)
                        except (ValueError, TypeError):
                            pass
                    await chatwoot.send_template_message(
                        customer_phone=appointment.customer.phone,
                        template_name=template_name,
                        body_params=body_params,
                        customer_name=customer_name,
                        conversation_id=conv_id,
                        fallback_content=(
                            f"Tu cita del {fecha} a las {hora} ha sido cancelada "
                            f"automáticamente al no recibir confirmación."
                        ),
                    )

                    # Create admin notification
                    await create_notification(
                        session,
                        NotificationType.AUTO_CANCELLED,
                        f"Cita auto-cancelada: {customer_name}",
                        f"La cita del {fecha} a las {hora} fue cancelada "
                        f"automáticamente por falta de confirmación.",
                        entity_id=appointment.id,
                    )
                    await session.commit()

                    cancellations += 1
                    logger.info(
                        f"Auto-cancelled appointment {appointment.id} "
                        f"for {appointment.customer.phone}"
                    )

                except Exception as e:
                    errors += 1
                    logger.error(
                        f"Error auto-cancelling appointment {appointment.id}: {e}",
                        exc_info=True,
                    )
                    await session.rollback()

    except Exception as e:
        logger.exception(f"Critical error in process_auto_cancellations: {e}")
        errors += 1

    # Log summary
    duration = (datetime.now(MADRID_TZ) - start_time).total_seconds()
    logger.info(
        f"Completed process_auto_cancellations in {duration:.2f}s: "
        f"cancelled={cancellations}, errors={errors}"
    )

    # Update health check
    await update_health_check(
        job_name="process_auto_cancellations",
        last_run=datetime.now(MADRID_TZ),
        status="healthy" if errors == 0 else "unhealthy",
        processed=cancellations,
        errors=errors,
    )


# =============================================================================
# Job 3: Send Reminders (2h before for confirmed appointments)
# =============================================================================

async def send_reminders() -> None:
    """
    Send N-hour reminder templates to confirmed appointments.

    Query: CONFIRMED appointments where reminder_sent_at IS NULL
           and start_time is within the reminder window.

    For each appointment:
    1. Build reminder template parameters
    2. Send WhatsApp template via Chatwoot
    3. Update reminder_sent_at timestamp
    4. Create admin notification
    """
    # Load dynamic settings from database
    dynamic_settings = await get_dynamic_settings()
    reminder_hours = dynamic_settings["reminder_hours_before"]

    now = datetime.now(MADRID_TZ)
    start_time = datetime.now(MADRID_TZ)

    logger.info(f"Starting send_reminders job at {now.isoformat()}")

    reminders_sent = 0
    errors = 0

    try:
        async with get_async_session() as session:
            # Query confirmed appointments that need reminder
            # Dynamic window with 30min buffer on each side
            window_start = now + timedelta(hours=reminder_hours - 0.5)
            window_end = now + timedelta(hours=reminder_hours + 0.5)

            result = await session.execute(
                select(Appointment)
                .options(
                    selectinload(Appointment.customer),
                    selectinload(Appointment.stylist),
                )
                .where(
                    and_(
                        Appointment.status == AppointmentStatus.CONFIRMED,
                        Appointment.reminder_sent_at.is_(None),
                        Appointment.start_time >= window_start,
                        Appointment.start_time <= window_end,
                    )
                )
            )
            appointments = list(result.scalars().all())

            if not appointments:
                logger.info("No appointments need reminders")
                return

            logger.info(f"Found {len(appointments)} appointments to send reminders")

            # Initialize Chatwoot client
            chatwoot = ChatwootClient()

            for appointment in appointments:
                try:
                    # Get service names
                    services = await get_services_by_ids(session, appointment.service_ids)
                    service_names = ", ".join([s.name for s in services])

                    # Format dates
                    appt_time = appointment.start_time.astimezone(MADRID_TZ)
                    fecha = format_date_spanish(appt_time)
                    hora = appt_time.strftime("%H:%M")

                    # Get customer name
                    customer_name = (
                        appointment.customer.first_name
                        or appointment.first_name
                        or "Cliente"
                    )

                    # Build template parameters
                    body_params = {
                        "1": customer_name,
                        "2": fecha,
                        "3": hora,
                        "4": service_names,
                    }

                    # Send reminder template
                    template_name = dynamic_settings["reminder_template_name"]
                    # Use existing conversation_id from customer if available
                    conv_id = None
                    if appointment.customer.chatwoot_conversation_id:
                        try:
                            conv_id = int(appointment.customer.chatwoot_conversation_id)
                        except (ValueError, TypeError):
                            pass
                    success = await chatwoot.send_template_message(
                        customer_phone=appointment.customer.phone,
                        template_name=template_name,
                        body_params=body_params,
                        customer_name=customer_name,
                        conversation_id=conv_id,
                        fallback_content=(
                            f"Recordatorio: Tu cita es hoy a las {hora}. "
                            f"Te esperamos en Peluquería Atrévete."
                        ),
                    )

                    if success:
                        # Update appointment
                        appointment.reminder_sent_at = now
                        await session.commit()

                        # Create notification
                        await create_notification(
                            session,
                            NotificationType.REMINDER_SENT,
                            f"Recordatorio enviado a {customer_name}",
                            f"Se ha enviado recordatorio para la cita de las {hora}",
                            entity_id=appointment.id,
                        )
                        await session.commit()

                        reminders_sent += 1
                        logger.info(
                            f"Sent reminder to {appointment.customer.phone} "
                            f"for appointment {appointment.id}"
                        )
                    else:
                        errors += 1
                        logger.error(
                            f"Failed to send reminder to {appointment.customer.phone}"
                        )

                except Exception as e:
                    errors += 1
                    logger.error(
                        f"Error processing reminder for appointment {appointment.id}: {e}",
                        exc_info=True,
                    )
                    await session.rollback()

    except Exception as e:
        logger.exception(f"Critical error in send_reminders: {e}")
        errors += 1

    # Log summary
    duration = (datetime.now(MADRID_TZ) - start_time).total_seconds()
    logger.info(
        f"Completed send_reminders in {duration:.2f}s: "
        f"sent={reminders_sent}, errors={errors}"
    )

    # Update health check
    await update_health_check(
        job_name="send_reminders",
        last_run=datetime.now(MADRID_TZ),
        status="healthy" if errors == 0 else "unhealthy",
        processed=reminders_sent,
        errors=errors,
    )


# =============================================================================
# Health Check
# =============================================================================

async def update_health_check(
    job_name: str,
    last_run: datetime,
    status: str,
    processed: int,
    errors: int,
) -> None:
    """
    Update health check file with job statistics.

    Args:
        job_name: Name of the job
        last_run: Timestamp of job completion
        status: Health status ('healthy' or 'unhealthy')
        processed: Number of items processed
        errors: Number of errors encountered
    """
    health_dir = Path("/tmp/health")
    health_dir.mkdir(parents=True, exist_ok=True)
    health_file = health_dir / "confirmation_worker_health.json"
    temp_file = health_dir / f"confirmation_worker_health.{int(time.time())}.tmp"

    # Load existing health data
    health_data = {}
    if health_file.exists():
        try:
            health_data = json.loads(health_file.read_text())
        except Exception:
            pass

    # Update job status
    health_data[job_name] = {
        "last_run": last_run.isoformat(),
        "status": status,
        "processed": processed,
        "errors": errors,
    }

    # Update overall status
    all_healthy = all(
        job.get("status") == "healthy"
        for job in health_data.values()
        if isinstance(job, dict)
    )
    health_data["overall_status"] = "healthy" if all_healthy else "unhealthy"
    health_data["last_updated"] = datetime.now(MADRID_TZ).isoformat()

    try:
        temp_file.write_text(json.dumps(health_data, indent=2))
        temp_file.rename(health_file)
        logger.debug(f"Health check file updated: {health_file}")
    except Exception as e:
        logger.error(f"Failed to write health check file: {e}", exc_info=True)


# =============================================================================
# Main Entry Point
# =============================================================================

async def async_main() -> None:
    """
    Main async entry point - runs confirmation jobs on schedule using a single event loop.

    IMPORTANT: Uses asyncio.sleep() instead of schedule + asyncio.run() to avoid
    event loop corruption. Each asyncio.run() creates a new event loop, but
    SQLAlchemy's asyncpg connections keep references to the previous loop,
    causing "Future attached to a different loop" errors.

    Schedule:
    - send_confirmations: Daily at configured time (default 10:00 AM Madrid)
    - process_auto_cancellations: Daily at configured time (default 10:00 AM Madrid)
    - send_reminders: Based on interval setting (hourly or every 30min)

    Handles graceful shutdown on SIGTERM/SIGINT.
    """
    global shutdown_requested

    # Load dynamic settings from database
    dynamic_settings = await get_dynamic_settings()

    logger.info("Appointment confirmation worker starting...")
    logger.info(
        f"Configuration (from database): "
        f"confirmation_hours_before={dynamic_settings['confirmation_hours_before']}, "
        f"auto_cancel_hours_before={dynamic_settings['auto_cancel_hours_before']}, "
        f"reminder_hours_before={dynamic_settings['reminder_hours_before']}, "
        f"TIMEZONE={MADRID_TZ}"
    )

    # Write initial health check file
    await update_health_check(
        job_name="startup",
        last_run=datetime.now(MADRID_TZ),
        status="healthy",
        processed=0,
        errors=0,
    )
    logger.info("Initial health check file written")

    # Get job times from settings
    confirmation_time = dynamic_settings["confirmation_job_time"]  # "10:00"
    auto_cancel_time = dynamic_settings["auto_cancel_job_time"]    # "10:00"
    reminder_interval = dynamic_settings["reminder_job_interval"]  # "hourly" or "30min"

    logger.info(
        f"Confirmation worker scheduled:\n"
        f"  - send_confirmations: daily at {confirmation_time}\n"
        f"  - process_auto_cancellations: daily at {auto_cancel_time}\n"
        f"  - send_reminders: {reminder_interval}"
    )

    # Track last execution times to avoid running jobs multiple times
    last_daily_run: str | None = None  # Format: "YYYY-MM-DD"
    last_reminder_run: datetime | None = None

    # Calculate reminder interval in minutes
    reminder_minutes = 30 if reminder_interval == "30min" else 60

    # Main loop - check every minute
    while not shutdown_requested:
        now = datetime.now(MADRID_TZ)
        current_time = now.strftime("%H:%M")
        current_date = now.strftime("%Y-%m-%d")

        # Check if we should run daily jobs (confirmation + auto-cancel)
        # Run if: correct time AND haven't run today
        if current_time == confirmation_time and last_daily_run != current_date:
            logger.info(f"Running daily jobs at {current_time}")
            try:
                await send_confirmations()
            except Exception as e:
                logger.error(f"Error in send_confirmations: {e}", exc_info=True)

            try:
                await process_auto_cancellations()
            except Exception as e:
                logger.error(f"Error in process_auto_cancellations: {e}", exc_info=True)

            last_daily_run = current_date

        # Check if we should run reminders
        # Run if: enough time has passed since last run
        should_run_reminders = False
        if last_reminder_run is None:
            # First run - run immediately
            should_run_reminders = True
        else:
            minutes_since_last = (now - last_reminder_run).total_seconds() / 60
            if minutes_since_last >= reminder_minutes:
                should_run_reminders = True

        if should_run_reminders:
            logger.info(f"Running send_reminders at {now.strftime('%H:%M:%S')}")
            try:
                await send_reminders()
            except Exception as e:
                logger.error(f"Error in send_reminders: {e}", exc_info=True)
            last_reminder_run = now

        # Sleep for 1 minute before checking again
        await asyncio.sleep(60)

    logger.info("Confirmation worker shutting down gracefully...")


def run_confirmation_worker() -> None:
    """
    Synchronous entry point that sets up logging and signal handlers,
    then runs the async main function.
    """
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Run the async main with a single event loop
    asyncio.run(async_main())


if __name__ == "__main__":
    run_confirmation_worker()

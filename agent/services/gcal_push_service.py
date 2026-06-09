"""
Google Calendar Push Service - Fire-and-Forget Async Push.

This module provides asynchronous push operations to Google Calendar.
In the DB-first architecture, this service is used AFTER the database
commit to push events to Google Calendar as a mirror for stylists' mobile viewing.

Architecture:
- DB commit happens FIRST (source of truth)
- Google Calendar push is fire-and-forget (async, non-blocking)
- Push failures are logged but don't roll back the booking
- Event IDs are stored back in DB when push succeeds

Usage:
    from agent.services.gcal_push_service import (
        push_appointment_to_gcal,
        push_blocking_event_to_gcal,
        delete_gcal_event,
    )

    # Push appointment after DB commit
    event_id = await push_appointment_to_gcal(
        appointment_id=uuid,
        stylist_id=uuid,
        customer_name="María García",
        service_names="Corte y tinte",
        start_time=datetime,
        duration_minutes=90
    )
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy import select, update

from agent.services.gcal_credential_factory import get_google_credentials
from agent.services.notification_service import (
    create_gcal_push_failed_notification,
    resolve_gcal_push_failed_notification,
)
from database.connection import get_async_session
from database.models import Appointment, BlockingEvent, Stylist
from shared.config import get_settings

logger = logging.getLogger(__name__)

MADRID_TZ = ZoneInfo("Europe/Madrid")

# Retry configuration for GCal API calls
GCAL_MAX_RETRIES = 3
GCAL_RETRY_BASE_DELAY = 1.0  # seconds


async def _write_gcal_status(
    appointment_id: UUID,
    status: str,
    operation: str,
    error: str | None,
) -> None:
    """Write gcal sync status to the appointment row.

    Opens a fresh short-lived session (never shares caller's session — fire-and-forget
    callers run detached and the caller's session is already closed).

    On success (status='synced'), resolves any open GCAL_PUSH_FAILED notification.
    On failure (status='failed'), creates a GCAL_PUSH_FAILED notification if none exists.

    Design: D2 (gcal-sync-resilience).
    """
    try:
        async with get_async_session() as session:
            # Check prior status for notification logic
            prior_result = await session.execute(
                select(Appointment.gcal_sync_status).where(Appointment.id == appointment_id)
            )
            prior_status = prior_result.scalar_one_or_none()

            await session.execute(
                update(Appointment)
                .where(Appointment.id == appointment_id)
                .values(
                    gcal_sync_status=status,
                    gcal_last_attempt_at=datetime.now(MADRID_TZ),
                    gcal_last_error=error[:1000] if error else None,
                    gcal_operation=operation,
                )
            )

            if status == "synced" and prior_status == "failed":
                await resolve_gcal_push_failed_notification(session, appointment_id)
            elif status == "failed":
                await create_gcal_push_failed_notification(session, appointment_id)

            await session.commit()
    except Exception as exc:
        logger.error(
            "Failed to write gcal sync status for appointment %s: %s", appointment_id, exc
        )


async def _retry_with_backoff(
    operation: callable,
    operation_name: str,
    max_retries: int = GCAL_MAX_RETRIES,
    base_delay: float = GCAL_RETRY_BASE_DELAY,
) -> Any:
    """
    Execute an operation with exponential backoff retry.

    Args:
        operation: Async callable to execute
        operation_name: Name for logging
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds (doubles each retry)

    Returns:
        Result of the operation

    Raises:
        Last exception if all retries fail
    """
    last_exception = None

    for attempt in range(max_retries):
        try:
            return await operation()
        except HttpError as e:
            # Don't retry 404 (not found) or 400 (bad request)
            if e.resp.status in (400, 404):
                raise
            last_exception = e
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    f"GCal {operation_name} failed (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {delay}s: {e}"
                )
                await asyncio.sleep(delay)
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    f"GCal {operation_name} failed (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {delay}s: {e}"
                )
                await asyncio.sleep(delay)

    logger.error(f"GCal {operation_name} failed after {max_retries} attempts")
    raise last_exception


# Event color codes for Google Calendar
EVENT_COLORS = {
    "pending": "5",  # Yellow
    "confirmed": "10",  # Green
    "vacation": "11",  # Red
    "meeting": "6",  # Orange
    "break": "2",  # Green (lighter)
    "general": "8",  # Gray
    "personal": "14",  # Pink
}


async def _get_calendar_service():
    """
    Create a Google Calendar API service instance using the credential factory.

    Uses get_google_credentials() which resolves OAuth2 tokens from DB (when
    configured) or falls back to the service account file. Opens a short-lived
    AsyncSession to allow the factory to resolve OAuth2 tokens from the database.

    Returns:
        Google Calendar service object
    """
    try:
        async with get_async_session() as session:
            credentials = await get_google_credentials(session=session)
        return build("calendar", "v3", credentials=credentials)
    except Exception as e:
        logger.error(f"Failed to create Google Calendar service: {e}")
        raise


async def _get_stylist_calendar_id(stylist_id: UUID) -> str | None:
    """
    Get the Google Calendar ID for a stylist.

    Args:
        stylist_id: UUID of the stylist

    Returns:
        Google Calendar ID or None if not found
    """
    try:
        async with get_async_session() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(Stylist.google_calendar_id).where(Stylist.id == stylist_id)
            )
            row = result.first()
            return row[0] if row else None

    except Exception as e:
        logger.error(f"Error fetching stylist calendar ID: {e}")
        return None


async def push_appointment_to_gcal(
    appointment_id: UUID,
    stylist_id: UUID,
    customer_name: str,
    service_names: str,
    start_time: datetime,
    duration_minutes: int,
    status: str = "pending",
    customer_phone: str | None = None,
    notes: str | None = None,
) -> str | None:
    """
    Push an appointment to Google Calendar as a fire-and-forget operation.

    This function runs in the background after DB commit. Failures are logged
    but don't affect the booking transaction.

    Args:
        appointment_id: UUID of the appointment (for updating DB with event_id)
        stylist_id: UUID of the stylist
        customer_name: Customer's name for the event title
        service_names: Service names for the event title
        start_time: Appointment start time (timezone-aware)
        duration_minutes: Duration of the appointment
        status: "pending" or "confirmed" (affects color and emoji)
        notes: Optional appointment notes shown in GCal description

    Returns:
        Google Calendar event ID if successful, None if failed

    Example:
        >>> event_id = await push_appointment_to_gcal(
        ...     appointment_id=uuid,
        ...     stylist_id=uuid,
        ...     customer_name="María García",
        ...     service_names="Corte y tinte",
        ...     start_time=datetime(2025, 12, 15, 10, 0, tzinfo=MADRID_TZ),
        ...     duration_minutes=90
        ... )
        >>> print(event_id)  # "abc123xyz..."
    """
    if get_settings().TEST_MODE_GCAL_SKIP:
        logger.info(
            "gcal_push.skipped op=push_appointment appointment_id=%s reason=TEST_MODE_GCAL_SKIP",
            appointment_id,
        )
        await _write_gcal_status(appointment_id, "not_applicable", "push_appointment", None)
        return None
    try:
        # Get stylist's calendar ID
        calendar_id = await _get_stylist_calendar_id(stylist_id)
        if not calendar_id:
            logger.warning(
                f"Cannot push appointment {appointment_id}: "
                f"No calendar ID found for stylist {stylist_id}"
            )
            return None

        # Calculate end time
        end_time = start_time + timedelta(minutes=duration_minutes)

        # Build event summary with status emoji and phone
        phone_suffix = f" - {customer_phone}" if customer_phone else ""
        if status == "pending":
            summary = f"🟡 {customer_name} - {service_names}{phone_suffix}"
        elif status == "confirmed":
            summary = f"🟢 {customer_name} - {service_names}{phone_suffix}"
        else:
            summary = f"{customer_name} - {service_names}{phone_suffix}"

        # Build event description
        description_parts = [
            f"Cliente: {customer_name}",
            f"Servicios: {service_names}",
            f"Estado: {status}",
            f"ID de la cita: {appointment_id}",
        ]
        if notes:
            description_parts.insert(2, f"Notas: {notes[:500]}")
        description = "\n".join(description_parts)

        # Determine color based on status
        color_id = EVENT_COLORS.get(status, "5")

        # Build event body
        event_body = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": "Europe/Madrid",
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": "Europe/Madrid",
            },
            "colorId": color_id,
        }

        # Create event in Google Calendar with retry
        service = await _get_calendar_service()
        loop = asyncio.get_event_loop()

        async def create_event_with_retry():
            def create_event():
                return (
                    service.events()
                    .insert(
                        calendarId=calendar_id,
                        body=event_body,
                    )
                    .execute()
                )

            return await loop.run_in_executor(None, create_event)

        event = await _retry_with_backoff(
            create_event_with_retry,
            f"push appointment {appointment_id}",
        )

        event_id = event.get("id")
        logger.info(f"Pushed appointment {appointment_id} to Google Calendar: event_id={event_id}")

        # Update appointment with Google Calendar event ID
        if event_id:
            await _update_appointment_gcal_id(appointment_id, event_id)

        await _write_gcal_status(appointment_id, "synced", "book", None)
        return event_id

    except HttpError as e:
        logger.error(
            f"Google Calendar API error pushing appointment {appointment_id}: {e}", exc_info=True
        )
        await _write_gcal_status(appointment_id, "failed", "book", str(e))
        return None
    except Exception as e:
        logger.error(
            f"Error pushing appointment {appointment_id} to Google Calendar: {e}", exc_info=True
        )
        await _write_gcal_status(appointment_id, "failed", "book", str(e))
        return None


async def _update_appointment_gcal_id(appointment_id: UUID, event_id: str) -> None:
    """
    Update appointment with Google Calendar event ID.

    Args:
        appointment_id: UUID of the appointment
        event_id: Google Calendar event ID
    """
    try:
        async with get_async_session() as session:
            await session.execute(
                update(Appointment)
                .where(Appointment.id == appointment_id)
                .values(google_calendar_event_id=event_id)
            )
            await session.commit()
            logger.debug(f"Updated appointment {appointment_id} with gcal_event_id={event_id}")

    except Exception as e:
        logger.error(
            f"Failed to update appointment {appointment_id} with gcal event ID: {e}", exc_info=True
        )


async def push_blocking_event_to_gcal(
    blocking_event_id: UUID,
    stylist_id: UUID,
    title: str,
    description: str | None,
    start_time: datetime,
    end_time: datetime,
    event_type: str = "general",
) -> str | None:
    """
    Push a blocking event to Google Calendar.

    Args:
        blocking_event_id: UUID of the blocking event
        stylist_id: UUID of the stylist
        title: Event title
        description: Event description
        start_time: Start time (timezone-aware)
        end_time: End time (timezone-aware)
        event_type: Type of blocking event (vacation, meeting, break, general)

    Returns:
        Google Calendar event ID if successful, None if failed
    """
    if get_settings().TEST_MODE_GCAL_SKIP:
        logger.info(
            "gcal_push.skipped op=push_blocking_event blocking_event_id=%s reason=TEST_MODE_GCAL_SKIP",
            blocking_event_id,
        )
        return None
    try:
        # Get stylist's calendar ID
        calendar_id = await _get_stylist_calendar_id(stylist_id)
        if not calendar_id:
            logger.warning(
                f"Cannot push blocking event {blocking_event_id}: "
                f"No calendar ID found for stylist {stylist_id}"
            )
            return None

        # Add emoji based on event type
        type_emojis = {
            "vacation": "🏖️",
            "meeting": "📅",
            "break": "☕",
            "general": "🚫",
            "personal": "💕",
        }
        emoji = type_emojis.get(event_type, "🚫")
        summary = f"{emoji} {title}"

        # Determine color based on event type
        color_id = EVENT_COLORS.get(event_type, "8")

        # Build event body
        event_body = {
            "summary": summary,
            "description": description or "",
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": "Europe/Madrid",
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": "Europe/Madrid",
            },
            "colorId": color_id,
        }

        # Create event in Google Calendar
        service = await _get_calendar_service()

        def create_event():
            return (
                service.events()
                .insert(
                    calendarId=calendar_id,
                    body=event_body,
                )
                .execute()
            )

        loop = asyncio.get_event_loop()
        event = await loop.run_in_executor(None, create_event)

        event_id = event.get("id")
        logger.info(
            f"Pushed blocking event {blocking_event_id} to Google Calendar: event_id={event_id}"
        )

        # Update blocking event with Google Calendar event ID
        if event_id:
            await _update_blocking_event_gcal_id(blocking_event_id, event_id)

        return event_id

    except HttpError as e:
        logger.error(
            f"Google Calendar API error pushing blocking event {blocking_event_id}: {e}",
            exc_info=True,
        )
        return None
    except Exception as e:
        logger.error(
            f"Error pushing blocking event {blocking_event_id} to Google Calendar: {e}",
            exc_info=True,
        )
        return None


async def _update_blocking_event_gcal_id(blocking_event_id: UUID, event_id: str) -> None:
    """
    Update blocking event with Google Calendar event ID.

    Args:
        blocking_event_id: UUID of the blocking event
        event_id: Google Calendar event ID
    """
    try:
        async with get_async_session() as session:
            await session.execute(
                update(BlockingEvent)
                .where(BlockingEvent.id == blocking_event_id)
                .values(google_calendar_event_id=event_id)
            )
            await session.commit()
            logger.debug(
                f"Updated blocking event {blocking_event_id} with gcal_event_id={event_id}"
            )

    except Exception as e:
        logger.error(
            f"Failed to update blocking event {blocking_event_id} with gcal event ID: {e}",
            exc_info=True,
        )


async def update_appointment_in_gcal(
    appointment_id: UUID,
    stylist_id: UUID,
    event_id: str,
    customer_name: str,
    service_names: str,
    start_time: datetime,
    duration_minutes: int,
    status: str = "confirmed",
    customer_phone: str | None = None,
    notes: str | None = None,
) -> bool:
    """
    Update an existing appointment in Google Calendar (full update).

    USE THIS FUNCTION when you need to update time, services, stylist, etc.
    (e.g., admin panel edits). Use update_gcal_event_status() when you only
    need to change the status/emoji (e.g., confirmation flow).

    Uses service.events().patch() to update only changed fields.

    Args:
        appointment_id: UUID of the appointment (for logging)
        stylist_id: UUID of the stylist (to get calendar ID)
        event_id: Google Calendar event ID (from appointment.google_calendar_event_id)
        customer_name: Updated customer name
        service_names: Updated service names
        start_time: Updated start time (timezone-aware)
        duration_minutes: Updated duration
        status: Updated status ("pending", "confirmed", etc.)

    Returns:
        True if updated successfully, False otherwise
    """
    if get_settings().TEST_MODE_GCAL_SKIP:
        logger.info(
            "gcal_push.skipped op=update_appointment appointment_id=%s reason=TEST_MODE_GCAL_SKIP",
            appointment_id,
        )
        await _write_gcal_status(appointment_id, "not_applicable", "update_appointment", None)
        return None
    try:
        # Get stylist's calendar ID
        calendar_id = await _get_stylist_calendar_id(stylist_id)
        if not calendar_id:
            logger.warning(
                f"Cannot update appointment {appointment_id}: "
                f"No calendar ID found for stylist {stylist_id}"
            )
            return False

        # Calculate end time
        end_time = start_time + timedelta(minutes=duration_minutes)

        # Build event summary with status emoji and phone
        phone_suffix = f" - {customer_phone}" if customer_phone else ""
        if status == "pending":
            summary = f"🟡 {customer_name} - {service_names}{phone_suffix}"
        elif status == "confirmed":
            summary = f"🟢 {customer_name} - {service_names}{phone_suffix}"
        else:
            summary = f"{customer_name} - {service_names}{phone_suffix}"

        # Build event description
        description_parts = [
            f"Cliente: {customer_name}",
            f"Servicios: {service_names}",
            f"Estado: {status}",
            f"ID de la cita: {appointment_id}",
        ]
        if notes:
            description_parts.insert(2, f"Notas: {notes[:500]}")
        description = "\n".join(description_parts)

        # Determine color based on status
        color_id = EVENT_COLORS.get(status, "5")

        # Build update body (only fields that might have changed)
        update_body = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": "Europe/Madrid",
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": "Europe/Madrid",
            },
            "colorId": color_id,
        }

        # Update event in Google Calendar (use patch for partial update)
        service = await _get_calendar_service()

        def update_event():
            return (
                service.events()
                .patch(
                    calendarId=calendar_id,
                    eventId=event_id,
                    body=update_body,
                )
                .execute()
            )

        # Run in thread pool to not block the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, update_event)

        logger.info(f"Updated appointment {appointment_id} in Google Calendar: event_id={event_id}")
        await _write_gcal_status(appointment_id, "synced", "reschedule", None)
        return True

    except HttpError as e:
        if e.resp.status == 404:
            logger.warning(
                f"Appointment {appointment_id} not found in Google Calendar "
                f"(event_id={event_id}). Event may have been deleted externally."
            )
            await _write_gcal_status(appointment_id, "failed", "reschedule", str(e))
            return False
        logger.error(
            f"Google Calendar API error updating appointment {appointment_id}: {e}", exc_info=True
        )
        await _write_gcal_status(appointment_id, "failed", "reschedule", str(e))
        return False
    except Exception as e:
        logger.error(
            f"Error updating appointment {appointment_id} in Google Calendar: {e}", exc_info=True
        )
        await _write_gcal_status(appointment_id, "failed", "reschedule", str(e))
        return False


async def update_blocking_event_in_gcal(
    blocking_event_id: UUID,
    stylist_id: UUID,
    event_id: str,
    title: str,
    description: str | None,
    start_time: datetime,
    end_time: datetime,
    event_type: str = "general",
) -> bool:
    """
    Update an existing blocking event in Google Calendar.

    Uses service.events().patch() to update only changed fields.

    Args:
        blocking_event_id: UUID of the blocking event (for logging)
        stylist_id: UUID of the stylist (to get calendar ID)
        event_id: Google Calendar event ID (from blocking_event.google_calendar_event_id)
        title: Updated event title
        description: Updated event description
        start_time: Updated start time (timezone-aware)
        end_time: Updated end time (timezone-aware)
        event_type: Updated event type (vacation, meeting, break, general, personal)

    Returns:
        True if updated successfully, False otherwise
    """
    try:
        # Get stylist's calendar ID
        calendar_id = await _get_stylist_calendar_id(stylist_id)
        if not calendar_id:
            logger.warning(
                f"Cannot update blocking event {blocking_event_id}: "
                f"No calendar ID found for stylist {stylist_id}"
            )
            return False

        # Add emoji based on event type
        type_emojis = {
            "vacation": "🏖️",
            "meeting": "📅",
            "break": "☕",
            "general": "🚫",
            "personal": "💕",
        }
        emoji = type_emojis.get(event_type, "🚫")
        summary = f"{emoji} {title}"

        # Determine color based on event type
        color_id = EVENT_COLORS.get(event_type, "8")

        # Build update body
        update_body = {
            "summary": summary,
            "description": description or "",
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": "Europe/Madrid",
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": "Europe/Madrid",
            },
            "colorId": color_id,
        }

        # Update event in Google Calendar
        service = await _get_calendar_service()

        def update_event():
            return (
                service.events()
                .patch(
                    calendarId=calendar_id,
                    eventId=event_id,
                    body=update_body,
                )
                .execute()
            )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, update_event)

        logger.info(
            f"Updated blocking event {blocking_event_id} in Google Calendar: event_id={event_id}"
        )
        return True

    except HttpError as e:
        if e.resp.status == 404:
            logger.warning(
                f"Blocking event {blocking_event_id} not found in Google Calendar "
                f"(event_id={event_id}). Event may have been deleted externally."
            )
            return False
        logger.error(
            f"Google Calendar API error updating blocking event {blocking_event_id}: {e}",
            exc_info=True,
        )
        return False
    except Exception as e:
        logger.error(
            f"Error updating blocking event {blocking_event_id} in Google Calendar: {e}",
            exc_info=True,
        )
        return False


async def delete_gcal_event(
    stylist_id: UUID,
    event_id: str,
    appointment_id: UUID | None = None,
) -> bool:
    """
    Delete an event from Google Calendar.

    Args:
        stylist_id: UUID of the stylist (to get calendar ID)
        event_id: Google Calendar event ID to delete
        appointment_id: Optional appointment UUID. When provided, writes gcal_sync_status
                        to the appointment row after the operation (D2, gcal-sync-resilience).
                        404 from GCal is treated as success (event already gone = synced).

    Returns:
        True if deleted successfully, False otherwise
    """
    if get_settings().TEST_MODE_GCAL_SKIP:
        if appointment_id is not None:
            logger.info(
                "gcal_push.skipped op=delete_event appointment_id=%s event_id=%s reason=TEST_MODE_GCAL_SKIP",
                appointment_id,
                event_id,
            )
            await _write_gcal_status(appointment_id, "not_applicable", "delete_event", None)
        else:
            logger.info(
                "gcal_push.skipped op=delete_event event_id=%s reason=TEST_MODE_GCAL_SKIP",
                event_id,
            )
        return None
    try:
        # Get stylist's calendar ID
        calendar_id = await _get_stylist_calendar_id(stylist_id)
        if not calendar_id:
            logger.warning(
                f"Cannot delete event {event_id}: No calendar ID found for stylist {stylist_id}"
            )
            return False

        # Delete event from Google Calendar
        service = await _get_calendar_service()

        def delete_event():
            service.events().delete(
                calendarId=calendar_id,
                eventId=event_id,
            ).execute()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, delete_event)

        logger.info(f"Deleted Google Calendar event: {event_id}")
        if appointment_id is not None:
            await _write_gcal_status(appointment_id, "synced", "cancel", None)
        return True

    except HttpError as e:
        if e.resp.status == 404:
            logger.warning(f"Event {event_id} not found in Google Calendar (already deleted?)")
            # 404 = event already gone — matches DB intent, treat as synced (D2)
            if appointment_id is not None:
                await _write_gcal_status(appointment_id, "synced", "cancel", None)
            return True
        logger.error(f"Google Calendar API error deleting event {event_id}: {e}")
        if appointment_id is not None:
            await _write_gcal_status(appointment_id, "failed", "cancel", str(e))
        return False
    except Exception as e:
        logger.error(f"Error deleting Google Calendar event {event_id}: {e}", exc_info=True)
        if appointment_id is not None:
            await _write_gcal_status(appointment_id, "failed", "cancel", str(e))
        return False


async def update_gcal_event_status(
    stylist_id: UUID,
    event_id: str,
    new_status: str,
    customer_name: str,
    service_names: str,
) -> bool:
    """
    Update the status (color and emoji) of a Google Calendar event.

    USE THIS FUNCTION when you only need to change the status/emoji (e.g., confirmation flow).
    Use update_appointment_in_gcal() when you need to update time, services, etc.

    Args:
        stylist_id: UUID of the stylist
        event_id: Google Calendar event ID
        new_status: New status ("pending", "confirmed", "cancelled")
        customer_name: Customer name for the event title
        service_names: Service names for the event title

    Returns:
        True if updated successfully, False otherwise
    """
    if get_settings().TEST_MODE_GCAL_SKIP:
        logger.info(
            "gcal_push.skipped op=update_gcal_event_status event_id=%s reason=TEST_MODE_GCAL_SKIP",
            event_id,
        )
        return None
    try:
        # Get stylist's calendar ID
        calendar_id = await _get_stylist_calendar_id(stylist_id)
        if not calendar_id:
            logger.warning(
                f"Cannot update event {event_id}: No calendar ID found for stylist {stylist_id}"
            )
            return False

        # Build new summary with status emoji
        if new_status == "pending":
            summary = f"🟡 {customer_name} - {service_names}"
        elif new_status == "confirmed":
            summary = f"🟢 {customer_name} - {service_names}"
        elif new_status == "cancelled":
            summary = f"❌ {customer_name} - {service_names}"
        else:
            summary = f"{customer_name} - {service_names}"

        color_id = EVENT_COLORS.get(new_status, "5")

        # Update event in Google Calendar with retry
        service = await _get_calendar_service()
        loop = asyncio.get_event_loop()

        async def update_event_with_retry():
            def update_event():
                return (
                    service.events()
                    .patch(
                        calendarId=calendar_id,
                        eventId=event_id,
                        body={
                            "summary": summary,
                            "colorId": color_id,
                        },
                    )
                    .execute()
                )

            return await loop.run_in_executor(None, update_event)

        await _retry_with_backoff(
            update_event_with_retry,
            f"update status for event {event_id}",
        )

        logger.info(f"Updated Google Calendar event {event_id} to status: {new_status}")
        return True

    except HttpError as e:
        if e.resp.status == 404:
            logger.warning(f"Event {event_id} not found in Google Calendar")
        else:
            logger.error(f"Google Calendar API error updating event {event_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error updating Google Calendar event {event_id}: {e}", exc_info=True)
        return False


async def fire_and_forget_push_appointment(
    appointment_id: UUID,
    stylist_id: UUID,
    customer_name: str,
    service_names: str,
    start_time: datetime,
    duration_minutes: int,
    status: str = "pending",
    notes: str | None = None,
) -> None:
    """
    Schedule appointment push as a background task (truly fire-and-forget).

    Use this when you want to return immediately without waiting for the push.

    Args:
        Same as push_appointment_to_gcal
    """
    asyncio.create_task(
        push_appointment_to_gcal(
            appointment_id=appointment_id,
            stylist_id=stylist_id,
            customer_name=customer_name,
            service_names=service_names,
            start_time=start_time,
            duration_minutes=duration_minutes,
            status=status,
            notes=notes,
        )
    )
    logger.info(f"Scheduled fire-and-forget push for appointment {appointment_id}")


async def fire_and_forget_push_blocking_event(
    blocking_event_id: UUID,
    stylist_id: UUID,
    title: str,
    description: str | None,
    start_time: datetime,
    end_time: datetime,
    event_type: str = "general",
) -> None:
    """
    Schedule blocking event push as a background task (truly fire-and-forget).

    Use this when you want to return immediately without waiting for the push.

    Args:
        Same as push_blocking_event_to_gcal
    """
    asyncio.create_task(
        push_blocking_event_to_gcal(
            blocking_event_id=blocking_event_id,
            stylist_id=stylist_id,
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            event_type=event_type,
        )
    )
    logger.info(f"Scheduled fire-and-forget push for blocking event {blocking_event_id}")

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
from typing import Any, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy import update

from database.connection import get_async_session
from database.models import Appointment, BlockingEvent, Stylist
from shared.config import get_settings

logger = logging.getLogger(__name__)

MADRID_TZ = ZoneInfo("Europe/Madrid")

# Retry configuration for GCal API calls
GCAL_MAX_RETRIES = 3
GCAL_RETRY_BASE_DELAY = 1.0  # seconds


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
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"GCal {operation_name} failed (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {delay}s: {e}"
                )
                await asyncio.sleep(delay)
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"GCal {operation_name} failed (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {delay}s: {e}"
                )
                await asyncio.sleep(delay)

    logger.error(f"GCal {operation_name} failed after {max_retries} attempts")
    raise last_exception


# Event color codes for Google Calendar
EVENT_COLORS = {
    "pending": "5",      # Yellow
    "confirmed": "10",   # Green
    "vacation": "11",    # Red
    "meeting": "6",      # Orange
    "break": "2",        # Green (lighter)
    "general": "8",      # Gray
    "personal": "14",    # Pink
}


def _get_calendar_service():
    """
    Create a Google Calendar API service instance.

    Returns:
        Google Calendar service object
    """
    settings = get_settings()

    try:
        credentials = service_account.Credentials.from_service_account_file(
            settings.GOOGLE_SERVICE_ACCOUNT_JSON,
            scopes=["https://www.googleapis.com/auth/calendar"]
        )
        return build("calendar", "v3", credentials=credentials)
    except Exception as e:
        logger.error(f"Failed to create Google Calendar service: {e}")
        raise


async def _get_stylist_calendar_id(stylist_id: UUID) -> Optional[str]:
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
) -> Optional[str]:
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
        description = (
            f"Cliente: {customer_name}\n"
            f"Servicios: {service_names}\n"
            f"Estado: {status}\n"
            f"ID de la cita: {appointment_id}"
        )

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
        service = _get_calendar_service()
        loop = asyncio.get_event_loop()

        async def create_event_with_retry():
            def create_event():
                return service.events().insert(
                    calendarId=calendar_id,
                    body=event_body,
                ).execute()
            return await loop.run_in_executor(None, create_event)

        event = await _retry_with_backoff(
            create_event_with_retry,
            f"push appointment {appointment_id}",
        )

        event_id = event.get("id")
        logger.info(
            f"Pushed appointment {appointment_id} to Google Calendar: "
            f"event_id={event_id}"
        )

        # Update appointment with Google Calendar event ID
        if event_id:
            await _update_appointment_gcal_id(appointment_id, event_id)

        return event_id

    except HttpError as e:
        logger.error(
            f"Google Calendar API error pushing appointment {appointment_id}: {e}",
            exc_info=True
        )
        return None
    except Exception as e:
        logger.error(
            f"Error pushing appointment {appointment_id} to Google Calendar: {e}",
            exc_info=True
        )
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
            f"Failed to update appointment {appointment_id} with gcal event ID: {e}",
            exc_info=True
        )


async def push_blocking_event_to_gcal(
    blocking_event_id: UUID,
    stylist_id: UUID,
    title: str,
    description: Optional[str],
    start_time: datetime,
    end_time: datetime,
    event_type: str = "general",
) -> Optional[str]:
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
        service = _get_calendar_service()

        def create_event():
            return service.events().insert(
                calendarId=calendar_id,
                body=event_body,
            ).execute()

        loop = asyncio.get_event_loop()
        event = await loop.run_in_executor(None, create_event)

        event_id = event.get("id")
        logger.info(
            f"Pushed blocking event {blocking_event_id} to Google Calendar: "
            f"event_id={event_id}"
        )

        # Update blocking event with Google Calendar event ID
        if event_id:
            await _update_blocking_event_gcal_id(blocking_event_id, event_id)

        return event_id

    except HttpError as e:
        logger.error(
            f"Google Calendar API error pushing blocking event {blocking_event_id}: {e}",
            exc_info=True
        )
        return None
    except Exception as e:
        logger.error(
            f"Error pushing blocking event {blocking_event_id} to Google Calendar: {e}",
            exc_info=True
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
            exc_info=True
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
        description = (
            f"Customer: {customer_name}\n"
            f"Services: {service_names}\n"
            f"Status: {status}\n"
            f"Appointment ID: {appointment_id}"
        )

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
        service = _get_calendar_service()

        def update_event():
            return service.events().patch(
                calendarId=calendar_id,
                eventId=event_id,
                body=update_body,
            ).execute()

        # Run in thread pool to not block the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, update_event)

        logger.info(
            f"Updated appointment {appointment_id} in Google Calendar: "
            f"event_id={event_id}"
        )
        return True

    except HttpError as e:
        if e.resp.status == 404:
            logger.warning(
                f"Appointment {appointment_id} not found in Google Calendar "
                f"(event_id={event_id}). Event may have been deleted externally."
            )
            return False
        logger.error(
            f"Google Calendar API error updating appointment {appointment_id}: {e}",
            exc_info=True
        )
        return False
    except Exception as e:
        logger.error(
            f"Error updating appointment {appointment_id} in Google Calendar: {e}",
            exc_info=True
        )
        return False


async def update_blocking_event_in_gcal(
    blocking_event_id: UUID,
    stylist_id: UUID,
    event_id: str,
    title: str,
    description: Optional[str],
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
        service = _get_calendar_service()

        def update_event():
            return service.events().patch(
                calendarId=calendar_id,
                eventId=event_id,
                body=update_body,
            ).execute()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, update_event)

        logger.info(
            f"Updated blocking event {blocking_event_id} in Google Calendar: "
            f"event_id={event_id}"
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
            exc_info=True
        )
        return False
    except Exception as e:
        logger.error(
            f"Error updating blocking event {blocking_event_id} in Google Calendar: {e}",
            exc_info=True
        )
        return False


async def delete_gcal_event(
    stylist_id: UUID,
    event_id: str,
) -> bool:
    """
    Delete an event from Google Calendar.

    Args:
        stylist_id: UUID of the stylist (to get calendar ID)
        event_id: Google Calendar event ID to delete

    Returns:
        True if deleted successfully, False otherwise
    """
    try:
        # Get stylist's calendar ID
        calendar_id = await _get_stylist_calendar_id(stylist_id)
        if not calendar_id:
            logger.warning(
                f"Cannot delete event {event_id}: "
                f"No calendar ID found for stylist {stylist_id}"
            )
            return False

        # Delete event from Google Calendar
        service = _get_calendar_service()

        def delete_event():
            service.events().delete(
                calendarId=calendar_id,
                eventId=event_id,
            ).execute()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, delete_event)

        logger.info(f"Deleted Google Calendar event: {event_id}")
        return True

    except HttpError as e:
        if e.resp.status == 404:
            logger.warning(f"Event {event_id} not found in Google Calendar (already deleted?)")
            return True  # Consider it deleted if not found
        logger.error(f"Google Calendar API error deleting event {event_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error deleting Google Calendar event {event_id}: {e}", exc_info=True)
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
    try:
        # Get stylist's calendar ID
        calendar_id = await _get_stylist_calendar_id(stylist_id)
        if not calendar_id:
            logger.warning(
                f"Cannot update event {event_id}: "
                f"No calendar ID found for stylist {stylist_id}"
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
        service = _get_calendar_service()
        loop = asyncio.get_event_loop()

        async def update_event_with_retry():
            def update_event():
                return service.events().patch(
                    calendarId=calendar_id,
                    eventId=event_id,
                    body={
                        "summary": summary,
                        "colorId": color_id,
                    },
                ).execute()
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
        )
    )
    logger.info(f"Scheduled fire-and-forget push for appointment {appointment_id}")


async def fire_and_forget_push_blocking_event(
    blocking_event_id: UUID,
    stylist_id: UUID,
    title: str,
    description: Optional[str],
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

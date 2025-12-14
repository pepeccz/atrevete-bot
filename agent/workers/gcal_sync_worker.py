"""
Google Calendar Sync Worker - Bidirectional sync between GCal and PostgreSQL.

This worker handles:
1. Sync GCal events -> BlockingEvents (create/update/delete)
2. Protect Appointments: Recreate in GCal if deleted externally

Architecture:
    - Runs every N minutes (configurable via system_settings)
    - Uses sync tokens for incremental sync (only changes since last sync)
    - Distinguishes between BlockingEvents and Appointments by google_calendar_event_id
    - Creates admin notifications for visibility

Event Classification:
    - Events WITH google_calendar_event_id in appointments table = Appointments (protected)
    - Events WITH google_calendar_event_id in blocking_events table = BlockingEvents (synced)
    - Events WITHOUT matching ID in either table = New external events -> Create BlockingEvent
"""

import asyncio
import json
import logging
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy import select, and_, delete, update
from sqlalchemy.orm import selectinload

from database.connection import get_async_session
from database.models import (
    Appointment,
    AppointmentStatus,
    BlockingEvent,
    BlockingEventType,
    GCalSyncState,
    Notification,
    NotificationType,
    Service,
    Stylist,
)
from shared.config import get_settings
from shared.settings_service import get_settings_service
from agent.services.gcal_push_service import (
    push_appointment_to_gcal,
    push_blocking_event_to_gcal,
)

# Configure logger
logger = logging.getLogger(__name__)

MADRID_TZ = ZoneInfo("Europe/Madrid")

# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_requested = True


# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


async def get_dynamic_settings() -> dict[str, Any]:
    """
    Load dynamic settings from database.

    Falls back to defaults if database is unavailable.

    Returns:
        Dict with setting values keyed by setting name.
    """
    try:
        settings_service = await get_settings_service()
        return {
            "gcal_sync_interval_minutes": await settings_service.get(
                "gcal_sync_interval_minutes", 5
            ),
            "gcal_sync_enabled": await settings_service.get("gcal_sync_enabled", True),
        }
    except Exception as e:
        logger.warning(f"Failed to load dynamic settings from DB, using defaults: {e}")
        return {
            "gcal_sync_interval_minutes": 5,
            "gcal_sync_enabled": True,
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
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        return build("calendar", "v3", credentials=credentials)
    except Exception as e:
        logger.error(f"Failed to create Google Calendar service: {e}")
        raise


async def create_notification(
    session,
    notification_type: NotificationType,
    title: str,
    message: str,
    entity_id: Optional[UUID] = None,
) -> None:
    """Create an admin panel notification."""
    try:
        notification = Notification(
            id=uuid4(),
            type=notification_type,
            title=title,
            message=message,
            entity_id=entity_id,
            is_read=False,
        )
        session.add(notification)
        await session.commit()
    except Exception as e:
        logger.error(f"Failed to create notification: {e}")


async def get_or_create_sync_state(
    session, stylist_id: UUID
) -> GCalSyncState:
    """Get or create sync state for a stylist."""
    result = await session.execute(
        select(GCalSyncState).where(GCalSyncState.stylist_id == stylist_id)
    )
    sync_state = result.scalar_one_or_none()

    if not sync_state:
        sync_state = GCalSyncState(
            id=uuid4(),
            stylist_id=stylist_id,
            sync_token=None,
            last_sync_at=None,
            events_synced=0,
        )
        session.add(sync_state)
        await session.commit()
        await session.refresh(sync_state)

    return sync_state


async def fetch_calendar_events(
    calendar_id: str,
    sync_token: Optional[str] = None,
) -> tuple[list[dict], Optional[str]]:
    """
    Fetch events from Google Calendar using sync token for incremental sync.

    Args:
        calendar_id: Google Calendar ID
        sync_token: Optional sync token from previous sync

    Returns:
        Tuple of (events list, new sync token)
    """
    service = _get_calendar_service()

    def _fetch():
        try:
            if sync_token:
                # Incremental sync - only changes since last sync
                request = service.events().list(
                    calendarId=calendar_id,
                    syncToken=sync_token,
                    showDeleted=True,  # Important: get deleted events too
                )
            else:
                # Full sync - get events from 7 days ago onwards to catch recent changes
                # NOTE: Don't use singleEvents=True as it prevents nextSyncToken from being returned
                time_min = (datetime.now(MADRID_TZ) - timedelta(days=7)).isoformat()
                request = service.events().list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    maxResults=500,
                )

            all_events = []
            while request:
                response = request.execute()
                all_events.extend(response.get("items", []))
                request = service.events().list_next(request, response)

            new_sync_token = response.get("nextSyncToken")
            logger.info(
                f"Calendar {calendar_id[-10:]}: fetched {len(all_events)} events, "
                f"has_sync_token={new_sync_token is not None}"
            )
            return all_events, new_sync_token

        except HttpError as e:
            if e.resp.status == 410:
                # Sync token expired, need full sync
                logger.warning(f"Sync token expired for {calendar_id}, doing full sync")
                return None, None
            raise

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _fetch)

    if result[0] is None:
        # Sync token expired, retry with full sync
        return await fetch_calendar_events(calendar_id, sync_token=None)

    return result


async def get_known_event_ids(session, stylist_id: UUID) -> tuple[set[str], set[str]]:
    """
    Get all known Google Calendar event IDs for a stylist.

    Returns:
        Tuple of (appointment_event_ids, blocking_event_ids)
    """
    # Get appointment event IDs
    result = await session.execute(
        select(Appointment.google_calendar_event_id).where(
            and_(
                Appointment.stylist_id == stylist_id,
                Appointment.google_calendar_event_id.is_not(None),
            )
        )
    )
    appointment_ids = {row[0] for row in result.all()}

    # Get blocking event IDs
    result = await session.execute(
        select(BlockingEvent.google_calendar_event_id).where(
            and_(
                BlockingEvent.stylist_id == stylist_id,
                BlockingEvent.google_calendar_event_id.is_not(None),
            )
        )
    )
    blocking_ids = {row[0] for row in result.all()}

    return appointment_ids, blocking_ids


async def process_gcal_event(
    session,
    stylist: Stylist,
    event: dict,
    appointment_event_ids: set[str],
    blocking_event_ids: set[str],
) -> tuple[str, Optional[str]]:
    """
    Process a single Google Calendar event.

    Returns:
        Tuple of (action_taken, error_message)
        action_taken: "created", "updated", "deleted", "recreated", "skipped"
    """
    event_id = event.get("id")
    status = event.get("status")  # "confirmed" or "cancelled"

    # Check if this is a known event
    is_appointment = event_id in appointment_event_ids
    is_blocking = event_id in blocking_event_ids
    is_deleted = status == "cancelled"

    if is_deleted:
        if is_appointment:
            # PROTECT: Recreate appointment in GCal
            return await recreate_appointment(session, stylist, event_id)
        elif is_blocking:
            # SYNC: Delete BlockingEvent from DB
            return await delete_blocking_event(session, stylist.id, event_id)
        else:
            # Unknown deleted event, ignore
            return "skipped", None

    # Event exists or was created
    if is_appointment:
        # Appointment exists, check if it was modified
        # For now, we don't sync appointment changes back to DB
        return "skipped", None
    elif is_blocking:
        # Update existing BlockingEvent
        return await update_blocking_event_from_gcal(session, stylist.id, event)
    else:
        # New external event - create BlockingEvent
        return await create_blocking_event_from_gcal(session, stylist.id, event)


async def recreate_appointment(
    session, stylist: Stylist, event_id: str
) -> tuple[str, Optional[str]]:
    """
    Recreate an appointment in Google Calendar that was deleted externally.

    Returns:
        Tuple of (action_taken, error_message)
    """
    try:
        # Find the appointment
        result = await session.execute(
            select(Appointment)
            .options(selectinload(Appointment.customer))
            .where(Appointment.google_calendar_event_id == event_id)
        )
        appointment = result.scalar_one_or_none()

        if not appointment:
            logger.warning(f"Appointment with gcal_id {event_id} not found in DB")
            return "skipped", "Appointment not found"

        # Only recreate if appointment is not cancelled
        if appointment.status == AppointmentStatus.CANCELLED:
            return "skipped", "Appointment already cancelled"

        # Get service names
        from database.models import Service

        result = await session.execute(
            select(Service).where(Service.id.in_(appointment.service_ids))
        )
        services = result.scalars().all()
        service_names = ", ".join([s.name for s in services])

        # Get customer name
        customer_name = (
            appointment.customer.first_name + " " + appointment.customer.last_name
            if appointment.customer
            else appointment.first_name or "Cliente"
        )

        # Recreate in Google Calendar
        new_event_id = await push_appointment_to_gcal(
            appointment_id=appointment.id,
            stylist_id=appointment.stylist_id,
            customer_name=customer_name,
            service_names=service_names,
            start_time=appointment.start_time,
            duration_minutes=appointment.duration_minutes,
            status=appointment.status.value if appointment.status else "pending",
            customer_phone=appointment.customer.phone if appointment.customer else None,
        )

        if new_event_id:
            # Update appointment with new event ID
            appointment.google_calendar_event_id = new_event_id
            await session.commit()

            logger.info(
                f"Recreated appointment {appointment.id} in GCal: {new_event_id}"
            )
            return "recreated", None
        else:
            return "error", "Failed to recreate in GCal"

    except Exception as e:
        logger.error(f"Error recreating appointment: {e}", exc_info=True)
        return "error", str(e)


async def delete_blocking_event(
    session, stylist_id: UUID, event_id: str
) -> tuple[str, Optional[str]]:
    """
    Delete a BlockingEvent from DB when deleted in GCal.

    Returns:
        Tuple of (action_taken, error_message)
    """
    try:
        result = await session.execute(
            select(BlockingEvent).where(
                and_(
                    BlockingEvent.stylist_id == stylist_id,
                    BlockingEvent.google_calendar_event_id == event_id,
                )
            )
        )
        blocking_event = result.scalar_one_or_none()

        if not blocking_event:
            return "skipped", "BlockingEvent not found"

        await session.delete(blocking_event)
        await session.commit()

        logger.info(f"Deleted BlockingEvent {blocking_event.id} (gcal: {event_id})")
        return "deleted", None

    except Exception as e:
        logger.error(f"Error deleting blocking event: {e}", exc_info=True)
        await session.rollback()
        return "error", str(e)


async def update_blocking_event_from_gcal(
    session, stylist_id: UUID, event: dict
) -> tuple[str, Optional[str]]:
    """
    Update a BlockingEvent from GCal changes.

    Returns:
        Tuple of (action_taken, error_message)
    """
    try:
        event_id = event.get("id")

        result = await session.execute(
            select(BlockingEvent).where(
                and_(
                    BlockingEvent.stylist_id == stylist_id,
                    BlockingEvent.google_calendar_event_id == event_id,
                )
            )
        )
        blocking_event = result.scalar_one_or_none()

        if not blocking_event:
            return "skipped", "BlockingEvent not found"

        # Parse event times
        start = event.get("start", {})
        end = event.get("end", {})

        start_time = parse_gcal_datetime(start)
        end_time = parse_gcal_datetime(end)

        if not start_time or not end_time:
            return "skipped", "Could not parse event times"

        # Update fields
        blocking_event.title = event.get("summary", "Bloqueo")
        blocking_event.description = event.get("description")
        blocking_event.start_time = start_time
        blocking_event.end_time = end_time

        await session.commit()

        logger.info(f"Updated BlockingEvent {blocking_event.id} from GCal")
        return "updated", None

    except Exception as e:
        logger.error(f"Error updating blocking event: {e}", exc_info=True)
        await session.rollback()
        return "error", str(e)


async def create_blocking_event_from_gcal(
    session, stylist_id: UUID, event: dict
) -> tuple[str, Optional[str]]:
    """
    Create a new BlockingEvent from an external GCal event.

    Returns:
        Tuple of (action_taken, error_message)
    """
    try:
        event_id = event.get("id")

        # Parse event times
        start = event.get("start", {})
        end = event.get("end", {})

        start_time = parse_gcal_datetime(start)
        end_time = parse_gcal_datetime(end)

        if not start_time or not end_time:
            return "skipped", "Could not parse event times"

        # Skip all-day events or events too far in the past
        if start_time < datetime.now(MADRID_TZ) - timedelta(days=1):
            return "skipped", "Event in the past"

        # Create new BlockingEvent
        blocking_event = BlockingEvent(
            id=uuid4(),
            stylist_id=stylist_id,
            title=event.get("summary", "Bloqueo externo"),
            description=event.get("description"),
            start_time=start_time,
            end_time=end_time,
            event_type=BlockingEventType.GENERAL,
            google_calendar_event_id=event_id,
        )

        session.add(blocking_event)
        await session.commit()

        logger.info(
            f"Created BlockingEvent {blocking_event.id} from GCal event {event_id}"
        )
        return "created", None

    except Exception as e:
        logger.error(f"Error creating blocking event: {e}", exc_info=True)
        await session.rollback()
        return "error", str(e)


def parse_gcal_datetime(dt_dict: dict) -> Optional[datetime]:
    """Parse Google Calendar datetime dict to datetime object."""
    if not dt_dict:
        return None

    if "dateTime" in dt_dict:
        # Specific time event
        dt_str = dt_dict["dateTime"]
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            return dt.astimezone(MADRID_TZ)
        except Exception:
            return None
    elif "date" in dt_dict:
        # All-day event
        try:
            d = datetime.strptime(dt_dict["date"], "%Y-%m-%d")
            return d.replace(tzinfo=MADRID_TZ)
        except Exception:
            return None

    return None


async def sync_stylist_calendar(
    session, stylist: Stylist
) -> dict[str, int]:
    """
    Sync a single stylist's Google Calendar.

    Returns:
        Dict with counts: created, updated, deleted, recreated, errors
    """
    stats = {
        "created": 0,
        "updated": 0,
        "deleted": 0,
        "recreated": 0,
        "skipped": 0,
        "errors": 0,
    }

    try:
        # Get sync state
        sync_state = await get_or_create_sync_state(session, stylist.id)

        # Fetch events from GCal
        events, new_sync_token = await fetch_calendar_events(
            stylist.google_calendar_id,
            sync_state.sync_token,
        )

        if not events:
            # No changes, but still save sync token for incremental sync
            if new_sync_token:
                sync_state.sync_token = new_sync_token
            sync_state.last_sync_at = datetime.now(MADRID_TZ)
            await session.commit()
            return stats

        # Get known event IDs
        appointment_ids, blocking_ids = await get_known_event_ids(session, stylist.id)

        # Process each event
        for event in events:
            action, error = await process_gcal_event(
                session, stylist, event, appointment_ids, blocking_ids
            )
            if action in stats:
                stats[action] += 1
            if error:
                stats["errors"] += 1

        # Update sync state
        sync_state.sync_token = new_sync_token
        sync_state.last_sync_at = datetime.now(MADRID_TZ)
        sync_state.events_synced += len(events)
        sync_state.last_error = None
        await session.commit()

        return stats

    except Exception as e:
        logger.error(
            f"Error syncing calendar for stylist {stylist.name}: {e}", exc_info=True
        )
        # Update sync state with error
        try:
            sync_state = await get_or_create_sync_state(session, stylist.id)
            sync_state.last_error = str(e)
            await session.commit()
        except Exception:
            pass
        stats["errors"] += 1
        return stats


async def recover_missing_gcal_pushes(session) -> dict[str, int]:
    """
    Find appointments and blocking_events that were never pushed to GCal
    (google_calendar_event_id is NULL) and push them.

    This is different from recreate_appointment() which handles events that
    were deleted externally from Google Calendar. This function handles cases
    where the initial push failed (timeout, rate limit, etc.) and the event
    was never created in GCal.

    Returns:
        Dict with counts: appointments_recovered, blocking_events_recovered, errors
    """
    stats = {"appointments_recovered": 0, "blocking_events_recovered": 0, "errors": 0}

    # =========================================================================
    # Recover Appointments
    # =========================================================================
    try:
        # Find appointments without GCal event ID (created in last 7 days, not cancelled)
        query = (
            select(Appointment)
            .options(selectinload(Appointment.customer))
            .where(
                and_(
                    Appointment.google_calendar_event_id.is_(None),
                    Appointment.status.in_(
                        [AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED]
                    ),
                    Appointment.created_at > datetime.now(MADRID_TZ) - timedelta(days=7),
                )
            )
        )
        result = await session.execute(query)
        appointments = result.scalars().all()

        if appointments:
            logger.info(f"Found {len(appointments)} appointments without GCal event ID")

        for appointment in appointments:
            try:
                # Get service names
                services_result = await session.execute(
                    select(Service).where(Service.id.in_(appointment.service_ids))
                )
                services = services_result.scalars().all()
                service_names = ", ".join([s.name for s in services]) if services else "Servicio"

                # Get customer name
                customer_name = (
                    appointment.first_name
                    or (appointment.customer.first_name if appointment.customer else None)
                    or "Cliente"
                )

                # Get customer phone
                customer_phone = (
                    appointment.customer.phone if appointment.customer else None
                )

                # Push to Google Calendar
                event_id = await push_appointment_to_gcal(
                    appointment_id=appointment.id,
                    stylist_id=appointment.stylist_id,
                    customer_name=customer_name,
                    service_names=service_names,
                    start_time=appointment.start_time,
                    duration_minutes=appointment.duration_minutes,
                    status=appointment.status.value,
                    customer_phone=customer_phone,
                )

                if event_id:
                    appointment.google_calendar_event_id = event_id
                    await session.commit()
                    stats["appointments_recovered"] += 1
                    logger.info(
                        f"Recovered appointment {appointment.id} → GCal event {event_id}"
                    )
                else:
                    stats["errors"] += 1
                    logger.warning(
                        f"Failed to recover appointment {appointment.id} - push returned None"
                    )

            except Exception as e:
                stats["errors"] += 1
                logger.error(
                    f"Error recovering appointment {appointment.id}: {e}", exc_info=True
                )

    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Error querying appointments for recovery: {e}", exc_info=True)

    # =========================================================================
    # Recover Blocking Events
    # =========================================================================
    try:
        # Find blocking events without GCal event ID (created in last 7 days)
        query = select(BlockingEvent).where(
            and_(
                BlockingEvent.google_calendar_event_id.is_(None),
                BlockingEvent.created_at > datetime.now(MADRID_TZ) - timedelta(days=7),
            )
        )
        result = await session.execute(query)
        blocking_events = result.scalars().all()

        if blocking_events:
            logger.info(
                f"Found {len(blocking_events)} blocking events without GCal event ID"
            )

        for event in blocking_events:
            try:
                # Push to Google Calendar
                event_id = await push_blocking_event_to_gcal(
                    blocking_event_id=event.id,
                    stylist_id=event.stylist_id,
                    title=event.title,
                    description=event.description,
                    start_time=event.start_time,
                    end_time=event.end_time,
                    event_type=event.event_type.value,
                )

                if event_id:
                    event.google_calendar_event_id = event_id
                    await session.commit()
                    stats["blocking_events_recovered"] += 1
                    logger.info(
                        f"Recovered blocking event {event.id} → GCal event {event_id}"
                    )
                else:
                    stats["errors"] += 1
                    logger.warning(
                        f"Failed to recover blocking event {event.id} - push returned None"
                    )

            except Exception as e:
                stats["errors"] += 1
                logger.error(
                    f"Error recovering blocking event {event.id}: {e}", exc_info=True
                )

    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Error querying blocking events for recovery: {e}", exc_info=True)

    return stats


async def run_gcal_sync() -> None:
    """
    Main sync job - syncs all stylist calendars.
    """
    # Check if sync is enabled
    dynamic_settings = await get_dynamic_settings()
    if not dynamic_settings.get("gcal_sync_enabled", True):
        logger.info("GCal sync is disabled, skipping")
        return

    now = datetime.now(MADRID_TZ)
    start_time = now
    logger.info(f"Starting GCal sync job at {now.isoformat()}")

    total_stats = {
        "created": 0,
        "updated": 0,
        "deleted": 0,
        "recreated": 0,
        "skipped": 0,
        "errors": 0,
        "stylists_synced": 0,
        "appointments_recovered": 0,
        "blocking_events_recovered": 0,
    }

    try:
        async with get_async_session() as session:
            # Step 1: Recover any failed pushes (appointments/blocking events without GCal ID)
            try:
                recovery_stats = await recover_missing_gcal_pushes(session)
                total_stats["appointments_recovered"] = recovery_stats["appointments_recovered"]
                total_stats["blocking_events_recovered"] = recovery_stats["blocking_events_recovered"]
                total_stats["errors"] += recovery_stats["errors"]

                if recovery_stats["appointments_recovered"] > 0 or recovery_stats["blocking_events_recovered"] > 0:
                    logger.info(
                        f"Recovery complete: appointments={recovery_stats['appointments_recovered']}, "
                        f"blocking_events={recovery_stats['blocking_events_recovered']}"
                    )
            except Exception as e:
                logger.error(f"Error in recovery phase: {e}", exc_info=True)
                total_stats["errors"] += 1

            # Step 2: Get all active stylists for bidirectional sync
            result = await session.execute(
                select(Stylist).where(Stylist.is_active == True)
            )
            stylists = list(result.scalars().all())

            if not stylists:
                logger.info("No active stylists to sync")
                return

            logger.info(f"Syncing {len(stylists)} stylist calendars")

            for stylist in stylists:
                try:
                    stats = await sync_stylist_calendar(session, stylist)
                    for key, value in stats.items():
                        if key in total_stats:
                            total_stats[key] += value
                    total_stats["stylists_synced"] += 1

                    # Log individual stylist stats if there were changes
                    changes = stats["created"] + stats["updated"] + stats["deleted"] + stats["recreated"]
                    if changes > 0:
                        logger.info(
                            f"Synced {stylist.name}: "
                            f"created={stats['created']}, updated={stats['updated']}, "
                            f"deleted={stats['deleted']}, recreated={stats['recreated']}"
                        )

                except Exception as e:
                    logger.error(
                        f"Error syncing stylist {stylist.name}: {e}", exc_info=True
                    )
                    total_stats["errors"] += 1

    except Exception as e:
        logger.exception(f"Critical error in run_gcal_sync: {e}")
        total_stats["errors"] += 1

    # Log summary
    duration = (datetime.now(MADRID_TZ) - start_time).total_seconds()
    logger.info(
        f"Completed GCal sync in {duration:.2f}s: "
        f"stylists={total_stats['stylists_synced']}, "
        f"created={total_stats['created']}, updated={total_stats['updated']}, "
        f"deleted={total_stats['deleted']}, recreated={total_stats['recreated']}, "
        f"recovered_appts={total_stats['appointments_recovered']}, "
        f"recovered_blocks={total_stats['blocking_events_recovered']}, "
        f"errors={total_stats['errors']}"
    )

    # Update health check
    await update_health_check(
        last_run=datetime.now(MADRID_TZ),
        status="healthy" if total_stats["errors"] == 0 else "unhealthy",
        stats=total_stats,
    )


async def update_health_check(
    last_run: datetime,
    status: str,
    stats: dict[str, int],
) -> None:
    """
    Update health check file with job statistics.
    """
    health_dir = Path("/tmp/health")
    health_dir.mkdir(parents=True, exist_ok=True)
    health_file = health_dir / "gcal_sync_worker_health.json"
    temp_file = health_dir / f"gcal_sync_worker_health.{int(time.time())}.tmp"

    health_data = {
        "last_run": last_run.isoformat(),
        "status": status,
        "stylists_synced": stats.get("stylists_synced", 0),
        "events_created": stats.get("created", 0),
        "events_updated": stats.get("updated", 0),
        "events_deleted": stats.get("deleted", 0),
        "appointments_recreated": stats.get("recreated", 0),
        "appointments_recovered": stats.get("appointments_recovered", 0),
        "blocking_events_recovered": stats.get("blocking_events_recovered", 0),
        "errors": stats.get("errors", 0),
        "last_updated": datetime.now(MADRID_TZ).isoformat(),
    }

    try:
        temp_file.write_text(json.dumps(health_data, indent=2))
        temp_file.rename(health_file)
        logger.debug(f"Health check file updated: {health_file}")
    except Exception as e:
        logger.error(f"Failed to write health check file: {e}", exc_info=True)


async def async_main() -> None:
    """
    Main async entry point - runs GCal sync on schedule using a single event loop.

    IMPORTANT: Uses asyncio.sleep() instead of schedule + asyncio.run() to avoid
    event loop corruption. Each asyncio.run() creates a new event loop, but
    SQLAlchemy's asyncpg connections keep references to the previous loop,
    causing "Future attached to a different loop" errors.

    Handles graceful shutdown on SIGTERM/SIGINT.
    """
    global shutdown_requested

    # Load dynamic settings
    dynamic_settings = await get_dynamic_settings()
    sync_interval = dynamic_settings.get("gcal_sync_interval_minutes", 5)

    logger.info("GCal sync worker starting...")
    logger.info(f"Configuration: sync_interval={sync_interval} minutes")

    # Write initial health check
    await update_health_check(
        last_run=datetime.now(MADRID_TZ),
        status="starting",
        stats={},
    )

    # Run once immediately on startup
    logger.info("Running initial sync...")
    await run_gcal_sync()

    logger.info(f"GCal sync worker scheduled: every {sync_interval} minutes")

    # Main loop with asyncio.sleep (single event loop, no schedule library)
    while not shutdown_requested:
        # Sleep for sync_interval minutes (checking shutdown flag every 30s)
        sleep_seconds = sync_interval * 60
        for _ in range(sleep_seconds // 30):
            if shutdown_requested:
                break
            await asyncio.sleep(30)

        if shutdown_requested:
            break

        # Reload settings in case they changed
        try:
            dynamic_settings = await get_dynamic_settings()
            new_interval = dynamic_settings.get("gcal_sync_interval_minutes", 5)
            if new_interval != sync_interval:
                logger.info(f"Sync interval changed: {sync_interval} -> {new_interval} minutes")
                sync_interval = new_interval
        except Exception as e:
            logger.warning(f"Failed to reload settings: {e}")

        # Run sync
        await run_gcal_sync()

    logger.info("GCal sync worker shutting down gracefully...")


def run_gcal_sync_worker() -> None:
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
    run_gcal_sync_worker()

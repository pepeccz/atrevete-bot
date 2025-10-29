"""
Google Calendar tools for availability checking and event management.

This module provides LangChain tools for:
- Querying available time slots by service category
- Creating calendar events (provisional/confirmed)
- Deleting calendar events
- Holiday detection across all calendars
- Rate limit handling with exponential backoff

All tools use Google Calendar API with service account authentication
and Europe/Madrid timezone for all datetime operations.
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import select
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from zoneinfo import ZoneInfo

from database.connection import get_async_session
from database.models import ServiceCategory, Stylist
from shared.config import get_settings

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

TIMEZONE = ZoneInfo("Europe/Madrid")

# Business hours (hour only, 24-hour format)
BUSINESS_HOURS = {
    "weekday": {"start": 10, "end": 20},  # Monday-Friday 10:00-20:00
    "saturday": {"start": 10, "end": 14},  # Saturday 10:00-14:00
}

# Slot duration in minutes
SLOT_DURATION_MINUTES = 30

# Holiday detection keywords
HOLIDAY_KEYWORDS = ["Festivo", "Cerrado", "Vacaciones"]

# Event color codes
EVENT_COLORS = {
    "provisional": "5",  # Yellow
    "confirmed": "10",   # Green
}


# ============================================================================
# Pydantic Schemas for Tool Parameters
# ============================================================================


class GetCalendarAvailabilitySchema(BaseModel):
    """Schema for getting calendar availability."""

    category: str = Field(
        description="Service category: 'Hairdressing', 'Aesthetics', or 'Both'"
    )
    date: str = Field(
        description="Date to check availability in YYYY-MM-DD format"
    )
    conversation_id: str = Field(
        default="", description="Conversation ID for logging traceability"
    )


class CreateCalendarEventSchema(BaseModel):
    """Schema for creating a calendar event."""

    stylist_id: str = Field(description="Stylist UUID as string")
    start_time: str = Field(
        description="Start time in ISO 8601 format (e.g., '2025-01-15T10:00:00+01:00')"
    )
    duration_minutes: int = Field(description="Duration in minutes")
    customer_name: str = Field(description="Customer full name")
    service_names: str = Field(description="Service names (comma-separated if multiple)")
    status: str = Field(
        default="provisional",
        description="Event status: 'provisional' or 'confirmed'"
    )
    appointment_id: str = Field(
        default="", description="Appointment UUID for metadata"
    )
    customer_id: str = Field(
        default="", description="Customer UUID for metadata"
    )
    conversation_id: str = Field(
        default="", description="Conversation ID for logging traceability"
    )


class DeleteCalendarEventSchema(BaseModel):
    """Schema for deleting a calendar event."""

    stylist_id: str = Field(description="Stylist UUID as string")
    event_id: str = Field(description="Google Calendar event ID")
    conversation_id: str = Field(
        default="", description="Conversation ID for logging traceability"
    )


# ============================================================================
# Calendar Client Initialization
# ============================================================================


class CalendarTools:
    """
    Google Calendar API client wrapper.

    Initializes service account authentication and provides
    access to Google Calendar API with automatic credential loading.

    Usage:
        tools = CalendarTools()
        service = tools.get_service()
        events = service.events().list(calendarId='...').execute()
    """

    def __init__(self):
        """Initialize Google Calendar API client with service account credentials."""
        settings = get_settings()

        try:
            # Load service account credentials from JSON file
            credentials = service_account.Credentials.from_service_account_file(
                settings.GOOGLE_SERVICE_ACCOUNT_JSON,
                scopes=["https://www.googleapis.com/auth/calendar"]
            )

            # Build Calendar API service
            self.service = build("calendar", "v3", credentials=credentials)

            logger.info("Google Calendar API client initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Google Calendar API client: {e}")
            raise

    def get_service(self):
        """Get the Calendar API service instance."""
        return self.service


# Global calendar client instance
_calendar_client: CalendarTools | None = None


def get_calendar_client() -> CalendarTools:
    """
    Get or create global CalendarTools instance.

    Returns:
        CalendarTools: Singleton calendar client instance
    """
    global _calendar_client
    if _calendar_client is None:
        _calendar_client = CalendarTools()
    return _calendar_client


# ============================================================================
# Helper Functions
# ============================================================================


async def get_stylists_by_category(category: str) -> list[Stylist]:
    """
    Query active stylists filtered by service category.

    Args:
        category: Service category ('Hairdressing', 'Aesthetics', or 'Both')

    Returns:
        List of active Stylist model instances
    """
    try:
        # Convert string to ServiceCategory enum
        service_category = ServiceCategory(category)
    except ValueError:
        logger.error(f"Invalid service category: {category}")
        return []

    async with get_async_session() as session:
        try:
            # Query stylists matching category or 'Both'
            query = select(Stylist).where(
                Stylist.is_active == True,
                Stylist.category.in_([service_category, ServiceCategory.BOTH])
            )

            result = await session.execute(query)
            stylists = list(result.scalars().all())

            logger.info(
                f"Found {len(stylists)} active stylists for category {category}"
            )
            return stylists

        except Exception as e:
            logger.error(f"Database error querying stylists: {e}")
            return []


async def get_stylist_by_id(stylist_id: UUID) -> Stylist | None:
    """
    Query stylist by UUID.

    Args:
        stylist_id: Stylist UUID

    Returns:
        Stylist model instance or None if not found
    """
    async with get_async_session() as session:
        try:
            query = select(Stylist).where(Stylist.id == stylist_id)
            result = await session.execute(query)
            stylist = result.scalar_one_or_none()

            if stylist:
                logger.info(f"Found stylist: {stylist.name} ({stylist_id})")
            else:
                logger.warning(f"Stylist not found: {stylist_id}")

            return stylist

        except Exception as e:
            logger.error(f"Database error querying stylist: {e}")
            return None


def generate_time_slots(date: datetime, day_of_week: int) -> list[datetime]:
    """
    Generate available time slots for a given date based on business hours.

    Args:
        date: Date to generate slots for (timezone-aware)
        day_of_week: Day of week (0=Monday, 6=Sunday)

    Returns:
        List of datetime objects representing slot start times
    """
    slots = []

    # Sunday is closed
    if day_of_week == 6:
        return slots

    # Determine business hours based on day of week
    if day_of_week == 5:  # Saturday
        hours_config = BUSINESS_HOURS["saturday"]
    else:  # Monday-Friday
        hours_config = BUSINESS_HOURS["weekday"]

    # Generate slots in 30-minute increments
    start_hour = hours_config["start"]
    end_hour = hours_config["end"]

    current_time = date.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    end_time = date.replace(hour=end_hour, minute=0, second=0, microsecond=0)

    while current_time < end_time:
        slots.append(current_time)
        current_time += timedelta(minutes=SLOT_DURATION_MINUTES)

    return slots


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(HttpError),
)
def fetch_calendar_events(
    service,
    calendar_id: str,
    time_min: str,
    time_max: str
) -> list[dict[str, Any]]:
    """
    Fetch calendar events with automatic retry on rate limit errors.

    Args:
        service: Google Calendar API service instance
        calendar_id: Google Calendar ID
        time_min: Start time in RFC3339 format
        time_max: End time in RFC3339 format

    Returns:
        List of event dictionaries

    Raises:
        HttpError: After 3 failed retry attempts
    """
    try:
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        return events_result.get("items", [])

    except HttpError as e:
        logger.warning(f"HTTP error fetching calendar events: {e}")
        raise


async def check_holiday_closure(
    service,
    date: datetime,
    conversation_id: str = ""
) -> dict[str, Any] | None:
    """
    Check if salon is closed due to holiday across ALL stylist calendars.

    Args:
        service: Google Calendar API service instance
        date: Date to check (timezone-aware)
        conversation_id: For logging traceability

    Returns:
        Dictionary with holiday info if detected, None otherwise
        Example: {"holiday_detected": true, "reason": "Festivo - Navidad"}
    """
    # Query ALL active stylists (regardless of category)
    async with get_async_session() as session:
        try:
            query = select(Stylist).where(Stylist.is_active == True)
            result = await session.execute(query)
            all_stylists = list(result.scalars().all())

        except Exception as e:
            logger.error(
                f"Database error querying all stylists | conversation_id={conversation_id}: {e}"
            )
            return None

    # Prepare time range for the entire day
    time_min = date.replace(hour=0, minute=0, second=0, microsecond=0)
    time_max = date.replace(hour=23, minute=59, second=59, microsecond=999999)

    time_min_str = time_min.isoformat()
    time_max_str = time_max.isoformat()

    # Check each calendar for holiday events
    for stylist in all_stylists:
        try:
            events = fetch_calendar_events(
                service,
                stylist.google_calendar_id,
                time_min_str,
                time_max_str
            )

            # Check each event for holiday keywords
            for event in events:
                summary = event.get("summary", "")

                # Check if any holiday keyword is present
                for keyword in HOLIDAY_KEYWORDS:
                    if keyword.lower() in summary.lower():
                        logger.info(
                            f"Holiday detected in {stylist.name}'s calendar: {summary} | "
                            f"conversation_id={conversation_id}"
                        )
                        return {
                            "holiday_detected": True,
                            "reason": summary,
                            "calendar": stylist.name
                        }

        except HttpError as e:
            if e.resp.status == 429:
                logger.error(
                    f"Rate limit exceeded after retries for {stylist.name} | "
                    f"conversation_id={conversation_id}"
                )
            else:
                logger.error(
                    f"Error checking calendar for {stylist.name} | "
                    f"conversation_id={conversation_id}: {e}"
                )
            # Continue checking other calendars even if one fails
            continue

        except Exception as e:
            logger.error(
                f"Unexpected error checking calendar for {stylist.name} | "
                f"conversation_id={conversation_id}: {e}"
            )
            continue

    return None


def is_slot_available(
    slot_time: datetime,
    busy_events: list[dict[str, Any]]
) -> bool:
    """
    Check if a time slot is available (not overlapping with busy events).

    Args:
        slot_time: Slot start time (timezone-aware)
        busy_events: List of busy event dictionaries from Calendar API

    Returns:
        True if slot is available, False if busy
    """
    slot_end = slot_time + timedelta(minutes=SLOT_DURATION_MINUTES)

    for event in busy_events:
        # Parse event start and end times
        event_start_str = event.get("start", {}).get("dateTime")
        event_end_str = event.get("end", {}).get("dateTime")

        if not event_start_str or not event_end_str:
            continue

        try:
            event_start = datetime.fromisoformat(event_start_str.replace("Z", "+00:00"))
            event_end = datetime.fromisoformat(event_end_str.replace("Z", "+00:00"))

            # Check for overlap: slot overlaps if it starts before event ends
            # and ends after event starts
            if slot_time < event_end and slot_end > event_start:
                return False

        except Exception as e:
            logger.warning(f"Error parsing event time: {e}")
            continue

    return True


# ============================================================================
# LangChain Tools
# ============================================================================


@tool(args_schema=GetCalendarAvailabilitySchema)
async def get_calendar_availability(
    category: str,
    date: str,
    conversation_id: str = ""
) -> dict[str, Any]:
    """
    Get available time slots for a service category on a specific date.

    Checks availability across all stylists who provide the requested service category.
    Respects business hours, busy events, and salon holiday closures.

    Args:
        category: Service category ('Hairdressing', 'Aesthetics', or 'Both')
        date: Date in YYYY-MM-DD format
        conversation_id: For logging traceability

    Returns:
        Dictionary with:
        - success: bool
        - available_slots: List of dicts with {time, stylist_id, stylist_name}
        - holiday_detected: bool (if salon is closed)
        - error: str (if failed)

    Example:
        {
            "success": true,
            "available_slots": [
                {"time": "10:00", "stylist_id": "uuid", "stylist_name": "Pilar"},
                {"time": "10:30", "stylist_id": "uuid", "stylist_name": "Pilar"}
            ]
        }
    """
    try:
        # Parse date string to datetime
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=TIMEZONE)
        except ValueError:
            return {
                "success": False,
                "error": f"Invalid date format: {date}. Expected YYYY-MM-DD"
            }

        # Get calendar client
        calendar_client = get_calendar_client()
        service = calendar_client.get_service()

        # Check for holiday closure across ALL calendars
        holiday_info = await check_holiday_closure(service, target_date, conversation_id)
        if holiday_info:
            return {
                "success": True,
                "available_slots": [],
                "holiday_detected": True,
                "reason": holiday_info.get("reason", "Salon closed"),
                "calendar": holiday_info.get("calendar", "")
            }

        # Query stylists for the requested category
        stylists = await get_stylists_by_category(category)

        if not stylists:
            return {
                "success": False,
                "error": f"No active stylists found for category: {category}"
            }

        # Generate time slots based on business hours
        day_of_week = target_date.weekday()
        time_slots = generate_time_slots(target_date, day_of_week)

        if not time_slots:
            return {
                "success": True,
                "available_slots": [],
                "reason": "Salon closed on this day"
            }

        # Prepare time range for API query
        time_min = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        time_max = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)

        time_min_str = time_min.isoformat()
        time_max_str = time_max.isoformat()

        # Collect available slots
        available_slots = []

        for stylist in stylists:
            try:
                # Fetch busy events for this stylist
                busy_events = fetch_calendar_events(
                    service,
                    stylist.google_calendar_id,
                    time_min_str,
                    time_max_str
                )

                # Check each time slot for availability
                for slot_time in time_slots:
                    if is_slot_available(slot_time, busy_events):
                        available_slots.append({
                            "time": slot_time.strftime("%H:%M"),
                            "stylist_id": str(stylist.id),
                            "stylist_name": stylist.name
                        })

            except RetryError as e:
                # Retry error means we exceeded max attempts (rate limit)
                logger.error(
                    f"Rate limit exceeded after 3 retries for {stylist.name} | "
                    f"conversation_id={conversation_id}"
                )
                return {
                    "success": False,
                    "error": "Rate limit exceeded after 3 retries. Please try again later."
                }

            except HttpError as e:
                logger.error(
                    f"HTTP error fetching calendar for {stylist.name} | "
                    f"conversation_id={conversation_id}: {e}"
                )
                continue

            except Exception as e:
                logger.error(
                    f"Error checking availability for {stylist.name} | "
                    f"conversation_id={conversation_id}: {e}"
                )
                continue

        logger.info(
            f"Found {len(available_slots)} available slots for {category} on {date} | "
            f"conversation_id={conversation_id}"
        )

        return {
            "success": True,
            "available_slots": available_slots
        }

    except Exception as e:
        logger.error(
            f"Unexpected error in get_calendar_availability | "
            f"conversation_id={conversation_id}: {e}"
        )
        return {
            "success": False,
            "error": f"Internal error: {str(e)}"
        }


@tool(args_schema=CreateCalendarEventSchema)
async def create_calendar_event(
    stylist_id: str,
    start_time: str,
    duration_minutes: int,
    customer_name: str,
    service_names: str,
    status: str = "provisional",
    appointment_id: str = "",
    customer_id: str = "",
    conversation_id: str = ""
) -> dict[str, Any]:
    """
    Create a calendar event for an appointment.

    Args:
        stylist_id: Stylist UUID as string
        start_time: Start time in ISO 8601 format
        duration_minutes: Duration in minutes
        customer_name: Customer full name
        service_names: Service names (comma-separated if multiple)
        status: 'provisional' or 'confirmed'
        appointment_id: Appointment UUID for metadata
        customer_id: Customer UUID for metadata
        conversation_id: For logging traceability

    Returns:
        Dictionary with:
        - success: bool
        - event_id: str (Google Calendar event ID)
        - calendar_id: str
        - start_time: str
        - end_time: str
        - error: str (if failed)
    """
    try:
        # Parse stylist UUID
        try:
            stylist_uuid = UUID(stylist_id)
        except ValueError:
            return {
                "success": False,
                "error": f"Invalid stylist_id UUID format: {stylist_id}"
            }

        # Query stylist to get google_calendar_id
        stylist = await get_stylist_by_id(stylist_uuid)
        if not stylist:
            return {
                "success": False,
                "error": f"Stylist not found: {stylist_id}"
            }

        # Parse start time
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            return {
                "success": False,
                "error": f"Invalid start_time format: {start_time}. Expected ISO 8601"
            }

        # Calculate end time
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        # Build event summary based on status
        if status == "provisional":
            summary = f"[PROVISIONAL] {customer_name} - {service_names}"
        else:
            summary = f"{customer_name} - {service_names}"

        # Build event description with metadata
        description_parts = [
            f"Customer: {customer_name}",
            f"Services: {service_names}",
            f"Status: {status}"
        ]

        if appointment_id:
            description_parts.append(f"Appointment ID: {appointment_id}")
        if customer_id:
            description_parts.append(f"Customer ID: {customer_id}")

        description = "\n".join(description_parts)

        # Determine color based on status
        color_id = EVENT_COLORS.get(status, EVENT_COLORS["provisional"])

        # Build event body
        event_body = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": "Europe/Madrid"
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": "Europe/Madrid"
            },
            "colorId": color_id
        }

        # Get calendar client
        calendar_client = get_calendar_client()
        service = calendar_client.get_service()

        # Create event with retry logic
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=4),
            retry=retry_if_exception_type(HttpError),
        )
        def create_event():
            return service.events().insert(
                calendarId=stylist.google_calendar_id,
                body=event_body
            ).execute()

        try:
            created_event = create_event()
        except RetryError as e:
            # Check the cause of the retry error
            if e.last_attempt.exception():
                original_error = e.last_attempt.exception()
                if isinstance(original_error, HttpError):
                    if original_error.resp.status == 429:
                        logger.error(
                            f"Rate limit exceeded after 3 retries creating event | "
                            f"conversation_id={conversation_id}"
                        )
                        return {
                            "success": False,
                            "error": "Rate limit exceeded after 3 retries. Please try again later."
                        }

            # Generic retry error
            logger.error(
                f"Failed to create event after retries | "
                f"conversation_id={conversation_id}: {e}"
            )
            return {
                "success": False,
                "error": "Failed to create calendar event after retries."
            }

        except HttpError as e:
            logger.error(
                f"HTTP error creating calendar event | "
                f"conversation_id={conversation_id}: {e}"
            )
            return {
                "success": False,
                "error": f"Failed to create calendar event: {str(e)}"
            }

        logger.info(
            f"Created {status} calendar event for {customer_name} with {stylist.name} | "
            f"event_id={created_event['id']} | conversation_id={conversation_id}"
        )

        return {
            "success": True,
            "event_id": created_event["id"],
            "calendar_id": stylist.google_calendar_id,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "summary": summary
        }

    except Exception as e:
        logger.error(
            f"Unexpected error in create_calendar_event | "
            f"conversation_id={conversation_id}: {e}"
        )
        return {
            "success": False,
            "error": f"Internal error: {str(e)}"
        }


@tool(args_schema=DeleteCalendarEventSchema)
async def delete_calendar_event(
    stylist_id: str,
    event_id: str,
    conversation_id: str = ""
) -> dict[str, Any]:
    """
    Delete a calendar event.

    Args:
        stylist_id: Stylist UUID as string
        event_id: Google Calendar event ID
        conversation_id: For logging traceability

    Returns:
        Dictionary with:
        - success: bool
        - error: str (if failed)
    """
    try:
        # Parse stylist UUID
        try:
            stylist_uuid = UUID(stylist_id)
        except ValueError:
            return {
                "success": False,
                "error": f"Invalid stylist_id UUID format: {stylist_id}"
            }

        # Query stylist to get google_calendar_id
        stylist = await get_stylist_by_id(stylist_uuid)
        if not stylist:
            return {
                "success": False,
                "error": f"Stylist not found: {stylist_id}"
            }

        # Get calendar client
        calendar_client = get_calendar_client()
        service = calendar_client.get_service()

        # Delete event with retry logic
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=4),
            retry=retry_if_exception_type(HttpError),
        )
        def delete_event():
            return service.events().delete(
                calendarId=stylist.google_calendar_id,
                eventId=event_id
            ).execute()

        try:
            delete_event()

            logger.info(
                f"Deleted calendar event {event_id} for {stylist.name} | "
                f"conversation_id={conversation_id}"
            )

            return {"success": True}

        except RetryError as e:
            # Check the cause of the retry error
            if e.last_attempt.exception():
                original_error = e.last_attempt.exception()
                if isinstance(original_error, HttpError):
                    if original_error.resp.status == 404:
                        # Event already deleted - idempotent operation
                        logger.info(
                            f"Event {event_id} not found (already deleted) | "
                            f"conversation_id={conversation_id}"
                        )
                        return {"success": True}
                    elif original_error.resp.status == 429:
                        # Rate limit error
                        logger.error(
                            f"Rate limit exceeded after 3 retries deleting event | "
                            f"conversation_id={conversation_id}"
                        )
                        return {
                            "success": False,
                            "error": "Rate limit exceeded after 3 retries. Please try again later."
                        }

            # Generic retry error
            logger.error(
                f"Failed to delete event after retries | "
                f"conversation_id={conversation_id}: {e}"
            )
            return {
                "success": False,
                "error": "Failed to delete calendar event after retries."
            }

        except HttpError as e:
            # This should rarely happen since retry decorator catches HttpError
            # But keeping for safety in case of non-retryable errors
            if e.resp.status == 404:
                logger.info(
                    f"Event {event_id} not found (already deleted) | "
                    f"conversation_id={conversation_id}"
                )
                return {"success": True}

            logger.error(
                f"HTTP error deleting calendar event | "
                f"conversation_id={conversation_id}: {e}"
            )
            return {
                "success": False,
                "error": f"Failed to delete calendar event: {str(e)}"
            }

    except Exception as e:
        logger.error(
            f"Unexpected error in delete_calendar_event | "
            f"conversation_id={conversation_id}: {e}"
        )
        return {
            "success": False,
            "error": f"Internal error: {str(e)}"
        }

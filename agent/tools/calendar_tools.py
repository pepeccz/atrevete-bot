"""Google Calendar tools — admin-compat shim, Phase 7.4.

api/routes/admin.py imports `fetch_calendar_events_async` and
`get_calendar_client` from this module via a lazy-import block.

These symbols were present in the old architecture.  This shim restores
them as thin wrappers so the admin route continues to work without any
changes to api/ code.

Architecture note:
  - Agent graph does NOT use this module for availability — it uses
    agent/services/availability_service.py (DB-first, <100ms).
  - This module is strictly an admin-panel helper for displaying
    Google Calendar events alongside DB appointments on the calendar view.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Calendar API timeout in seconds
CALENDAR_API_TIMEOUT = 5.0


class CalendarTools:
    """Google Calendar API client wrapper for admin panel use.

    Uses lazy async initialization via get_service() so credentials are
    resolved through the credential factory (OAuth2 or service account).

    Usage:
        client = get_calendar_client()
        service = await client.get_service()
        events = service.events().list(calendarId='...').execute()
    """

    async def get_service(self) -> Any:
        """Return a fresh Google Calendar API service instance.

        Resolves credentials through get_google_credentials() — prefers
        OAuth2 from DB, falls back to service account file.
        """
        from googleapiclient.discovery import build

        from agent.services.gcal_credential_factory import get_google_credentials
        from database.connection import get_async_session

        try:
            async with get_async_session() as session:
                credentials = await get_google_credentials(session=session)
            service = build("calendar", "v3", credentials=credentials)
            logger.info("Google Calendar API client initialized successfully")
            return service
        except Exception as e:
            logger.error("Failed to initialize Google Calendar API client: %s", e)
            raise


# Module-level singleton
_calendar_client: CalendarTools | None = None


def get_calendar_client() -> CalendarTools:
    """Return the module-level CalendarTools singleton, creating it on first call."""
    global _calendar_client
    if _calendar_client is None:
        _calendar_client = CalendarTools()
    return _calendar_client


def _fetch_calendar_events_sync(
    service: Any,
    calendar_id: str,
    time_min: str,
    time_max: str,
) -> list[dict[str, Any]]:
    """Synchronous Google Calendar list call (runs inside asyncio.to_thread)."""
    events_result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return events_result.get("items", [])


async def fetch_calendar_events_async(
    service: Any,
    calendar_id: str,
    time_min: str,
    time_max: str,
    timeout: float = CALENDAR_API_TIMEOUT,
) -> list[dict[str, Any]]:
    """Async Google Calendar event list with timeout protection.

    Delegates to a thread so the blocking HTTP call does not block the
    event loop.  Returns an empty list on timeout.

    Args:
        service: Google Calendar API service (from CalendarTools.get_service()).
        calendar_id: Google Calendar ID string.
        time_min: Start of range in RFC3339 / ISO 8601 format.
        time_max: End of range in RFC3339 / ISO 8601 format.
        timeout: Max seconds to wait before returning empty list.

    Returns:
        List of Google Calendar event dicts.
    """
    try:
        events = await asyncio.wait_for(
            asyncio.to_thread(
                _fetch_calendar_events_sync,
                service,
                calendar_id,
                time_min,
                time_max,
            ),
            timeout=timeout,
        )
        return events
    except TimeoutError:
        logger.warning(
            "fetch_calendar_events_async timed out after %.1fs for calendar %s",
            timeout,
            calendar_id,
        )
        return []
    except Exception as e:
        logger.error("fetch_calendar_events_async error for calendar %s: %s", calendar_id, e)
        return []


__all__ = [
    "CalendarTools",
    "get_calendar_client",
    "fetch_calendar_events_async",
]

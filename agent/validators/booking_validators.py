"""
Booking validation functions for business rules enforcement.

This module implements validation logic for appointment booking:
- Minimum advance notice (3 days required)
- Buffer validation between consecutive appointments (10 minutes)
- Business hours validation
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from agent.tools.calendar_tools import fetch_calendar_events, get_calendar_client, get_stylist_by_id

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Europe/Madrid")
DEFAULT_MIN_ADVANCE_DAYS = 3
DEFAULT_BUFFER_MINUTES = 10


async def validate_min_advance_notice(
    requested_date: datetime,
    min_days: int = DEFAULT_MIN_ADVANCE_DAYS,
    conversation_id: str = ""
) -> dict[str, Any]:
    """
    Validate that requested date has minimum advance notice.

    Per business rules: Appointments must be scheduled at least 3 days in advance.

    Args:
        requested_date: Date customer wants to book (timezone-aware)
        min_days: Minimum days of advance notice required (default: 3)
        conversation_id: For logging traceability

    Returns:
        Dictionary with:
        - valid: bool (True if >= min_days advance notice)
        - reason: str | None (explanation if invalid)
        - days_difference: int (actual days between now and requested_date)
        - earliest_date: datetime | None (earliest valid date if invalid)
        - earliest_date_formatted: str | None (formatted earliest date)

    Example:
        >>> # Today is 2025-11-01, customer requests 2025-11-02
        >>> result = await validate_min_advance_notice(
        ...     datetime(2025, 11, 2, tzinfo=TIMEZONE)
        ... )
        >>> result["valid"]
        False
        >>> result["earliest_date_formatted"]
        "jueves 4 de noviembre"  # 2025-11-04
    """
    try:
        current_time = datetime.now(TIMEZONE)
        current_date = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        requested_date_normalized = requested_date.replace(hour=0, minute=0, second=0, microsecond=0)

        # Calculate days difference
        days_difference = (requested_date_normalized - current_date).days

        logger.info(
            f"Validating minimum advance notice | "
            f"requested_date={requested_date.date()} | "
            f"days_difference={days_difference} | "
            f"min_days={min_days} | "
            f"conversation_id={conversation_id}"
        )

        # Check if meets minimum advance notice
        if days_difference >= min_days:
            logger.info(
                f"Advance notice validation passed | "
                f"days_difference={days_difference} >= min_days={min_days} | "
                f"conversation_id={conversation_id}"
            )
            return {
                "valid": True,
                "reason": None,
                "days_difference": days_difference,
                "earliest_date": None,
                "earliest_date_formatted": None
            }

        # Validation failed - calculate earliest valid date
        earliest_date = current_date + timedelta(days=min_days)

        # Format earliest date in Spanish
        from agent.nodes.availability_nodes import format_spanish_date
        earliest_date_formatted = format_spanish_date(earliest_date)

        reason = (
            f"La fecha solicitada ({requested_date.date()}) tiene solo {days_difference} días de antelación. "
            f"Se requieren mínimo {min_days} días."
        )

        logger.warning(
            f"Advance notice validation failed | "
            f"days_difference={days_difference} < min_days={min_days} | "
            f"earliest_date={earliest_date.date()} | "
            f"conversation_id={conversation_id}"
        )

        return {
            "valid": False,
            "reason": reason,
            "days_difference": days_difference,
            "earliest_date": earliest_date,
            "earliest_date_formatted": earliest_date_formatted
        }

    except Exception as e:
        logger.exception(
            f"Error validating minimum advance notice | "
            f"conversation_id={conversation_id}: {e}"
        )
        return {
            "valid": False,
            "reason": f"Error en validación: {str(e)}",
            "days_difference": None,
            "earliest_date": None,
            "earliest_date_formatted": None
        }


async def validate_buffer_between_appointments(
    stylist_id: UUID,
    start_time: datetime,
    duration_minutes: int,
    buffer_minutes: int = DEFAULT_BUFFER_MINUTES,
    conversation_id: str = ""
) -> dict[str, Any]:
    """
    Validate that there's required buffer between appointments.

    Per business rules: 10-minute buffer required between consecutive appointments
    for stylist preparation and cleanup.

    Checks Google Calendar for conflicts:
    - Before: No appointment ending within buffer window before start_time
    - After: No appointment starting within buffer window after end_time

    Args:
        stylist_id: UUID of stylist to check
        start_time: Proposed appointment start time (timezone-aware)
        duration_minutes: Duration of proposed appointment in minutes
        buffer_minutes: Required buffer in minutes (default: 10)
        conversation_id: For logging traceability

    Returns:
        Dictionary with:
        - valid: bool (True if buffer requirements met)
        - reason: str | None (explanation if invalid)
        - conflicting_event: dict | None (details of conflicting event)

    Example:
        >>> # Proposed: 15:00-16:00, existing appointment: 14:55-15:30
        >>> result = await validate_buffer_between_appointments(
        ...     stylist_id=UUID("..."),
        ...     start_time=datetime(2025, 11, 5, 15, 0, tzinfo=TIMEZONE),
        ...     duration_minutes=60
        ... )
        >>> result["valid"]
        False
        >>> result["reason"]
        "Conflicto: hay una cita que termina a las 15:30 (buffer insuficiente)"
    """
    try:
        # Get stylist to access calendar_id
        stylist = await get_stylist_by_id(stylist_id)
        if not stylist:
            logger.error(
                f"Stylist not found for buffer validation | "
                f"stylist_id={stylist_id} | "
                f"conversation_id={conversation_id}"
            )
            return {
                "valid": False,
                "reason": "Estilista no encontrada",
                "conflicting_event": None
            }

        # Calculate appointment end time
        end_time = start_time + timedelta(minutes=duration_minutes)

        # Calculate buffer windows
        buffer_before_start = start_time - timedelta(minutes=buffer_minutes)
        buffer_after_end = end_time + timedelta(minutes=buffer_minutes)

        logger.info(
            f"Validating buffer | "
            f"stylist={stylist.name} | "
            f"proposed_time={start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')} | "
            f"buffer={buffer_minutes}min | "
            f"conversation_id={conversation_id}"
        )

        # Query Google Calendar for events on this date
        calendar_client = get_calendar_client()
        service = calendar_client.get_service()

        # Extend search window to cover buffer periods
        time_min = buffer_before_start.replace(hour=0, minute=0, second=0, microsecond=0)
        time_max = buffer_after_end.replace(hour=23, minute=59, second=59, microsecond=999999)

        time_min_str = time_min.isoformat()
        time_max_str = time_max.isoformat()

        # Fetch events
        events = fetch_calendar_events(
            service,
            stylist.google_calendar_id,
            time_min_str,
            time_max_str
        )

        # Check each event for buffer conflicts
        for event in events:
            event_start_str = event.get("start", {}).get("dateTime")
            event_end_str = event.get("end", {}).get("dateTime")

            if not event_start_str or not event_end_str:
                continue

            try:
                event_start = datetime.fromisoformat(event_start_str.replace("Z", "+00:00"))
                event_end = datetime.fromisoformat(event_end_str.replace("Z", "+00:00"))

                # Check for buffer violations:

                # Case 1: Existing appointment ends too close to proposed start
                # (event_end + buffer > proposed_start)
                if event_end > buffer_before_start and event_end <= start_time:
                    reason = (
                        f"Conflicto: hay una cita que termina a las {event_end.strftime('%H:%M')} "
                        f"(se necesitan {buffer_minutes} min de buffer antes de tu cita)"
                    )
                    logger.warning(
                        f"Buffer validation failed (before) | "
                        f"existing_end={event_end.strftime('%H:%M')} | "
                        f"proposed_start={start_time.strftime('%H:%M')} | "
                        f"buffer_violated={buffer_minutes}min | "
                        f"conversation_id={conversation_id}"
                    )
                    return {
                        "valid": False,
                        "reason": reason,
                        "conflicting_event": {
                            "summary": event.get("summary", "Cita existente"),
                            "start": event_start.isoformat(),
                            "end": event_end.isoformat()
                        }
                    }

                # Case 2: Existing appointment starts too close to proposed end
                # (event_start < proposed_end + buffer)
                if event_start < buffer_after_end and event_start >= end_time:
                    reason = (
                        f"Conflicto: hay una cita que empieza a las {event_start.strftime('%H:%M')} "
                        f"(se necesitan {buffer_minutes} min de buffer después de tu cita)"
                    )
                    logger.warning(
                        f"Buffer validation failed (after) | "
                        f"existing_start={event_start.strftime('%H:%M')} | "
                        f"proposed_end={end_time.strftime('%H:%M')} | "
                        f"buffer_violated={buffer_minutes}min | "
                        f"conversation_id={conversation_id}"
                    )
                    return {
                        "valid": False,
                        "reason": reason,
                        "conflicting_event": {
                            "summary": event.get("summary", "Cita existente"),
                            "start": event_start.isoformat(),
                            "end": event_end.isoformat()
                        }
                    }

                # Case 3: Direct overlap (already caught by availability check, but double-check)
                if event_start < end_time and event_end > start_time:
                    reason = f"Conflicto: hay una cita de {event_start.strftime('%H:%M')} a {event_end.strftime('%H:%M')}"
                    logger.warning(
                        f"Buffer validation failed (overlap) | "
                        f"conversation_id={conversation_id}"
                    )
                    return {
                        "valid": False,
                        "reason": reason,
                        "conflicting_event": {
                            "summary": event.get("summary", "Cita existente"),
                            "start": event_start.isoformat(),
                            "end": event_end.isoformat()
                        }
                    }

            except Exception as e:
                logger.warning(f"Error parsing event time during buffer validation: {e}")
                continue

        # No conflicts found - validation passed
        logger.info(
            f"Buffer validation passed | "
            f"no conflicts found | "
            f"conversation_id={conversation_id}"
        )

        return {
            "valid": True,
            "reason": None,
            "conflicting_event": None
        }

    except Exception as e:
        logger.exception(
            f"Error validating buffer between appointments | "
            f"conversation_id={conversation_id}: {e}"
        )
        return {
            "valid": False,
            "reason": f"Error en validación de buffer: {str(e)}",
            "conflicting_event": None
        }

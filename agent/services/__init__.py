"""
Agent services module.

Provides business logic services for the agent layer.

Services:
- availability_service: DB-first availability checking
- gcal_push_service: Fire-and-forget Google Calendar push
- escalation_service: Human handoff workflow (Chatwoot + notifications)
"""

from agent.services.availability_service import (
    check_slot_availability,
    get_available_slots,
    get_busy_periods,
    get_calendar_events_for_range,
    get_stylist_by_id,
    is_holiday,
)
from agent.services.escalation_service import (
    create_escalation_notification,
    disable_bot_in_chatwoot,
    trigger_escalation,
)
from agent.services.gcal_push_service import (
    delete_gcal_event,
    fire_and_forget_push_appointment,
    fire_and_forget_push_blocking_event,
    push_appointment_to_gcal,
    push_blocking_event_to_gcal,
    update_gcal_event_status,
)

__all__ = [
    # Availability service
    "check_slot_availability",
    "get_available_slots",
    "get_busy_periods",
    "get_calendar_events_for_range",
    "get_stylist_by_id",
    "is_holiday",
    # GCal push service
    "delete_gcal_event",
    "fire_and_forget_push_appointment",
    "fire_and_forget_push_blocking_event",
    "push_appointment_to_gcal",
    "push_blocking_event_to_gcal",
    "update_gcal_event_status",
    # Escalation service
    "create_escalation_notification",
    "disable_bot_in_chatwoot",
    "trigger_escalation",
]

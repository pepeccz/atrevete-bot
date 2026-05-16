"""Google Calendar push service — forward shim.

Implementation lives in agent.services.gcal_push_service.
This module is a thin re-export shim so api/routes/admin.py can import from
shared.* without crossing the api → agent boundary.

Do NOT add implementation logic here. All logic stays in agent.services.
Test mock paths (agent.services.gcal_push_service.*) remain unchanged.
"""

from agent.services.gcal_push_service import (
    delete_gcal_event,
    fire_and_forget_push_blocking_event,
    push_appointment_to_gcal,
    update_appointment_in_gcal,
    update_blocking_event_in_gcal,
)

__all__ = [
    "delete_gcal_event",
    "push_appointment_to_gcal",
    "update_appointment_in_gcal",
    "fire_and_forget_push_blocking_event",
    "update_blocking_event_in_gcal",
]

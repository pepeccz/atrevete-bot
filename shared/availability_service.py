"""Public availability domain API — forward shim.

Implementation lives in agent.services.availability_service.
This module is a thin re-export shim so api/routes/admin.py can import from
shared.* without crossing the api → agent boundary.

Do NOT add implementation logic here. All logic stays in agent.services.
Test mock paths (agent.services.availability_service.*) remain unchanged.
"""

from agent.services.availability_service import (
    get_available_slots,
    get_calendar_events_for_range,
    is_holiday,
)

__all__ = [
    "get_available_slots",
    "is_holiday",
    "get_calendar_events_for_range",
]

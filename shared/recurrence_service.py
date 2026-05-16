"""Recurrence service — forward shim.

Implementation lives in agent.services.recurrence_service.
This module is a thin re-export shim so api/routes/admin.py can import from
shared.* without crossing the api → agent boundary.

Symbols re-exported here match exactly the multi-line import at admin.py:61
(expand_recurrence, check_conflicts_for_dates, get_business_hours_summary,
get_remaining_week_days, format_byday, format_bymonthday, parse_byday).

Do NOT add implementation logic here. All logic stays in agent.services.
Test mock paths (agent.services.recurrence_service.*) remain unchanged.
"""

from agent.services.recurrence_service import (
    check_conflicts_for_dates,
    expand_recurrence,
    format_byday,
    format_bymonthday,
    get_business_hours_summary,
    get_remaining_week_days,
    parse_byday,
)

__all__ = [
    "expand_recurrence",
    "check_conflicts_for_dates",
    "get_business_hours_summary",
    "get_remaining_week_days",
    "format_byday",
    "format_bymonthday",
    "parse_byday",
]

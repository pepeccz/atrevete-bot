"""Backward-compat shim — implementation moved to shared.calendar_service.

This module is retained so that existing import paths (e.g. test mock paths
for agent.tools.calendar_tools.*) continue to resolve without modification.

The canonical implementation now lives in shared/calendar_service.py.
Do NOT add implementation logic here — this is a thin re-export only.

See ADR sdd/agent-tools-shared-extraction (Decision 4) for rationale.
"""

from shared.calendar_service import (
    CalendarTools,
    get_calendar_client,
    fetch_calendar_events_async,
)

__all__ = [
    "CalendarTools",
    "get_calendar_client",
    "fetch_calendar_events_async",
]

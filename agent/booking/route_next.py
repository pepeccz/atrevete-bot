"""route_next dispatcher — Phase 5.10.

Pure function: maps booking.step → node name.
Used as the target of Command(goto=route_next(state)) in booking leaves.

Special case: slot step checks offered_slots:
  - None → fetch_availability (trigger tool node first)
  - non-None → ask_slot (user picks from existing list)
"""

from __future__ import annotations

from typing import Any

from langgraph.constants import END

_STEP_TO_NODE: dict[str, str] = {
    "service": "ask_service",
    "audience": "ask_audience",
    "more_services": "ask_more_services",
    "stylist": "ask_stylist",
    "date": "ask_date",
    "name": "ask_name",
    "notes": "ask_notes",
    "confirm": "await_confirmation",
    "done": END,
}


def route_next(state: dict[str, Any]) -> str:
    """Map current booking step to next node name."""
    booking = state.get("booking") or {}
    step = booking.get("step") if booking else None

    if step is None:
        return "ask_service"

    if step == "slot":
        offered_slots = booking.get("offered_slots")
        if offered_slots is None:
            return "fetch_availability"
        return "ask_slot"

    return _STEP_TO_NODE.get(step, "ask_service")

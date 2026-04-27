"""Closed vocabulary of next-step descriptors returned by booking-flow tools.

Every tool in the booking flow sets `next_step` to one of these values so the
LLM can narrate the current state to the customer without interpreting imperative
instructions. Tools are stateless; the LLM accumulates context from prior
ToolMessage payloads in conversation history.

Refs: R9, R10, R19
"""

from __future__ import annotations

from typing import Literal

NextStep = Literal[
    "service_required",  # update_booking — no services collected yet; LLM asks which service
    "stylist_required",  # update_booking | check_availability — stylist absent and no_preference=False
    "date_required",  # update_booking | check_availability — date_iso missing or invalid
    "audience_required",  # update_booking — service family ambiguous; payload: variants, family
    "advance_policy_violated",  # check_availability — date < today+min_days; payload: first_valid_date, policy_min_days
    "confirmation_required",  # book — confirmed!=True; LLM waits for explicit customer affirmation
    "incomplete_booking",  # book — required slot absent; payload: missing (list of slot names)
    "booking_ready",  # update_booking — all three booking slots collected; LLM calls check_availability
    "slot_not_available",  # check_availability — no free slot on requested day; payload: available_slots
    "reoffer_slots",  # book — race conflict on submit; payload: available_slots
    "retry_later",  # any tool — transient DB/GCal failure; no payload required
    "booking_complete",  # book — success; payload: appointment_id, calendar_link
]

# Required payload keys per next_step value.
# Values NOT listed here require no specific payload keys.
# Used by tests (R9, R19) and optionally by the LLM to validate tool output.
NEXT_STEP_PAYLOAD_CONTRACT: dict[str, tuple[str, ...]] = {
    "audience_required": ("variants", "family"),
    "advance_policy_violated": ("first_valid_date", "policy_min_days"),
    "incomplete_booking": ("missing",),
    "slot_not_available": ("available_slots",),
    "reoffer_slots": ("available_slots",),
    "booking_complete": ("appointment_id", "calendar_link"),
}

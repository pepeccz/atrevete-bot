"""Canonical booking substep contracts and validation helpers."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping, TypedDict, cast


class BookingSubstep(StrEnum):
    """Typed booking substeps serialized as lowercase strings."""

    SERVICE_SELECTION = "service_selection"
    STYLIST_SELECTION = "stylist_selection"
    SLOT_SELECTION = "slot_selection"
    NOTES = "notes"
    CONFIRMATION = "confirmation"
    COMPLETED = "completed"


class BookingDraftContext(TypedDict, total=False):
    """Canonical booking draft stored inside mode_context or draft_contexts."""

    booking_step: str
    service_id: str
    service_name: str
    service_category: str
    service_duration_minutes: int
    service_family: str | None
    selected_services: list[str]
    stylist_id: str
    stylist_name: str
    recurrent_stylist_id: str | None
    recurrent_stylist_name: str | None
    recurrent_stylist_slot_summary: str | None
    selected_slot: dict[str, Any]
    slot_summary: str
    notes: str | None
    customer_name: str | None
    customer_phone: str | None
    pending_clarification: dict[str, Any] | None
    candidate_services: list[dict[str, Any]]
    candidate_service_ids: list[str]
    pending_recommendations: list[str]
    recommendations_shown: bool
    availability_start_date: str | None
    availability_time_range: str | None
    last_intent: str
    last_intent_confidence: float
    pending_cancel: bool
    awaiting_human: bool


_BOOKING_SUBSTEP_ALIASES: dict[str, BookingSubstep] = {
    "customer_data": BookingSubstep.NOTES,
    "datetime_selection": BookingSubstep.SLOT_SELECTION,
}


ALLOWED_TRANSITIONS: dict[BookingSubstep, list[BookingSubstep]] = {
    BookingSubstep.SERVICE_SELECTION: [
        BookingSubstep.SERVICE_SELECTION,
        BookingSubstep.STYLIST_SELECTION,
    ],
    BookingSubstep.STYLIST_SELECTION: [
        BookingSubstep.SERVICE_SELECTION,
        BookingSubstep.STYLIST_SELECTION,
        BookingSubstep.SLOT_SELECTION,
    ],
    BookingSubstep.SLOT_SELECTION: [
        BookingSubstep.STYLIST_SELECTION,
        BookingSubstep.SLOT_SELECTION,
        BookingSubstep.NOTES,
    ],
    BookingSubstep.NOTES: [
        BookingSubstep.NOTES,
        BookingSubstep.CONFIRMATION,
    ],
    BookingSubstep.CONFIRMATION: [
        BookingSubstep.SERVICE_SELECTION,
        BookingSubstep.SLOT_SELECTION,
        BookingSubstep.CONFIRMATION,
        BookingSubstep.COMPLETED,
    ],
    BookingSubstep.COMPLETED: [],
}


BOOKING_PRESERVE_ON_GENERAL: set[str] = {
    "booking_step",
    "service_id",
    "service_name",
    "service_category",
    "service_duration_minutes",
    "service_family",
    "selected_services",
    "stylist_id",
    "stylist_name",
    "recurrent_stylist_id",
    "recurrent_stylist_name",
    "recurrent_stylist_slot_summary",
    "selected_slot",
    "slot_summary",
    "notes",
    "customer_name",
    "customer_phone",
    "pending_clarification",
    "candidate_services",
    "candidate_service_ids",
    "pending_recommendations",
    "recommendations_shown",
    "availability_start_date",
    "availability_time_range",
    "last_intent",
    "last_intent_confidence",
    "pending_cancel",
}

BOOKING_FREEZE_ON_ESCALATION: set[str] = set(BOOKING_PRESERVE_ON_GENERAL) | {"awaiting_human"}

CONTEXT_PRESERVE_RULES: dict[str, set[str]] = {
    "GENERAL": BOOKING_PRESERVE_ON_GENERAL,
    "ESCALATION": BOOKING_FREEZE_ON_ESCALATION,
}

_REQUIRED_FIELDS_BY_SUBSTEP: dict[BookingSubstep, set[str]] = {
    BookingSubstep.SERVICE_SELECTION: set(),
    BookingSubstep.STYLIST_SELECTION: {"service_id", "service_name"},
    BookingSubstep.SLOT_SELECTION: {"service_id", "service_name", "stylist_id", "stylist_name"},
    BookingSubstep.NOTES: {
        "service_id",
        "service_name",
        "stylist_id",
        "stylist_name",
        "selected_slot",
    },
    BookingSubstep.CONFIRMATION: {
        "service_id",
        "service_name",
        "stylist_id",
        "stylist_name",
        "selected_slot",
    },
    BookingSubstep.COMPLETED: {
        "service_id",
        "service_name",
        "stylist_id",
        "stylist_name",
        "selected_slot",
    },
}


def normalize_booking_substep(value: BookingSubstep | str | None) -> BookingSubstep:
    """Normalize serialized step values into the canonical enum."""

    if isinstance(value, BookingSubstep):
        return value
    if not value:
        return BookingSubstep.SERVICE_SELECTION
    aliased_value = _BOOKING_SUBSTEP_ALIASES.get(str(value).lower(), str(value).lower())
    try:
        return BookingSubstep(aliased_value)
    except ValueError as exc:
        raise ValueError(f"Invalid booking substep: {value!r}") from exc


def is_transition_allowed(
    current_substep: BookingSubstep | str,
    next_substep: BookingSubstep | str,
) -> bool:
    """Return True when the substep change is valid."""

    current = normalize_booking_substep(current_substep)
    target = normalize_booking_substep(next_substep)
    return target in ALLOWED_TRANSITIONS[current]


def validate_booking_context(
    context: Mapping[str, Any] | None,
    *,
    previous_substep: BookingSubstep | str | None = None,
) -> BookingDraftContext:
    """Validate serialized booking draft context for the current substep."""

    candidate = dict(context or {})
    current_substep = normalize_booking_substep(candidate.get("booking_step"))

    if previous_substep is not None and not is_transition_allowed(previous_substep, current_substep):
        prev = normalize_booking_substep(previous_substep)
        raise ValueError(
            f"Invalid booking transition: {prev.value} -> {current_substep.value}"
        )

    missing_fields = sorted(
        field for field in _REQUIRED_FIELDS_BY_SUBSTEP[current_substep] if not candidate.get(field)
    )
    if missing_fields:
        missing = ", ".join(missing_fields)
        raise ValueError(
            f"Booking context missing required fields for {current_substep.value}: {missing}"
        )

    candidate["booking_step"] = current_substep.value
    return cast(BookingDraftContext, candidate)


def preserve_booking_context(
    context: Mapping[str, Any] | None,
    target_mode: str,
) -> BookingDraftContext:
    """Return the booking context snapshot allowed for a mode transition."""

    candidate = dict(context or {})
    allowed_keys = CONTEXT_PRESERVE_RULES.get(target_mode.upper())
    if not allowed_keys:
        return cast(BookingDraftContext, {})

    preserved = {key: candidate[key] for key in allowed_keys if key in candidate}
    if target_mode.upper() == "ESCALATION":
        preserved["awaiting_human"] = True

    if "booking_step" in candidate:
        preserved["booking_step"] = normalize_booking_substep(candidate["booking_step"]).value

    return cast(BookingDraftContext, preserved)

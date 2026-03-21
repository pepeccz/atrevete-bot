"""Canonical booking substep contracts and validation helpers."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Mapping, TypedDict, cast


class BookingSubstep(StrEnum):
    """Typed booking substeps serialized as lowercase strings."""

    SERVICE_SELECTION = "service_selection"
    ADD_ONS = "add_ons"
    STYLIST_SELECTION = "stylist_selection"
    SLOT_SELECTION = "slot_selection"
    CUSTOMER_NAME = "customer_name"
    NOTES = "notes"
    CONFIRMATION = "confirmation"
    COMPLETED = "completed"


class BookingStepTransition(StrEnum):
    """Semantic labels that explain why the booking flow moved between steps.

    These values are stored alongside booking state so prompts, tests, and future
    analytics can distinguish a normal step advance from UX-specific detours such
    as keeping the user in slot selection after a stylist has no availability.
    """

    NORMAL = "normal"
    DATE_SUBSTITUTED = "date_substituted"
    NO_SLOTS_FOR_STYLIST = "no_slots_for_stylist"
    USER_CANCELLED = "user_cancelled"


class InterpretationReason(StrEnum):
    """Canonical semantic reasons produced while interpreting availability results.

    The values are shared by booking mode and availability tools so semantic
    payloads stay stable across prompt rendering, transition decisions, and tests.
    """

    MINIMUM_DAYS_RULE = "minimum_days_rule"
    NO_AVAILABILITY = "no_availability"
    STYLIST_UNAVAILABLE = "stylist_unavailable"
    SUCCESS = "success"


class SlotInterpretation(TypedDict, total=False):
    """Semantic interpretation of availability tool responses.

    This typed dict decouples raw tool payload shapes from booking-step decisions.
    `_interpret_slot_tool_results()` normalizes both legacy and semantic tool
    responses into this structure before `_advance_step()` decides whether the
    flow should stay in `slot_selection` or continue.

    Example:
        {
            "has_slots": False,
            "substitution_made": True,
            "substitution_reason": "minimum_days_rule",
            "date_requested": date(2026, 3, 17),
            "min_valid_date": date(2026, 3, 19),
            "no_slots_for_chosen_stylist": True,
        }
    """

    has_slots: bool
    substitution_made: bool
    date_requested: date | None
    date_substituted: date | None
    substitution_reason: str | None
    min_valid_date: date | None
    no_slots_for_chosen_stylist: bool
    no_slots_for_any_stylist: bool
    stylist_name: str | None
    available_slots: list[dict[str, Any]] | None


class BookingDraftContext(TypedDict, total=False):
    """Canonical booking draft stored inside mode_context or draft_contexts.

    T3.2 Contract — selected_slot:
        Must be the canonical DTO written by booking_mode._handle_slot_selection after
        _resolve_slot_from_message() finds a match:
            {
                "start_time": str,           # ISO datetime — equals offered_slots[i].full_datetime
                "date": str,                 # YYYY-MM-DD
                "time": str,                 # HH:MM
                "stylist_id": str,           # UUID
                "stylist_name": str,
                "duration_minutes": int | None,
            }
        book() reads selected_slot["start_time"] for the appointment datetime.
        Never store raw resolved_slot — always normalize through the DTO builder.

    offered_slots:
        Always overwritten from the latest availability tool result (DESIGN-1).
        Each entry guaranteed to have full_datetime via _normalize_slot_entry().
    """

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
    selected_slot: dict[str, Any]  # Canonical DTO: {start_time (ISO), date, time, stylist_id, stylist_name, duration_minutes}
    slot_summary: str
    notes: str | None
    customer_name: str | None
    customer_phone: str | None
    pending_clarification: dict[str, Any] | None
    candidate_services: list[dict[str, Any]]
    candidate_service_ids: list[str]
    pending_recommendations: list[str]
    recommendations_shown: bool
    add_ons_options: list[dict[str, Any]] | None
    add_ons_declined: bool
    offered_slots: list[dict[str, Any]] | None
    availability_start_date: str | None
    availability_time_range: str | None
    substitution_made: bool
    substitution_reason: str | None
    date_requested: str | None
    date_substituted: str | None
    min_valid_date: str | None
    no_slots_for_stylist: bool
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
        BookingSubstep.ADD_ONS,
        BookingSubstep.STYLIST_SELECTION,
    ],
    BookingSubstep.ADD_ONS: [
        BookingSubstep.ADD_ONS,
        BookingSubstep.STYLIST_SELECTION,
        BookingSubstep.SERVICE_SELECTION,
    ],
    BookingSubstep.STYLIST_SELECTION: [
        BookingSubstep.SERVICE_SELECTION,
        BookingSubstep.ADD_ONS,
        BookingSubstep.STYLIST_SELECTION,
        BookingSubstep.SLOT_SELECTION,
    ],
    BookingSubstep.SLOT_SELECTION: [
        BookingSubstep.SLOT_SELECTION,
        BookingSubstep.CUSTOMER_NAME,
        BookingSubstep.NOTES,
        BookingSubstep.STYLIST_SELECTION,
    ],
    BookingSubstep.CUSTOMER_NAME: [
        BookingSubstep.CUSTOMER_NAME,
        BookingSubstep.NOTES,
        BookingSubstep.SLOT_SELECTION,
    ],
    BookingSubstep.NOTES: [
        BookingSubstep.NOTES,
        BookingSubstep.CONFIRMATION,
        BookingSubstep.SLOT_SELECTION,
        BookingSubstep.CUSTOMER_NAME,
    ],
    BookingSubstep.CONFIRMATION: [
        BookingSubstep.COMPLETED,
        BookingSubstep.NOTES,
        BookingSubstep.SLOT_SELECTION,
        BookingSubstep.SERVICE_SELECTION,
        # T5.3: Allow rewind to CUSTOMER_NAME and STYLIST_SELECTION from confirmation
        # so _booking_payload_ready() can rewind to the earliest broken contract edge.
        BookingSubstep.CUSTOMER_NAME,
        BookingSubstep.STYLIST_SELECTION,
    ],
    BookingSubstep.COMPLETED: [],
}


STEP_TOOL_REGISTRY: dict[BookingSubstep, list[str]] = {
    BookingSubstep.SERVICE_SELECTION: ["query_info", "search_services"],
    BookingSubstep.ADD_ONS: ["search_services"],
    BookingSubstep.STYLIST_SELECTION: [],
    BookingSubstep.SLOT_SELECTION: ["check_availability", "find_next_available"],
    BookingSubstep.CUSTOMER_NAME: [],
    BookingSubstep.NOTES: [],
    BookingSubstep.CONFIRMATION: [],
    BookingSubstep.COMPLETED: [],
}
"""Canonical `BookingSubstep -> tool names` registry for the booking flow.

Keep this mapping in sync with the tools passed to each `_handle_*` method in
`booking_mode.py`. Tests and docs treat it as the single source of truth for
which tools the LLM may use at each step.

Example:
    `STEP_TOOL_REGISTRY[BookingSubstep.SLOT_SELECTION]` returns
    `["check_availability", "find_next_available"]`.
"""


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
    "add_ons_options",
    "add_ons_declined",
    "availability_start_date",
    "availability_time_range",
    "substitution_made",
    "substitution_reason",
    "date_requested",
    "date_substituted",
    "min_valid_date",
    "no_slots_for_stylist",
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
    BookingSubstep.ADD_ONS: {"service_id", "service_name"},
    BookingSubstep.STYLIST_SELECTION: {"service_id", "service_name"},
    BookingSubstep.SLOT_SELECTION: {"service_id", "service_name", "stylist_id", "stylist_name"},
    BookingSubstep.CUSTOMER_NAME: {
        "service_id",
        "service_name",
        "stylist_id",
        "stylist_name",
        "selected_slot",
    },
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

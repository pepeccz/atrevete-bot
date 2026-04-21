"""
State Authority Registry for BookingContext.

Single source of truth for which module owns (writes) each BookingContext field
and which modules read it. Used by:

- Unit tests (REQ-4): walk BookingContext.__annotations__ and assert every field
  appears in BOOKING_STATE_AUTHORITY.
- AST lint (REQ-3 / Phase 5): scripts/check_booking_state_orphans.py uses this
  registry to detect orphan writes (wrong owner) and orphan reads (zero writers).

Design decision (AD-1 from design doc):
  Plain dict is greppable, no runtime overhead, and the AST lint script can parse
  it with ast.literal_eval. Chosen over decorator-based registration (too magic)
  and YAML sidecar (desync risk).

DO NOT import from agent.booking.* here — this module is imported by those
modules and a circular import would result.
"""

from __future__ import annotations

from typing import Any, TypedDict

# ---------------------------------------------------------------------------
# FieldAuthority shape
# ---------------------------------------------------------------------------


class FieldAuthority(TypedDict):
    """Declarative authority record for a single BookingContext field."""

    owner_module: str  # e.g. "agent.tools.booking_data_tools"
    owner_symbol: str  # e.g. "update_booking" — the primary writer function
    readers: list[str]  # qualified symbol ids of known readers
    transient: bool  # True = exempt from writer/reader pairing enforcement
    notes: str  # human rationale; required, never empty


# ---------------------------------------------------------------------------
# BOOKING_STATE_AUTHORITY — one entry per BookingContext field
# ---------------------------------------------------------------------------
# Keep in the same order as agent/state/schemas.py BookingContext.
# After Phase 4 purge: booking_step, available_slots, _disambiguation_questions_shown
# are removed from BookingContext and therefore NOT listed here.

BOOKING_STATE_AUTHORITY: dict[str, FieldAuthority] = {
    # ── Service data ─────────────────────────────────────────────────────
    "last_services": {
        "owner_module": "agent.tools.booking_data_tools",
        "owner_symbol": "update_booking",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
            "agent.modes.booking_mode.BookingModeNode._post_tool_result",
            "agent.modes.booking_mode.BookingModeNode.handle",
        ],
        "transient": False,
        "notes": "Set by update_booking when services are resolved.",
    },
    "last_service_category": {
        "owner_module": "agent.tools.booking_data_tools",
        "owner_symbol": "update_booking",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
            "agent.modes.booking_mode.BookingModeNode._update_service_category",
        ],
        "transient": False,
        "notes": (
            "Set by update_booking; also set by booking_mode._update_service_category "
            "as a permitted mirror (category inference from catalog)."
        ),
    },
    "last_total_duration_minutes": {
        "owner_module": "agent.tools.booking_data_tools",
        "owner_symbol": "update_booking",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
        ],
        "transient": False,
        "notes": "Total duration of all selected services in minutes.",
    },
    # ── Stylist data ──────────────────────────────────────────────────────
    "last_stylist": {
        "owner_module": "agent.tools.booking_data_tools",
        "owner_symbol": "update_booking",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
            "agent.modes.booking_mode.BookingModeNode._post_tool_result",
        ],
        "transient": False,
        "notes": (
            "Written by update_booking (service selection) and patch_pipeline "
            "(digit/slot selection resolver) and availability result post-processing."
        ),
    },
    "no_preference_stylist": {
        "owner_module": "agent.tools.booking_data_tools",
        "owner_symbol": "update_booking",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
            "agent.modes.booking_mode.BookingModeNode._post_tool_result",
        ],
        "transient": False,
        "notes": "True when customer chose 'Sin preferencia'; clears last_stylist slot tracking.",
    },
    "available_stylists": {
        "owner_module": "agent.tools.booking_data_tools",
        "owner_symbol": "update_booking",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
        ],
        "transient": False,
        "notes": (
            "Mirror of _offered_stylists minus the 'Sin preferencia' sentinel. "
            "DO NOT add new readers — prefer _offered_stylists as canonical. REQ-13."
        ),
    },
    "_offered_stylists": {
        "owner_module": "agent.tools.booking_data_tools",
        "owner_symbol": "update_booking",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
        ],
        "transient": False,
        "notes": (
            "Canonical stylist list including 'Sin preferencia' sentinel. "
            "available_stylists is a mirror of this without the sentinel."
        ),
    },
    # ── Slot data ──────────────────────────────────────────────────────────
    "offered_slots": {
        "owner_module": "agent.tools.booking_data_tools",
        "owner_symbol": "update_booking",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
            "agent.modes.booking_mode.BookingModeNode._post_tool_result",
        ],
        "transient": False,
        "notes": "Written by update_booking on service/stylist selection; cleared on slot pick.",
    },
    "selected_slot": {
        "owner_module": "agent.tools.booking_data_tools",
        "owner_symbol": "update_booking",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
            "agent.modes.booking_mode.BookingModeNode._post_tool_result",
            "agent.modes.booking_mode.BookingModeNode.handle",
        ],
        "transient": False,
        "notes": "The slot dict chosen by the customer; cleared when services change.",
    },
    # ── Customer data ──────────────────────────────────────────────────────
    "customer_name": {
        "owner_module": "agent.tools.booking_data_tools",
        "owner_symbol": "update_booking",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
        ],
        "transient": False,
        "notes": "Full name (first + last) resolved during name collection step.",
    },
    "customer_first_name": {
        "owner_module": "agent.tools.booking_data_tools",
        "owner_symbol": "update_booking",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
        ],
        "transient": False,
        "notes": "First name component; set together with customer_name.",
    },
    "customer_last_name": {
        "owner_module": "agent.tools.booking_data_tools",
        "owner_symbol": "update_booking",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
        ],
        "transient": False,
        "notes": "Last name component; may be None.",
    },
    "customer_id": {
        "owner_module": "agent.booking.patch_pipeline",
        "owner_symbol": "resolve_customer_from_state",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
            "agent.modes.booking_mode.BookingModeNode.handle",
        ],
        "transient": False,
        "notes": "UUID of the resolved customer; written by pre-loop resolver.",
    },
    # ── Handoff hints ──────────────────────────────────────────────────────
    "opening_booking_request": {
        "owner_module": "agent.graphs.conversation_flow",
        "owner_symbol": "_build_initial_booking_context",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
            "agent.modes.booking_mode.BookingModeNode.handle",
        ],
        "transient": False,
        "notes": (
            "Original user request text; set by router on BOOKING entry or pre-loop "
            "prefill in booking_mode when missing."
        ),
    },
    "service_audience_hint": {
        "owner_module": "agent.graphs.conversation_flow",
        "owner_symbol": "_build_initial_booking_context",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
            "agent.tools.booking_data_tools.update_booking",
        ],
        "transient": False,
        "notes": (
            "Audience hint (señora/caballero/niño) passed from router or greeting_mode; "
            "cleared by update_booking when service_audience_hint is accepted."
        ),
    },
    "preferred_stylist_name": {
        "owner_module": "agent.graphs.conversation_flow",
        "owner_symbol": "_build_initial_booking_context",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
        ],
        "transient": False,
        "notes": "Stylist preference from router handoff; consumed by grounding to pre-select.",
    },
    "preferred_date_hint": {
        "owner_module": "agent.graphs.conversation_flow",
        "owner_symbol": "_build_initial_booking_context",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
        ],
        "transient": False,
        "notes": "Date/time preference from router handoff; consumed by grounding.",
    },
    # ── Disambiguation / confirmation / capability fields ──────────────────
    "pending_disambiguations": {
        "owner_module": "agent.tools.booking_data_tools",
        "owner_symbol": "update_booking",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
            "agent.booking.middleware.invariants.BookingInvariantMiddleware",
            "agent.tools.booking_data_tools._build_response",
        ],
        "transient": False,
        "notes": (
            "List of audience-disambiguation dicts. Renamed from _audience_ambiguity "
            "in Phase 2 with shape change: single dict → list[dict]. "
            "Cleared by update_booking when service_audience_hint is accepted."
        ),
    },
    "confirmed": {
        "owner_module": "agent.booking.patch_pipeline",
        "owner_symbol": "resolve_confirmation",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
            "agent.modes.booking_mode.BookingModeNode.handle",
            "agent.booking.middleware.invariants.BookingInvariantMiddleware",
        ],
        "transient": False,
        "notes": "True when customer confirmed the booking summary via affirmation.",
    },
    "booked_appointment_id": {
        "owner_module": "agent.modes.booking_mode",
        "owner_symbol": "BookingModeNode._post_tool_result",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
        ],
        "transient": False,
        "notes": (
            "Appointment UUID set after successful book() call. "
            "Currently zero production writers — field is structurally declared "
            "but never populated; kept to avoid breaking grounding reader. "
            "TODO: wire from book() tool result in a follow-up SDD."
        ),
    },
    # ── Flow control / UX flags ────────────────────────────────────────────
    "add_more_asked": {
        "owner_module": "agent.booking.patch_pipeline",
        "owner_symbol": "resolve_add_more_negation",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
            "agent.modes.booking_mode.BookingModeNode.handle",
        ],
        "transient": False,
        "notes": (
            "Sole writer is resolve_add_more_negation (pre-loop resolver). "
            "Prevents grounding from re-asking for more services after negation."
        ),
    },
    "notes": {
        "owner_module": "agent.tools.booking_data_tools",
        "owner_symbol": "update_booking",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
        ],
        "transient": False,
        "notes": "Customer appointment notes (allergies, preferences, etc.).",
    },
    "notes_state": {
        "owner_module": "agent.tools.booking_data_tools",
        "owner_symbol": "update_booking",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
        ],
        "transient": False,
        "notes": "FSM for notes collection: not_asked | skipped | provided.",
    },
    "_booking_completed": {
        "owner_module": "agent.modes.booking_mode",
        "owner_symbol": "BookingModeNode._post_tool_result",
        "readers": [
            "agent.modes.booking_mode.BookingModeNode.handle",
        ],
        "transient": False,
        "notes": "Set True on successful book() call; guards re-entry into booking loop.",
    },
    "_confirmation_shown": {
        "owner_module": "agent.booking.middleware.invariants",
        "owner_symbol": "BookingInvariantMiddleware",
        "readers": [
            "agent.booking.grounding.compute_next_prompt",
            "agent.modes.booking_mode.BookingModeNode.handle",
        ],
        "transient": False,
        "notes": (
            "Set by BookingInvariantMiddleware CONFIRMATION_REQUIRED gate; "
            "cascade-cleared by booking_mode._post_tool_result when services change."
        ),
    },
    "_suggested_customer_name": {
        "owner_module": "agent.booking.patch_pipeline",
        "owner_symbol": "resolve_customer_from_state",
        "readers": ["prompt"],
        "transient": True,
        "notes": (
            "Name suggestion injected into the system prompt for the LLM to propose "
            "to the customer. The LLM is the sole consumer (reader='prompt'). "
            "Marked transient=True — exempt from writer/reader pairing enforcement."
        ),
    },
}

# ---------------------------------------------------------------------------
# Derived views — kept in sync with BOOKING_STATE_AUTHORITY
# ---------------------------------------------------------------------------

#: Maps each BookingContext field to its authoritative writer module.
#: Consumed by AST lint (Phase 5) and unit tests.
FIELD_WRITERS: dict[str, str] = {
    field: authority["owner_module"] for field, authority in BOOKING_STATE_AUTHORITY.items()
}

#: Maps each BookingContext field to its list of reader symbols.
#: Consumed by AST lint (Phase 5) and unit tests.
FIELD_READERS: dict[str, list[str]] = {
    field: authority["readers"] for field, authority in BOOKING_STATE_AUTHORITY.items()
}


# ---------------------------------------------------------------------------
# compute_state_for_grounding — AD-4
# ---------------------------------------------------------------------------


def compute_state_for_grounding(
    state: dict[str, Any], booking_context: dict[str, Any]
) -> dict[str, Any]:
    """
    Return a new state dict with booking_context rebound to the post-resolver value.

    Called by BookingModeNode.handle() just before assigning self._current_state,
    so that BookingGroundingMiddleware.before_model() reads the current
    (post-resolver) booking_context rather than the stale checkpoint value.

    Args:
        state: The ConversationState dict from the checkpoint.
        booking_context: The live local dict produced by pre-loop resolvers.

    Returns:
        A shallow copy of state with state["booking_context"] replaced by
        booking_context. The original state dict is NOT mutated.
    """
    return {**state, "booking_context": booking_context}

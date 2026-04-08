"""
ConversationState schema for LangGraph StateGraph - v6.0 Mode-Based Architecture.

This module defines the typed state structure for v6.0 architecture with independent mode nodes.
The state is immutable - nodes must return new dicts rather than mutating the input state.

Architecture:
- 4 independent mode nodes: GREETING, BOOKING, GENERAL, ESCALATION
- Router node selects mode based on intent + state flags
- Mode-specific context stored in mode_context dict (cleared on mode transitions via __reset__ sentinel)

Evolution: v6.0 adds current_mode, mode_context, mode_history for mode-based routing.
FIX-005: merge_dicts supports __reset__ sentinel to clear stale booking data on mode transitions.
"""

from operator import add as operator_add
from typing import Annotated, Any, TypedDict
from uuid import UUID


# ============================================================================
# BookingContext — Typed dict for durable booking state (Phase 1 / AD-2)
# ============================================================================


class BookingContext(TypedDict, total=False):
    """
    Typed container for all booking-flow state.

    Replaces the usage of booking-related keys inside mode_context, which used
    a merge_dicts reducer that could not delete keys. BookingContext uses a
    full-replace reducer (replace_booking_context), so writing a new
    BookingContext atomically replaces the old one — no stale keys survive.

    All fields are optional (total=False) because the context is built
    incrementally as the booking flow progresses.
    """

    # Booking step FSM
    booking_step: (
        str  # service_selection|stylist_selection|datetime_selection|name_collection|confirmation
    )

    # Service data
    last_services: list[str]  # e.g. ["CORTE LARGO"]
    last_total_duration_minutes: int | None

    # Stylist data
    last_stylist: str | None  # e.g. "Pilar"
    no_preference_stylist: bool

    # Slot data
    offered_slots: list[dict[str, Any]]  # from check_availability
    selected_slot: dict[str, Any] | None  # user-confirmed slot

    # Customer data
    customer_name: str | None
    customer_id: str | None

    _booking_completed: bool

    # Handoff hints (from router / greeting mode)
    service_audience_hint: str | None
    preferred_stylist_name: str | None  # from router handoff hints
    preferred_date_hint: str | None

    # Extra
    notes: str | None
    notes_asked: bool  # True after the notes question has been presented to the user


def replace_booking_context(
    current: dict[str, Any] | None, update: dict[str, Any] | None
) -> dict[str, Any]:
    """
    Full-replace reducer for booking_context.

    Unlike merge_dicts, this reducer REPLACES the entire booking_context on
    every update. This ensures deleted keys (e.g. offered_slots after a slot
    is selected) actually disappear from state instead of persisting as zombies.

    Semantics:
    - update is truthy (non-empty dict) → return dict(update) [full replace]
    - update is falsy (None or {}) → return current or {} [no-op / keep current]

    Args:
        current: The previous BookingContext value from the checkpoint
        update: The new BookingContext value returned by a node

    Returns:
        The resolved BookingContext dict
    """
    if update:
        return dict(update)
    return current or {}


# ============================================================================
# Type alias for Any (needed by reducer functions)
# ============================================================================


# ============================================================================
# merge_dicts — Custom reducer for mode_context with __reset__ sentinel support
# ============================================================================


def preserve_if_none(current: Any, update: Any) -> Any:
    """
    Reducer that keeps the current value if update is None.

    Used for fields like customer_name and customer_id that should not be
    overwritten with None once set (prevents accidental resets).

    Args:
        current: Current value in state
        update: New value from node return dict

    Returns:
        update if update is not None, else current
    """
    if update is None:
        return current
    return update


def append_unique_list(current: list | None, update: list | None) -> list:
    """
    Reducer that appends unique items from update to current list.

    Used for mode_history to avoid duplicate consecutive entries.

    Args:
        current: Current list (or None)
        update: New items to add (or None)

    Returns:
        Combined list with no consecutive duplicates
    """
    current = current or []
    update = update or []
    result = list(current)
    for item in update:
        if not result or result[-1] != item:
            result.append(item)
    return result


def merge_dicts(current: dict | None, update: dict | None) -> dict:
    """
    Merge two dicts, with __reset__ sentinel support.

    If update contains {"__reset__": True, ...rest}, returns ONLY rest,
    ignoring current entirely. This clears stale booking data on mode transitions.

    Otherwise performs standard shallow merge (update wins on conflict).
    If either argument is None, it is treated as an empty dict.

    Args:
        current: Current dict value in state (or None)
        update: New dict to merge in (or None)

    Returns:
        Merged dict (or reset dict if __reset__ sentinel present)

    Examples:
        >>> merge_dicts({"a": 1}, {"b": 2})
        {"a": 1, "b": 2}
        >>> merge_dicts({"a": 1, "step": "old"}, {"__reset__": True, "step": "new"})
        {"step": "new"}
        >>> merge_dicts(None, None)
        {}
    """
    current = current or {}
    update = update or {}
    if update.get("__reset__"):
        return {k: v for k, v in update.items() if k != "__reset__"}
    return {**current, **update}


# ============================================================================
# transition_mode — Helper to build state updates for mode transitions
# ============================================================================


def transition_mode(
    state: "ConversationState",
    new_mode: str,
    context_update: dict | None = None,
) -> dict:
    """
    Build state update dict for transitioning to a new mode.

    Clears mode_context (via __reset__ sentinel) to prevent stale booking data
    from leaking across mode boundaries. Appends the old mode to mode_history.
    Saves old mode_context as a draft in draft_contexts (keyed by old mode name).

    Args:
        state: Current conversation state
        new_mode: Target mode name (GREETING/BOOKING/GENERAL/ESCALATION)
        context_update: Optional additional keys to include in the new mode_context
                        alongside the __reset__ sentinel.

    Returns:
        Partial state dict with:
        - current_mode: new_mode
        - previous_mode: old current_mode (for back-tracking)
        - mode_context: {"__reset__": True, ...context_update}
        - mode_history: list containing the OLD mode (appended)
        - draft_contexts: old mode_context saved under old mode key (if non-empty
                          and mode actually changed)
        - updated_at: ISO 8601 timestamp of transition

    Example:
        >>> update = transition_mode(state, "GENERAL")
        >>> # update["mode_context"] will contain {"__reset__": True}
        >>> # Which merge_dicts will use to reset stale booking data
        >>> update = transition_mode(state, "BOOKING", context_update={"intent": "book"})
        >>> # update["mode_context"] == {"__reset__": True, "intent": "book"}
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    old_mode = state.get("current_mode") or "GREETING"
    history = list(state.get("mode_history", []))
    # Append the OLD mode to history (history tracks from where we came)
    history.append(old_mode)

    # Build new mode_context with __reset__ sentinel + any new data
    new_mode_context: dict = {"__reset__": True}
    if context_update:
        new_mode_context.update(context_update)

    # Save old mode_context as draft (only if mode changed and context is non-empty)
    old_mode_context = state.get("mode_context") or {}
    existing_drafts = dict(state.get("draft_contexts") or {})
    if old_mode != new_mode and old_mode_context:
        existing_drafts[old_mode] = dict(old_mode_context)

    now_str = datetime.now(ZoneInfo("Europe/Madrid")).isoformat()

    return {
        "current_mode": new_mode,
        "previous_mode": old_mode,
        "mode_context": new_mode_context,
        "mode_history": history,
        "draft_contexts": existing_drafts,
        "updated_at": now_str,
    }


class ConversationState(TypedDict, total=False):
    """
    State schema for v3.2 architecture with granular state detection.

    This TypedDict defines conversation context plus booking state flags for
    granular prompt loading. All fields are optional (total=False) to allow
    partial state updates.

    Core Principle: GPT-4.1-mini + tools handle all logic. State stores:
    - Conversation history (messages)
    - Booking progress flags (for granular prompt loading)
    - Metadata for checkpointing
    - Escalation state

    v3.2 Enhancement: Added service_selected, slot_selected flags to enable
    7-state detection (GENERAL, SERVICE_SELECTION, AVAILABILITY_CHECK,
    CUSTOMER_DATA, BOOKING_CONFIRMATION, BOOKING_EXECUTION, POST_BOOKING)
    for focused prompt loading.

    Fields (31 total):
        # Core Metadata (5 fields)
        conversation_id: LangGraph thread_id for checkpointing
        customer_phone: E.164 phone (e.g., +34612345678)
        messages: Recent conversation history (FIFO windowing)
            Format: [{"role": "user"|"assistant", "content": str, "timestamp": str}]
            Use add_message() helper to ensure correct format
        metadata: Flexible dict for custom data
        user_message: Incoming message to process

        # Message Management (2 fields)
        conversation_summary: Summary for context window management
        total_message_count: Total messages (including summarized)

        # Escalation Tracking (3 fields)
        escalation_triggered: Whether escalated to human
        escalation_reason: Why escalated (e.g., "medical_consultation")
        error_count: Consecutive errors (for auto-escalation)

        # Tool Execution Tracking - v3.2 Enhanced (5 fields)
        customer_data_collected: True after manage_customer returns customer_id
        service_selected: List of service names selected (e.g., ["CORTE LARGO", "TINTE COMPLETO"])
        slot_selected: Selected slot dict {stylist_id, start_time, duration}
        booking_confirmed: True after user confirms booking summary
        appointment_created: True after book() successfully creates appointment

        # Node Tracking (1 field)
        last_node: Last executed node (for debugging)

        # Timestamps (2 fields)
        created_at: Conversation start (Europe/Madrid)
        updated_at: Last modification (Europe/Madrid)

        # First Interaction Detection (4 fields) - v3.3 customer greeting, v6.2 deferred customer creation
        is_first_interaction: True if customer's first message ever (messages empty)
        customer_first_name: Current first_name from database Customer record
        pending_whatsapp_name: v6.2 WhatsApp display name for pass-through (not used for creation)
        ai_disclosure_sent: True after the first-turn AI disclosure has been delivered

        # Cancellation Flow State (3 fields) - v3.4 customer-initiated cancellation
        cancellation_in_progress: True when in cancellation flow
        pending_cancellation_id: UUID string of appointment selected for cancellation
        cancellation_appointments: List of appointment dicts shown for selection

        # Pending Decline State (2 fields) - v3.5 double confirmation for cancellation
        pending_decline_appointment_id: UUID of appointment awaiting decline confirmation
        pending_decline_initiated_at: ISO 8601 timestamp when decline was initiated

        # Deprecated Fields (2 fields - kept for backward compatibility, will be removed)
        customer_id: DEPRECATED - tools handle customer identification internally
        customer_name: DEPRECATED - tools handle customer name internally
    """

    # ============================================================================
    # Core Metadata (5 fields)
    # ============================================================================
    conversation_id: str
    customer_phone: str
    messages: Annotated[list[dict[str, Any]], operator_add]
    metadata: dict[str, Any]
    user_message: str | None

    # ============================================================================
    # Message Management (2 fields)
    # ============================================================================
    conversation_summary: str | None
    total_message_count: int

    # ============================================================================
    # Escalation Tracking (3 fields)
    # ============================================================================
    escalation_triggered: bool
    escalation_reason: str | None
    error_count: int

    # ============================================================================
    # Tool Execution Tracking (5 fields) - v3.2 enhanced state detection
    # ============================================================================
    customer_data_collected: bool  # True after manage_customer returns customer_id
    service_selected: (
        list[str] | None
    )  # List of service names selected by user (supports multi-service booking)
    slot_selected: dict[str, Any] | None  # Selected slot: {stylist_id, start_time, duration}
    booking_confirmed: bool  # True after user confirms booking summary
    appointment_created: bool  # True after book() successfully creates appointment

    # ============================================================================
    # FSM State - ADR-011: Single Source of Truth (1 field)
    # ============================================================================
    fsm_state: dict[str, Any] | None  # DEPRECATED: use booking substep context instead

    # ============================================================================
    # Node Tracking (1 field)
    # ============================================================================
    last_node: str | None

    # ============================================================================
    # Timestamps (2 fields) — stored as ISO 8601 strings
    # ============================================================================
    created_at: str
    updated_at: str

    # ============================================================================
    # First Interaction Detection (4 fields) - v3.3 customer greeting, v6.2 deferred customer creation
    # ============================================================================
    is_first_interaction: bool  # True if this is the customer's first message ever
    ai_disclosure_sent: bool  # True after the first-turn AI disclosure has been delivered
    customer_first_name: str | None  # Current customer first_name from database
    pending_whatsapp_name: (
        str | None
    )  # v6.2: WhatsApp display name for pass-through to booking flow

    # ============================================================================
    # Cancellation Flow State (3 fields) - v3.4 customer-initiated cancellation
    # ============================================================================
    cancellation_in_progress: bool  # True when in cancellation flow
    pending_cancellation_id: str | None  # UUID of appointment selected for cancellation
    cancellation_appointments: list[dict[str, Any]] | None  # Appointments shown for selection

    # ============================================================================
    # Booking State Flags (5 fields) - created by book tool result
    # ============================================================================
    customer_data_collected: bool  # True after manage_customer returns customer_id
    service_selected: (
        list[str] | None
    )  # List of service names selected by user (supports multi-service booking)
    slot_selected: dict[str, Any] | None  # Selected slot: {stylist_id, start_time, duration}
    booking_confirmed: bool  # True after user confirms booking summary
    appointment_created: bool  # True after book() successfully creates appointment

    # ============================================================================
    # Node Tracking (1 field)
    # ============================================================================
    pending_decline_appointment_id: str | None  # UUID of appointment pending decline confirmation
    pending_decline_initiated_at: str | None  # ISO 8601 timestamp when decline was initiated
    pending_confirmation_appointment_id: (
        str | None
    )  # UUID string of appointment awaiting confirm/decline reply

    # ============================================================================
    # v6.0 Mode-Based Architecture Fields
    # mode_context may carry GREETING subflow keys such as greeting_step,
    # suggested_name, and the router-owned last_intent metadata.
    # ============================================================================
    current_mode: str  # Active mode: GREETING / BOOKING / GENERAL / ESCALATION
    previous_mode: str | None  # Previous mode (for back-tracking and debugging)
    mode_context: Annotated[
        dict[str, Any], merge_dicts
    ]  # Mode-specific transient data (booking_step, last_intent, etc.)
    mode_history: Annotated[
        list[str], append_unique_list
    ]  # Ordered list of mode transitions (for debugging)
    draft_contexts: Annotated[
        dict[str, Any], merge_dicts
    ]  # Saved mode contexts keyed by mode name (for resumption)

    # ============================================================================
    # v6.1 Booking Context — typed, durable booking state (Phase 1 + Phase 2)
    # Uses replace_booking_context reducer: full-replace, no stale key zombies.
    # All booking keys (last_services, last_stylist, offered_slots, etc.) live
    # here instead of mode_context. mode_context retains only routing metadata.
    # ============================================================================
    booking_context: Annotated[BookingContext | None, replace_booking_context]

    # ============================================================================
    # Resilience Layer Fields (v5.1)
    # ============================================================================
    retry_state: dict[str, Any] | None  # Retry state for resilience layer
    fallback_metrics: dict[str, Any] | None  # Metrics from fallback chain

    # ============================================================================
    # Deprecated Fields (kept for backward compatibility - will be removed)
    # ============================================================================
    customer_id: UUID | None  # DEPRECATED: Tools manage customer_id internally
    customer_name: str | None  # DEPRECATED: Tools manage customer_name internally


# ============================================================================
# create_initial_state — Factory for test/agent bootstrap
# ============================================================================


def create_initial_state(
    conversation_id: str,
    customer_phone: str = "",
    customer_name: str | None = None,
    customer_id: str | None = None,
) -> dict[str, Any]:
    """
    Create a minimal valid initial ConversationState dict.

    Used by tests and agent/main.py to bootstrap a new conversation.
    All optional fields default to safe/empty values.

    Args:
        conversation_id: LangGraph thread_id (unique per conversation)
        customer_phone: E.164 phone number (e.g., "+34612345678")
        customer_name: Customer first name if already known (returning customer)
        customer_id: Customer DB UUID if already known (returning customer)

    Returns:
        Dict compatible with ConversationState TypedDict
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Europe/Madrid"))
    now_str = now.isoformat()

    return {
        # Core metadata
        "conversation_id": conversation_id,
        "customer_phone": customer_phone,
        "messages": [],
        "metadata": {},
        "user_message": None,
        # Message management
        "conversation_summary": None,
        "total_message_count": 0,
        # Escalation
        "escalation_triggered": False,
        "escalation_reason": None,
        "error_count": 0,
        # Tool tracking
        "customer_data_collected": False,
        "service_selected": None,
        "slot_selected": None,
        "booking_confirmed": False,
        "appointment_created": False,
        # Node tracking
        "last_node": None,
        # Timestamps (ISO 8601 strings)
        "created_at": now_str,
        "updated_at": now_str,
        # First interaction
        "is_first_interaction": True,
        "ai_disclosure_sent": False,
        "customer_first_name": customer_name,
        "pending_whatsapp_name": None,
        # Cancellation flow
        "cancellation_in_progress": False,
        "pending_cancellation_id": None,
        "cancellation_appointments": None,
        # Decline flow
        "pending_decline_appointment_id": None,
        "pending_decline_initiated_at": None,
        "pending_confirmation_appointment_id": None,
        # v6.0 mode fields
        "current_mode": "GREETING",
        "previous_mode": None,
        "mode_context": {},
        "mode_history": [],
        "draft_contexts": {},
        # v6.1 booking context (typed, replace-reducer — no stale key zombies)
        "booking_context": {},
        # Resilience layer
        "retry_state": None,
        "fallback_metrics": None,
        # Deprecated (kept for backward compat)
        "customer_id": customer_id,
        "customer_name": customer_name,
    }

"""
ConversationState schema for LangGraph StateGraph — M2 refactor.

This module defines the typed state structure for the mode-based architecture.
The state is immutable — nodes must return new dicts rather than mutating the input.

Milestone 2 (`refactor/create-agent-migration`) introduces:
- A typed ``BookingContext`` TypedDict that captures every booking-flow key
  currently stored under ``state["booking_context"]``.
- A generic ``replace_dict`` reducer (full-replace semantics, ``None`` is a no-op)
  that is used for ``booking_context``. ``replace_booking_context`` remains as
  a thin backwards-compat alias so pre-existing tests and callers keep working.
- Deduplication of the ``customer_data_collected`` TypedDict annotation (it was
  declared twice; only the last ever took effect at runtime).

The ``merge_dicts`` reducer and its ``__reset__`` sentinel are retained for
``mode_context`` and ``draft_contexts`` because the router, modes, and several
test suites rely on the sentinel to clear stale mode data in place. A full
migration off ``__reset__`` is scheduled for Milestone 8.
"""

from __future__ import annotations

from operator import add as operator_add
from typing import Annotated, Any, TypedDict
from uuid import UUID


# ============================================================================
# BookingContext — Typed dict for durable booking state
# ============================================================================


class BookingContext(TypedDict, total=False):
    """
    Typed container for every booking-flow field used by the agent.

    All keys are optional (``total=False``) because the context is built
    incrementally as the booking conversation progresses. The fields listed
    here mirror the keys that ``agent/modes/booking_mode.py``,
    ``agent/tools/booking_data_tools.py``, and ``agent/graphs/conversation_flow.py``
    actually read or write.

    The reducer attached to the ``booking_context`` state field is
    ``replace_dict``: any non-``None`` update fully replaces the previous
    context. This guarantees that deleted keys (for example, ``offered_slots``
    after a slot is selected) actually disappear from state instead of
    lingering as zombies.
    """

    # ── Booking step FSM ────────────────────────────────────────────────
    booking_step: str  # service_selection | stylist_selection | datetime_selection | name_collection | confirmation

    # ── Service data ────────────────────────────────────────────────────
    last_services: list[str]  # e.g. ["CORTE LARGO"]
    last_service_category: str | None  # ServiceCategory.value (e.g. "MUJER")
    last_total_duration_minutes: int | None

    # ── Stylist data ────────────────────────────────────────────────────
    last_stylist: str | None
    no_preference_stylist: bool | None
    available_stylists: list[str] | None
    _offered_stylists: list[str] | None  # includes "Sin preferencia" sentinel

    # ── Slot data ───────────────────────────────────────────────────────
    offered_slots: list[dict[str, Any]] | None
    selected_slot: dict[str, Any] | None

    # ── Customer data ───────────────────────────────────────────────────
    customer_name: str | None
    customer_first_name: str | None
    customer_last_name: str | None
    customer_id: str | None

    # ── Handoff hints from router / greeting mode ───────────────────────
    opening_booking_request: str | None
    service_audience_hint: str | None
    preferred_stylist_name: str | None
    preferred_date_hint: str | None

    # ── Flow control / UX flags ─────────────────────────────────────────
    add_more_asked: bool
    notes: str | None
    notes_asked: bool
    _booking_completed: bool
    _confirmation_shown: bool  # Solo setteable via return path explícito al reducer en _post_tool_result. No mutar in-place fuera de ese bloque.
    _disambiguation_questions_shown: bool
    _suggested_customer_name: str | None


# ============================================================================
# replace_dict — Clean full-replace reducer for dict-shaped state
# ============================================================================


def replace_dict(current: dict | None, update: dict | None) -> dict:
    """
    Full-replace reducer for dict-shaped state fields.

    Semantics:
    - ``update is None``  → keep ``current`` unchanged (or ``{}`` if ``current`` is ``None``).
    - ``update is not None`` (including ``{}``) → return a fresh copy of ``update``.

    This reducer is intentionally simple. It does not merge keys and it does
    not honor the legacy ``__reset__`` sentinel — callers get clean "last
    write wins" semantics across the whole dict, which is exactly what
    ``booking_context`` needs to avoid stale-key zombies.

    Args:
        current: Previous value from the checkpoint (may be ``None``).
        update: New value returned by a node (``None`` means "no-op").

    Returns:
        The resolved dict. A shallow ``dict(update)`` copy is made when an
        update is provided so that mutating the result cannot leak back into
        the caller.
    """
    if update is not None:
        return dict(update)
    return dict(current) if current else {}


# Backwards-compat alias: a number of tests and modules still import
# ``replace_booking_context`` from this module. They all expect the exact
# full-replace semantics that ``replace_dict`` now provides.
replace_booking_context = replace_dict


# ============================================================================
# Legacy reducers — kept for backwards compatibility (scheduled for M8 cleanup)
# ============================================================================


def preserve_if_none(current: Any, update: Any) -> Any:
    """
    Reducer that keeps ``current`` when ``update`` is ``None``.

    Used for fields that should not be overwritten with ``None`` once set
    (for example, ``customer_name`` and ``customer_id``).
    """
    if update is None:
        return current
    return update


def append_unique_list(current: list | None, update: list | None) -> list:
    """
    Append items from ``update`` to ``current`` while suppressing consecutive
    duplicates.

    Used for ``mode_history`` to avoid noisy adjacent repeats of the same mode.
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
    Shallow-merge two dicts with ``__reset__`` sentinel support.

    If ``update`` is ``{"__reset__": True, ...rest}`` the reducer returns only
    the ``rest`` keys, dropping everything previously in ``current``. Otherwise
    it performs ``{**current, **update}``.

    This reducer is DEPRECATED and will be removed in Milestone 8 once every
    caller (``mode_context``, ``draft_contexts``, and the router's
    ``transition_mode`` helper) is migrated to ``replace_dict``. It is kept
    here so the existing router, modes, and regression tests continue to work
    unchanged during the create_agent migration.
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
    Build a partial state update for transitioning to ``new_mode``.

    Under the ``replace_dict`` reducer (SDD #2, P2) the returned
    ``mode_context`` IS the full new context — callers do not need to merge
    with the previous mode's context, and there is no ``__reset__`` sentinel.
    Stale routing metadata from the outgoing mode is dropped automatically
    because replace_dict semantics fully overwrite the field.

    Returns a partial ``ConversationState`` dict containing:

    - ``current_mode``  → ``new_mode``
    - ``previous_mode`` → the previous ``current_mode``
    - ``mode_context``  → ``dict(context_update)`` (or ``{}`` when None)
    - ``mode_history``  → list containing the outgoing mode (appended)
    - ``draft_contexts``→ outgoing ``mode_context`` saved under its mode key
      (only when the mode actually changed and the previous context was non-empty)
    - ``updated_at``    → ISO 8601 timestamp (Europe/Madrid)
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    old_mode = state.get("current_mode") or "GREETING"
    history = list(state.get("mode_history", []))
    history.append(old_mode)

    new_mode_context: dict = dict(context_update) if context_update else {}

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


# ============================================================================
# ConversationState — Top-level state schema
# ============================================================================


class ConversationState(TypedDict, total=False):
    """
    Top-level state schema for the v6.x mode-based conversation graph.

    All fields are optional (``total=False``) to allow partial state updates.
    Custom reducers are attached via ``Annotated[T, reducer_fn]``.
    """

    # ── Core metadata ────────────────────────────────────────────────────
    conversation_id: str
    customer_phone: str
    messages: Annotated[list[dict[str, Any]], operator_add]
    metadata: dict[str, Any]
    user_message: str | None

    # ── Message management ──────────────────────────────────────────────
    conversation_summary: str | None
    total_message_count: int

    # ── Escalation tracking ─────────────────────────────────────────────
    escalation_triggered: bool
    escalation_reason: str | None
    error_count: int

    # ── Tool-execution / booking-flag tracking ──────────────────────────
    # NOTE: ``customer_data_collected`` was previously declared twice in this
    # TypedDict. Python keeps only the last annotation at runtime so the
    # duplicate had no effect, but it was confusing. Consolidated into a
    # single block here.
    customer_data_collected: bool
    service_selected: list[str] | None
    slot_selected: dict[str, Any] | None
    booking_confirmed: bool
    appointment_created: bool

    # ── Legacy FSM (deprecated — removed in M8) ─────────────────────────
    fsm_state: dict[str, Any] | None

    # ── Node tracking / timestamps ──────────────────────────────────────
    last_node: str | None
    created_at: str
    updated_at: str

    # ── First interaction detection ─────────────────────────────────────
    is_first_interaction: bool
    ai_disclosure_sent: bool
    customer_first_name: str | None
    pending_whatsapp_name: str | None

    # ── Cancellation / decline flow ─────────────────────────────────────
    cancellation_in_progress: bool
    pending_cancellation_id: str | None
    cancellation_appointments: list[dict[str, Any]] | None
    pending_decline_appointment_id: str | None
    pending_decline_initiated_at: str | None
    pending_confirmation_appointment_id: str | None

    # ── Mode-based architecture ─────────────────────────────────────────
    current_mode: str
    previous_mode: str | None
    mode_context: Annotated[dict[str, Any], merge_dicts]
    mode_history: Annotated[list[str], append_unique_list]
    draft_contexts: Annotated[dict[str, Any], merge_dicts]

    # ── Typed booking context (replace-dict reducer) ────────────────────
    booking_context: Annotated[BookingContext | None, replace_dict]

    # ── Cross-conversation customer memory (Store API) ──────────────────
    customer_memories: dict[str, Any] | None

    # ── Resilience layer ────────────────────────────────────────────────
    retry_state: dict[str, Any] | None
    fallback_metrics: dict[str, Any] | None

    # ── Deprecated (kept for backwards compatibility) ───────────────────
    customer_id: UUID | None
    customer_name: str | None


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

    Used by tests and ``agent/main.py`` to bootstrap a new conversation. All
    optional fields default to safe/empty values.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now_str = datetime.now(ZoneInfo("Europe/Madrid")).isoformat()

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
        # Cross-conversation memory (v6.3 Store API)
        "customer_memories": None,
        # Deprecated (kept for backward compat)
        "customer_id": customer_id,
        "customer_name": customer_name,
    }

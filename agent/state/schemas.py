"""
ConversationState schema for LangGraph StateGraph - v6.0 Mode-Based Architecture.

This module defines the typed state structure for the agent-architecture-rebuild.
State uses Annotated reducers for proper LangGraph checkpoint merging.

Architecture:
- Mode-based routing replaces FSM-driven booking flow
- Reducers ensure fields persist correctly between conversation turns
- Single source of truth: LangGraph checkpoint (Redis)
- No FSM dependency — all flow control via mode + LLM reasoning

Design principles:
- Fields WITH reducers: persist between turns (merge, not replace)
- Fields WITHOUT reducers: replaced each turn (transient data)
- preserve_if_none: simple scalar values that should survive turns
- merge_dicts: nested dicts that accumulate across turns
- add (operator): append-only message list
"""

from __future__ import annotations

from datetime import datetime
from operator import add
from typing import Annotated, Any, Literal, TypedDict
from zoneinfo import ZoneInfo


# ============================================================================
# Reducer Functions
# ============================================================================


def preserve_if_none(current: Any, update: Any) -> Any:
    """
    Preserve checkpoint value if update is None.

    Use for fields that should persist unless explicitly changed.
    If the incoming update is None, keep the existing checkpoint value.

    Args:
        current: Value from checkpoint (previous turn)
        update: Value from current node output

    Returns:
        update if not None, else current
    """
    if update is None:
        return current
    return update


def merge_dicts(current: dict | None, update: dict | None) -> dict:
    """
    Shallow merge dictionaries, preserving existing keys.

    Use for nested data structures that accumulate across turns:
    - mode_context: Per-mode working data
    - draft_contexts: Saved contexts from other modes

    Behavior:
    - If update is None → return current (preserve)
    - If current is None → return update (initialize)
    - Otherwise → shallow merge {**current, **update}

    Args:
        current: Value from checkpoint
        update: Value from current node output

    Returns:
        Merged dict (never None)
    """
    if update is None:
        return current or {}
    if current is None:
        return update or {}
    return {**current, **update}


def append_unique_list(current: list | None, update: list | None) -> list:
    """
    Append to list, avoiding duplicates.

    Use for mode_history to track navigation without repeating entries.

    Args:
        current: List from checkpoint
        update: List from current node output

    Returns:
        Combined list with unique items only
    """
    if update is None:
        return current or []
    if current is None:
        return update or []
    result = list(current)
    for item in update:
        if item not in result:
            result.append(item)
    return result


# ============================================================================
# Mode Definition
# ============================================================================

ConversationMode = Literal["GREETING", "BOOKING", "GENERAL", "ESCALATION"]
"""
Conversation modes for the mode-based architecture.

- GREETING: Initial contact / first interaction
- BOOKING: Appointment booking flow
- GENERAL: Informational queries (FAQs, hours, services)
- ESCALATION: Human handoff triggered
"""


# ============================================================================
# Main State Schema
# ============================================================================


class ConversationState(TypedDict, total=False):
    """
    State schema for v6.0 mode-based architecture.

    All fields are optional (total=False) to allow partial state updates.
    Nodes return dicts with only changed fields; reducers handle merging.

    CRITICAL — Reducer rules:
    - Annotated[T, preserve_if_none]: scalar value persists unless explicitly set
    - Annotated[dict, merge_dicts]: dict merges with checkpoint value
    - Annotated[list, add]: list appends (from operator.add)
    - Annotated[list, append_unique_list]: list appends without duplicates
    - No annotation: field is REPLACED each turn (transient)

    Fields (22 total):

    # Core Identity (4 fields)
        conversation_id: LangGraph thread_id — stable across all turns
        customer_phone: E.164 format (e.g., +34612345678)
        customer_id: Database UUID (str) for the Customer record
        customer_name: Display name for the customer

    # Mode Management (5 fields)
        current_mode: Active conversation mode (ConversationMode)
        previous_mode: Mode before last transition (for context)
        mode_history: Ordered list of visited modes (unique, append-only)
        mode_context: Arbitrary per-mode working data (merged across turns)
        draft_contexts: Saved context snapshots keyed by mode name

    # Messages (3 fields)
        messages: Append-only conversation history
            Format: [{"role": "user"|"assistant", "content": str, "timestamp": str}]
        user_message: Current incoming message (transient — replaced each turn)
        conversation_summary: FIFO summary of older messages (for context compression)

    # Message Metadata (2 fields)
        total_message_count: Total messages including summarized ones
        is_first_interaction: True only on the very first message of a conversation

    # Escalation (3 fields)
        escalation_triggered: True once escalation_to_human is called
        escalation_reason: Why escalation was triggered
        error_count: Consecutive LLM/tool errors (auto-escalates at threshold)

    # Resilience Layer (2 fields)
        retry_state: Current LLM call retry progress; reset to None on success
        fallback_metrics: Provider-switch metrics from FallbackChain; None if no switch

    # Timestamps (2 fields)
        created_at: Conversation start time (ISO 8601, Europe/Madrid)
        updated_at: Last state modification (ISO 8601, Europe/Madrid)

    # Debug (1 field)
        last_node: Last executed LangGraph node name
    """

    # ============================================================================
    # Core Identity (persisted via reducers)
    # ============================================================================
    conversation_id: Annotated[str | None, preserve_if_none]
    customer_phone: Annotated[str | None, preserve_if_none]
    customer_id: Annotated[str | None, preserve_if_none]
    customer_name: Annotated[str | None, preserve_if_none]

    # ============================================================================
    # Mode Management (persisted via reducers)
    # ============================================================================
    current_mode: Annotated[str | None, preserve_if_none]   # ConversationMode literal
    previous_mode: Annotated[str | None, preserve_if_none]
    mode_history: Annotated[list, append_unique_list]
    mode_context: Annotated[dict, merge_dicts]
    draft_contexts: Annotated[dict, merge_dicts]

    # ============================================================================
    # Messages
    # ============================================================================
    messages: Annotated[list, add]           # append-only via operator.add
    user_message: str | None                 # transient — replaced each turn
    conversation_summary: str | None

    # ============================================================================
    # Message Metadata
    # ============================================================================
    total_message_count: int
    is_first_interaction: bool

    # ============================================================================
    # Escalation Tracking (persisted via reducers)
    # ============================================================================
    escalation_triggered: bool
    escalation_reason: str | None
    error_count: int

    # ============================================================================
    # Resilience Layer (persisted via reducers)
    # ============================================================================
    retry_state: Annotated[dict | None, preserve_if_none]
    fallback_metrics: Annotated[dict | None, preserve_if_none]

    # ============================================================================
    # Timestamps (persisted via reducers)
    # ============================================================================
    created_at: Annotated[str | None, preserve_if_none]
    updated_at: str | None                   # transient — updated each turn

    # ============================================================================
    # Debug
    # ============================================================================
    last_node: str | None


# ============================================================================
# Factory Function
# ============================================================================


def create_initial_state(
    conversation_id: str,
    customer_phone: str,
) -> ConversationState:
    """
    Create a fully initialised ConversationState for a new conversation.

    Args:
        conversation_id: LangGraph thread_id (stable, used as checkpoint key)
        customer_phone: Customer phone in E.164 format (e.g., +34612345678)

    Returns:
        Fully initialised ConversationState with sensible defaults.
    """
    now = datetime.now(ZoneInfo("Europe/Madrid")).isoformat()

    return ConversationState(
        # Core Identity
        conversation_id=conversation_id,
        customer_phone=customer_phone,
        customer_id=None,
        customer_name=None,
        # Mode Management
        current_mode="GREETING",
        previous_mode=None,
        mode_history=[],
        mode_context={},
        draft_contexts={},
        # Messages
        messages=[],
        user_message=None,
        conversation_summary=None,
        # Message Metadata
        total_message_count=0,
        is_first_interaction=True,
        # Escalation
        escalation_triggered=False,
        escalation_reason=None,
        error_count=0,
        # Resilience
        retry_state=None,
        fallback_metrics=None,
        # Timestamps
        created_at=now,
        updated_at=now,
        # Debug
        last_node=None,
    )


# ============================================================================
# Mode Transition Helper
# ============================================================================


def transition_mode(
    current_state: ConversationState,
    new_mode: str,
    context_update: dict | None = None,
) -> dict:
    """
    Build a partial state update dict for a mode transition.

    This function does NOT mutate ``current_state``. It returns a dict
    suitable for merging by LangGraph reducers.

    Behavior:
    1. Save current mode_context into draft_contexts under the old mode key.
    2. Set previous_mode to the current mode.
    3. Set current_mode to new_mode.
    4. Reset mode_context to context_update (or empty dict if none provided).
    5. Append old mode to mode_history.

    Args:
        current_state: Current conversation state (not mutated).
        new_mode: Target ConversationMode to transition to.
        context_update: Optional initial context for the new mode.

    Returns:
        Partial state update dict. Merge into LangGraph state via node return.

    Example:
        >>> update = transition_mode(state, "BOOKING", {"intent": "book_appointment"})
        >>> # Return update from your node; reducers will merge it
    """
    now = datetime.now(ZoneInfo("Europe/Madrid")).isoformat()
    old_mode = current_state.get("current_mode")
    old_context = current_state.get("mode_context") or {}

    # Save current context as draft if mode is changing
    draft_update: dict = {}
    if old_mode and old_mode != new_mode and old_context:
        draft_update = {old_mode: old_context}

    # Build mode_history entry (single item list — append_unique_list will merge)
    history_entry: list = [old_mode] if old_mode else []

    return {
        "current_mode": new_mode,
        "previous_mode": old_mode,
        "mode_history": history_entry,
        "mode_context": context_update or {},
        "draft_contexts": draft_update,
        "updated_at": now,
    }

"""
ConversationState schema for LangGraph StateGraph - v5.0 FSM Architecture.

This module defines the typed state structure for v5.0 architecture with FSM-driven booking flow.
The state is immutable - nodes must return new dicts rather than mutating the input state.

Architecture:
- Single conversational_agent node handles all conversation via GPT-4.1-mini + 8 consolidated tools
- Booking delegated to BookingTransaction handler (atomic, no graph nodes)
- FSM state consolidated in LangGraph checkpoint (ADR-011: Single Source of Truth)
"""

from datetime import datetime
from typing import Any, Literal, TypedDict
from uuid import UUID

from agent.resilience.retry_strategy import RetryState
from agent.resilience.error_classifier import FallbackMetrics


class ConversationState(TypedDict, total=False):
    """
    State schema for v5.0 FSM architecture.

    This TypedDict defines conversation context for the FSM-driven booking flow.
    All fields are optional (total=False) to allow partial state updates.

    Core Principle: GPT-4.1-mini + tools handle all logic. State stores:
    - Conversation history (messages)
    - FSM state (ADR-011: Single Source of Truth in LangGraph checkpoint)
    - Metadata for checkpointing
    - Escalation state

    Fields (28 total):
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

        # FSM State - ADR-011: Single Source of Truth (1 field)
        fsm_state: Consolidated FSM state from BookingFSM
            Structure: {"state": str, "collected_data": dict, "last_updated": str}
            Use BookingFSM.to_dict() to serialize, BookingFSM.from_dict() to deserialize
            Replaces separate fsm:{conversation_id} Redis key (eliminated dual persistence)

        # Node Tracking (1 field)
        last_node: Last executed node (for debugging)

        # Timestamps (2 fields)
        created_at: Conversation start (Europe/Madrid)
        updated_at: Last modification (Europe/Madrid)

        # First Interaction Detection (6 fields) - v3.3 customer greeting, v6.1 name confirmation, v6.2 deferred customer creation
        is_first_interaction: True if customer's first message ever (messages empty)
        customer_needs_name: True if WhatsApp name contains numbers/emojis
        customer_first_name: Current first_name from database Customer record
        name_confirmation_pending: v6.1 True while waiting for name confirmation
        pending_intent: v6.1 Stores user message if they express intent before confirming name
        pending_whatsapp_name: v6.2 WhatsApp name stored for customer creation after name confirmation

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

        # Resilience Layer State (2 fields) - Phase 4 integration
        retry_state: Optional retry tracking state for the current LLM call
            Structure from RetryStrategy: {attempt_count, last_error_type, next_retry_at,
            total_retries_used, budget_exhausted}
            Reset to None after a successful response.
        fallback_metrics: Optional metrics from FallbackChain on last provider switch
            Structure: {primary_provider, fallback_provider, primary_error_type,
            fallback_succeeded, latency_ms}
            Populated when FallbackChain switches providers.
    """

    # ============================================================================
    # Core Metadata (5 fields)
    # ============================================================================
    conversation_id: str
    customer_phone: str
    messages: list[dict[str, Any]]
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
    # FSM State - ADR-011: Single Source of Truth (1 field)
    # ============================================================================
    fsm_state: dict[str, Any] | None  # BookingFSM serialized state: {state, collected_data, last_updated}

    # ============================================================================
    # Node Tracking (1 field)
    # ============================================================================
    last_node: str | None

    # ============================================================================
    # Timestamps (2 fields)
    # ============================================================================
    created_at: datetime
    updated_at: datetime

    # ============================================================================
    # First Interaction Detection (6 fields) - v3.3 customer greeting, v6.1 name confirmation, v6.2 deferred customer creation
    # ============================================================================
    is_first_interaction: bool  # True if this is the customer's first message ever
    customer_needs_name: bool  # True if WhatsApp name is not readable (numbers/emojis)
    customer_first_name: str | None  # Current customer first_name from database
    name_confirmation_pending: bool  # v6.1: True while waiting for user to confirm/provide name
    pending_intent: str | None  # v6.1: Stores user message if they express intent before confirming name
    pending_whatsapp_name: str | None  # v6.2: WhatsApp name stored for customer creation after name confirmation

    # ============================================================================
    # Cancellation Flow State (3 fields) - v3.4 customer-initiated cancellation
    # ============================================================================
    cancellation_in_progress: bool  # True when in cancellation flow
    pending_cancellation_id: str | None  # UUID of appointment selected for cancellation
    cancellation_appointments: list[dict[str, Any]] | None  # Appointments shown for selection

    # ============================================================================
    # Pending Decline State (2 fields) - v3.5 double confirmation for cancellation
    # ============================================================================
    pending_decline_appointment_id: str | None  # UUID of appointment pending decline confirmation
    pending_decline_initiated_at: str | None  # ISO 8601 timestamp when decline was initiated

    # ============================================================================
    # Deprecated Fields (kept for backward compatibility - will be removed)
    # ============================================================================
    customer_id: UUID | None  # DEPRECATED: Tools manage customer_id internally
    customer_name: str | None  # DEPRECATED: Tools manage customer_name internally

    # ============================================================================
    # Resilience Layer State (2 fields) - Phase 4 integration
    # ============================================================================
    retry_state: RetryState | None  # Current LLM call retry progress; None on success
    fallback_metrics: FallbackMetrics | None  # FallbackChain provider-switch metrics; None if no switch

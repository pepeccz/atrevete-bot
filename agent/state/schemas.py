"""
ConversationState schema for LangGraph StateGraph - v3.2 Architecture (Optimized).

This module defines the typed state structure for v3.2 architecture with granular state detection.
The state is immutable - nodes must return new dicts rather than mutating the input state.

Architecture:
- Single conversational_agent node handles all conversation via GPT-4.1-mini + 8 consolidated tools
- Booking delegated to BookingTransaction handler (atomic, no graph nodes)
- Enhanced state tracking for granular prompt loading (6 booking states)

Evolution: v3.2 adds granular state flags (service_selected, slot_selected)
to enable focused prompt loading per booking phase, reducing token usage by 60-70%.
"""

from datetime import datetime
from typing import Any, Literal, TypedDict
from uuid import UUID


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

    Fields (20 total):
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

        # Deprecated Fields (2 fields - kept for backward compatibility, will be removed)
        customer_id: DEPRECATED - tools handle customer identification internally
        customer_name: DEPRECATED - tools handle customer name internally
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
    # Tool Execution Tracking (5 fields) - v3.2 enhanced state detection
    # ============================================================================
    customer_data_collected: bool  # True after manage_customer returns customer_id
    service_selected: list[str] | None  # List of service names selected by user (supports multi-service booking)
    slot_selected: dict[str, Any] | None  # Selected slot: {stylist_id, start_time, duration}
    booking_confirmed: bool  # True after user confirms booking summary
    appointment_created: bool  # True after book() successfully creates appointment

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
    # Deprecated Fields (kept for backward compatibility - will be removed)
    # ============================================================================
    customer_id: UUID | None  # DEPRECATED: Tools manage customer_id internally
    customer_name: str | None  # DEPRECATED: Tools manage customer_name internally

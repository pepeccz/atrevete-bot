"""
ConversationState schema for LangGraph StateGraph - v3.0 Architecture (Simplified).

This module defines the minimalist typed state structure for v3.0 architecture.
The state is immutable - nodes must return new dicts rather than mutating the input state.

Architecture:
- Single conversational_agent node handles all conversation via Claude + 7 consolidated tools
- Booking delegated to BookingTransaction handler (atomic, no graph nodes)

Simplification: Reduced from 50 fields (v2 hybrid) to 15 fields (v3 tool-based).
Claude's reasoning + tool calling replaces explicit state tracking for booking phases.
"""

from datetime import datetime
from typing import Any, Literal, TypedDict
from uuid import UUID


class ConversationState(TypedDict, total=False):
    """
    Minimalist state schema for v3.0 tool-based architecture.

    This TypedDict defines only essential conversation context. All fields are
    optional (total=False) to allow partial state updates.

    Core Principle: Claude + tools handle all logic. State only stores:
    - Conversation history (messages)
    - Metadata for checkpointing
    - Escalation state

    No booking phases, no explicit state transitions - Claude orchestrates everything
    through tool calls (query_info, manage_customer, check_availability, book, etc.)

    Fields (15 total):
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

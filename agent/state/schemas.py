"""
ConversationState schema for LangGraph StateGraph.

This module defines the typed state structure used throughout the conversational
agent workflow. The state is immutable - nodes must return new dicts rather than
mutating the input state.
"""

from datetime import datetime
from typing import Any, Literal, TypedDict
from uuid import UUID


class ConversationState(TypedDict, total=False):
    """
    State schema for conversation flow in LangGraph.

    This TypedDict defines the complete conversation context that is passed
    between nodes in the StateGraph. All fields are optional (total=False)
    to allow partial state updates.

    Fields:
        conversation_id: LangGraph thread_id used for checkpointing
        customer_phone: E.164 formatted phone number (e.g., +34612345678)
        customer_name: Customer's name (may be empty for new customers)
        messages: Recent 10 message exchanges (FIFO windowing) with 'role', 'content', 'timestamp' keys
        current_intent: Classified intent (booking, modification, cancellation, etc.)
        metadata: Flexible dict for future use and custom data

        # Optional fields for future stories:
        customer_id: Database UUID for identified customers
        is_returning_customer: Whether customer has previous bookings
        created_at: When conversation started (UTC datetime)
        updated_at: When conversation was last modified (UTC datetime)

        # Extended fields for future functionality:
        customer_history: List of previous appointments/services
        preferred_stylist_id: Customer's preferred stylist UUID
        conversation_summary: Summary of conversation for context window management
        requested_services: List of service UUIDs for booking
        suggested_pack_id: Suggested service pack UUID
        provisional_appointment_id: Temporary appointment ID before payment
        payment_link_url: Stripe payment link URL
        is_group_booking: Whether booking is for multiple people
        is_third_party_booking: Whether booking is for someone else
        escalated: Whether conversation has been escalated to human
        escalation_reason: Why escalation occurred
        awaiting_name_confirmation: Whether bot is waiting for name confirmation
        customer_identified: Whether customer has been fully identified
        clarification_attempts: Counter for ambiguous name confirmation attempts
        last_node: Name of last executed node (for debugging)
        error_count: Number of errors encountered (for escalation logic)
    """

    # Core conversation metadata (required for all conversations)
    conversation_id: str
    customer_phone: str
    customer_name: str | None
    messages: list[dict[str, Any]]
    current_intent: Literal["booking", "modification", "cancellation", "faq", "indecision", "usual_service", "escalation", "greeting_only", "inquiry"] | None
    metadata: dict[str, Any]

    # FAQ context (Story 2.6, enhanced for multi-FAQ and AI generation)
    faq_detected: bool
    detected_faq_id: str | None  # Backward compatibility: first FAQ ID
    detected_faq_ids: list[str]  # NEW: List of all detected FAQ IDs for compound queries
    query_complexity: Literal["simple", "compound", "contextual", "none"]  # NEW: Query complexity classification
    faq_context: list[dict[str, Any]]  # NEW: FAQ data from database for AI generation
    faq_answered: bool

    # Customer context (populated after identification)
    customer_id: UUID | None
    is_returning_customer: bool
    customer_history: list[dict[str, Any]]
    preferred_stylist_id: UUID | None

    # Message management (Story 2.5a, 2.5b)
    conversation_summary: str | None  # Compressed history of messages beyond recent 10 (updated every 5 exchanges)
    total_message_count: int  # Tracks all messages sent, including summarized ones

    # Booking context (populated during booking flow)
    requested_services: list[UUID]
    suggested_pack_id: UUID | None
    provisional_appointment_id: UUID | None
    payment_link_url: str | None

    # Group/third-party booking flags
    is_group_booking: bool
    is_third_party_booking: bool

    # Escalation tracking
    escalated: bool
    escalation_reason: str | None

    # Name confirmation tracking (Story 2.2)
    awaiting_name_confirmation: bool
    customer_identified: bool
    clarification_attempts: int

    # Node execution tracking
    last_node: str | None
    error_count: int

    # Timestamps
    created_at: datetime
    updated_at: datetime

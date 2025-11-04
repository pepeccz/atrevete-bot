"""
ConversationState schema for LangGraph StateGraph - Hybrid Architecture (Simplified).

This module defines the simplified typed state structure for the hybrid architecture.
The state is immutable - nodes must return new dicts rather than mutating the input state.

Architecture:
- Tier 1: Conversational agent (handles FAQs, inquiries, identification via Claude + tools)
- Tier 2: Transactional nodes (booking, payment, availability via explicit nodes)

Simplification: Reduced from 158 fields to 50 fields by removing conversational
tracking fields now handled by Claude's reasoning in the conversational_agent node.
"""

from datetime import datetime
from typing import Any, Literal, TypedDict
from uuid import UUID


class ConversationState(TypedDict, total=False):
    """
    Simplified state schema for hybrid architecture conversation flow.

    This TypedDict defines the complete conversation context that is passed
    between nodes in the StateGraph. All fields are optional (total=False)
    to allow partial state updates.

    Core Principle: Conversational orchestration is handled by Claude + tools.
    State only tracks essential data needed for transactional operations.

    Fields:
        # Core Conversation Metadata
        conversation_id: LangGraph thread_id used for checkpointing
        customer_phone: E.164 formatted phone number (e.g., +34612345678)
        customer_name: Customer's name (may be empty for new customers)
        messages: Recent 10 message exchanges (FIFO windowing) with dict format:
            {
                "role": "user" | "assistant",  # NEVER "human" or "ai" - use user/assistant only
                "content": str,                 # Message text content
                "timestamp": str                # ISO 8601 format in Europe/Madrid timezone
            }
            NOTE: Use add_message() helper from state.helpers to ensure correct format
        metadata: Flexible dict for future use and custom data

        # Customer Context (populated by customer_tools)
        customer_id: Database UUID for identified customers
        is_returning_customer: Whether customer has previous bookings
        customer_history: List of previous appointments/services
        preferred_stylist_id: Customer's preferred stylist UUID

        # Message Management (Story 2.5a, 2.5b)
        conversation_summary: Summary of conversation for context window management
        total_message_count: Tracks all messages sent, including summarized ones

        # Booking Context (Tier 2 transactional flow)
        requested_services: List of service UUIDs for booking
        requested_date: Date in YYYY-MM-DD format
        requested_time: Time in HH:MM format (if specific time requested)
        provisional_appointment_id: Temporary appointment ID before payment
        payment_link_url: Stripe payment link URL
        pending_service_clarification: Ambiguous service info when multiple matches found
            (Claude must clarify with customer before proceeding to booking)

        # Tier 1 → Tier 2 Transition
        booking_intent_confirmed: True when customer ready to book (triggers Tier 2)

        # Availability Context (Tier 2: check_availability node)
        available_slots: Available slots from multi-calendar check
        prioritized_slots: Top 2-3 slots to present to customer
        suggested_dates: Alternative dates when requested date is fully booked
        is_same_day: Flag for same-day booking (affects provisional block timeout)
        holiday_detected: Flag for holiday closure detection

        # Consultation Context (from offer_consultation_tool)
        consultation_service_id: ID of CONSULTA GRATUITA service
        skip_payment_flow: Flag to bypass payment for free consultations

        # Multi-booking Context (Tier 2: separate bookings for mixed categories)
        pending_bookings: Queue of bookings to process (for separate bookings)
        current_booking_index: Index of currently processing booking
        is_multi_booking_flow: Flag for separate booking flow

        # Booking Flags
        is_group_booking: Whether booking is for multiple people
        is_third_party_booking: Whether booking is for someone else

        # Node Execution Tracking
        last_node: Name of last executed node (for debugging)
        error_count: Number of errors encountered (for escalation logic)

        # Timestamps
        created_at: When conversation started (Europe/Madrid timezone)
        updated_at: When conversation was last modified (Europe/Madrid timezone)
    """

    # ============================================================================
    # Core Conversation Metadata (Always present)
    # ============================================================================
    conversation_id: str
    customer_phone: str
    customer_name: str | None
    messages: list[dict[str, Any]]
    metadata: dict[str, Any]
    user_message: str | None  # Incoming user message to be processed by graph nodes

    # ============================================================================
    # Customer Context (Populated by customer_tools)
    # ============================================================================
    customer_id: UUID | None
    is_returning_customer: bool
    customer_history: list[dict[str, Any]]
    preferred_stylist_id: UUID | None

    # ============================================================================
    # Message Management (Story 2.5a, 2.5b)
    # ============================================================================
    conversation_summary: str | None
    total_message_count: int

    # ============================================================================
    # Booking Context (Tier 2 Transactional Flow)
    # ============================================================================
    requested_services: list[UUID]
    requested_date: str | None
    requested_time: str | None
    provisional_appointment_id: UUID | None
    payment_link_url: str | None
    awaiting_date_input: bool  # Flag when waiting for customer to provide booking date

    # Service Ambiguity Handling (Tier 1: Conversational Agent)
    pending_service_clarification: dict[str, Any] | None  # Ambiguous service info for Claude to resolve
    # Structure: {"query": str, "options": [{"id": str, "name": str, "price_euros": float, "duration_minutes": int, "category": str}]}

    # Booking Phase Tracking (NEW - for 4-phase booking flow)
    booking_phase: Literal["service_selection", "availability", "customer_data", "payment"] | None

    # Slot Selection (NEW - Fase 2 completion)
    selected_slot: dict[str, Any] | None  # {"time": "15:00", "stylist_id": "...", "date": "2025-11-05"}
    selected_stylist_id: UUID | None  # Stylist UUID from selected slot

    # Customer Data Collection (NEW - Fase 3)
    customer_notes: str | None  # Optional notes from customer (allergies, preferences)
    awaiting_customer_name: bool  # Waiting for customer name confirmation/input
    awaiting_customer_notes: bool  # Waiting for customer notes input

    # Payment Management (NEW - Fase 4)
    payment_timeout_at: datetime | None  # When provisional booking expires
    total_price: Any  # Decimal - Total cost of services/pack
    advance_payment_amount: Any  # Decimal - 20% deposit amount

    # ============================================================================
    # Tier 1 → Tier 2 Transition Signal
    # ============================================================================
    booking_intent_confirmed: bool  # NEW: Set by conversational_agent to trigger booking flow

    # ============================================================================
    # Availability Context (Tier 2: check_availability node)
    # ============================================================================
    available_slots: list[dict[str, Any]]
    prioritized_slots: list[dict[str, Any]]
    suggested_dates: list[dict[str, Any]]
    is_same_day: bool
    holiday_detected: bool

    # ============================================================================
    # Consultation Context (from offer_consultation_tool in Tier 1)
    # ============================================================================
    consultation_service_id: UUID | None
    skip_payment_flow: bool

    # ============================================================================
    # Multi-booking Context (Tier 2: separate bookings for mixed categories)
    # ============================================================================
    pending_bookings: list[dict[str, Any]]
    current_booking_index: int
    is_multi_booking_flow: bool

    # ============================================================================
    # Booking Flags
    # ============================================================================
    is_group_booking: bool
    is_third_party_booking: bool

    # ============================================================================
    # Node Execution Tracking
    # ============================================================================
    last_node: str | None
    error_count: int

    # ============================================================================
    # Timestamps
    # ============================================================================
    created_at: datetime
    updated_at: datetime

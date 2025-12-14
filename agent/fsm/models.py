"""
FSM data models for booking flow.

This module defines the core data structures used by the BookingFSM:
- IntentType: Enum of recognized intent types
- Intent: Structured representation of user intent
- FSMResult: Result of FSM transition operations
- CollectedData: TypedDict for accumulated booking data
- FSMAction: Prescriptive action specification (v5.0 architecture)
- ToolCall: Tool call specification for FSMAction
- ActionType: Types of actions FSM can prescribe
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypedDict

# Import FSMAction system (v5.0 prescriptive architecture)
from agent.fsm.fsm_action import ActionType, FSMAction, ToolCall


class IntentType(str, Enum):
    """Types of user intent recognized by the system."""

    # Booking flow intents
    START_BOOKING = "start_booking"
    SELECT_SERVICE = "select_service"
    CONFIRM_SERVICES = "confirm_services"
    SELECT_STYLIST = "select_stylist"
    SELECT_SLOT = "select_slot"
    CONFIRM_STYLIST_CHANGE = "confirm_stylist_change"  # v4.2: Confirm when choosing different stylist
    PROVIDE_CUSTOMER_DATA = "provide_customer_data"
    USE_CUSTOMER_NAME = "use_customer_name"  # v6.0: User wants to use their name
    PROVIDE_THIRD_PARTY_BOOKING = "provide_third_party_booking"  # v6.0: Booking for someone else without name
    CONFIRM_NAME = "confirm_name"  # v6.0: User confirms shown name
    CORRECT_NAME = "correct_name"  # v6.0: User corrects their name
    CONFIRM_BOOKING = "confirm_booking"
    CANCEL_BOOKING = "cancel_booking"

    # General intents
    GREETING = "greeting"
    FAQ = "faq"
    CHECK_AVAILABILITY = "check_availability"
    ESCALATE = "escalate"
    UPDATE_NAME = "update_name"  # User updates their name in IDLE state
    UNKNOWN = "unknown"

    # Appointment confirmation intents (48h confirmation flow)
    CONFIRM_APPOINTMENT = "confirm_appointment"  # User confirms upcoming appointment
    DECLINE_APPOINTMENT = "decline_appointment"  # User says can't attend appointment

    # Appointment cancellation intents (customer-initiated cancellation)
    INITIATE_CANCELLATION = "initiate_cancellation"  # User wants to cancel appointment
    SELECT_CANCELLATION = "select_cancellation"  # User selects appointment by number
    CONFIRM_CANCELLATION = "confirm_cancellation"  # User confirms cancellation
    ABORT_CANCELLATION = "abort_cancellation"  # User aborts cancellation flow
    INSIST_CANCELLATION = "insist_cancellation"  # User insists despite window restriction

    # Double confirmation intents (decline flow) - v3.5
    CONFIRM_DECLINE = "confirm_decline"  # User confirms cancellation after double-confirm prompt
    ABORT_DECLINE = "abort_decline"  # User changes mind after double-confirm prompt

    # Appointment query intent (customer checks their appointments)
    CHECK_MY_APPOINTMENTS = "check_my_appointments"  # User asks about their appointments


class BookingState(str, Enum):
    """States of the booking flow FSM."""

    IDLE = "idle"  # No active booking
    SERVICE_SELECTION = "service_selection"  # Selecting services
    STYLIST_SELECTION = "stylist_selection"  # Selecting stylist
    SLOT_SELECTION = "slot_selection"  # Selecting time slot
    CUSTOMER_DATA = "customer_data"  # Collecting customer info
    CONFIRMATION = "confirmation"  # Confirming booking
    BOOKED = "booked"  # Booking completed


class SlotData(TypedDict, total=False):
    """Structure for selected slot data."""

    start_time: str  # ISO 8601 datetime string
    duration_minutes: int


class ServiceDetail(TypedDict):
    """
    Enriched service metadata from database lookup.

    Used to store service information including duration for accurate
    total duration calculation. This enables the FSM to display correct
    estimated duration in confirmation messages.
    """

    name: str  # Service name (e.g., "Corte de Caballero")
    duration_minutes: int  # Duration in minutes from database


class CollectedData(TypedDict, total=False):
    """
    TypedDict for data accumulated during booking flow.

    All fields are optional as they are collected progressively.

    Service data is stored in two formats for compatibility:
    - services: list[str] for book() tool compatibility
    - service_details: list[ServiceDetail] for duration calculation
    """

    services: list[str]  # List of selected service names (for book() compatibility)
    service_details: list[ServiceDetail]  # Enriched service data with durations
    total_duration_minutes: int  # Calculated sum of all service durations
    stylist_id: str  # UUID of selected stylist (as string)
    slot: SlotData  # Selected time slot
    first_name: str  # Customer first name (required for booking)
    last_name: str  # Customer last name (optional)
    notes: str  # Additional notes (optional)
    appointment_id: str  # Generated after book() succeeds


@dataclass
class Intent:
    """
    Structured representation of user intent extracted by LLM.

    Attributes:
        type: The type of intent detected
        entities: Extracted entities relevant to the intent
        confidence: Confidence score 0.0-1.0
        raw_message: Original user message
        requires_tool: Whether this intent requires a tool call
        tool_name: Name of the tool to call (if requires_tool is True)
        service_query: Cleaned service keywords extracted by LLM for search
                      (e.g., "mechas" from "Holaaa quiero hacerme las mechas")
    """

    type: IntentType
    entities: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    raw_message: str = ""
    requires_tool: bool = False
    tool_name: str | None = None
    service_query: str | None = None


@dataclass
class FSMResult:
    """
    Result of an FSM transition operation.

    Attributes:
        success: Whether the transition was successful
        new_state: The resulting state after transition
        collected_data: Current accumulated data
        next_action: Suggested next action for the agent
        validation_errors: List of validation errors if transition failed
    """

    success: bool
    new_state: BookingState
    collected_data: dict[str, Any] = field(default_factory=dict)
    next_action: str = ""
    validation_errors: list[str] = field(default_factory=list)


@dataclass
class ResponseGuidance:
    """
    Proactive guidance for LLM response generation (Story 5-7b).

    Used by BookingFSM.get_response_guidance() to provide FSM-aware directives
    to the LLM before generating responses. This enables proactive guidance
    that prevents incoherent responses instead of just validating them post-hoc.

    Attributes:
        must_show: Elements the LLM MUST include in the response (e.g., ["lista de estilistas"])
        must_ask: Question the LLM MUST ask the user (e.g., "¿Con quién te gustaría la cita?")
        forbidden: Elements the LLM MUST NOT mention (e.g., ["horarios", "confirmación"])
        context_hint: Brief context hint for the LLM about current state
        required_tool_call: Tool that MUST be called before confirming selection (e.g., "search_services")

    Example:
        >>> guidance = ResponseGuidance(
        ...     must_show=["lista de estilistas disponibles"],
        ...     must_ask="¿Con quién te gustaría la cita?",
        ...     forbidden=["horarios específicos", "datos del cliente"],
        ...     context_hint="Usuario debe elegir estilista. NO mostrar horarios aún.",
        ...     required_tool_call="search_services"
        ... )
    """

    must_show: list[str] = field(default_factory=list)
    must_ask: str | None = None
    forbidden: list[str] = field(default_factory=list)
    context_hint: str = ""
    required_tool_call: str | None = None


@dataclass
class CoherenceResult:
    """
    Result of response coherence validation (Story 5-7a).

    Used by ResponseValidator to indicate whether an LLM response
    is coherent with the current FSM state before sending to user.

    Attributes:
        is_coherent: Whether the response is coherent with FSM state
        violations: List of detected violations (e.g., "Menciona estilistas en SERVICE_SELECTION")
        correction_hint: Suggested hint for LLM to regenerate coherent response
        confidence: Confidence score 0.0-1.0 in the validation result

    Example:
        >>> result = CoherenceResult(
        ...     is_coherent=False,
        ...     violations=["Menciona nombres de estilistas en SERVICE_SELECTION"],
        ...     correction_hint="NO menciones estilistas. Solo pregunta sobre servicios.",
        ...     confidence=0.95
        ... )
    """

    is_coherent: bool
    violations: list[str] = field(default_factory=list)
    correction_hint: str | None = None
    confidence: float = 1.0

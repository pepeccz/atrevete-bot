"""
Intent types for routing, confirmation, and cancellation services.

HISTORICAL CONTEXT: This enum lived in agent/fsm/models.py as the residual
of the v5.0 prescriptive BookingFSM. All associated models (BookingState,
Intent, FSMResult, CollectedData, SlotData, ServiceDetail, ResponseGuidance,
CoherenceResult) were removed in the agent-rework surgical cleanup.

The enum was moved here during the agent/ folder consolidation — IntentType
is a routing/intent concept, not an FSM artifact.
"""

from enum import Enum


class IntentType(str, Enum):
    """Types of user intent recognized by the confirmation / cancellation services."""

    # Booking flow intents
    START_BOOKING = "start_booking"
    SELECT_SERVICE = "select_service"
    CONFIRM_SERVICES = "confirm_services"
    SELECT_STYLIST = "select_stylist"
    SELECT_SLOT = "select_slot"
    CONFIRM_STYLIST_CHANGE = "confirm_stylist_change"
    PROVIDE_CUSTOMER_DATA = "provide_customer_data"
    USE_CUSTOMER_NAME = "use_customer_name"
    PROVIDE_THIRD_PARTY_BOOKING = "provide_third_party_booking"
    CONFIRM_NAME = "confirm_name"
    CORRECT_NAME = "correct_name"
    PROVIDE_NAME = "provide_name"
    CONFIRM_BOOKING = "confirm_booking"
    CANCEL_BOOKING = "cancel_booking"

    # General intents
    GREETING = "greeting"
    FAQ = "faq"
    CHECK_AVAILABILITY = "check_availability"
    ESCALATE = "escalate"
    UPDATE_NAME = "update_name"
    UNKNOWN = "unknown"

    # Appointment confirmation intents (48h confirmation flow)
    CONFIRM_APPOINTMENT = "confirm_appointment"
    DECLINE_APPOINTMENT = "decline_appointment"

    # Appointment cancellation intents (customer-initiated cancellation)
    INITIATE_CANCELLATION = "initiate_cancellation"
    SELECT_CANCELLATION = "select_cancellation"
    CONFIRM_CANCELLATION = "confirm_cancellation"
    ABORT_CANCELLATION = "abort_cancellation"
    INSIST_CANCELLATION = "insist_cancellation"

    # Double confirmation intents (decline flow)
    CONFIRM_DECLINE = "confirm_decline"
    ABORT_DECLINE = "abort_decline"

    # Appointment query intent
    CHECK_MY_APPOINTMENTS = "check_my_appointments"

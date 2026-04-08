"""
FSM module for booking flow control (legacy v5.0 prescriptive architecture).

NOTICE: The BookingFSM core is DEPRECATED and removed in v6.0.
Only models remain for service-level intent type definitions.

v6.0 Change:
- REMOVED: BookingFSM (replaced by BookingSubstep-based mode architecture)
- REMOVED: intent_extractor (replaced by v6.0 IntentRouter)
- REMOVED: fsm_action.py (ActionType, FSMAction, ToolCall — dead code, no active importers)
- KEPT: models.py for IntentType used in cancellation/confirmation services

Public exports:
    - BookingState: Enum of FSM states (legacy, used in integration tests)
    - Intent: Structured user intent representation
    - IntentType: Enum of recognized intent types
    - FSMResult: Result of FSM transition operations
    - CollectedData: TypedDict for accumulated booking data
    - ResponseGuidance: Proactive response guidance (legacy)
    - SlotData: TypedDict for slot information
"""

from agent.fsm.models import (
    BookingState,
    CollectedData,
    FSMResult,
    Intent,
    IntentType,
    ResponseGuidance,
    SlotData,
)

__all__ = [
    # Core types (still used in services and integration tests)
    "BookingState",
    "CollectedData",
    "FSMResult",
    "Intent",
    "IntentType",
    "ResponseGuidance",
    "SlotData",
]

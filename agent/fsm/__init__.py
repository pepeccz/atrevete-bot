"""
FSM module for booking flow control (legacy v5.0 prescriptive architecture).

NOTICE: The BookingFSM core is DEPRECATED and removed in v6.0.
Only models remain for service-level intent type definitions.

v6.0 Change:
- REMOVED: BookingFSM (replaced by BookingSubstep-based mode architecture)
- REMOVED: intent_extractor (replaced by v6.0 IntentRouter)
- KEPT: models.py for IntentType used in cancellation/confirmation services

Public exports:
    - ActionType: Enum for action types (tool calls)
    - FSMAction: Action structure (prescriptive tool execution)
    - ToolCall: Tool call specification
    - BookingState: Enum of FSM states (legacy)
    - Intent: Structured user intent representation
    - IntentType: Enum of recognized intent types
    - FSMResult: Result of FSM transition operations
    - CollectedData: TypedDict for accumulated booking data
    - ResponseGuidance: Proactive response guidance (legacy)
    - SlotData: TypedDict for slot information
"""

from agent.fsm.fsm_action import ActionType, FSMAction, ToolCall
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
    # Core types (still used in services)
    "ActionType",
    "BookingState",
    "CollectedData",
    "FSMAction",
    "FSMResult",
    "Intent",
    "IntentType",
    "ResponseGuidance",
    "SlotData",
    "ToolCall",
]
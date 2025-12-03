"""
FSM module for booking flow control (v5.0 prescriptive architecture).

This module provides the BookingFSM class and related models for controlling
the booking conversation flow. The FSM validates state transitions, accumulates
data, and persists state to checkpoint (ADR-011: single source of truth).

v5.0 Changes:
- REMOVED: tool_validation.py (FSM now prescribes tools, no post-hoc validation)
- REMOVED: response_validator.py (templates prevent hallucinations, no reactive validation)
- ADDED: get_required_action() returns FSMAction (prescriptive tool execution)

Public exports:
    - BookingFSM: Main FSM controller class with prescriptive actions
    - BookingState: Enum of FSM states
    - Intent: Structured user intent representation
    - IntentType: Enum of recognized intent types
    - FSMResult: Result of FSM transition operations
    - CollectedData: TypedDict for accumulated booking data
    - SlotData: TypedDict for slot information
    - extract_intent: LLM-based intent extraction function (NLU only)
    - ResponseGuidance: Proactive response guidance (legacy, v4.0)
"""

from agent.fsm.booking_fsm import BookingFSM
from agent.fsm.fsm_action import ActionType, FSMAction, ToolCall
from agent.fsm.intent_extractor import extract_intent
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
    # Core FSM (v5.0)
    "ActionType",
    "BookingFSM",
    "BookingState",
    "CollectedData",
    "FSMAction",
    "FSMResult",
    "Intent",
    "IntentType",
    "ResponseGuidance",
    "SlotData",
    "ToolCall",
    "extract_intent",
]

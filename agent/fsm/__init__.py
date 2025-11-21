"""
FSM module for booking flow control.

This module provides the BookingFSM class and related models for controlling
the booking conversation flow. The FSM validates state transitions, accumulates
data, and persists state to Redis.

Public exports:
    - BookingFSM: Main FSM controller class
    - BookingState: Enum of FSM states
    - Intent: Structured user intent representation
    - IntentType: Enum of recognized intent types
    - FSMResult: Result of FSM transition operations
    - CollectedData: TypedDict for accumulated booking data
    - SlotData: TypedDict for slot information
    - extract_intent: LLM-based intent extraction function
    - Tool validation (Story 5-4):
        - validate_tool_call: Validate tool permission in FSM state
        - can_execute_tool: Quick boolean check for tool permission
        - get_allowed_tools: Get list of allowed tools for current state
        - ToolExecutionError: Exception with FSM context
        - ToolValidationResult: Result of tool validation
        - TOOL_STATE_PERMISSIONS: Tool-to-state mapping
        - TOOL_DATA_REQUIREMENTS: Tool-to-data requirements mapping
        - log_tool_execution: Log tool execution with FSM context
"""

from agent.fsm.booking_fsm import BookingFSM
from agent.fsm.intent_extractor import extract_intent
from agent.fsm.models import (
    BookingState,
    CollectedData,
    FSMResult,
    Intent,
    IntentType,
    SlotData,
)
from agent.fsm.tool_validation import (
    TOOL_DATA_REQUIREMENTS,
    TOOL_STATE_PERMISSIONS,
    ToolExecutionError,
    ToolValidationResult,
    can_execute_tool,
    get_allowed_tools,
    log_tool_execution,
    validate_tool_call,
)

__all__ = [
    # Core FSM
    "BookingFSM",
    "BookingState",
    "CollectedData",
    "FSMResult",
    "Intent",
    "IntentType",
    "SlotData",
    "extract_intent",
    # Tool validation (Story 5-4)
    "validate_tool_call",
    "can_execute_tool",
    "get_allowed_tools",
    "ToolExecutionError",
    "ToolValidationResult",
    "TOOL_STATE_PERMISSIONS",
    "TOOL_DATA_REQUIREMENTS",
    "log_tool_execution",
]

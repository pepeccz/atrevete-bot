"""
Tool Validation Module for FSM-Based Tool Access Control.

This module implements FSM-aware validation for tool calls, ensuring tools
only execute when the current FSM state permits. This is a core component
of the v4.0 FSM Hybrid Architecture (ADR-006).

Architecture:
    LLM (NLU)      → Interprets INTENT + Generates LANGUAGE
    FSM Control    → Controls FLOW + Validates PROGRESS + **Validates TOOLS**
    Tool Calls     → Executes ACTIONS **only if FSM authorizes**

Key Concepts:
- Tools are mapped to allowed FSM states
- Some tools require specific collected_data fields
- Validation happens BEFORE tool execution
- Errors are recoverable and logged with FSM context
"""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent.fsm.models import BookingState

if TYPE_CHECKING:
    from agent.fsm.booking_fsm import BookingFSM

logger = logging.getLogger(__name__)


# ============================================================================
# Tool State Permissions Matrix
# ============================================================================
# Maps tool names to the FSM states where they are allowed to execute.
# Based on Story 5-4 specification in Dev Notes.

TOOL_STATE_PERMISSIONS: dict[str, list[BookingState]] = {
    # Informational tools - available in all states
    "query_info": list(BookingState),  # ANY state (informational)
    "escalate_to_human": list(BookingState),  # ANY state (always available)
    "get_customer_history": list(BookingState),  # ANY state (informational)

    # Service search - IDLE and SERVICE_SELECTION (browsing/selecting services)
    "search_services": [
        BookingState.IDLE,
        BookingState.SERVICE_SELECTION,
    ],

    # Customer management - CUSTOMER_DATA state (collecting customer info)
    # Also allowed in IDLE for pre-registration scenarios
    "manage_customer": [
        BookingState.IDLE,
        BookingState.CUSTOMER_DATA,
    ],

    # Availability tools - require services selected, checking slots
    "check_availability": [
        BookingState.STYLIST_SELECTION,
        BookingState.SLOT_SELECTION,
    ],
    "find_next_available": [
        BookingState.STYLIST_SELECTION,
        BookingState.SLOT_SELECTION,
    ],

    # Booking - CONFIRMATION state only (all data collected and confirmed)
    "book": [
        BookingState.CONFIRMATION,
    ],
}


# ============================================================================
# Tool Data Requirements
# ============================================================================
# Maps tools to the collected_data fields they require in the FSM.

TOOL_DATA_REQUIREMENTS: dict[str, list[str]] = {
    # Service search requires nothing
    "search_services": [],

    # Availability tools require services to be selected
    "check_availability": ["services"],
    "find_next_available": ["services"],

    # Booking requires complete data
    "book": ["services", "stylist_id", "slot", "first_name"],

    # Other tools have no requirements
    "query_info": [],
    "escalate_to_human": [],
    "get_customer_history": [],
    "manage_customer": [],
}


# ============================================================================
# Exception Classes
# ============================================================================


@dataclass
class ToolExecutionError(Exception):
    """
    Exception raised when tool execution fails with FSM context.

    Captures the FSM state at the time of failure for debugging and recovery.

    Attributes:
        tool_name: Name of the tool that failed
        fsm_state: FSM state at time of failure
        error_code: Machine-readable error code
        message: Human-readable error message
        details: Additional error context
    """
    tool_name: str
    fsm_state: BookingState
    error_code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for logging and error responses."""
        return {
            "error": self.error_code,
            "message": self.message,
            "tool_name": self.tool_name,
            "fsm_state": self.fsm_state.value,
            "details": self.details,
        }


@dataclass
class ToolValidationResult:
    """
    Result of tool validation check.

    Attributes:
        allowed: Whether the tool call is permitted
        error_code: Error code if not allowed (None if allowed)
        error_message: Human-readable error message (None if allowed)
        redirect_message: Suggested message to redirect user (None if allowed)
    """
    allowed: bool
    error_code: str | None = None
    error_message: str | None = None
    redirect_message: str | None = None


# ============================================================================
# Validation Functions
# ============================================================================


def validate_tool_call(
    tool_name: str,
    fsm: "BookingFSM",
) -> ToolValidationResult:
    """
    Validate if a tool call is permitted in the current FSM state.

    Checks both:
    1. State permissions - is the tool allowed in this state?
    2. Data requirements - does FSM have required collected_data?

    Args:
        tool_name: Name of the tool being called
        fsm: BookingFSM instance with current state and collected_data

    Returns:
        ToolValidationResult with allowed=True/False and error details

    Example:
        >>> fsm = BookingFSM("conv-123")
        >>> fsm.state = BookingState.SERVICE_SELECTION
        >>> result = validate_tool_call("book", fsm)
        >>> result.allowed
        False
        >>> result.error_code
        "TOOL_STATE_NOT_ALLOWED"
    """
    # Check if tool is in permissions matrix
    allowed_states = TOOL_STATE_PERMISSIONS.get(tool_name)

    if allowed_states is None:
        # Unknown tool - allow by default but log warning
        logger.warning(
            "Unknown tool in FSM validation: %s | Allowing by default",
            tool_name,
            extra={
                "tool_name": tool_name,
                "fsm_state": fsm.state.value,
                "conversation_id": fsm.conversation_id,
            }
        )
        return ToolValidationResult(allowed=True)

    # Check state permission
    if fsm.state not in allowed_states:
        allowed_states_str = ", ".join(s.value for s in allowed_states)

        logger.warning(
            "Tool call rejected by FSM | tool=%s | current_state=%s | allowed_states=[%s]",
            tool_name,
            fsm.state.value,
            allowed_states_str,
            extra={
                "tool_name": tool_name,
                "fsm_state": fsm.state.value,
                "allowed_states": [s.value for s in allowed_states],
                "conversation_id": fsm.conversation_id,
            }
        )

        redirect_msg = _get_redirect_message(tool_name, fsm.state)

        return ToolValidationResult(
            allowed=False,
            error_code="TOOL_STATE_NOT_ALLOWED",
            error_message=(
                f"La herramienta '{tool_name}' no está permitida en el estado '{fsm.state.value}'. "
                f"Estados permitidos: {allowed_states_str}"
            ),
            redirect_message=redirect_msg,
        )

    # Check data requirements
    required_fields = TOOL_DATA_REQUIREMENTS.get(tool_name, [])
    missing_fields = []
    collected = fsm.collected_data

    for field in required_fields:
        value = collected.get(field)
        if value is None:
            missing_fields.append(field)
        elif isinstance(value, (list, str)) and len(value) == 0:
            missing_fields.append(field)

    if missing_fields:
        logger.warning(
            "Tool call rejected - missing data | tool=%s | state=%s | missing=%s",
            tool_name,
            fsm.state.value,
            missing_fields,
            extra={
                "tool_name": tool_name,
                "fsm_state": fsm.state.value,
                "missing_fields": missing_fields,
                "collected_data_keys": list(collected.keys()),
                "conversation_id": fsm.conversation_id,
            }
        )

        return ToolValidationResult(
            allowed=False,
            error_code="MISSING_REQUIRED_DATA",
            error_message=(
                f"Faltan datos requeridos para '{tool_name}': {', '.join(missing_fields)}"
            ),
            redirect_message=_get_missing_data_redirect(missing_fields),
        )

    # All checks passed
    logger.info(
        "Tool call validated | tool=%s | state=%s",
        tool_name,
        fsm.state.value,
        extra={
            "tool_name": tool_name,
            "fsm_state": fsm.state.value,
            "conversation_id": fsm.conversation_id,
        }
    )

    return ToolValidationResult(allowed=True)


def can_execute_tool(tool_name: str, fsm: "BookingFSM") -> bool:
    """
    Quick check if a tool can execute in current FSM state.

    Convenience function that returns only boolean result.
    Use validate_tool_call() when you need error details.

    Args:
        tool_name: Name of the tool
        fsm: BookingFSM instance

    Returns:
        True if tool can execute, False otherwise
    """
    result = validate_tool_call(tool_name, fsm)
    return result.allowed


def get_allowed_tools(fsm: "BookingFSM") -> list[str]:
    """
    Get list of tools allowed in the current FSM state.

    Useful for informing the LLM about available actions.

    Args:
        fsm: BookingFSM instance with current state

    Returns:
        List of tool names allowed in current state
    """
    allowed = []
    for tool_name, allowed_states in TOOL_STATE_PERMISSIONS.items():
        if fsm.state in allowed_states:
            # Also check data requirements
            required = TOOL_DATA_REQUIREMENTS.get(tool_name, [])
            has_required = all(
                fsm.collected_data.get(f) is not None
                for f in required
            )
            if has_required:
                allowed.append(tool_name)

    return allowed


# ============================================================================
# Helper Functions
# ============================================================================


def _get_redirect_message(tool_name: str, current_state: BookingState) -> str:
    """Generate a natural redirect message based on tool and current state."""

    # Tool-specific redirects
    if tool_name == "book":
        if current_state == BookingState.SERVICE_SELECTION:
            return "Primero necesitamos seleccionar los servicios que deseas."
        elif current_state == BookingState.STYLIST_SELECTION:
            return "Antes de reservar, ¿con qué estilista te gustaría la cita?"
        elif current_state == BookingState.SLOT_SELECTION:
            return "Falta elegir el horario para tu cita."
        elif current_state == BookingState.CUSTOMER_DATA:
            return "Necesito tu nombre para completar la reserva."
        else:
            return "Necesitamos completar algunos pasos antes de reservar."

    elif tool_name in ["check_availability", "find_next_available"]:
        if current_state == BookingState.IDLE:
            return "¿Qué servicio te gustaría reservar?"
        elif current_state == BookingState.SERVICE_SELECTION:
            return "Primero confirma los servicios que deseas para buscar disponibilidad."
        else:
            return "Primero necesitamos saber qué servicios deseas."

    elif tool_name == "search_services":
        if current_state in [BookingState.CONFIRMATION, BookingState.BOOKED]:
            return "Los servicios ya están seleccionados para esta reserva."
        else:
            return "Puedo ayudarte a buscar servicios."

    # Generic fallback
    return "Por favor, continúa con el paso actual del proceso de reserva."


def _get_missing_data_redirect(missing_fields: list[str]) -> str:
    """Generate redirect message for missing data fields."""

    field_messages = {
        "services": "¿Qué servicios te gustaría reservar?",
        "stylist_id": "¿Con qué estilista prefieres tu cita?",
        "slot": "¿Qué horario prefieres para tu cita?",
        "first_name": "¿Me puedes dar tu nombre para la reserva?",
    }

    # Return message for first missing field
    for field in missing_fields:
        if field in field_messages:
            return field_messages[field]

    return "Necesito más información para continuar con la reserva."


# ============================================================================
# Logging Helpers
# ============================================================================


def log_tool_execution(
    tool_name: str,
    fsm: "BookingFSM",
    result: dict[str, Any],
    success: bool,
    error: str | None = None,
) -> None:
    """
    Log tool execution with FSM context.

    Implements AC #6: logs show FSM state, tool name, result, new state.

    Args:
        tool_name: Name of executed tool
        fsm: BookingFSM instance
        result: Tool execution result
        success: Whether execution succeeded
        error: Error message if failed
    """
    extra = {
        "tool_name": tool_name,
        "fsm_state": fsm.state.value,
        "conversation_id": fsm.conversation_id,
        "collected_data_keys": list(fsm.collected_data.keys()),
        "success": success,
    }

    if success:
        # Log success with result preview
        result_preview = str(result)[:200] if result else "None"
        logger.info(
            "Tool executed | tool=%s | state=%s | success=True | result_preview=%s",
            tool_name,
            fsm.state.value,
            result_preview,
            extra=extra,
        )
    else:
        # Log failure with error
        extra["error"] = error
        logger.warning(
            "Tool execution failed | tool=%s | state=%s | error=%s",
            tool_name,
            fsm.state.value,
            error,
            extra=extra,
        )

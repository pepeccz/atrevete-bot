"""
State-Action Coherence Auditor for Booking System (ADR-012).

This module provides post-response auditing to detect misalignment between:
- FSM state and actual database records
- Response content and tool executions
- State flags and FSM transitions

The auditor acts as Layer 4 defense against booking hallucinations, catching
cases where earlier layers (FSM enforcement, ResponseValidator, tool tracking) fail.

Created: 2025-11-28
Related: ADR-012 (Fix critical booking hallucination bug)
"""

import re
import logging
from dataclasses import dataclass
from typing import Any, Literal

from agent.fsm.booking_fsm import BookingFSM, BookingState

logger = logging.getLogger(__name__)


@dataclass
class AuditResult:
    """
    Result of state-action coherence audit.

    Attributes:
        coherent: True if state and actions are aligned, False if violations detected
        violations: List of violation descriptions (empty if coherent)
        severity: "critical" if violations require immediate action, None otherwise
    """
    coherent: bool
    violations: list[str]
    severity: Literal["critical", "warning"] | None


class StateActionAuditor:
    """
    Audits state-action coherence after response generation.

    This auditor performs post-response validation to detect misalignment between
    FSM state, tool executions, and response content. It catches bugs where the
    system appears to confirm bookings without actually executing book() tool.

    Audit Rules:
    1. If FSM in BOOKED state → verify appointment_created flag is True
    2. If response confirms booking → verify book() tool was called
    3. If appointment_created=True → verify FSM reached BOOKED at some point

    On critical violations, the auditor recommends auto-escalation to human staff
    and response override to prevent false confirmations reaching users.
    """

    # Spanish booking confirmation patterns
    BOOKING_CONFIRMATION_PATTERNS = [
        r"(ya he|he|hemos)\s+(reservado|agendado|creado|confirmado)\s+(tu|su|la)\s+cita",
        r"(reservado|agendado|confirmado)\s+(tu|su)\s+cita",
        r"cita\s+(está|ha sido)\s+(reservada|agendada|creada|confirmada)",
        r"(reserva|cita)\s+(confirmada|reservada|agendada)",
    ]

    def __init__(self) -> None:
        """Initialize the auditor."""
        pass  # Stateless auditor - no initialization needed

    async def audit(
        self,
        fsm: BookingFSM,
        response: str,
        tools_executed: set[str],
        state: dict[str, Any],
    ) -> AuditResult:
        """
        Audit state-action coherence after response generation.

        Args:
            fsm: The booking FSM instance with current state
            response: The assistant's response text to be sent to user
            tools_executed: Set of tool names that were called this turn
            state: The conversation state dict (TypedDict at runtime)

        Returns:
            AuditResult with coherence status, violations, and severity

        Example:
            >>> auditor = StateActionAuditor()
            >>> result = await auditor.audit(
            ...     fsm=fsm,
            ...     response="Ya he reservado tu cita",
            ...     tools_executed=set(),  # book() was NOT called
            ...     state={"appointment_created": False}
            ... )
            >>> result.coherent
            False
            >>> result.severity
            'critical'
        """
        violations: list[str] = []

        # ================================================================
        # RULE 1: FSM State vs appointment_created Flag
        # ================================================================
        # If FSM reached BOOKED state, the appointment_created flag MUST be True
        # This catches bugs where FSM transitions to BOOKED without actually
        # executing the booking transaction
        if fsm.state == BookingState.BOOKED:
            if not state.get("appointment_created"):
                violation = (
                    f"FSM in BOOKED state but appointment_created=False | "
                    f"FSM state indicates booking complete but flag not set"
                )
                violations.append(violation)
                logger.critical(
                    "AUDIT VIOLATION: FSM-State mismatch",
                    extra={
                        "fsm_state": fsm.state.value,
                        "appointment_created": False,
                        "violation": "Rule 1"
                    }
                )

        # ================================================================
        # RULE 2: Response Content vs Tool Execution
        # ================================================================
        # If response claims booking was created, verify book() tool was called
        # This is the PRIMARY defense against hallucinations - catches LLM
        # generating "booking confirmed" without actually calling book()
        if self._response_confirms_booking(response):
            if "book" not in tools_executed:
                violation = (
                    f"Response confirms booking but book() not called | "
                    f"Response: '{self._truncate_response(response)}'"
                )
                violations.append(violation)
                logger.critical(
                    "AUDIT VIOLATION: Booking hallucination detected",
                    extra={
                        "tools_executed": list(tools_executed),
                        "response_excerpt": self._truncate_response(response),
                        "violation": "Rule 2"
                    }
                )

        # ================================================================
        # RULE 3: appointment_created Flag vs FSM History
        # ================================================================
        # If appointment_created=True, FSM must be in BOOKED or IDLE (post-reset)
        # This catches bugs where the flag is set without FSM transition
        if state.get("appointment_created"):
            # Valid states after booking: BOOKED (before reset) or IDLE (after reset)
            valid_states = [BookingState.BOOKED, BookingState.IDLE]
            if fsm.state not in valid_states:
                violation = (
                    f"appointment_created=True but FSM in {fsm.state.value} | "
                    f"Flag indicates booking complete but FSM in unexpected state"
                )
                violations.append(violation)
                logger.warning(
                    "AUDIT VIOLATION: Flag-FSM mismatch",
                    extra={
                        "appointment_created": True,
                        "fsm_state": fsm.state.value,
                        "expected_states": [s.value for s in valid_states],
                        "violation": "Rule 3"
                    }
                )

        # ================================================================
        # Determine Severity
        # ================================================================
        # Rule 2 violations (booking hallucination) are CRITICAL - must be prevented
        # Rule 1 and 3 violations are warnings (edge cases, less critical)
        severity: Literal["critical", "warning"] | None = None
        if violations:
            # Check if any violation is from Rule 2 (booking hallucination)
            has_hallucination = any("book() not called" in v for v in violations)
            severity = "critical" if has_hallucination else "warning"

        coherent = len(violations) == 0

        if not coherent:
            logger.info(
                f"Audit completed: {'PASS' if coherent else 'FAIL'}",
                extra={
                    "coherent": coherent,
                    "violations_count": len(violations),
                    "severity": severity
                }
            )

        return AuditResult(
            coherent=coherent,
            violations=violations,
            severity=severity
        )

    def _response_confirms_booking(self, response: str) -> bool:
        """
        Check if response contains booking confirmation language.

        Args:
            response: The assistant's response text

        Returns:
            True if response appears to confirm a booking was created

        Examples:
            >>> auditor._response_confirms_booking("Ya he reservado tu cita")
            True
            >>> auditor._response_confirms_booking("Veo que quieres agendar")
            False
        """
        for pattern in self.BOOKING_CONFIRMATION_PATTERNS:
            if re.search(pattern, response, re.IGNORECASE):
                return True
        return False

    def _truncate_response(self, response: str, max_length: int = 100) -> str:
        """
        Truncate response for logging (first 100 chars).

        Args:
            response: The full response text
            max_length: Maximum length to return

        Returns:
            Truncated response with ellipsis if needed
        """
        if len(response) <= max_length:
            return response
        return response[:max_length] + "..."

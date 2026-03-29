"""
Mode nodes for v6.0 conversation architecture.

5 independent mode nodes replace the single FSM mega-node:
- GreetingMode: First contact, name collection (fires ONCE per new customer)
- BookingMode: LLM-driven appointment booking flow
- GeneralMode: FAQ / informational queries (read-only tools)
- EscalationMode: Human handoff
- AppointmentManagementMode: LLM-driven appointment query/cancel/reschedule
"""

from agent.modes.appointment_management_mode import AppointmentManagementMode
from agent.modes.base import AgenticLoopResult, BaseModeNode, ModeResult
from agent.modes.escalation_mode import EscalationMode
from agent.modes.general_mode import GeneralMode
from agent.modes.greeting_mode import GreetingMode

__all__ = [
    "AgenticLoopResult",
    "AppointmentManagementMode",
    "BaseModeNode",
    "EscalationMode",
    "GeneralMode",
    "GreetingMode",
    "ModeResult",
]

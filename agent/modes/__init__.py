"""
Mode nodes for v6.0 conversation architecture.

Migration state (see ``docs/refactor/PLAN.md``):

- M3: GreetingMode — migrated to ``create_agent`` + middleware.
      Public factory: ``greeting_mode.build_greeting_node``.
- M4: GeneralMode — migrated to ``create_agent`` + TokenTrackingMiddleware.
      Public factory: ``general_mode.build_general_node``.
- M4: EscalationMode — migrated to a pure FSM factory (no LLM).
      Public factory: ``escalation_mode.build_escalation_node``.
- M6+: BookingMode, AppointmentManagementMode still inherit from
       ``BaseModeNode``; they migrate in later milestones.
"""

from agent.modes.appointment_management_mode import AppointmentManagementMode
from agent.modes.base import AgenticLoopResult, BaseModeNode, ModeResult
from agent.modes.escalation_mode import build_escalation_node
from agent.modes.general_mode import build_general_node
from agent.modes.greeting_mode import build_greeting_node

__all__ = [
    "AgenticLoopResult",
    "AppointmentManagementMode",
    "BaseModeNode",
    "ModeResult",
    "build_escalation_node",
    "build_general_node",
    "build_greeting_node",
]

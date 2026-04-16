"""
Mode nodes for v6.0 conversation architecture.

Migration state (see ``docs/refactor/PLAN.md``):

- M3: GreetingMode has been migrated to ``create_agent`` + middleware. It is
  exposed as ``agent.modes.greeting_mode.build_greeting_node`` and no longer
  inherits from ``BaseModeNode``.
- M4+: GeneralMode, BookingMode, EscalationMode, AppointmentManagementMode
  still inherit from ``BaseModeNode``; they migrate in later milestones.
"""

from agent.modes.appointment_management_mode import AppointmentManagementMode
from agent.modes.base import AgenticLoopResult, BaseModeNode, ModeResult
from agent.modes.escalation_mode import EscalationMode
from agent.modes.general_mode import GeneralMode
from agent.modes.greeting_mode import build_greeting_node

__all__ = [
    "AgenticLoopResult",
    "AppointmentManagementMode",
    "BaseModeNode",
    "EscalationMode",
    "GeneralMode",
    "ModeResult",
    "build_greeting_node",
]

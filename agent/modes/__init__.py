"""
Agent Modes package — v6.0 mode-based architecture.

This package contains the mode node implementations for the agent-architecture-rebuild.
Each mode handles a specific conversational context.

Available modes:
- BaseModeNode: Abstract base class (agent/modes/base.py)
- ModeResult: Return type for all mode handle() methods
- GreetingMode: First contact + name confirmation (agent/modes/greeting_mode.py)
- GeneralMode: FAQ and informational queries (agent/modes/general_mode.py)
- BookingMode: Full appointment booking flow (agent/modes/booking_mode.py)
- EscalationMode: Human handoff (agent/modes/escalation_mode.py)
"""

from agent.modes.base import BaseModeNode, ModeResult
from agent.modes.booking_mode import BookingMode
from agent.modes.escalation_mode import EscalationMode
from agent.modes.general_mode import GeneralMode
from agent.modes.greeting_mode import GreetingMode

__all__ = [
    "BaseModeNode",
    "ModeResult",
    "GreetingMode",
    "GeneralMode",
    "BookingMode",
    "EscalationMode",
]

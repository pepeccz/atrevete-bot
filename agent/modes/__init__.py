"""
Mode nodes for v6.0 conversation architecture.

4 independent mode nodes replace the single FSM mega-node:
- GreetingMode: First contact, name collection (fires ONCE per new customer)
- BookingMode: Full multi-step appointment booking flow
- GeneralMode: FAQ / informational queries (read-only tools)
- EscalationMode: Human handoff
"""

from agent.modes.base import AgenticLoopResult, BaseModeNode, ModeResult
from agent.modes.booking_mode import BookingMode
from agent.modes.escalation_mode import EscalationMode
from agent.modes.general_mode import GeneralMode
from agent.modes.greeting_mode import GreetingMode

__all__ = [
    "AgenticLoopResult",
    "BaseModeNode",
    "BookingMode",
    "EscalationMode",
    "GeneralMode",
    "GreetingMode",
    "ModeResult",
]

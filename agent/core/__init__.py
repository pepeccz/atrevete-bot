"""
agent.core — E1 capability-contract scaffolding.

Reusable primitives for synthetic state delivery and future resolvers
(negation, digit selection, appointment management).

E1 additions: Capability ABC — the 7-property contract every conversational
capability must satisfy. Zero in-runtime callers in E1; first concrete
implementation is BookingCapability in E2.
"""

from agent.core.capability import Capability
from agent.core.state_delivery import (
    SYNTHETIC_TOOL_CALL_ID_PREFIX,
    build_synthetic_state_delivery,
    deliver_state_update,
)

__all__ = [
    # E1: Capability ABC
    "Capability",
    # Pre-E1: synthetic state delivery
    "SYNTHETIC_TOOL_CALL_ID_PREFIX",
    "build_synthetic_state_delivery",
    "deliver_state_update",
]

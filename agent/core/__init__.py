"""
agent.core — E1 capability-contract scaffolding.

Reusable primitives for synthetic state delivery and future resolvers
(negation, digit selection, appointment management).
"""

from agent.core.state_delivery import (
    SYNTHETIC_TOOL_CALL_ID_PREFIX,
    build_synthetic_state_delivery,
    deliver_state_update,
)

__all__ = [
    "SYNTHETIC_TOOL_CALL_ID_PREFIX",
    "build_synthetic_state_delivery",
    "deliver_state_update",
]

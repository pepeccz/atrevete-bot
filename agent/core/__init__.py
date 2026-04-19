"""agent.core — runtime primitives used by modes and middleware."""

from agent.core.state_delivery import (
    SYNTHETIC_TOOL_CALL_ID_PREFIX,
    build_synthetic_state_delivery,
    deliver_state_update,
)
from agent.core.status_line import build_status_line

__all__ = [
    "SYNTHETIC_TOOL_CALL_ID_PREFIX",
    "build_synthetic_state_delivery",
    "deliver_state_update",
    "build_status_line",
]

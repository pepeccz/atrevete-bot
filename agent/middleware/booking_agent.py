"""Backwards-compatibility alias for ``NodeBridgeMiddleware``.

M6 introduced a booking-specific bridge class; M7 generalised it to
``agent.middleware.node_bridge.NodeBridgeMiddleware``. This module re-exports
the generic class under the old name so existing imports (and the M6 commit
trail) keep resolving.
"""

from agent.middleware.node_bridge import NodeBridgeMiddleware as BookingAgentMiddleware

__all__ = ["BookingAgentMiddleware"]

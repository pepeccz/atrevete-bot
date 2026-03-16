"""
Routing layer for v6.0 mode-based architecture.

This module implements intent routing using keyword + LLM hybrid classification.

Key components:
- IntentRouter: Classifies intents and provides mode hints for the v6.0 router

v6.0 Changes:
- REMOVED: BookingHandler (replaced by BookingMode)
- REMOVED: NonBookingHandler (replaced by GeneralMode)
- REMOVED: ResponseFormatter (handled by mode nodes)
- KEPT: IntentRouter for intent classification
"""

from agent.routing.intent_router import IntentRouter

__all__ = [
    "IntentRouter",
]
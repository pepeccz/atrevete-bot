"""
Routing layer for agent-architecture-rebuild (v6.0 mode-based architecture).

This module exports intent classification types for the new keyword + LLM hybrid
IntentRouter, as well as the legacy FSM-based routing components (kept for
backward compatibility until full cutover in later batches).

New components (v6.0):
- IntentRouter: Keyword + LLM hybrid classifier
- IntentType: Literal type for the 8 simplified intent categories
- IntentResult: Dataclass for classification results
- classify_by_keywords: Fast synchronous keyword-only classifier

Legacy components (v5.0 — to be removed after cutover):
- BookingHandler: FSM-prescriptive booking flow
- NonBookingHandler: Conversational FAQ/greeting flow
- ResponseFormatter: Template-based response formatting
"""

from agent.routing.intent_router import (
    KEYWORD_MAP,
    IntentResult,
    IntentRouter,
    IntentType,
    classify_by_keywords,
)

__all__ = [
    # New v6.0 components
    "IntentRouter",
    "IntentType",
    "IntentResult",
    "classify_by_keywords",
    "KEYWORD_MAP",
]

# Legacy exports — kept for backward compatibility with conversational_agent.py
# These will be removed when conversational_agent.py is replaced in later batches
try:
    from agent.routing.booking_handler import BookingHandler, ResponseFormatter
    from agent.routing.non_booking_handler import NonBookingHandler

    __all__ += ["BookingHandler", "NonBookingHandler", "ResponseFormatter"]
except ImportError:
    pass  # Legacy handlers not available — that's OK for new architecture

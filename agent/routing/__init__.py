"""
Routing layer for v5.0 prescriptive FSM architecture.

This module implements intent routing, separating booking flows (FSM prescribes tools)
from non-booking flows (LLM handles conversationally with safe tools).

Key components:
- IntentRouter: Routes intents to booking or non-booking handlers
- BookingHandler: Prescriptive booking flow (FSM decides tools)
- NonBookingHandler: Conversational FAQ/greeting flow (LLM decides)
- ResponseFormatter: Formats responses using Jinja2 templates + LLM creativity

Architecture:
    Intent → IntentRouter
        ├─ BOOKING_INTENTS → BookingHandler
        │   ↓
        │   FSM.get_required_action() → FSMAction
        │   ↓
        │   Execute Prescribed Tools
        │   ↓
        │   ResponseFormatter (template + LLM creativity)
        │
        └─ NON_BOOKING_INTENTS → NonBookingHandler
            ↓
            LLM with Safe Tools (query_info, escalate)
            ↓
            Response
"""

from agent.routing.booking_handler import BookingHandler, ResponseFormatter
from agent.routing.intent_router import IntentRouter
from agent.routing.non_booking_handler import NonBookingHandler

__all__ = [
    "IntentRouter",
    "BookingHandler",
    "NonBookingHandler",
    "ResponseFormatter",
]

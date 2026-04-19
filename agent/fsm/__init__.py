"""
Residual FSM module — IntentType only.

The v5.0 BookingFSM was removed during the v6.0 mode-based migration.
All associated models (BookingState, Intent, FSMResult, CollectedData,
SlotData, ResponseGuidance, CoherenceResult) were dead code and were
removed in the agent-rework surgical cleanup.

Only IntentType remains, used by cancellation / confirmation services.
"""

from agent.fsm.models import IntentType

__all__ = ["IntentType"]

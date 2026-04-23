"""Intent type enum used by confirmation/cancellation services.

Kept minimal and stable — services reference these names in their dispatch
logic. Adding new intents is safe; removing or renaming is a breaking change.
"""

from __future__ import annotations

from enum import StrEnum


class IntentType(StrEnum):
    """Intents recognised by appointment confirmation/cancellation services."""

    CONFIRM_APPOINTMENT = "CONFIRM_APPOINTMENT"
    DECLINE_APPOINTMENT = "DECLINE_APPOINTMENT"
    CONFIRM_DECLINE = "CONFIRM_DECLINE"
    ABORT_DECLINE = "ABORT_DECLINE"
    INITIATE_CANCELLATION = "INITIATE_CANCELLATION"
    SELECT_CANCELLATION = "SELECT_CANCELLATION"
    CONFIRM_CANCELLATION = "CONFIRM_CANCELLATION"
    ABORT_CANCELLATION = "ABORT_CANCELLATION"
    INSIST_CANCELLATION = "INSIST_CANCELLATION"

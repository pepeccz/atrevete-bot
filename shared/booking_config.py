"""
Booking flow configuration — inlined constants with Pydantic validation.

HISTORICAL CONTEXT: This module previously lived at `agent/config/` as a
YAML-driven loader with a 1-minute TTL cache (agent/config/booking.yaml
+ agent/config/__init__.py). The YAML path was removed during the
agent/ folder consolidation — config changes now require a restart,
which is consistent with how the rest of shared/config.py behaves.

The `async def get_booking_config()` signature is preserved for backward
compatibility with the existing call sites (booking_mode, availability_tools).
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class ToolChoicePolicy(StrEnum):
    NEVER_FORCE = "never_force"
    FORCE_AFTER_SERVICE = "force_after_service_known"
    ALWAYS_FORCE = "always_force"


class SlotStrategy(StrEnum):
    ONE_PER_STYLIST = "one_per_stylist"
    TIME_SPREAD = "time_spread"
    NONE = "none"


class BookingConfig(BaseModel):
    """Booking flow behavior — all fields have safe defaults."""

    max_slots_to_present: int = Field(default=5, ge=1, le=20)
    slot_diversification_strategy: SlotStrategy = Field(default=SlotStrategy.ONE_PER_STYLIST)
    auto_search_extra_days: int = Field(default=3, ge=0, le=14)
    max_slots_per_day: int = Field(default=2, ge=1, le=10)
    tool_choice_policy: ToolChoicePolicy = Field(default=ToolChoicePolicy.NEVER_FORCE)


_BOOKING_CONFIG = BookingConfig()


async def get_booking_config() -> BookingConfig:
    """Return the singleton BookingConfig.

    Async signature preserved for backward compat with call sites that awaited
    the previous YAML loader (which was async due to the TTL cache).
    """
    return _BOOKING_CONFIG

"""Booking configuration — YAML-driven with TTL cache."""

import logging
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from agent.prompts.loader import _TtlCache

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).parent
_BOOKING_YAML = _CONFIG_DIR / "booking.yaml"


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
    tool_choice_policy: ToolChoicePolicy = Field(default=ToolChoicePolicy.NEVER_FORCE)


_booking_config_cache = _TtlCache(ttl_minutes=1)


def _load_booking_config_from_disk() -> BookingConfig:
    """Load and validate booking.yaml, falling back to defaults on any error.

    Per-key fallback: if some fields are invalid, reject only those and use defaults.
    """
    if not _BOOKING_YAML.exists():
        logger.warning("booking.yaml not found at %s — using defaults", _BOOKING_YAML)
        return BookingConfig()

    try:
        with open(_BOOKING_YAML, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except Exception as e:
        logger.warning("Failed to parse booking.yaml: %s — using defaults", e)
        return BookingConfig()

    if not isinstance(raw, dict):
        logger.warning("booking.yaml root is not a dict — using defaults")
        return BookingConfig()

    # Try full validation first
    try:
        config = BookingConfig(**raw)
        logger.info("Loaded booking config from %s", _BOOKING_YAML)
        return config
    except ValidationError as exc:
        # Per-key fallback: remove invalid fields and retry
        bad_fields = set()
        for error in exc.errors():
            if error.get("loc"):
                bad_fields.add(str(error["loc"][0]))
        logger.warning(
            "booking.yaml: invalid fields %s — using defaults for those", bad_fields
        )
        cleaned = {k: v for k, v in raw.items() if k not in bad_fields}
        try:
            return BookingConfig(**cleaned)
        except ValidationError:
            logger.error("booking.yaml: fallback parse also failed — using all defaults")
            return BookingConfig()


async def get_booking_config() -> BookingConfig:
    """Return the cached BookingConfig (1-min TTL, async-safe, never raises)."""
    return await _booking_config_cache.get_or_load(_load_booking_config_from_disk)


def invalidate_booking_config() -> None:
    """Force cache refresh on next call."""
    _booking_config_cache.invalidate()
    logger.info("Booking config cache invalidated")

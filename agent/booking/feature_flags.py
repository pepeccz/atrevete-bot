"""
Feature flag helpers for the BookingCapability path.

Design: §6.2, §7 (per-conversation Redis override for canary rollout)

Public API:
    BOOKING_CAPABILITY_KEY_PREFIX — Redis key prefix (e.g. used by admin panel)
    resolve_booking_capability_flag — sync function returning (use_new_path, source)
"""

from __future__ import annotations

import logging

from shared.config import get_settings
from shared.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# Module-level settings — patched in tests via
# ``patch("agent.booking.feature_flags.settings")``
settings = get_settings()

# Redis key prefix — admin panel uses this to seed canary overrides.
# Full key: booking:capability:{conversation_id}  (value: "1"/"on" or "0"/"off")
BOOKING_CAPABILITY_KEY_PREFIX = "booking:capability:"

# Deprecated alias kept for backward compatibility
BOOKING_FLAG_KEY_PREFIX = BOOKING_CAPABILITY_KEY_PREFIX

# Values accepted as "flag ON"
_ON_VALUES: frozenset[str] = frozenset({"1", "on", "true", "yes"})
# Values accepted as "flag OFF"
_OFF_VALUES: frozenset[str] = frozenset({"0", "off", "false", "no"})


def resolve_booking_capability_flag(
    conversation_id: str | None,
) -> tuple[bool, str]:
    """Determine whether to use the new capability booking path for this conversation.

    Synchronous — reads Redis synchronously (sync Redis client expected).

    Priority:
    1. Redis key ``booking:capability:{conversation_id}`` — per-conversation override
       (value "1"/"on" → ON; value "0"/"off" → OFF).
    2. Global ``USE_CAPABILITY_BOOKING`` setting — default.

    Returns:
        (use_new_path: bool, source: str)
        source is "redis-override" when Redis controlled the decision, "global" otherwise.

    Errors:
        Redis failures are caught and logged; falls back to global setting (fail-open).
    """
    if conversation_id:
        try:
            redis = get_redis_client()
            key = f"{BOOKING_CAPABILITY_KEY_PREFIX}{conversation_id}"
            value = redis.get(key)
            if value is not None:
                value_lower = str(value).lower().strip()
                if value_lower in _ON_VALUES:
                    logger.info(
                        "feature_flag.booking",
                        extra={
                            "conversation_id": conversation_id,
                            "path": "capability",
                            "source": "redis-override",
                            "redis_key": key,
                            "redis_value": value_lower,
                        },
                    )
                    return (True, "redis-override")
                elif value_lower in _OFF_VALUES:
                    logger.info(
                        "feature_flag.booking",
                        extra={
                            "conversation_id": conversation_id,
                            "path": "legacy",
                            "source": "redis-override",
                            "redis_key": key,
                            "redis_value": value_lower,
                        },
                    )
                    return (False, "redis-override")
                else:
                    logger.warning(
                        "feature_flag.booking: unrecognised Redis value %r for key %s — "
                        "ignoring, falling back to global flag",
                        value_lower,
                        key,
                    )
        except Exception as exc:
            logger.warning(
                "feature_flag.booking: Redis check failed (%s) — falling back to global flag",
                exc,
            )

    # Fall back to global settings flag
    use_new = settings.USE_CAPABILITY_BOOKING
    logger.debug(
        "feature_flag.booking",
        extra={
            "conversation_id": conversation_id,
            "path": "capability" if use_new else "legacy",
            "source": "global",
        },
    )
    return (use_new, "global")

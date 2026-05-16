"""
Cache invalidation signals via Redis Pub/Sub.

This module provides a lightweight, fail-open publisher for cross-container
cache invalidation signals. When the API mutates stylist data, it publishes
a signal so that the Agent can clear its in-memory caches immediately instead
of waiting for the natural TTL to expire.

Design decisions:
- Fail-open: publish failure NEVER raises. The caller's DB mutation is more
  important than the cache signal. The TTL (10min stylist, 5min dynamic)
  serves as the fallback.
- Direct client access: we call get_redis_client().publish() directly rather
  than using publish_to_channel() because that helper raises HTTPException on
  failure — inappropriate outside of HTTP request context.
- Typed payload: JSON with entity, action, and ISO 8601 timestamp.
"""

import json
import logging
from datetime import UTC, datetime

from shared.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# Redis Pub/Sub channel for cache invalidation signals
CACHE_INVALIDATE_CHANNEL = "cache:invalidate"


async def publish_cache_invalidation(entity: str, action: str = "update") -> None:
    """
    Publish a cache invalidation signal to Redis.

    Fail-open: if Redis is unavailable or publish fails for any reason,
    the exception is caught, logged at WARNING, and NOT re-raised. The
    caller's database mutation is already committed at this point.

    Args:
        entity: The entity type that changed (e.g., "stylists")
        action: The mutation action ("create", "update", or "delete")

    Example payload published:
        {"entity": "stylists", "action": "update", "timestamp": "2025-12-09T10:30:00+00:00"}
    """
    try:
        redis = get_redis_client()
        payload = json.dumps({
            "entity": entity,
            "action": action,
            "timestamp": datetime.now(UTC).isoformat(),
        })
        await redis.publish(CACHE_INVALIDATE_CHANNEL, payload)
        logger.debug(
            f"Cache invalidation signal published: entity={entity}, action={action}"
        )
    except Exception as exc:
        logger.warning(
            f"Cache invalidation signal failed (fail-open): entity={entity}, "
            f"action={action}, error={exc}"
        )

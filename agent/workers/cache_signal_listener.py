"""
Cache invalidation signal listener for the Agent service.

This worker subscribes to the Redis pub/sub channel "cache:invalidate" and
clears the Agent's in-memory caches whenever the API signals a mutation.

Architecture context:
    - The API and Agent run in separate Docker containers with independent
      memory spaces. In-memory caches cannot be shared directly.
    - When a stylist is created/updated/deleted via the admin API, the API
      publishes a signal on "cache:invalidate".
    - This listener receives the signal and clears both in-memory caches so
      the Agent loads fresh data on the next invocation.

Caches cleared on signal:
    - shared.stylist_cache._STYLIST_CONTEXT_CACHE (10-min TTL, used in prompts)
    - agent.prompts.dynamic_context._DYNAMIC_CONTEXT_CACHE (5-min TTL)

Design decisions:
    - Dedicated pubsub() connection: redis.asyncio pub/sub mode puts the
      connection into a special state; it cannot share the pool connection
      used by other redis operations.
    - Exponential backoff on reconnect: starts at 1s, doubles to max 30s.
      On successful reconnect, backoff resets to the initial value.
    - Malformed JSON is silently skipped (logged at WARNING) — one bad
      message must not break the listener loop.
    - asyncio.CancelledError is propagated cleanly for graceful shutdown.
"""

import asyncio
import json
import logging

from shared.redis_client import get_redis_client
from shared.stylist_cache import clear_stylist_context_cache
from agent.prompts.dynamic_context import clear_dynamic_context_cache

logger = logging.getLogger(__name__)

# Redis Pub/Sub channel to subscribe to
CACHE_INVALIDATE_CHANNEL = "cache:invalidate"

# Exponential backoff configuration (seconds)
_BACKOFF_INITIAL = 1
_BACKOFF_MAX = 30


async def run_cache_signal_listener() -> None:
    """
    Infinite loop that subscribes to cache:invalidate and clears in-memory caches.

    This function is designed to be launched as an asyncio.create_task() in
    agent/main.py alongside the other workers. It never returns normally —
    it runs until the task is cancelled (graceful shutdown).

    On Redis errors it reconnects with exponential backoff (1s → 2s → 4s → 30s max).
    On successful reconnect the backoff resets to 1s.
    """
    logger.info(
        f"Cache signal listener starting | channel={CACHE_INVALIDATE_CHANNEL}"
    )

    backoff = _BACKOFF_INITIAL

    while True:
        pubsub = None
        try:
            client = get_redis_client()
            pubsub = client.pubsub()
            await pubsub.subscribe(CACHE_INVALIDATE_CHANNEL)

            # Reset backoff on successful connection
            backoff = _BACKOFF_INITIAL
            logger.info(
                f"Cache signal listener subscribed | channel={CACHE_INVALIDATE_CHANNEL}"
            )

            async for raw_message in pubsub.listen():
                # Skip subscription confirmation and other control messages
                if raw_message["type"] != "message":
                    continue

                try:
                    payload = json.loads(raw_message["data"])
                    entity = payload.get("entity", "unknown")
                    action = payload.get("action", "unknown")

                    logger.info(
                        f"Cache invalidation signal received: "
                        f"entity={entity}, action={action}"
                    )

                    # Clear both in-memory caches
                    clear_stylist_context_cache()
                    clear_dynamic_context_cache()

                    logger.info(
                        "In-memory caches cleared after invalidation signal: "
                        f"entity={entity}, action={action}"
                    )

                except json.JSONDecodeError as exc:
                    # Malformed payload — log and skip, do NOT crash the listener
                    logger.warning(
                        f"Cache signal listener: malformed JSON in message, "
                        f"skipping: {exc}"
                    )
                    continue

        except asyncio.CancelledError:
            # Graceful shutdown: unsubscribe and exit cleanly
            logger.info("Cache signal listener cancelled — shutting down")
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(CACHE_INVALIDATE_CHANNEL)
                    await pubsub.close()
                except Exception as cleanup_exc:
                    logger.warning(
                        f"Cache signal listener: error during cleanup: {cleanup_exc}"
                    )
            return

        except Exception as exc:
            # Redis connection error or unexpected failure — reconnect with backoff
            logger.warning(
                f"Cache signal listener error (reconnecting in {backoff}s): {exc}"
            )
            if pubsub is not None:
                try:
                    await pubsub.close()
                except Exception:
                    pass

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)

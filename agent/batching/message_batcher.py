"""
Message Batcher - Collects messages within a time window before processing.

This module implements a per-conversation message batching system that:
1. Collects messages arriving within a configurable time window
2. Combines them into a single batch when the window expires
3. Invokes a callback to process the entire batch as one input
4. Persists batches to Redis for crash recovery (Phase 6 resilience)

This reduces fragmented responses when users send multiple quick messages.
"""

import asyncio
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Callable, Coroutine

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Redis persistence configuration
BATCH_KEY_PREFIX = "batcher:pending:"
BATCH_TTL_SECONDS = 300  # 5 min TTL (> max batch window of 120s)


class MessageBatcher:
    """
    Batches messages per conversation within a configurable time window.

    When the first message arrives for a conversation, starts a timer.
    Additional messages within the window are collected.
    When timer expires, all messages are passed to the callback as a batch.

    Thread-safe: Uses per-conversation locks to handle concurrent messages.

    Example:
        >>> batcher = MessageBatcher(window_seconds=30)
        >>> batcher.set_callback(process_batch)
        >>> await batcher.add_message("conv-123", {"message_text": "Hello"})
        >>> await batcher.add_message("conv-123", {"message_text": "I need help"})
        >>> # After 30 seconds, process_batch is called with both messages
    """

    def __init__(self, window_seconds: int = 30, redis_client: Redis | None = None):
        """
        Initialize the MessageBatcher.

        Args:
            window_seconds: Time window in seconds to collect messages.
                           Set to 0 to disable batching (immediate processing).
            redis_client: Optional Redis client for crash recovery persistence.
                         If not provided, batches are stored in-memory only.
        """
        self.window_seconds = window_seconds
        self.batches: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.timers: dict[str, asyncio.Task] = {}
        self.locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._callback: Callable[[str, list[dict]], Coroutine] | None = None
        self._redis: Redis | None = redis_client

        persistence_status = "enabled" if redis_client else "disabled"
        logger.info(
            f"MessageBatcher initialized | window_seconds={window_seconds} | "
            f"persistence={persistence_status}"
        )

    def set_callback(
        self, callback: Callable[[str, list[dict]], Coroutine]
    ) -> None:
        """
        Set the callback to invoke when a batch expires.

        Args:
            callback: Async function that receives (conversation_id, messages_list)
        """
        self._callback = callback

    async def add_message(
        self, conversation_id: str, message_data: dict
    ) -> None:
        """
        Add a message to the batch for this conversation.

        If batching is disabled (window_seconds=0), processes immediately.
        Otherwise, adds to batch and starts/extends timer.

        Args:
            conversation_id: Unique identifier for the conversation
            message_data: Message data dict (must contain "message_text")
        """
        # If batching disabled, process immediately
        if self.window_seconds == 0:
            if self._callback:
                await self._callback(conversation_id, [message_data])
            return

        async with self.locks[conversation_id]:
            # Add message to batch with timestamp
            self.batches[conversation_id].append({
                **message_data,
                "received_at": datetime.now(UTC).isoformat(),
            })

            batch_size = len(self.batches[conversation_id])
            logger.info(
                f"Message added to batch | conversation_id={conversation_id} | "
                f"batch_size={batch_size} | window={self.window_seconds}s"
            )

            # Persist batch to Redis for crash recovery
            await self._persist_batch(conversation_id, self.batches[conversation_id])

            # Start timer if this is the first message in batch
            if conversation_id not in self.timers:
                timer = asyncio.create_task(
                    self._wait_and_process(conversation_id)
                )
                self.timers[conversation_id] = timer
                logger.debug(
                    f"Timer started | conversation_id={conversation_id} | "
                    f"expires_in={self.window_seconds}s"
                )

    async def _wait_and_process(self, conversation_id: str) -> None:
        """
        Wait for window to expire, then process the batch.

        Internal method called by the timer task.

        Args:
            conversation_id: Conversation whose batch to process
        """
        try:
            await asyncio.sleep(self.window_seconds)

            async with self.locks[conversation_id]:
                # Extract and clear batch
                batch = self.batches.pop(conversation_id, [])
                self.timers.pop(conversation_id, None)

                if batch and self._callback:
                    logger.info(
                        f"Batch window expired | conversation_id={conversation_id} | "
                        f"processing {len(batch)} messages"
                    )
                    try:
                        await self._callback(conversation_id, batch)
                        # Clear persisted batch after successful processing
                        await self._clear_persisted_batch(conversation_id)
                    except Exception as e:
                        logger.error(
                            f"Error processing batch | conversation_id={conversation_id} | "
                            f"error={str(e)}",
                            exc_info=True,
                        )
                        # NOTE: We do NOT clear persisted batch on error
                        # It will be recovered on next startup

        except asyncio.CancelledError:
            logger.debug(
                f"Timer cancelled | conversation_id={conversation_id}"
            )
            raise

    async def flush_all(self) -> None:
        """
        Flush all pending batches immediately.

        Call this during graceful shutdown to process any remaining messages
        without waiting for their timers to expire.
        """
        logger.info(
            f"Flushing all batches | pending_conversations={len(self.batches)}"
        )

        # Cancel all timers
        for conversation_id, timer in list(self.timers.items()):
            timer.cancel()
            logger.debug(f"Timer cancelled during flush | conversation_id={conversation_id}")

        # Process remaining batches
        for conversation_id, batch in list(self.batches.items()):
            if batch and self._callback:
                logger.info(
                    f"Flushing batch on shutdown | conversation_id={conversation_id} | "
                    f"messages={len(batch)}"
                )
                try:
                    await self._callback(conversation_id, batch)
                except Exception as e:
                    logger.error(
                        f"Error flushing batch | conversation_id={conversation_id} | "
                        f"error={str(e)}",
                        exc_info=True,
                    )

        self.batches.clear()
        self.timers.clear()
        logger.info("All batches flushed")

    @property
    def pending_count(self) -> int:
        """Return the number of conversations with pending batches."""
        return len(self.batches)

    def get_batch_size(self, conversation_id: str) -> int:
        """Return the current batch size for a conversation."""
        return len(self.batches.get(conversation_id, []))

    # =========================================================================
    # REDIS PERSISTENCE METHODS (Phase 6 - Crash Recovery)
    # =========================================================================

    async def _persist_batch(self, conversation_id: str, messages: list[dict]) -> None:
        """
        Persist batch to Redis for crash recovery.

        Args:
            conversation_id: Conversation identifier
            messages: List of message dicts to persist
        """
        if not self._redis:
            return  # No Redis client, skip persistence

        key = f"{BATCH_KEY_PREFIX}{conversation_id}"
        try:
            await self._redis.set(
                key,
                json.dumps(messages),
                ex=BATCH_TTL_SECONDS,
            )
            logger.debug(
                f"Batch persisted to Redis | conversation_id={conversation_id} | "
                f"messages={len(messages)}"
            )
        except Exception as e:
            # Log but don't fail - persistence is best-effort
            logger.warning(
                f"Failed to persist batch to Redis | conversation_id={conversation_id} | "
                f"error={str(e)}"
            )

    async def _clear_persisted_batch(self, conversation_id: str) -> None:
        """
        Clear persisted batch after successful processing.

        Args:
            conversation_id: Conversation identifier
        """
        if not self._redis:
            return  # No Redis client, skip

        key = f"{BATCH_KEY_PREFIX}{conversation_id}"
        try:
            await self._redis.delete(key)
            logger.debug(
                f"Persisted batch cleared | conversation_id={conversation_id}"
            )
        except Exception as e:
            # Log but don't fail
            logger.warning(
                f"Failed to clear persisted batch | conversation_id={conversation_id} | "
                f"error={str(e)}"
            )

    async def recover_pending_batches(self) -> int:
        """
        Recover pending batches from Redis on startup.

        Scans for any batches that were persisted before a crash and
        immediately processes them.

        Returns:
            Number of batches recovered and processed
        """
        if not self._redis:
            logger.info("No Redis client - skipping batch recovery")
            return 0

        if not self._callback:
            logger.warning("No callback set - cannot recover batches")
            return 0

        recovered = 0
        try:
            # Use SCAN instead of KEYS for non-blocking iteration
            cursor = 0
            while True:
                cursor, keys = await self._redis.scan(
                    cursor=cursor,
                    match=f"{BATCH_KEY_PREFIX}*",
                    count=100,
                )

                for key in keys:
                    try:
                        # Extract conversation_id from key
                        key_str = key.decode() if isinstance(key, bytes) else key
                        conversation_id = key_str.replace(BATCH_KEY_PREFIX, "")

                        # Get and parse messages
                        messages_json = await self._redis.get(key)
                        if messages_json:
                            messages_str = (
                                messages_json.decode()
                                if isinstance(messages_json, bytes)
                                else messages_json
                            )
                            messages = json.loads(messages_str)

                            logger.info(
                                f"Recovering batch | conversation_id={conversation_id} | "
                                f"messages={len(messages)}"
                            )

                            # Process the recovered batch immediately
                            try:
                                await self._callback(conversation_id, messages)
                                recovered += 1
                            except Exception as e:
                                logger.error(
                                    f"Error processing recovered batch | "
                                    f"conversation_id={conversation_id} | error={str(e)}",
                                    exc_info=True,
                                )

                            # Clear the persisted batch after processing
                            await self._redis.delete(key)

                    except Exception as e:
                        logger.error(
                            f"Error recovering single batch | key={key} | error={str(e)}",
                            exc_info=True,
                        )

                if cursor == 0:
                    break

            if recovered > 0:
                logger.info(f"Batch recovery complete | recovered={recovered}")
            else:
                logger.debug("No pending batches to recover")

        except Exception as e:
            logger.error(
                f"Batch recovery failed | error={str(e)}",
                exc_info=True,
            )

        return recovered

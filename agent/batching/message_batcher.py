"""
Message Batcher - Collects messages within a time window before processing.

This module implements a per-conversation message batching system that:
1. Collects messages arriving within a configurable time window
2. Combines them into a single batch when the window expires
3. Invokes a callback to process the entire batch as one input

This reduces fragmented responses when users send multiple quick messages.
"""

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


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

    def __init__(self, window_seconds: int = 30):
        """
        Initialize the MessageBatcher.

        Args:
            window_seconds: Time window in seconds to collect messages.
                           Set to 0 to disable batching (immediate processing).
        """
        self.window_seconds = window_seconds
        self.batches: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.timers: dict[str, asyncio.Task] = {}
        self.locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._callback: Callable[[str, list[dict]], Coroutine] | None = None

        logger.info(
            f"MessageBatcher initialized | window_seconds={window_seconds}"
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
                    except Exception as e:
                        logger.error(
                            f"Error processing batch | conversation_id={conversation_id} | "
                            f"error={str(e)}",
                            exc_info=True,
                        )

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

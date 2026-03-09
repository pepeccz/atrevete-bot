"""
Progressive Retry Strategy with Exponential Backoff and Budget Tracking.

This module implements retry logic for LLM API failures classified by the
ErrorClassifier. Each ErrorType receives different retry treatment:

- TRANSIENT: up to 3 retries, exponential backoff (1s → 2s → 4s)
- RATE_LIMIT: up to 1 retry, respects Retry-After header (or 60s default)
- PERMANENT: no retry — will always fail, fail fast
- VALIDATION: no retry — data must be fixed before retrying
- PARTIAL_FAILURE: no retry — requires compensating action, not blind retry

Retry budgets prevent runaway retry loops per conversation:
- MAX_TOTAL_RETRIES = 5 per conversation (across all error types)
- Budget is tracked in-memory per conversation_id with asyncio.Lock

Usage:
    from agent.resilience.retry_strategy import RetryStrategy, RetryBudget

    budget = RetryBudget()
    strategy = RetryStrategy()

    classified = classifier.classify(exc)
    state: RetryState = {
        "attempt_count": 1,
        "last_error_type": classified.error_type,
        "next_retry_at": None,
        "total_retries_used": 0,
        "budget_exhausted": False,
    }

    decision = strategy.should_retry(classified, state)
    if decision.should_retry and budget.consume(conversation_id, classified.error_type):
        await asyncio.sleep(decision.delay_seconds)
        # retry...
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TypedDict

from agent.resilience.error_classifier import ClassifiedError, ErrorType, RetryDecision

logger = logging.getLogger(__name__)


# =============================================================================
# T-005: Retry State types and policy constants
# =============================================================================

# Policy constants — single source of truth for retry behaviour
MAX_RETRIES_TRANSIENT: int = 3
"""Maximum retry attempts for TRANSIENT errors (network glitches, 5xx)."""

MAX_RETRIES_RATE_LIMIT: int = 1
"""Maximum retry attempts for RATE_LIMIT errors (always 1 — wait, then try once)."""

BASE_DELAY: float = 1.0
"""Base delay in seconds for exponential backoff calculation."""

MAX_DELAY: float = 4.0
"""Maximum delay cap in seconds — exponential backoff will not exceed this."""

JITTER_FACTOR: float = 0.1
"""Jitter fraction applied to delay: ±(JITTER_FACTOR * delay) random offset."""

RATE_LIMIT_DEFAULT_DELAY: float = 60.0
"""Default delay (seconds) for RATE_LIMIT when no Retry-After header is present."""


class RetryState(TypedDict):
    """
    Mutable state tracking retry progress for a single operation.

    This is passed into RetryStrategy.should_retry() on each attempt and
    updated by the caller after a decision is made. It represents ONE
    operation's retry history (not the conversation-level budget).

    Fields:
        attempt_count: Number of attempts made so far (1-indexed; 1 = first try).
        last_error_type: ErrorType from the most recent ClassifiedError.
        next_retry_at: ISO-8601 timestamp of when the next retry is scheduled,
                       or None if no delay has been calculated yet.
        total_retries_used: Retries consumed for this operation (attempt_count - 1).
        budget_exhausted: True if the conversation-level RetryBudget is spent.
    """

    attempt_count: int
    last_error_type: ErrorType | None
    next_retry_at: str | None
    total_retries_used: int
    budget_exhausted: bool


# =============================================================================
# T-006: RetryStrategy — should_retry() and calculate_delay()
# =============================================================================


class RetryStrategy:
    """
    Stateless retry decision engine.

    Consumes a ClassifiedError and the current RetryState to produce a
    RetryDecision. Does NOT mutate state — callers are responsible for
    updating their RetryState after acting on the decision.

    Thread-safe (stateless): a single instance can be shared across coroutines.
    """

    def should_retry(
        self,
        classified_error: ClassifiedError,
        retry_state: RetryState,
    ) -> RetryDecision:
        """
        Decide whether to retry an operation based on error type and attempt history.

        Args:
            classified_error: The ClassifiedError produced by ErrorClassifier.classify()
            retry_state: Current retry progress for this specific operation.

        Returns:
            RetryDecision with should_retry, delay_seconds, attempt_number, and reason.
        """
        error_type = classified_error.error_type
        attempt = retry_state["attempt_count"]

        # Budget exhaustion overrides everything
        if retry_state["budget_exhausted"]:
            logger.warning(
                "RetryStrategy: conversation retry budget exhausted | "
                "error_type=%s | attempt=%d",
                error_type,
                attempt,
            )
            return RetryDecision(
                should_retry=False,
                delay_seconds=0.0,
                attempt_number=attempt,
                reason="Retry budget exhausted for this conversation",
            )

        if error_type == ErrorType.TRANSIENT:
            return self._decide_transient(classified_error, attempt)

        if error_type == ErrorType.RATE_LIMIT:
            return self._decide_rate_limit(classified_error, attempt)

        if error_type == ErrorType.PERMANENT:
            logger.info(
                "RetryStrategy: PERMANENT error — not retrying | attempt=%d | msg=%s",
                attempt,
                classified_error.message,
            )
            return RetryDecision(
                should_retry=False,
                delay_seconds=0.0,
                attempt_number=attempt,
                reason="Permanent error — retrying will not succeed",
            )

        if error_type == ErrorType.VALIDATION:
            logger.info(
                "RetryStrategy: VALIDATION error — not retrying | attempt=%d | errors=%s",
                attempt,
                classified_error.validation_errors,
            )
            return RetryDecision(
                should_retry=False,
                delay_seconds=0.0,
                attempt_number=attempt,
                reason="Validation error — data must be corrected before retrying",
            )

        if error_type == ErrorType.PARTIAL_FAILURE:
            logger.info(
                "RetryStrategy: PARTIAL_FAILURE — not retrying (compensating action required) | "
                "attempt=%d | succeeded=%s",
                attempt,
                list(classified_error.partial_results.keys()),
            )
            return RetryDecision(
                should_retry=False,
                delay_seconds=0.0,
                attempt_number=attempt,
                reason="Partial failure — compensating action required, not blind retry",
            )

        # Defensive: unknown error type — fail safe
        logger.warning(
            "RetryStrategy: unknown error_type '%s' — not retrying", error_type
        )
        return RetryDecision(
            should_retry=False,
            delay_seconds=0.0,
            attempt_number=attempt,
            reason=f"Unknown error type: {error_type}",
        )

    def calculate_delay(
        self,
        attempt: int,
        error_type: ErrorType,
        retry_after: float | None = None,
    ) -> float:
        """
        Calculate the delay in seconds before the next retry attempt.

        For TRANSIENT errors uses exponential backoff with jitter:
            delay = BASE_DELAY * (2 ** (attempt - 1))
            jitter = random.uniform(-JITTER_FACTOR, JITTER_FACTOR) * delay
            final  = min(delay + jitter, MAX_DELAY)

        For RATE_LIMIT errors uses the Retry-After header value (or default):
            delay = retry_after if provided else RATE_LIMIT_DEFAULT_DELAY

        All other error types return 0.0 (they should not be retried at all,
        but this method is callable for completeness).

        Args:
            attempt: The attempt number that just failed (1-indexed).
                     attempt=1 → first failure → delay before second try.
            error_type: ErrorType of the classified error.
            retry_after: Optional Retry-After header value in seconds
                         (relevant for RATE_LIMIT errors only).

        Returns:
            Delay in seconds (float, always >= 0.0).
        """
        if error_type == ErrorType.RATE_LIMIT:
            delay = retry_after if retry_after is not None else RATE_LIMIT_DEFAULT_DELAY
            logger.debug(
                "RetryStrategy.calculate_delay: RATE_LIMIT | "
                "retry_after=%s | delay=%.2fs",
                retry_after,
                delay,
            )
            return max(0.0, delay)

        if error_type == ErrorType.TRANSIENT:
            # Exponential backoff: BASE_DELAY * 2^(attempt-1)
            # attempt=1 → 1s, attempt=2 → 2s, attempt=3 → 4s
            raw_delay = BASE_DELAY * (2 ** (attempt - 1))

            # Jitter: random offset in range [-jitter, +jitter]
            jitter_range = JITTER_FACTOR * raw_delay
            jitter = random.uniform(-jitter_range, jitter_range)

            delay = min(raw_delay + jitter, MAX_DELAY)
            delay = max(0.0, delay)  # Never negative

            logger.debug(
                "RetryStrategy.calculate_delay: TRANSIENT | "
                "attempt=%d | raw=%.2fs | jitter=%.3fs | final=%.2fs",
                attempt,
                raw_delay,
                jitter,
                delay,
            )
            return delay

        # Non-retryable types — return 0 (caller should not be calling this)
        return 0.0

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _decide_transient(
        self, classified_error: ClassifiedError, attempt: int
    ) -> RetryDecision:
        """Retry decision for TRANSIENT errors."""
        if attempt > MAX_RETRIES_TRANSIENT:
            logger.warning(
                "RetryStrategy: TRANSIENT max retries reached | "
                "attempt=%d | max=%d",
                attempt,
                MAX_RETRIES_TRANSIENT,
            )
            return RetryDecision(
                should_retry=False,
                delay_seconds=0.0,
                attempt_number=attempt,
                reason=f"Max retries ({MAX_RETRIES_TRANSIENT}) reached for TRANSIENT error",
            )

        delay = self.calculate_delay(attempt, ErrorType.TRANSIENT)
        logger.info(
            "RetryStrategy: TRANSIENT retry | attempt=%d | delay=%.2fs | msg=%s",
            attempt,
            delay,
            classified_error.message,
        )
        return RetryDecision(
            should_retry=True,
            delay_seconds=delay,
            attempt_number=attempt,
            reason=f"TRANSIENT error on attempt {attempt} — retrying with backoff",
        )

    def _decide_rate_limit(
        self, classified_error: ClassifiedError, attempt: int
    ) -> RetryDecision:
        """Retry decision for RATE_LIMIT errors."""
        if attempt > MAX_RETRIES_RATE_LIMIT:
            logger.warning(
                "RetryStrategy: RATE_LIMIT max retries reached | "
                "attempt=%d | max=%d",
                attempt,
                MAX_RETRIES_RATE_LIMIT,
            )
            return RetryDecision(
                should_retry=False,
                delay_seconds=0.0,
                attempt_number=attempt,
                reason=f"Max retries ({MAX_RETRIES_RATE_LIMIT}) reached for RATE_LIMIT error",
            )

        delay = self.calculate_delay(
            attempt,
            ErrorType.RATE_LIMIT,
            retry_after=classified_error.retry_after,
        )
        logger.info(
            "RetryStrategy: RATE_LIMIT retry | attempt=%d | delay=%.2fs | "
            "retry_after=%s",
            attempt,
            delay,
            classified_error.retry_after,
        )
        return RetryDecision(
            should_retry=True,
            delay_seconds=delay,
            attempt_number=attempt,
            reason=(
                f"Rate limited on attempt {attempt} — "
                f"waiting {delay:.1f}s before retry"
            ),
        )


# =============================================================================
# T-007: RetryBudget — per-conversation retry budget with asyncio.Lock
# =============================================================================


class RetryBudget:
    """
    Per-conversation retry budget that prevents runaway retry loops.

    Each conversation gets a fixed budget of MAX_TOTAL_RETRIES retries
    across all error types. Once exhausted, no further retries are allowed
    until the budget is explicitly reset (e.g., on conversation end).

    Thread-safe via asyncio.Lock (one lock per conversation_id).

    Attributes:
        MAX_TOTAL_RETRIES: Maximum retries allowed per conversation (class constant).
    """

    MAX_TOTAL_RETRIES: int = 5
    """Maximum total retries permitted per conversation (across all error types)."""

    def __init__(self) -> None:
        # Dict mapping conversation_id → retries consumed so far
        self._budgets: dict[str, int] = {}
        # Per-conversation locks to prevent race conditions in concurrent coroutines
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, conversation_id: str) -> asyncio.Lock:
        """Get or create the asyncio.Lock for a conversation."""
        if conversation_id not in self._locks:
            self._locks[conversation_id] = asyncio.Lock()
        return self._locks[conversation_id]

    async def consume(self, conversation_id: str, error_type: ErrorType) -> bool:
        """
        Attempt to consume one retry from the conversation's budget.

        Args:
            conversation_id: Unique identifier for the conversation.
            error_type: The ErrorType of the error being retried (for logging).

        Returns:
            True if the budget had remaining retries and one was consumed.
            False if the budget is exhausted — caller must NOT retry.
        """
        lock = self._get_lock(conversation_id)
        async with lock:
            used = self._budgets.get(conversation_id, 0)
            remaining = self.MAX_TOTAL_RETRIES - used

            if remaining <= 0:
                logger.warning(
                    "RetryBudget: budget exhausted | conversation_id=%s | "
                    "used=%d | max=%d | error_type=%s",
                    conversation_id,
                    used,
                    self.MAX_TOTAL_RETRIES,
                    error_type,
                )
                return False

            self._budgets[conversation_id] = used + 1
            logger.debug(
                "RetryBudget: consumed 1 retry | conversation_id=%s | "
                "used=%d | remaining=%d | error_type=%s",
                conversation_id,
                used + 1,
                remaining - 1,
                error_type,
            )
            return True

    async def reset(self, conversation_id: str) -> None:
        """
        Reset the retry budget for a conversation back to full capacity.

        Call this when a conversation ends, when a successful response is
        received, or when a new booking flow starts.

        Args:
            conversation_id: Unique identifier for the conversation to reset.
        """
        lock = self._get_lock(conversation_id)
        async with lock:
            if conversation_id in self._budgets:
                prev = self._budgets.pop(conversation_id)
                logger.debug(
                    "RetryBudget: reset | conversation_id=%s | was_used=%d",
                    conversation_id,
                    prev,
                )

    async def get_remaining(self, conversation_id: str) -> int:
        """
        Get the number of retries remaining in the budget for a conversation.

        Args:
            conversation_id: Unique identifier for the conversation.

        Returns:
            Number of retries still available (0 if exhausted).
        """
        lock = self._get_lock(conversation_id)
        async with lock:
            used = self._budgets.get(conversation_id, 0)
            return max(0, self.MAX_TOTAL_RETRIES - used)

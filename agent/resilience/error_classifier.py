"""
Error Classification System for LLM API errors.

This module provides domain-specific error classification for all external API
calls made by the conversational agent. It classifies exceptions into five
categories and provides retryability decisions.

Error Categories:
- TRANSIENT: Temporary network/server issues — safe to retry with backoff
- RATE_LIMIT: API quota exceeded — retry after the indicated delay
- PERMANENT: Auth failures, not found — do not retry (will always fail)
- VALIDATION: Schema/business rule violations — fix data before retrying
- PARTIAL_FAILURE: Some tools succeeded, others failed — partial recovery

Usage:
    from agent.resilience.error_classifier import ErrorClassifier

    classifier = ErrorClassifier()
    classified = classifier.classify(exc)
    if classified.is_retryable:
        await asyncio.sleep(classified.retry_after or backoff_delay)
        # retry...
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# T-001: Error Type Enums and Dataclasses
# =============================================================================


class ErrorType(str, Enum):
    """
    Classification of LLM API and external service errors.

    Determines how the resilience layer responds to each error class.
    """

    TRANSIENT = "transient"
    """Temporary failure — network glitch, server overload. Retry with backoff."""

    RATE_LIMIT = "rate_limit"
    """API quota exceeded (HTTP 429). Retry after Retry-After delay."""

    PERMANENT = "permanent"
    """Non-recoverable failure — auth error, resource not found. Do not retry."""

    VALIDATION = "validation"
    """Schema or business rule violation. Must fix data before retrying."""

    PARTIAL_FAILURE = "partial_failure"
    """Some operations succeeded, others failed. Preserve successful results."""


# Mapping of ErrorType to retryability (single source of truth)
_RETRYABLE_TYPES: frozenset[ErrorType] = frozenset({
    ErrorType.TRANSIENT,
    ErrorType.RATE_LIMIT,
})


@dataclass
class ClassifiedError:
    """
    Fully classified error with retryability decision and metadata.

    Produced by ErrorClassifier.classify() for every caught exception.
    Consumers use this to decide: retry, fallback, or fail permanently.

    Attributes:
        error_type: The category of the error
        original_exception: The raw exception that was classified
        http_status: HTTP status code if applicable (None for non-HTTP errors)
        retry_after: Seconds to wait before retrying (only for RATE_LIMIT errors)
        message: Human-readable description of the error
        is_retryable: True if retrying may succeed; False if the error is permanent
        validation_errors: Field-level validation error details (VALIDATION only)
        partial_results: Successfully completed results before failure (PARTIAL_FAILURE only)
        classified_at: UTC timestamp when classification occurred
    """

    error_type: ErrorType
    original_exception: Exception
    http_status: int | None = None
    retry_after: float | None = None
    message: str = ""
    is_retryable: bool = False
    validation_errors: list[str] = field(default_factory=list)
    partial_results: dict[str, Any] = field(default_factory=dict)
    classified_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self) -> None:
        """Ensure is_retryable is consistent with error_type."""
        # Enforce canonical retryability — callers should not override this
        self.is_retryable = self.error_type in _RETRYABLE_TYPES


@dataclass
class RetryDecision:
    """
    Decision about whether and how to retry a failed operation.

    Produced by RetryStrategy (Phase 2) using ClassifiedError as input.
    Included here so Phase 1 consumers can reference the type.
    """

    should_retry: bool
    """Whether to attempt the operation again."""

    delay_seconds: float = 0.0
    """Seconds to wait before the next attempt (may be 0 if no delay needed)."""

    attempt_number: int = 1
    """The attempt that just failed (1-indexed)."""

    reason: str = ""
    """Human-readable explanation of the retry decision."""


@dataclass
class FallbackMetrics:
    """
    Metrics collected during a fallback operation.

    Used by FallbackChain (Phase 3) to track provider switching behaviour.
    Included here so Phase 1 consumers can import the type.
    """

    primary_provider: str
    """Name of the primary LLM provider that failed."""

    fallback_provider: str | None = None
    """Name of the fallback provider that was used (None if no fallback attempted)."""

    primary_error_type: ErrorType | None = None
    """Error type that triggered the fallback."""

    fallback_succeeded: bool = False
    """Whether the fallback call succeeded."""

    latency_ms: float = 0.0
    """Total time including primary failure and fallback call, in milliseconds."""


# =============================================================================
# T-002: ErrorClassifier Implementation
# =============================================================================


class ErrorClassifier:
    """
    Classifies exceptions from LLM API calls and external services.

    Handles three exception families:
    - openai exceptions (APIStatusError, RateLimitError, AuthenticationError, etc.)
    - httpx exceptions (TimeoutException, ConnectError, HTTPStatusError)
    - Built-in Python exceptions (TimeoutError, ConnectionError, ValueError, etc.)

    Classification priority (top wins):
    1. openai.RateLimitError → RATE_LIMIT
    2. openai.AuthenticationError / openai.PermissionDeniedError → PERMANENT
    3. openai.NotFoundError → PERMANENT
    4. openai.APIStatusError (HTTP 429) → RATE_LIMIT
    5. openai.APIStatusError (5xx) → TRANSIENT
    6. openai.APIStatusError (401, 403, 404) → PERMANENT
    7. openai.APIConnectionError / openai.APITimeoutError → TRANSIENT
    8. httpx.TimeoutException / httpx.ConnectError → TRANSIENT
    9. httpx.HTTPStatusError → mapped by status code
    10. asyncio.TimeoutError / TimeoutError / ConnectionError → TRANSIENT
    11. ValueError (schema/parsing failures) → VALIDATION
    12. Any unknown exception → TRANSIENT (safe default)

    Usage:
        classifier = ErrorClassifier()
        result = classifier.classify(some_exception)
        print(result.error_type, result.is_retryable, result.retry_after)
    """

    def classify(self, exc: Exception) -> ClassifiedError:
        """
        Classify an exception into an ErrorType with full metadata.

        Args:
            exc: The exception to classify. Any Python exception is accepted.

        Returns:
            ClassifiedError with error_type, retryability, and extracted metadata.
        """
        # --- openai exceptions (most specific first) ---------------------------
        try:
            from openai import (
                APIConnectionError as OpenAIConnectionError,
                APIStatusError,
                APITimeoutError as OpenAITimeoutError,
                AuthenticationError,
                NotFoundError,
                PermissionDeniedError,
                RateLimitError,
            )

            if isinstance(exc, RateLimitError):
                return self._classify_rate_limit(exc)

            if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
                return ClassifiedError(
                    error_type=ErrorType.PERMANENT,
                    original_exception=exc,
                    http_status=exc.status_code,
                    message=f"Authentication/permission failure: {exc}",
                )

            if isinstance(exc, NotFoundError):
                return ClassifiedError(
                    error_type=ErrorType.PERMANENT,
                    original_exception=exc,
                    http_status=exc.status_code,
                    message=f"Resource not found: {exc}",
                )

            if isinstance(exc, APIStatusError):
                return self._classify_by_http_status(
                    exc, status=exc.status_code, message=str(exc)
                )

            if isinstance(exc, (OpenAIConnectionError, OpenAITimeoutError)):
                return ClassifiedError(
                    error_type=ErrorType.TRANSIENT,
                    original_exception=exc,
                    message=f"OpenAI connection/timeout: {exc}",
                )

        except ImportError:
            # openai package not installed in this environment — skip these checks
            logger.debug("openai package not available; skipping openai exception checks")

        # --- httpx exceptions -------------------------------------------------
        try:
            import httpx

            if isinstance(exc, httpx.TimeoutException):
                return ClassifiedError(
                    error_type=ErrorType.TRANSIENT,
                    original_exception=exc,
                    message=f"HTTP timeout: {exc}",
                )

            if isinstance(exc, httpx.ConnectError):
                return ClassifiedError(
                    error_type=ErrorType.TRANSIENT,
                    original_exception=exc,
                    message=f"HTTP connection error: {exc}",
                )

            if isinstance(exc, httpx.HTTPStatusError):
                status = exc.response.status_code if exc.response is not None else None
                return self._classify_by_http_status(
                    exc, status=status, message=str(exc)
                )

        except ImportError:
            logger.debug("httpx package not available; skipping httpx exception checks")

        # --- asyncio / built-in exceptions ------------------------------------
        import asyncio

        if isinstance(exc, asyncio.TimeoutError):
            return ClassifiedError(
                error_type=ErrorType.TRANSIENT,
                original_exception=exc,
                message="asyncio timeout",
            )

        if isinstance(exc, TimeoutError):
            return ClassifiedError(
                error_type=ErrorType.TRANSIENT,
                original_exception=exc,
                message=f"Timeout: {exc}",
            )

        if isinstance(exc, ConnectionError):
            return ClassifiedError(
                error_type=ErrorType.TRANSIENT,
                original_exception=exc,
                message=f"Connection error: {exc}",
            )

        if isinstance(exc, ValueError):
            return ClassifiedError(
                error_type=ErrorType.VALIDATION,
                original_exception=exc,
                message=f"Validation error: {exc}",
                validation_errors=[str(exc)],
            )

        # --- Unknown exception: default to TRANSIENT (safe, allows retry) -----
        logger.warning(
            "ErrorClassifier: unknown exception type '%s' — defaulting to TRANSIENT | error=%s",
            type(exc).__name__,
            exc,
        )
        return ClassifiedError(
            error_type=ErrorType.TRANSIENT,
            original_exception=exc,
            message=f"Unknown error ({type(exc).__name__}): {exc}",
        )

    def classify_partial_failure(
        self,
        exc: Exception,
        partial_results: dict[str, Any],
    ) -> ClassifiedError:
        """
        Classify a partial failure where some tool calls succeeded and others failed.

        Use this when a multi-tool LLM response partially succeeded (e.g., the
        booking was created in the DB but the Google Calendar push failed).

        Args:
            exc: The exception from the failing operation
            partial_results: Dict mapping tool_name → result for successful calls

        Returns:
            ClassifiedError with PARTIAL_FAILURE type and preserved partial results
        """
        return ClassifiedError(
            error_type=ErrorType.PARTIAL_FAILURE,
            original_exception=exc,
            message=f"Partial failure — some tools succeeded: {list(partial_results.keys())}",
            partial_results=partial_results,
        )

    def is_retryable(self, error_type: ErrorType) -> bool:
        """
        Check if an ErrorType is safe to retry.

        Args:
            error_type: The ErrorType to check

        Returns:
            True if retrying may succeed (TRANSIENT or RATE_LIMIT)
        """
        return error_type in _RETRYABLE_TYPES

    def get_retry_after(self, exc: Exception) -> float | None:
        """
        Extract the Retry-After value (seconds) from an exception, if available.

        Handles:
        - openai.RateLimitError — checks response headers
        - openai.APIStatusError — checks response headers
        - httpx.HTTPStatusError — checks response headers

        Args:
            exc: The exception to inspect

        Returns:
            Float seconds to wait, or None if no Retry-After header found
        """
        # Try to extract from openai exceptions
        try:
            from openai import APIStatusError

            if isinstance(exc, APIStatusError) and exc.response is not None:
                return self._parse_retry_after_header(
                    exc.response.headers.get("retry-after")
                    or exc.response.headers.get("Retry-After")
                )
        except (ImportError, AttributeError):
            pass

        # Try to extract from httpx exceptions
        try:
            import httpx

            if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
                return self._parse_retry_after_header(
                    exc.response.headers.get("retry-after")
                    or exc.response.headers.get("Retry-After")
                )
        except (ImportError, AttributeError):
            pass

        return None

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _classify_rate_limit(self, exc: Exception) -> ClassifiedError:
        """Build a RATE_LIMIT ClassifiedError, extracting Retry-After if present."""
        retry_after = self.get_retry_after(exc)
        http_status: int | None = None

        try:
            # openai.RateLimitError has status_code attribute
            http_status = getattr(exc, "status_code", None)
        except Exception:
            pass

        return ClassifiedError(
            error_type=ErrorType.RATE_LIMIT,
            original_exception=exc,
            http_status=http_status or 429,
            retry_after=retry_after,
            message=f"Rate limit exceeded: {exc}",
        )

    def _classify_by_http_status(
        self,
        exc: Exception,
        status: int | None,
        message: str,
    ) -> ClassifiedError:
        """Classify an HTTP error by its status code."""
        if status == 429:
            return self._classify_rate_limit(exc)

        if status in {500, 502, 503, 504}:
            return ClassifiedError(
                error_type=ErrorType.TRANSIENT,
                original_exception=exc,
                http_status=status,
                message=f"Server error HTTP {status}: {message}",
            )

        if status in {401, 403}:
            return ClassifiedError(
                error_type=ErrorType.PERMANENT,
                original_exception=exc,
                http_status=status,
                message=f"Auth error HTTP {status}: {message}",
            )

        if status == 404:
            return ClassifiedError(
                error_type=ErrorType.PERMANENT,
                original_exception=exc,
                http_status=status,
                message=f"Not found HTTP 404: {message}",
            )

        if status is not None and status >= 400:
            # 4xx client errors (other than 401, 403, 404, 429) → PERMANENT
            # These indicate a problem with the request itself
            return ClassifiedError(
                error_type=ErrorType.PERMANENT,
                original_exception=exc,
                http_status=status,
                message=f"Client error HTTP {status}: {message}",
            )

        # Unknown or no status — default to TRANSIENT
        return ClassifiedError(
            error_type=ErrorType.TRANSIENT,
            original_exception=exc,
            http_status=status,
            message=f"HTTP error (status={status}): {message}",
        )

    @staticmethod
    def _parse_retry_after_header(value: str | None) -> float | None:
        """
        Parse a Retry-After header value to float seconds.

        Handles two RFC 7231 formats:
        - Delta-seconds: "120" → 120.0
        - HTTP-date: "Wed, 21 Oct 2015 07:28:00 GMT" → seconds until that time

        Args:
            value: Raw header string or None

        Returns:
            Float seconds to wait, or None if unparseable
        """
        if not value:
            return None

        # Try integer/float seconds first (most common in modern APIs)
        try:
            seconds = float(value.strip())
            return max(0.0, seconds)  # Clamp to non-negative
        except (ValueError, AttributeError):
            pass

        # Try HTTP-date format
        from email.utils import parsedate_to_datetime
        import datetime as dt

        try:
            retry_at = parsedate_to_datetime(value)
            now = dt.datetime.now(dt.timezone.utc)
            delta = (retry_at - now).total_seconds()
            return max(0.0, delta)
        except Exception:
            logger.debug(
                "ErrorClassifier: could not parse Retry-After header '%s'", value
            )
            return None

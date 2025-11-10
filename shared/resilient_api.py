"""
Resilient API client with retry logic and error handling.

This module provides decorators and utilities for making API calls more resilient
by implementing exponential backoff, retry logic, and graceful error handling.

Used for:
- Google Calendar API calls
- Database operations
- External service integrations
"""

import asyncio
import logging
from typing import Any, Callable, TypeVar, ParamSpec
from functools import wraps

from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Type variables for generic decorators
P = ParamSpec('P')
T = TypeVar('T')


async def call_with_retry(
    func: Callable[P, T],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 10.0,
    exponential_base: float = 2.0,
    *args: P.args,
    **kwargs: P.kwargs
) -> T:
    """
    Call a function with exponential backoff retry logic.

    Args:
        func: Function to call (can be sync or async)
        max_retries: Maximum number of retry attempts (default: 3)
        initial_delay: Initial delay between retries in seconds (default: 1.0)
        max_delay: Maximum delay between retries in seconds (default: 10.0)
        exponential_base: Base for exponential backoff (default: 2.0)
        *args: Positional arguments to pass to func
        **kwargs: Keyword arguments to pass to func

    Returns:
        Result from successful function call

    Raises:
        Exception: If all retries are exhausted, raises the last exception

    Example:
        >>> result = await call_with_retry(
        ...     some_api_function,
        ...     max_retries=3,
        ...     arg1="value1",
        ...     arg2="value2"
        ... )
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            # Call function (handle both sync and async)
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            # Success
            if attempt > 0:
                logger.info(
                    f"Function {func.__name__} succeeded on attempt {attempt + 1}"
                )
            return result

            last_exception = e

            # Check if this is a retryable error
            if not is_retryable_error(e):
                logger.warning(
                    f"Non-retryable error in {func.__name__}: {e}"
                )
                raise

            # Last attempt - don't sleep, just raise
            if attempt == max_retries:
                logger.error(
                    f"Function {func.__name__} failed after {max_retries + 1} attempts: {e}"
                )
                raise

            # Calculate delay with exponential backoff
            delay = min(initial_delay * (exponential_base ** attempt), max_delay)

            logger.warning(
                f"Function {func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}), "
                f"retrying in {delay:.2f}s: {e}"
            )

            await asyncio.sleep(delay)

    # Should never reach here, but for type safety
    if last_exception:
        raise last_exception


def is_retryable_error(error: Exception) -> bool:
    """
    Determine if an error is retryable.

    Args:
        error: Exception to check

    Returns:
        bool: True if error is retryable, False otherwise

    Retryable errors:
    - Google Calendar API: 429 (rate limit), 500, 502, 503, 504
    - Network errors, timeouts
    """
    # Google Calendar HTTP errors
    if isinstance(error, HttpError):
        status = error.resp.status
        # Retryable: Rate limit, server errors
        return status in (429, 500, 502, 503, 504)

        return True

        return True

        return True

    # Generic network/timeout errors
    if isinstance(error, (ConnectionError, TimeoutError, OSError)):
        return True

    # Database connection errors (asyncpg)
    error_name = type(error).__name__
    if error_name in ("InterfaceError", "OperationalError"):
        return True

    # Default: non-retryable
    return False


def retry_on_error(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 10.0,
    exponential_base: float = 2.0,
):
    """
    Decorator for automatic retry logic on async functions.

    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        exponential_base: Base for exponential backoff

    Example:
        >>> @retry_on_error(max_retries=3)
        >>> async def fetch_calendar_data():
        ...     return await calendar_api.get_events()
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return await call_with_retry(
                func,
                max_retries=max_retries,
                initial_delay=initial_delay,
                max_delay=max_delay,
                exponential_base=exponential_base,
                *args,
                **kwargs
            )
        return wrapper
    return decorator


class ResilientAPIError(Exception):
    """
    Exception raised when all retry attempts are exhausted.

    Attributes:
        message: Error message
        original_error: Original exception that caused the failure
        attempts: Number of attempts made
    """

    def __init__(self, message: str, original_error: Exception, attempts: int):
        self.message = message
        self.original_error = original_error
        self.attempts = attempts
        super().__init__(self.message)

    def __str__(self):
        return (
            f"{self.message} (failed after {self.attempts} attempts, "
            f"original error: {type(self.original_error).__name__}: {self.original_error})"
        )


async def call_with_escalation(
    func: Callable[P, T],
    escalation_callback: Callable[[Exception], Any] | None = None,
    max_retries: int = 3,
    *args: P.args,
    **kwargs: P.kwargs
) -> T | None:
    """
    Call a function with retry logic and optional escalation on failure.

    If all retries fail, calls escalation_callback (if provided) and returns None.
    This is useful for non-critical operations where you want to escalate but not crash.

    Args:
        func: Function to call
        escalation_callback: Optional async function to call on complete failure
        max_retries: Maximum number of retry attempts
        *args: Positional arguments to pass to func
        **kwargs: Keyword arguments to pass to func

    Returns:
        Result from function or None if failed and escalated

    Example:
        >>> async def escalate_to_human(error):
        ...     await notify_staff(f"API failure: {error}")
        >>>
        >>> result = await call_with_escalation(
        ...     fetch_critical_data,
        ...     escalation_callback=escalate_to_human,
        ...     arg1="value"
        ... )
    """
    try:
        return await call_with_retry(func, max_retries=max_retries, *args, **kwargs)

    except Exception as e:
        logger.error(
            f"Function {func.__name__} failed after all retries, escalating: {e}",
            exc_info=True
        )

        # Call escalation callback if provided
        if escalation_callback:
            try:
                if asyncio.iscoroutinefunction(escalation_callback):
                    await escalation_callback(e)
                else:
                    escalation_callback(e)
            except Exception as escalation_error:
                logger.error(
                    f"Escalation callback failed: {escalation_error}",
                    exc_info=True
                )

        return None

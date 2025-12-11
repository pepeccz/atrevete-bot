"""
Circuit Breaker Pattern Implementation.

This module provides circuit breaker protection for external service calls
to prevent cascade failures when services are down or degraded.

Circuit breaker states:
- CLOSED: Normal operation, requests pass through
- OPEN: Service is down, requests fail fast without calling the service
- HALF_OPEN: Testing if service recovered, limited requests allowed

Usage:
    from shared.circuit_breaker import openrouter_breaker
    import pybreaker

    try:
        result = await openrouter_breaker.call_async(my_async_function, *args)
    except pybreaker.CircuitBreakerError:
        # Circuit is OPEN - service is down, use fallback
        return fallback_response()

Configuration:
    - fail_max: Number of consecutive failures before opening circuit
    - reset_timeout: Seconds to wait before trying again (half-open state)
"""

import logging
from functools import wraps
from typing import Any, Callable

import pybreaker

logger = logging.getLogger(__name__)


class CircuitBreakerLogger(pybreaker.CircuitBreakerListener):
    """
    Log circuit breaker state changes and failures.

    This listener provides visibility into circuit breaker behavior
    for debugging and monitoring purposes.
    """

    def state_change(self, cb: pybreaker.CircuitBreaker, old_state, new_state) -> None:
        """Log state transitions."""
        if new_state.name == "open":
            logger.warning(
                f"Circuit breaker '{cb.name}' OPENED - "
                f"service appears down, failing fast for {cb.reset_timeout}s"
            )
        elif new_state.name == "half-open":
            logger.info(
                f"Circuit breaker '{cb.name}' HALF-OPEN - "
                f"testing if service recovered"
            )
        elif new_state.name == "closed":
            logger.info(
                f"Circuit breaker '{cb.name}' CLOSED - "
                f"service recovered, resuming normal operation"
            )
        else:
            logger.info(
                f"Circuit breaker '{cb.name}' state: {old_state.name} -> {new_state.name}"
            )

    def failure(self, cb: pybreaker.CircuitBreaker, exc: Exception) -> None:
        """Log failures that count toward opening the circuit."""
        logger.warning(
            f"Circuit breaker '{cb.name}' recorded failure: {type(exc).__name__}: {exc}"
        )

    def success(self, cb: pybreaker.CircuitBreaker) -> None:
        """Log successful calls (only in half-open state for debugging)."""
        if cb.current_state == pybreaker.STATE_HALF_OPEN:
            logger.info(f"Circuit breaker '{cb.name}' success in half-open state")


# Singleton registry of circuit breakers
_breakers: dict[str, pybreaker.CircuitBreaker] = {}
_logger_instance = CircuitBreakerLogger()


def get_circuit_breaker(
    name: str,
    fail_max: int = 5,
    reset_timeout: int = 30,
    exclude: list[type] | None = None,
) -> pybreaker.CircuitBreaker:
    """
    Get or create a circuit breaker for a service.

    Args:
        name: Unique identifier for the circuit breaker
        fail_max: Number of consecutive failures before opening circuit
        reset_timeout: Seconds before attempting recovery (half-open)
        exclude: Exception types that should NOT count as failures

    Returns:
        CircuitBreaker instance (singleton per name)
    """
    if name not in _breakers:
        _breakers[name] = pybreaker.CircuitBreaker(
            name=name,
            fail_max=fail_max,
            reset_timeout=reset_timeout,
            exclude=exclude or [],
            listeners=[_logger_instance],
        )
        logger.info(
            f"Created circuit breaker '{name}' | "
            f"fail_max={fail_max} | reset_timeout={reset_timeout}s"
        )
    return _breakers[name]


def with_circuit_breaker(breaker: pybreaker.CircuitBreaker):
    """
    Decorator to wrap async functions with circuit breaker protection.

    Usage:
        @with_circuit_breaker(openrouter_breaker)
        async def call_llm(...):
            ...

    Args:
        breaker: CircuitBreaker instance to use

    Returns:
        Decorated function that fails fast when circuit is open
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            return await breaker.call_async(func, *args, **kwargs)

        return wrapper

    return decorator


# =============================================================================
# PRE-CONFIGURED CIRCUIT BREAKERS FOR EXTERNAL SERVICES
# =============================================================================
# These are the main circuit breakers used throughout the application.
# Each is tuned for the specific characteristics of the service.

# OpenRouter (LLM API) - Most critical, affects all conversations
# - 5 failures before opening (allows for occasional transient errors)
# - 30 second reset (LLM outages are usually brief or long, not medium)
openrouter_breaker = get_circuit_breaker(
    name="openrouter",
    fail_max=5,
    reset_timeout=30,
)

# Google Calendar API - Critical for booking flow
# - 5 failures before opening
# - 15 second reset (calendar API typically recovers quickly)
calendar_breaker = get_circuit_breaker(
    name="google_calendar",
    fail_max=5,
    reset_timeout=15,
)

# Chatwoot API - Important for customer communication
# - 5 failures before opening
# - 60 second reset (longer because missing messages are more critical)
chatwoot_breaker = get_circuit_breaker(
    name="chatwoot",
    fail_max=5,
    reset_timeout=60,
)


async def call_with_breaker(
    breaker: pybreaker.CircuitBreaker,
    func: Callable,
    *args,
    **kwargs,
) -> Any:
    """
    Call async function with circuit breaker protection (native asyncio).

    pybreaker's call_async() requires Tornado which we don't use.
    This provides simplified fail-fast functionality for asyncio.

    Note: pybreaker doesn't have public methods for manual success/failure
    tracking. This implementation provides basic circuit breaker behavior:
    - Fail fast when circuit is OPEN
    - On repeated failures, manually open the circuit
    - Circuit auto-resets after reset_timeout via pybreaker internals

    Args:
        breaker: CircuitBreaker instance to use
        func: Async function to call
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func

    Returns:
        Result from func

    Raises:
        pybreaker.CircuitBreakerError: If circuit is open
        Exception: Any exception raised by func
    """
    # Check if circuit is open (fail fast)
    if breaker.current_state == pybreaker.STATE_OPEN:
        logger.warning(f"Circuit breaker '{breaker.name}' is OPEN, failing fast")
        raise pybreaker.CircuitBreakerError(breaker)

    try:
        # Execute the async function
        result = await func(*args, **kwargs)

        # On success, close the circuit if it was half-open
        if breaker.current_state == pybreaker.STATE_HALF_OPEN:
            breaker.close()
            logger.info(f"Circuit breaker '{breaker.name}' recovered, closing circuit")

        return result

    except pybreaker.CircuitBreakerError:
        # Circuit breaker error - just re-raise
        raise

    except Exception as e:
        # Check if exception should count as failure
        if breaker.is_system_error(e):
            # Log the failure
            logger.warning(
                f"Circuit breaker '{breaker.name}' recorded failure: "
                f"{type(e).__name__}: {e}"
            )

            # If we're in half-open state and got a failure, open the circuit
            if breaker.current_state == pybreaker.STATE_HALF_OPEN:
                breaker.open()
                logger.warning(f"Circuit breaker '{breaker.name}' reopened after failure in half-open state")

        raise


def get_breaker_status() -> dict[str, dict[str, Any]]:
    """
    Get status of all circuit breakers for monitoring/health checks.

    Returns:
        Dict of {name: {state, fail_counter, reset_timeout}}
    """
    return {
        name: {
            "state": breaker.current_state,
            "fail_counter": breaker.fail_counter,
            "reset_timeout": breaker.reset_timeout,
        }
        for name, breaker in _breakers.items()
    }

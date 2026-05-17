"""
Mock LLM Provider harness for resilience layer integration tests.

Provides configurable mock providers that simulate:
- Normal responses (configurable response text)
- Transient failures (raise ConnectionError/TimeoutError after N calls)
- Rate limit responses (raise 429 with Retry-After header)
- Permanent failures (raise 401 AuthenticationError)
- Partial failures (calendar sync marked as failed)

Usage:
    from tests.mocks.mock_llm_providers import (
        MockLLMProvider,
        make_transient_error,
        make_rate_limit_error,
        make_permanent_error,
        make_timeout_error,
    )

    # Provider that fails twice then succeeds
    provider = MockLLMProvider(
        responses=["Hello, I can help!"],
        fail_first_n=2,
        failure_factory=make_transient_error,
    )
    # Call 1: raises transient error
    # Call 2: raises transient error
    # Call 3: returns MagicMock with content="Hello, I can help!"
    response = await provider.ainvoke(messages)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

# =============================================================================
# Error factory helpers — build real openai/httpx exception instances
# =============================================================================


def make_transient_error() -> Exception:
    """
    Build a transient error that ErrorClassifier classifies as TRANSIENT.

    Uses ConnectionError (built-in) which is guaranteed to be available
    without any optional dependencies. The ErrorClassifier classifies it
    as TRANSIENT with is_retryable=True.

    Returns:
        ConnectionError instance.
    """
    return ConnectionError("Connection refused by remote server")


def make_timeout_error() -> Exception:
    """
    Build a timeout error that ErrorClassifier classifies as TRANSIENT.

    Returns:
        TimeoutError instance.
    """
    return TimeoutError("Request timed out after 30 seconds")


def make_rate_limit_error(retry_after: float = 60.0) -> Exception:
    """
    Build a rate-limit error that ErrorClassifier classifies as RATE_LIMIT.

    Attempts to build an openai.RateLimitError with a mocked response that
    carries a Retry-After header. Falls back to a plain Exception with
    http_status=429 semantics if openai is not importable in test env.

    Args:
        retry_after: Value (in seconds) to set in the Retry-After header.

    Returns:
        openai.RateLimitError or a stand-in httpx.HTTPStatusError with 429.
    """
    try:
        from openai import RateLimitError

        mock_response = MagicMock()
        mock_response.headers = {"retry-after": str(retry_after)}
        mock_response.status_code = 429
        return RateLimitError(
            f"Rate limit exceeded. Retry after {retry_after}s",
            response=mock_response,
            body=None,
        )
    except ImportError:
        pass

    # Fallback: httpx 429 (also classified as RATE_LIMIT by ErrorClassifier)
    try:
        import httpx

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 429
        mock_response.headers = {"retry-after": str(retry_after)}
        return httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=MagicMock(),
            response=mock_response,
        )
    except ImportError:
        pass

    # Last resort: generic exception (won't have retry_after extracted,
    # but will be classified as TRANSIENT and still retried)
    return RuntimeError("Rate limit exceeded (mock fallback)")


def make_permanent_error() -> Exception:
    """
    Build a permanent error that ErrorClassifier classifies as PERMANENT.

    Uses openai.AuthenticationError (401) which is the canonical permanent
    failure (invalid API key). Falls back to an httpx 401 error.

    Returns:
        openai.AuthenticationError or httpx.HTTPStatusError with 401.
    """
    try:
        from openai import AuthenticationError

        mock_response = MagicMock()
        mock_response.status_code = 401
        return AuthenticationError(
            "Invalid API key provided",
            response=mock_response,
            body=None,
        )
    except ImportError:
        pass

    try:
        import httpx

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401
        mock_response.headers = {}
        return httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=mock_response,
        )
    except ImportError:
        pass

    return PermissionError("Invalid API key (mock fallback)")


def make_openai_connection_error() -> Exception:
    """
    Build an openai.APIConnectionError that ErrorClassifier classifies as TRANSIENT.

    Returns:
        openai.APIConnectionError or ConnectionError fallback.
    """
    try:
        from openai import APIConnectionError

        return APIConnectionError(
            message="Connection error — host unreachable",
            request=MagicMock(),
        )
    except ImportError:
        return ConnectionError("API connection refused")


def make_openai_timeout_error() -> Exception:
    """
    Build an openai.APITimeoutError that ErrorClassifier classifies as TRANSIENT.

    Returns:
        openai.APITimeoutError or TimeoutError fallback.
    """
    try:
        from openai import APITimeoutError

        return APITimeoutError(request=MagicMock())
    except ImportError:
        return TimeoutError("API request timed out")


# =============================================================================
# MockLLMProvider — configurable fake LLM client
# =============================================================================


class MockLLMProvider:
    """
    Configurable mock LLM provider for integration testing of the resilience layer.

    Simulates the interface used by FallbackChain: any callable that accepts
    ``llm=<ChatOpenAI>`` and returns a result (or raises an exception).

    Can be configured to:
    - Return normal responses (list of response strings, used in rotation)
    - Fail the first N calls with a configurable exception
    - Always fail (permanent failure mode)

    Usage:
        # Fails 2 times with TRANSIENT, then succeeds
        provider = MockLLMProvider(
            responses=["Hola, te ayudo!"],
            fail_first_n=2,
            failure_factory=make_transient_error,
        )

        # Always succeeds immediately
        provider = MockLLMProvider(responses=["OK"])

        # Always fails permanently
        provider = MockLLMProvider(
            responses=[],
            fail_always=True,
            failure_factory=make_permanent_error,
        )
    """

    def __init__(
        self,
        responses: list[str] | None = None,
        fail_first_n: int = 0,
        fail_always: bool = False,
        failure_factory: Callable[[], Exception] | None = None,
    ) -> None:
        """
        Initialise the mock provider.

        Args:
            responses: List of response strings to cycle through on success.
                       Defaults to ["Mock response from LLM provider"].
            fail_first_n: Raise failure_factory() for the first N calls.
                          After N failures, the provider starts returning
                          normal responses. Ignored if fail_always=True.
            fail_always: If True, every call raises failure_factory().
                         Overrides fail_first_n.
            failure_factory: Callable that returns an Exception to raise.
                             Defaults to make_transient_error.
        """
        self._responses = responses or ["Mock response from LLM provider"]
        self._fail_first_n = fail_first_n
        self._fail_always = fail_always
        self._failure_factory = failure_factory or make_transient_error
        self._call_count = 0

    @property
    def call_count(self) -> int:
        """Number of times this provider has been called (including failures)."""
        return self._call_count

    def _should_fail(self) -> bool:
        """Return True if this call should raise an exception."""
        if self._fail_always:
            return True
        return self._call_count <= self._fail_first_n

    def _build_response(self) -> MagicMock:
        """Build a mock LLM response object with .content attribute."""
        response_text = self._responses[
            (self._call_count - 1) % len(self._responses)
        ]
        mock_response = MagicMock()
        mock_response.content = response_text
        return mock_response

    async def ainvoke(self, messages: Any, **kwargs: Any) -> MagicMock:
        """
        Async LLM invocation — the primary interface used in tests.

        Args:
            messages: LangChain message list (ignored in mock).
            **kwargs: Any additional kwargs (ignored).

        Returns:
            MagicMock with .content set to the configured response string.

        Raises:
            Exception: Whatever failure_factory() returns, if configured to fail.
        """
        self._call_count += 1

        if self._should_fail():
            raise self._failure_factory()

        return self._build_response()

    def reset(self) -> None:
        """Reset call count (useful between test cases in the same class)."""
        self._call_count = 0


# =============================================================================
# Convenience builders for common test scenarios
# =============================================================================


def make_always_success_provider(response: str = "Success response") -> MockLLMProvider:
    """Provider that always succeeds immediately."""
    return MockLLMProvider(responses=[response])


def make_transient_then_success_provider(
    fail_count: int = 1,
    success_response: str = "Success after retry",
) -> MockLLMProvider:
    """Provider that fails N times with TRANSIENT, then succeeds."""
    return MockLLMProvider(
        responses=[success_response],
        fail_first_n=fail_count,
        failure_factory=make_transient_error,
    )


def make_rate_limit_then_success_provider(
    retry_after: float = 0.01,  # Short delay for tests
    success_response: str = "Success after rate limit",
) -> MockLLMProvider:
    """Provider that fails once with RATE_LIMIT (short retry_after), then succeeds."""
    return MockLLMProvider(
        responses=[success_response],
        fail_first_n=1,
        failure_factory=lambda: make_rate_limit_error(retry_after=retry_after),
    )


def make_always_permanent_failure_provider() -> MockLLMProvider:
    """Provider that always fails with PERMANENT error (401 auth)."""
    return MockLLMProvider(
        responses=[],
        fail_always=True,
        failure_factory=make_permanent_error,
    )


def make_always_transient_failure_provider() -> MockLLMProvider:
    """Provider that always fails with TRANSIENT error (connection refused)."""
    return MockLLMProvider(
        responses=[],
        fail_always=True,
        failure_factory=make_transient_error,
    )

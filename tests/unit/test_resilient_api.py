"""
Unit tests for resilient_api.py - Resilient API client with retry logic.

Tests coverage:
- call_with_retry() - Exponential backoff retry logic
- is_retryable_error() - Error classification
- retry_on_error() - Decorator for automatic retries
- call_with_escalation() - Retry with escalation callback
- ResilientAPIError - Custom exception class
- Retry behavior: success, transient failures, permanent failures
- Exponential backoff calculation
- Max delay capping
- Both sync and async function support
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
from googleapiclient.errors import HttpError

from shared.resilient_api import (
    call_with_retry,
    is_retryable_error,
    retry_on_error,
    call_with_escalation,
    ResilientAPIError,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_http_response():
    """Create a mock HTTP response for HttpError testing."""
    def create_response(status: int):
        response = MagicMock()
        response.status = status
        response.reason = "Test error"
        return response
    return create_response


# ============================================================================
# Test is_retryable_error()
# ============================================================================


class TestIsRetryableError:
    """Test error classification logic."""

    def test_http_error_429_is_retryable(self, mock_http_response):
        """Test that rate limit (429) is retryable."""
        response = mock_http_response(429)
        error = HttpError(resp=response, content=b"Rate limit exceeded")

        assert is_retryable_error(error) is True

    def test_http_error_500_is_retryable(self, mock_http_response):
        """Test that server error (500) is retryable."""
        response = mock_http_response(500)
        error = HttpError(resp=response, content=b"Internal server error")

        assert is_retryable_error(error) is True

    def test_http_error_502_is_retryable(self, mock_http_response):
        """Test that bad gateway (502) is retryable."""
        response = mock_http_response(502)
        error = HttpError(resp=response, content=b"Bad gateway")

        assert is_retryable_error(error) is True

    def test_http_error_503_is_retryable(self, mock_http_response):
        """Test that service unavailable (503) is retryable."""
        response = mock_http_response(503)
        error = HttpError(resp=response, content=b"Service unavailable")

        assert is_retryable_error(error) is True

    def test_http_error_504_is_retryable(self, mock_http_response):
        """Test that gateway timeout (504) is retryable."""
        response = mock_http_response(504)
        error = HttpError(resp=response, content=b"Gateway timeout")

        assert is_retryable_error(error) is True

    def test_http_error_400_not_retryable(self, mock_http_response):
        """Test that client error (400) is not retryable."""
        response = mock_http_response(400)
        error = HttpError(resp=response, content=b"Bad request")

        assert is_retryable_error(error) is False

    def test_http_error_404_not_retryable(self, mock_http_response):
        """Test that not found (404) is not retryable."""
        response = mock_http_response(404)
        error = HttpError(resp=response, content=b"Not found")

        assert is_retryable_error(error) is False

    def test_connection_error_is_retryable(self):
        """Test that ConnectionError is retryable."""
        error = ConnectionError("Connection refused")

        assert is_retryable_error(error) is True

    def test_timeout_error_is_retryable(self):
        """Test that TimeoutError is retryable."""
        error = TimeoutError("Request timeout")

        assert is_retryable_error(error) is True

    def test_os_error_is_retryable(self):
        """Test that OSError is retryable."""
        error = OSError("Network unreachable")

        assert is_retryable_error(error) is True

    def test_value_error_not_retryable(self):
        """Test that ValueError is not retryable."""
        error = ValueError("Invalid argument")

        assert is_retryable_error(error) is False

    def test_key_error_not_retryable(self):
        """Test that KeyError is not retryable."""
        error = KeyError("missing_key")

        assert is_retryable_error(error) is False


# ============================================================================
# Test call_with_retry() - Success Cases
# ============================================================================


class TestCallWithRetrySuccess:
    """Test successful retry scenarios."""

    @pytest.mark.asyncio
    async def test_async_function_succeeds_first_try(self):
        """Test async function succeeding on first attempt."""
        async def mock_func(value):
            return value * 2

        result = await call_with_retry(mock_func, max_retries=3, value=21)

        assert result == 42

    @pytest.mark.asyncio
    async def test_sync_function_succeeds_first_try(self):
        """Test sync function succeeding on first attempt."""
        def mock_func(value):
            return value * 2

        result = await call_with_retry(mock_func, max_retries=3, value=21)

        assert result == 42

    @pytest.mark.asyncio
    async def test_async_function_succeeds_after_transient_failure(self):
        """Test async function succeeding after one retry."""
        call_count = [0]

        async def mock_func():
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("Temporary network error")
            return "success"

        with patch("shared.resilient_api.asyncio.sleep", new_callable=AsyncMock):
            result = await call_with_retry(mock_func, max_retries=3, initial_delay=0.1)

        assert result == "success"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_multiple_transient_failures_then_success(self):
        """Test function succeeding after multiple retries."""
        call_count = [0]

        async def mock_func():
            call_count[0] += 1
            if call_count[0] < 3:
                raise TimeoutError("Timeout")
            return "success"

        with patch("shared.resilient_api.asyncio.sleep", new_callable=AsyncMock):
            result = await call_with_retry(mock_func, max_retries=3, initial_delay=0.1)

        assert result == "success"
        assert call_count[0] == 3


# ============================================================================
# Test call_with_retry() - Failure Cases
# ============================================================================


class TestCallWithRetryFailure:
    """Test retry failure scenarios."""

    @pytest.mark.asyncio
    async def test_permanent_error_fails_immediately(self, mock_http_response):
        """Test that non-retryable error fails without retry."""
        async def mock_func():
            response = mock_http_response(400)
            raise HttpError(resp=response, content=b"Bad request")

        with pytest.raises(HttpError):
            await call_with_retry(mock_func, max_retries=3)

    @pytest.mark.asyncio
    async def test_exhausts_all_retries(self):
        """Test that retries are exhausted and exception is raised."""
        call_count = [0]

        async def mock_func():
            call_count[0] += 1
            raise ConnectionError("Persistent network error")

        with pytest.raises(ConnectionError), \
             patch("shared.resilient_api.asyncio.sleep", new_callable=AsyncMock):
            await call_with_retry(mock_func, max_retries=3, initial_delay=0.1)

        # Should try: initial + 3 retries = 4 attempts
        assert call_count[0] == 4

    @pytest.mark.asyncio
    async def test_value_error_not_retried(self):
        """Test that ValueError fails immediately without retry."""
        call_count = [0]

        async def mock_func():
            call_count[0] += 1
            raise ValueError("Invalid value")

        with pytest.raises(ValueError):
            await call_with_retry(mock_func, max_retries=3)

        # Should only try once
        assert call_count[0] == 1


# ============================================================================
# Test Exponential Backoff
# ============================================================================


class TestExponentialBackoff:
    """Test exponential backoff delay calculation."""

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self):
        """Test that delays increase exponentially."""
        call_count = [0]
        sleep_delays = []

        async def mock_func():
            call_count[0] += 1
            raise ConnectionError("Error")

        async def mock_sleep(delay):
            sleep_delays.append(delay)

        with pytest.raises(ConnectionError), \
             patch("shared.resilient_api.asyncio.sleep", side_effect=mock_sleep):
            await call_with_retry(
                mock_func,
                max_retries=3,
                initial_delay=1.0,
                exponential_base=2.0
            )

        # Expected delays: 1.0, 2.0, 4.0 (exponential: initial * base^attempt)
        assert len(sleep_delays) == 3
        assert sleep_delays[0] == 1.0  # 1.0 * 2^0
        assert sleep_delays[1] == 2.0  # 1.0 * 2^1
        assert sleep_delays[2] == 4.0  # 1.0 * 2^2

    @pytest.mark.asyncio
    async def test_max_delay_capping(self):
        """Test that delay is capped at max_delay."""
        call_count = [0]
        sleep_delays = []

        async def mock_func():
            call_count[0] += 1
            raise ConnectionError("Error")

        async def mock_sleep(delay):
            sleep_delays.append(delay)

        with pytest.raises(ConnectionError), \
             patch("shared.resilient_api.asyncio.sleep", side_effect=mock_sleep):
            await call_with_retry(
                mock_func,
                max_retries=3,
                initial_delay=5.0,
                max_delay=8.0,
                exponential_base=2.0
            )

        # Expected delays: 5.0, 8.0 (capped), 8.0 (capped)
        assert len(sleep_delays) == 3
        assert sleep_delays[0] == 5.0   # 5.0 * 2^0 = 5.0
        assert sleep_delays[1] == 8.0   # min(5.0 * 2^1, 8.0) = 8.0
        assert sleep_delays[2] == 8.0   # min(5.0 * 2^2, 8.0) = 8.0

    @pytest.mark.asyncio
    async def test_custom_exponential_base(self):
        """Test exponential backoff with custom base."""
        call_count = [0]
        sleep_delays = []

        async def mock_func():
            call_count[0] += 1
            raise ConnectionError("Error")

        async def mock_sleep(delay):
            sleep_delays.append(delay)

        with pytest.raises(ConnectionError), \
             patch("shared.resilient_api.asyncio.sleep", side_effect=mock_sleep):
            await call_with_retry(
                mock_func,
                max_retries=2,
                initial_delay=1.0,
                exponential_base=3.0
            )

        # Expected delays: 1.0, 3.0 (1.0 * 3^1)
        assert len(sleep_delays) == 2
        assert sleep_delays[0] == 1.0
        assert sleep_delays[1] == 3.0


# ============================================================================
# Test retry_on_error() Decorator
# ============================================================================


class TestRetryOnErrorDecorator:
    """Test automatic retry decorator."""

    @pytest.mark.asyncio
    async def test_decorator_successful_call(self):
        """Test decorator on successful function."""
        @retry_on_error(max_retries=3)
        async def decorated_func(value):
            return value * 2

        result = await decorated_func(21)

        assert result == 42

    @pytest.mark.asyncio
    async def test_decorator_with_retry(self):
        """Test decorator retries on transient error."""
        call_count = [0]

        @retry_on_error(max_retries=3, initial_delay=0.1)
        async def decorated_func():
            call_count[0] += 1
            if call_count[0] == 1:
                raise TimeoutError("Timeout")
            return "success"

        with patch("shared.resilient_api.asyncio.sleep", new_callable=AsyncMock):
            result = await decorated_func()

        assert result == "success"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_decorator_exhausts_retries(self):
        """Test decorator raises after exhausting retries."""
        call_count = [0]

        @retry_on_error(max_retries=2, initial_delay=0.1)
        async def decorated_func():
            call_count[0] += 1
            raise ConnectionError("Error")

        with pytest.raises(ConnectionError), \
             patch("shared.resilient_api.asyncio.sleep", new_callable=AsyncMock):
            await decorated_func()

        # Should try: initial + 2 retries = 3 attempts
        assert call_count[0] == 3


# ============================================================================
# Test call_with_escalation()
# ============================================================================


class TestCallWithEscalation:
    """Test retry with escalation callback."""

    @pytest.mark.asyncio
    async def test_escalation_on_complete_failure(self):
        """Test that escalation callback is called on complete failure."""
        escalation_called = [False]

        async def mock_func():
            raise ConnectionError("Persistent error")

        async def escalation_callback(error):
            escalation_called[0] = True
            assert isinstance(error, ConnectionError)

        with patch("shared.resilient_api.asyncio.sleep", new_callable=AsyncMock):
            result = await call_with_escalation(
                mock_func,
                escalation_callback=escalation_callback,
                max_retries=2
            )

        assert result is None
        assert escalation_called[0] is True

    @pytest.mark.asyncio
    async def test_no_escalation_on_success(self):
        """Test that escalation is not called on success."""
        escalation_called = [False]

        async def mock_func():
            return "success"

        async def escalation_callback(error):
            escalation_called[0] = True

        result = await call_with_escalation(
            mock_func,
            escalation_callback=escalation_callback,
            max_retries=2
        )

        assert result == "success"
        assert escalation_called[0] is False

    @pytest.mark.asyncio
    async def test_escalation_callback_optional(self):
        """Test that escalation_callback is optional."""
        async def mock_func():
            raise ConnectionError("Error")

        with patch("shared.resilient_api.asyncio.sleep", new_callable=AsyncMock):
            result = await call_with_escalation(
                mock_func,
                escalation_callback=None,
                max_retries=1
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_sync_escalation_callback(self):
        """Test that sync escalation callback works."""
        escalation_called = [False]

        async def mock_func():
            raise ConnectionError("Error")

        def escalation_callback(error):  # Sync callback
            escalation_called[0] = True

        with patch("shared.resilient_api.asyncio.sleep", new_callable=AsyncMock):
            result = await call_with_escalation(
                mock_func,
                escalation_callback=escalation_callback,
                max_retries=1
            )

        assert result is None
        assert escalation_called[0] is True

    @pytest.mark.asyncio
    async def test_escalation_callback_exception_handled(self):
        """Test that exception in escalation callback is handled gracefully."""
        async def mock_func():
            raise ConnectionError("Error")

        async def faulty_escalation(error):
            raise ValueError("Escalation error")

        with patch("shared.resilient_api.asyncio.sleep", new_callable=AsyncMock):
            result = await call_with_escalation(
                mock_func,
                escalation_callback=faulty_escalation,
                max_retries=1
            )

        # Should still return None, not crash
        assert result is None


# ============================================================================
# Test ResilientAPIError
# ============================================================================


class TestResilientAPIError:
    """Test custom exception class."""

    def test_resilient_api_error_attributes(self):
        """Test that ResilientAPIError has correct attributes."""
        original = ValueError("Original error")
        error = ResilientAPIError("API failed", original, attempts=3)

        assert error.message == "API failed"
        assert error.original_error is original
        assert error.attempts == 3

    def test_resilient_api_error_string_representation(self):
        """Test string representation of ResilientAPIError."""
        original = ValueError("Original error")
        error = ResilientAPIError("API failed", original, attempts=3)

        error_str = str(error)
        assert "API failed" in error_str
        assert "3 attempts" in error_str
        assert "ValueError" in error_str
        assert "Original error" in error_str


# ============================================================================
# Test Logging Behavior
# ============================================================================


class TestLoggingBehavior:
    """Test that retry logic logs appropriately."""

    @pytest.mark.asyncio
    async def test_logs_retry_attempts(self):
        """Test that retry attempts are logged."""
        call_count = [0]

        async def mock_func():
            call_count[0] += 1
            if call_count[0] < 3:
                raise TimeoutError("Timeout")
            return "success"

        with patch("shared.resilient_api.logger") as mock_logger, \
             patch("shared.resilient_api.asyncio.sleep", new_callable=AsyncMock):
            result = await call_with_retry(mock_func, max_retries=3, initial_delay=0.1)

        # Should log warnings for each retry
        assert mock_logger.warning.call_count >= 2

    @pytest.mark.asyncio
    async def test_logs_success_after_retry(self):
        """Test that success after retry is logged."""
        call_count = [0]

        async def mock_func():
            call_count[0] += 1
            if call_count[0] == 1:
                raise TimeoutError("Timeout")
            return "success"

        with patch("shared.resilient_api.logger") as mock_logger, \
             patch("shared.resilient_api.asyncio.sleep", new_callable=AsyncMock):
            result = await call_with_retry(mock_func, max_retries=3)

        # Should log info for success after retry
        mock_logger.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_logs_complete_failure(self):
        """Test that complete failure is logged."""
        async def mock_func():
            raise ConnectionError("Persistent error")

        with pytest.raises(ConnectionError), \
             patch("shared.resilient_api.logger") as mock_logger, \
             patch("shared.resilient_api.asyncio.sleep", new_callable=AsyncMock):
            await call_with_retry(mock_func, max_retries=2)

        # Should log error for complete failure
        mock_logger.error.assert_called_once()


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_zero_retries(self):
        """Test with max_retries=0 (single attempt only)."""
        call_count = [0]

        async def mock_func():
            call_count[0] += 1
            raise ConnectionError("Error")

        with pytest.raises(ConnectionError):
            await call_with_retry(mock_func, max_retries=0)

        # Should only try once
        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_none_return_value(self):
        """Test function returning None is handled correctly."""
        async def mock_func():
            return None

        result = await call_with_retry(mock_func, max_retries=3)

        assert result is None

    @pytest.mark.asyncio
    async def test_async_function_with_args_and_kwargs(self):
        """Test async function with both positional and keyword arguments."""
        async def mock_func(a, b, c=10):
            return a + b + c

        result = await call_with_retry(mock_func, 5, 15, max_retries=3, c=20)

        assert result == 40

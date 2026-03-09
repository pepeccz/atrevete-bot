"""
Unit tests for agent/resilience/error_classifier.py

Coverage:
- ErrorType enum completeness and values
- ClassifiedError dataclass: field defaults, is_retryable auto-computation
- RetryDecision and FallbackMetrics dataclass smoke tests
- ErrorClassifier.classify() for all five error categories
- Edge cases: unknown exceptions default to TRANSIENT
- Retry-After header parsing (numeric and HTTP-date)
- classify_partial_failure() preserves partial results
- is_retryable() helper
- get_retry_after() header extraction

Test naming follows project convention: test_<scenario_description>
"""

import asyncio
from datetime import datetime, timezone
from http.client import responses
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from agent.resilience import (
    ClassifiedError,
    ErrorClassifier,
    ErrorType,
    FallbackMetrics,
    RetryDecision,
)
from agent.resilience.error_classifier import _RETRYABLE_TYPES


# =============================================================================
# ErrorType enum
# =============================================================================


class TestErrorTypeEnum:
    """Verify ErrorType has exactly the five required categories."""

    def test_has_five_values(self):
        """ErrorType enum defines exactly 5 error categories."""
        assert len(ErrorType) == 5

    def test_all_expected_values_present(self):
        """All required ErrorType variants are present."""
        expected = {"transient", "rate_limit", "permanent", "validation", "partial_failure"}
        actual = {e.value for e in ErrorType}
        assert actual == expected

    def test_is_str_enum(self):
        """ErrorType values are strings (usable in logs/JSON without conversion)."""
        for et in ErrorType:
            assert isinstance(et.value, str)

    def test_retryable_types_are_transient_and_rate_limit(self):
        """Only TRANSIENT and RATE_LIMIT are retryable."""
        assert _RETRYABLE_TYPES == frozenset({ErrorType.TRANSIENT, ErrorType.RATE_LIMIT})


# =============================================================================
# ClassifiedError dataclass
# =============================================================================


class TestClassifiedError:
    """Verify ClassifiedError field defaults and is_retryable logic."""

    def test_transient_is_retryable(self):
        """TRANSIENT errors are marked retryable."""
        ce = ClassifiedError(
            error_type=ErrorType.TRANSIENT,
            original_exception=Exception("net"),
        )
        assert ce.is_retryable is True

    def test_rate_limit_is_retryable(self):
        """RATE_LIMIT errors are marked retryable."""
        ce = ClassifiedError(
            error_type=ErrorType.RATE_LIMIT,
            original_exception=Exception("429"),
        )
        assert ce.is_retryable is True

    def test_permanent_is_not_retryable(self):
        """PERMANENT errors are NOT retryable."""
        ce = ClassifiedError(
            error_type=ErrorType.PERMANENT,
            original_exception=Exception("401"),
        )
        assert ce.is_retryable is False

    def test_validation_is_not_retryable(self):
        """VALIDATION errors are NOT retryable (must fix data first)."""
        ce = ClassifiedError(
            error_type=ErrorType.VALIDATION,
            original_exception=ValueError("bad field"),
        )
        assert ce.is_retryable is False

    def test_partial_failure_is_not_retryable(self):
        """PARTIAL_FAILURE errors are NOT retryable as-is."""
        ce = ClassifiedError(
            error_type=ErrorType.PARTIAL_FAILURE,
            original_exception=Exception("partial"),
        )
        assert ce.is_retryable is False

    def test_defaults_are_sensible(self):
        """ClassifiedError defaults are safe (no None surprises for lists/dicts)."""
        ce = ClassifiedError(
            error_type=ErrorType.TRANSIENT,
            original_exception=Exception("x"),
        )
        assert ce.http_status is None
        assert ce.retry_after is None
        assert ce.message == ""
        assert ce.validation_errors == []
        assert ce.partial_results == {}
        assert isinstance(ce.classified_at, datetime)

    def test_post_init_forces_correct_retryability(self):
        """is_retryable is always computed from error_type, ignoring manual override."""
        # Even if someone passes is_retryable=True for PERMANENT, __post_init__ corrects it
        ce = ClassifiedError(
            error_type=ErrorType.PERMANENT,
            original_exception=Exception(),
            is_retryable=True,  # wrong — should be corrected
        )
        assert ce.is_retryable is False


# =============================================================================
# RetryDecision and FallbackMetrics smoke tests
# =============================================================================


class TestRetryDecision:
    def test_retry_decision_defaults(self):
        rd = RetryDecision(should_retry=True)
        assert rd.delay_seconds == 0.0
        assert rd.attempt_number == 1
        assert rd.reason == ""

    def test_retry_decision_no_retry(self):
        rd = RetryDecision(should_retry=False, reason="permanent error")
        assert rd.should_retry is False
        assert rd.reason == "permanent error"


class TestFallbackMetrics:
    def test_fallback_metrics_defaults(self):
        fm = FallbackMetrics(primary_provider="openrouter")
        assert fm.fallback_provider is None
        assert fm.primary_error_type is None
        assert fm.fallback_succeeded is False
        assert fm.latency_ms == 0.0

    def test_fallback_metrics_with_values(self):
        fm = FallbackMetrics(
            primary_provider="openrouter",
            fallback_provider="groq",
            primary_error_type=ErrorType.RATE_LIMIT,
            fallback_succeeded=True,
            latency_ms=342.5,
        )
        assert fm.fallback_succeeded is True
        assert fm.latency_ms == 342.5


# =============================================================================
# ErrorClassifier — openai exceptions
# =============================================================================


class TestErrorClassifierOpenAI:
    """Tests for openai exception family classification."""

    def setup_method(self):
        self.classifier = ErrorClassifier()

    # --- RateLimitError -------------------------------------------------------

    def test_openai_rate_limit_error_is_rate_limit(self):
        """openai.RateLimitError → RATE_LIMIT."""
        from openai import RateLimitError

        mock_response = MagicMock()
        mock_response.headers = {"retry-after": "30"}
        mock_response.status_code = 429
        exc = RateLimitError("too many requests", response=mock_response, body=None)

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.RATE_LIMIT
        assert result.is_retryable is True
        assert result.http_status == 429

    def test_openai_rate_limit_extracts_retry_after(self):
        """RateLimitError with Retry-After header — value is extracted."""
        from openai import RateLimitError

        mock_response = MagicMock()
        mock_response.headers = {"retry-after": "60"}
        mock_response.status_code = 429
        exc = RateLimitError("rate limited", response=mock_response, body=None)

        result = self.classifier.classify(exc)

        assert result.retry_after == 60.0

    def test_openai_rate_limit_without_retry_after_header(self):
        """RateLimitError without Retry-After header — retry_after is None."""
        from openai import RateLimitError

        mock_response = MagicMock()
        mock_response.headers = {}
        mock_response.status_code = 429
        exc = RateLimitError("rate limited", response=mock_response, body=None)

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.RATE_LIMIT
        assert result.retry_after is None

    # --- AuthenticationError / PermissionDeniedError --------------------------

    def test_openai_authentication_error_is_permanent(self):
        """openai.AuthenticationError → PERMANENT."""
        from openai import AuthenticationError

        mock_response = MagicMock()
        mock_response.status_code = 401
        exc = AuthenticationError("invalid key", response=mock_response, body=None)

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.PERMANENT
        assert result.is_retryable is False

    def test_openai_permission_denied_is_permanent(self):
        """openai.PermissionDeniedError → PERMANENT."""
        from openai import PermissionDeniedError

        mock_response = MagicMock()
        mock_response.status_code = 403
        exc = PermissionDeniedError("forbidden", response=mock_response, body=None)

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.PERMANENT
        assert result.is_retryable is False

    # --- NotFoundError --------------------------------------------------------

    def test_openai_not_found_is_permanent(self):
        """openai.NotFoundError → PERMANENT."""
        from openai import NotFoundError

        mock_response = MagicMock()
        mock_response.status_code = 404
        exc = NotFoundError("model not found", response=mock_response, body=None)

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.PERMANENT
        assert result.is_retryable is False
        assert result.http_status == 404

    # --- APIStatusError (generic HTTP status) ---------------------------------

    def test_openai_api_status_500_is_transient(self):
        """openai.APIStatusError HTTP 500 → TRANSIENT."""
        from openai import InternalServerError

        mock_response = MagicMock()
        mock_response.status_code = 500
        exc = InternalServerError("internal error", response=mock_response, body=None)

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.TRANSIENT
        assert result.is_retryable is True

    def test_openai_api_status_503_is_transient(self):
        """openai.APIStatusError HTTP 503 → TRANSIENT."""
        from openai import APIStatusError

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.headers = {}
        exc = APIStatusError("service unavailable", response=mock_response, body=None)

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.TRANSIENT
        assert result.http_status == 503

    def test_openai_api_status_502_is_transient(self):
        """openai.APIStatusError HTTP 502 → TRANSIENT."""
        from openai import APIStatusError

        mock_response = MagicMock()
        mock_response.status_code = 502
        mock_response.headers = {}
        exc = APIStatusError("bad gateway", response=mock_response, body=None)

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.TRANSIENT

    def test_openai_api_status_504_is_transient(self):
        """openai.APIStatusError HTTP 504 → TRANSIENT."""
        from openai import APIStatusError

        mock_response = MagicMock()
        mock_response.status_code = 504
        mock_response.headers = {}
        exc = APIStatusError("gateway timeout", response=mock_response, body=None)

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.TRANSIENT

    # --- APIConnectionError / APITimeoutError ---------------------------------

    def test_openai_connection_error_is_transient(self):
        """openai.APIConnectionError → TRANSIENT."""
        from openai import APIConnectionError

        # APIConnectionError requires keyword args (openai v2 API)
        exc = APIConnectionError(message="connection refused", request=MagicMock())

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.TRANSIENT
        assert result.is_retryable is True

    def test_openai_timeout_error_is_transient(self):
        """openai.APITimeoutError → TRANSIENT."""
        from openai import APITimeoutError

        # APITimeoutError requires keyword args (openai v2 API)
        exc = APITimeoutError(request=MagicMock())

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.TRANSIENT
        assert result.is_retryable is True


# =============================================================================
# ErrorClassifier — httpx exceptions
# =============================================================================


class TestErrorClassifierHTTPX:
    """Tests for httpx exception family classification."""

    def setup_method(self):
        self.classifier = ErrorClassifier()

    def test_httpx_timeout_is_transient(self):
        """httpx.TimeoutException → TRANSIENT."""
        import httpx

        exc = httpx.ReadTimeout("read timeout", request=MagicMock())

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.TRANSIENT
        assert result.is_retryable is True

    def test_httpx_connect_error_is_transient(self):
        """httpx.ConnectError → TRANSIENT."""
        import httpx

        exc = httpx.ConnectError("connection refused", request=MagicMock())

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.TRANSIENT
        assert result.is_retryable is True

    def test_httpx_status_429_is_rate_limit(self):
        """httpx.HTTPStatusError with 429 → RATE_LIMIT."""
        import httpx

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 429
        mock_response.headers = {"retry-after": "10"}
        exc = httpx.HTTPStatusError("429", request=MagicMock(), response=mock_response)

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.RATE_LIMIT

    def test_httpx_status_500_is_transient(self):
        """httpx.HTTPStatusError with 500 → TRANSIENT."""
        import httpx

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.headers = {}
        exc = httpx.HTTPStatusError("500", request=MagicMock(), response=mock_response)

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.TRANSIENT

    def test_httpx_status_401_is_permanent(self):
        """httpx.HTTPStatusError with 401 → PERMANENT."""
        import httpx

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401
        mock_response.headers = {}
        exc = httpx.HTTPStatusError("401", request=MagicMock(), response=mock_response)

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.PERMANENT
        assert result.is_retryable is False

    def test_httpx_status_403_is_permanent(self):
        """httpx.HTTPStatusError with 403 → PERMANENT."""
        import httpx

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 403
        mock_response.headers = {}
        exc = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_response)

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.PERMANENT

    def test_httpx_status_404_is_permanent(self):
        """httpx.HTTPStatusError with 404 → PERMANENT."""
        import httpx

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 404
        mock_response.headers = {}
        exc = httpx.HTTPStatusError("404", request=MagicMock(), response=mock_response)

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.PERMANENT


# =============================================================================
# ErrorClassifier — built-in Python exceptions
# =============================================================================


class TestErrorClassifierBuiltins:
    """Tests for built-in Python exception classification."""

    def setup_method(self):
        self.classifier = ErrorClassifier()

    def test_asyncio_timeout_is_transient(self):
        """asyncio.TimeoutError → TRANSIENT."""
        exc = asyncio.TimeoutError()

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.TRANSIENT
        assert result.is_retryable is True

    def test_builtin_timeout_error_is_transient(self):
        """TimeoutError → TRANSIENT."""
        exc = TimeoutError("operation timed out")

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.TRANSIENT

    def test_connection_error_is_transient(self):
        """ConnectionError → TRANSIENT."""
        exc = ConnectionError("connection refused")

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.TRANSIENT
        assert result.is_retryable is True

    def test_value_error_is_validation(self):
        """ValueError → VALIDATION."""
        exc = ValueError("invalid field: 'price' must be positive")

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.VALIDATION
        assert result.is_retryable is False
        assert len(result.validation_errors) > 0
        assert "invalid field" in result.validation_errors[0]

    def test_value_error_captures_message_in_validation_errors(self):
        """ValueError message is captured in validation_errors list."""
        exc = ValueError("missing required field: service_id")

        result = self.classifier.classify(exc)

        assert "missing required field: service_id" in result.validation_errors


# =============================================================================
# ErrorClassifier — edge cases
# =============================================================================


class TestErrorClassifierEdgeCases:
    """Edge cases and unknown error handling."""

    def setup_method(self):
        self.classifier = ErrorClassifier()

    def test_unknown_exception_defaults_to_transient(self):
        """Any unknown exception type → TRANSIENT (safe default allows retry)."""

        class WeirdCustomError(Exception):
            pass

        exc = WeirdCustomError("something strange happened")

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.TRANSIENT
        assert result.is_retryable is True

    def test_unknown_exception_includes_type_name_in_message(self):
        """Unknown exception message includes the class name for debugging."""

        class MySpecialError(Exception):
            pass

        exc = MySpecialError("detail")
        result = self.classifier.classify(exc)

        assert "MySpecialError" in result.message

    def test_runtime_error_defaults_to_transient(self):
        """RuntimeError → TRANSIENT (not a ValueError, not a connection error)."""
        exc = RuntimeError("unexpected internal state")

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.TRANSIENT

    def test_keyboard_interrupt_defaults_to_transient(self):
        """Even KeyboardInterrupt → TRANSIENT (safe default)."""
        exc = KeyboardInterrupt()

        result = self.classifier.classify(exc)

        assert result.error_type == ErrorType.TRANSIENT


# =============================================================================
# ErrorClassifier — Retry-After header parsing
# =============================================================================


class TestRetryAfterParsing:
    """Tests for Retry-After header extraction and parsing."""

    def setup_method(self):
        self.classifier = ErrorClassifier()

    def test_parse_integer_retry_after(self):
        """Retry-After: 120 → 120.0 seconds."""
        result = self.classifier._parse_retry_after_header("120")
        assert result == 120.0

    def test_parse_float_retry_after(self):
        """Retry-After: 2.5 → 2.5 seconds."""
        result = self.classifier._parse_retry_after_header("2.5")
        assert result == 2.5

    def test_parse_zero_retry_after(self):
        """Retry-After: 0 → 0.0 seconds."""
        result = self.classifier._parse_retry_after_header("0")
        assert result == 0.0

    def test_parse_retry_after_with_whitespace(self):
        """Retry-After header with surrounding spaces is handled."""
        result = self.classifier._parse_retry_after_header("  30  ")
        assert result == 30.0

    def test_none_retry_after_returns_none(self):
        """Missing Retry-After header → None."""
        result = self.classifier._parse_retry_after_header(None)
        assert result is None

    def test_empty_string_retry_after_returns_none(self):
        """Empty Retry-After header → None."""
        result = self.classifier._parse_retry_after_header("")
        assert result is None

    def test_invalid_retry_after_returns_none(self):
        """Unparseable Retry-After → None (no crash)."""
        result = self.classifier._parse_retry_after_header("not-a-number")
        assert result is None

    def test_negative_retry_after_clamped_to_zero(self):
        """Negative Retry-After is clamped to 0.0."""
        result = self.classifier._parse_retry_after_header("-5")
        assert result == 0.0

    def test_http_date_retry_after(self):
        """Retry-After in HTTP-date format is parsed and converted to seconds."""
        # Use a date far in the future so the test doesn't flicker at midnight
        import datetime as dt

        future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=3600)
        http_date = future.strftime("%a, %d %b %Y %H:%M:%S GMT")

        result = self.classifier._parse_retry_after_header(http_date)

        assert result is not None
        # Should be roughly 3600 seconds ± 5s tolerance for test runtime
        assert 3590 < result <= 3605

    def test_get_retry_after_from_openai_rate_limit(self):
        """get_retry_after() extracts header from openai.RateLimitError."""
        from openai import RateLimitError

        mock_response = MagicMock()
        mock_response.headers = {"retry-after": "45"}
        exc = RateLimitError("too many requests", response=mock_response, body=None)

        result = self.classifier.get_retry_after(exc)

        assert result == 45.0

    def test_get_retry_after_returns_none_for_non_http_error(self):
        """get_retry_after() returns None for exceptions with no HTTP response."""
        exc = ConnectionError("cannot connect")

        result = self.classifier.get_retry_after(exc)

        assert result is None


# =============================================================================
# ErrorClassifier — classify_partial_failure()
# =============================================================================


class TestClassifyPartialFailure:
    """Tests for partial failure classification."""

    def setup_method(self):
        self.classifier = ErrorClassifier()

    def test_classify_partial_failure_returns_partial_failure_type(self):
        """classify_partial_failure() always returns PARTIAL_FAILURE."""
        exc = Exception("calendar push failed")
        partial = {"book": {"appointment_id": "abc-123", "status": "confirmed"}}

        result = self.classifier.classify_partial_failure(exc, partial_results=partial)

        assert result.error_type == ErrorType.PARTIAL_FAILURE

    def test_classify_partial_failure_preserves_partial_results(self):
        """Successful tool results are preserved in partial_results."""
        exc = Exception("gcal push failed")
        partial = {
            "book": {"appointment_id": "uuid-1"},
            "notify": {"sent": True},
        }

        result = self.classifier.classify_partial_failure(exc, partial_results=partial)

        assert result.partial_results == partial
        assert result.partial_results["book"]["appointment_id"] == "uuid-1"

    def test_classify_partial_failure_is_not_retryable(self):
        """PARTIAL_FAILURE is not blindly retryable (prevents double-booking)."""
        exc = Exception("push failed")

        result = self.classifier.classify_partial_failure(exc, partial_results={})

        assert result.is_retryable is False

    def test_classify_partial_failure_includes_succeeded_keys_in_message(self):
        """Message mentions which tools succeeded for debugging."""
        exc = Exception("push failed")
        partial = {"book": {}, "send_confirmation": {}}

        result = self.classifier.classify_partial_failure(exc, partial_results=partial)

        # Message should mention the succeeded operations
        assert "book" in result.message or "send_confirmation" in result.message


# =============================================================================
# ErrorClassifier — is_retryable() helper
# =============================================================================


class TestIsRetryableHelper:
    """Tests for the is_retryable() helper method."""

    def setup_method(self):
        self.classifier = ErrorClassifier()

    def test_transient_is_retryable(self):
        assert self.classifier.is_retryable(ErrorType.TRANSIENT) is True

    def test_rate_limit_is_retryable(self):
        assert self.classifier.is_retryable(ErrorType.RATE_LIMIT) is True

    def test_permanent_is_not_retryable(self):
        assert self.classifier.is_retryable(ErrorType.PERMANENT) is False

    def test_validation_is_not_retryable(self):
        assert self.classifier.is_retryable(ErrorType.VALIDATION) is False

    def test_partial_failure_is_not_retryable(self):
        assert self.classifier.is_retryable(ErrorType.PARTIAL_FAILURE) is False


# =============================================================================
# Package-level import checks (T-004 integration validation)
# =============================================================================


class TestPackageImports:
    """Verify the package __init__.py exports are correct and importable."""

    def test_all_exports_importable_from_package(self):
        """All names in __all__ are importable from agent.resilience."""
        from agent import resilience

        for name in resilience.__all__:
            assert hasattr(resilience, name), f"agent.resilience missing export: {name}"

    def test_error_classifier_is_exported(self):
        """ErrorClassifier is importable from agent.resilience."""
        from agent.resilience import ErrorClassifier

        assert ErrorClassifier is not None

    def test_error_type_is_exported(self):
        """ErrorType is importable from agent.resilience."""
        from agent.resilience import ErrorType

        assert ErrorType is not None

    def test_classified_error_is_exported(self):
        """ClassifiedError is importable from agent.resilience."""
        from agent.resilience import ClassifiedError

        assert ClassifiedError is not None

    def test_retry_decision_is_exported(self):
        """RetryDecision is importable from agent.resilience."""
        from agent.resilience import RetryDecision

        assert RetryDecision is not None

    def test_fallback_metrics_is_exported(self):
        """FallbackMetrics is importable from agent.resilience."""
        from agent.resilience import FallbackMetrics

        assert FallbackMetrics is not None

    def test_no_circular_imports(self):
        """Importing agent.resilience does not trigger circular imports."""
        # If this test runs without ImportError, we're clean
        import importlib
        import sys

        # Remove cached modules to force a fresh import
        mods_to_remove = [k for k in sys.modules if k.startswith("agent.resilience")]
        for mod in mods_to_remove:
            del sys.modules[mod]

        module = importlib.import_module("agent.resilience")
        assert module is not None

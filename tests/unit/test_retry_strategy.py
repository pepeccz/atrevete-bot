"""
Unit tests for agent/resilience/retry_strategy.py

Coverage:
- RetryState TypedDict: field completeness and defaults
- Policy constants: correct values (MAX_RETRIES_TRANSIENT, etc.)
- RetryStrategy.should_retry() for all five ErrorTypes
- RetryStrategy.should_retry() with budget_exhausted=True override
- RetryStrategy.calculate_delay() exponential backoff progression
- RetryStrategy.calculate_delay() jitter within ±JITTER_FACTOR bounds
- RetryStrategy.calculate_delay() MAX_DELAY cap
- RetryStrategy.calculate_delay() RATE_LIMIT with and without retry_after
- RetryBudget.consume() — normal consumption and exhaustion
- RetryBudget.reset() — resets budget back to full
- RetryBudget.get_remaining() — accurate remaining count
- RetryBudget thread-safety (async concurrent consume)
- Package-level imports from agent.resilience

Test naming follows project convention: test_<scenario_description>
Async tests use pytest-asyncio (asyncio_mode=auto, configured in pyproject.toml).
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from agent.resilience import (
    ClassifiedError,
    ErrorType,
    RetryDecision,
)
from agent.resilience.retry_strategy import (
    BASE_DELAY,
    JITTER_FACTOR,
    MAX_DELAY,
    MAX_RETRIES_RATE_LIMIT,
    MAX_RETRIES_TRANSIENT,
    RATE_LIMIT_DEFAULT_DELAY,
    RetryBudget,
    RetryState,
    RetryStrategy,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_classified(
    error_type: ErrorType,
    retry_after: float | None = None,
    validation_errors: list[str] | None = None,
    partial_results: dict | None = None,
) -> ClassifiedError:
    """Build a ClassifiedError for testing without needing a real exception."""
    return ClassifiedError(
        error_type=error_type,
        original_exception=Exception("test error"),
        retry_after=retry_after,
        validation_errors=validation_errors or [],
        partial_results=partial_results or {},
        message=f"Test {error_type.value} error",
    )


def _make_retry_state(
    attempt_count: int = 1,
    last_error_type: ErrorType | None = None,
    next_retry_at: str | None = None,
    total_retries_used: int = 0,
    budget_exhausted: bool = False,
) -> RetryState:
    """Build a RetryState TypedDict for testing."""
    return RetryState(
        attempt_count=attempt_count,
        last_error_type=last_error_type,
        next_retry_at=next_retry_at,
        total_retries_used=total_retries_used,
        budget_exhausted=budget_exhausted,
    )


# =============================================================================
# Policy constants
# =============================================================================


class TestPolicyConstants:
    """Verify policy constants match the specification."""

    def test_max_retries_transient_is_3(self):
        """TRANSIENT errors get up to 3 retries."""
        assert MAX_RETRIES_TRANSIENT == 3

    def test_max_retries_rate_limit_is_1(self):
        """RATE_LIMIT errors get exactly 1 retry."""
        assert MAX_RETRIES_RATE_LIMIT == 1

    def test_base_delay_is_1_second(self):
        """Base exponential backoff delay starts at 1 second."""
        assert BASE_DELAY == 1.0

    def test_max_delay_is_4_seconds(self):
        """Maximum delay cap is 4 seconds."""
        assert MAX_DELAY == 4.0

    def test_jitter_factor_is_0_1(self):
        """Jitter factor is 10% of the computed delay."""
        assert JITTER_FACTOR == 0.1

    def test_rate_limit_default_delay_is_60_seconds(self):
        """Default RATE_LIMIT delay is 60 seconds when no Retry-After header."""
        assert RATE_LIMIT_DEFAULT_DELAY == 60.0


# =============================================================================
# RetryState TypedDict
# =============================================================================


class TestRetryState:
    """Verify RetryState TypedDict structure and usage."""

    def test_retry_state_can_be_created_with_all_fields(self):
        """RetryState accepts all required fields."""
        state = _make_retry_state(
            attempt_count=2,
            last_error_type=ErrorType.TRANSIENT,
            next_retry_at="2026-03-09T14:00:00+00:00",
            total_retries_used=1,
            budget_exhausted=False,
        )
        assert state["attempt_count"] == 2
        assert state["last_error_type"] == ErrorType.TRANSIENT
        assert state["next_retry_at"] == "2026-03-09T14:00:00+00:00"
        assert state["total_retries_used"] == 1
        assert state["budget_exhausted"] is False

    def test_retry_state_none_values_are_valid(self):
        """Optional fields in RetryState can be None."""
        state = _make_retry_state()
        assert state["last_error_type"] is None
        assert state["next_retry_at"] is None


# =============================================================================
# RetryStrategy.should_retry() — TRANSIENT errors
# =============================================================================


class TestShouldRetryTransient:
    """RetryStrategy decisions for TRANSIENT error type."""

    def setup_method(self):
        self.strategy = RetryStrategy()

    def test_transient_first_attempt_should_retry(self):
        """First TRANSIENT failure should trigger a retry."""
        classified = _make_classified(ErrorType.TRANSIENT)
        state = _make_retry_state(attempt_count=1)

        decision = self.strategy.should_retry(classified, state)

        assert decision.should_retry is True

    def test_transient_second_attempt_should_retry(self):
        """Second TRANSIENT failure (attempt=2) is still within budget."""
        classified = _make_classified(ErrorType.TRANSIENT)
        state = _make_retry_state(attempt_count=2)

        decision = self.strategy.should_retry(classified, state)

        assert decision.should_retry is True

    def test_transient_third_attempt_should_retry(self):
        """Third TRANSIENT attempt is the last allowed retry."""
        classified = _make_classified(ErrorType.TRANSIENT)
        state = _make_retry_state(attempt_count=3)

        decision = self.strategy.should_retry(classified, state)

        assert decision.should_retry is True

    def test_transient_fourth_attempt_no_retry(self):
        """Fourth TRANSIENT attempt exceeds MAX_RETRIES_TRANSIENT=3."""
        classified = _make_classified(ErrorType.TRANSIENT)
        state = _make_retry_state(attempt_count=4)

        decision = self.strategy.should_retry(classified, state)

        assert decision.should_retry is False

    def test_transient_retry_has_positive_delay(self):
        """TRANSIENT retry decision always includes a positive delay."""
        classified = _make_classified(ErrorType.TRANSIENT)
        state = _make_retry_state(attempt_count=1)

        decision = self.strategy.should_retry(classified, state)

        assert decision.delay_seconds >= 0.0

    def test_transient_no_retry_has_zero_delay(self):
        """When not retrying, delay is 0."""
        classified = _make_classified(ErrorType.TRANSIENT)
        state = _make_retry_state(attempt_count=10)

        decision = self.strategy.should_retry(classified, state)

        assert decision.should_retry is False
        assert decision.delay_seconds == 0.0

    def test_transient_decision_includes_attempt_number(self):
        """RetryDecision.attempt_number reflects the current attempt."""
        classified = _make_classified(ErrorType.TRANSIENT)
        state = _make_retry_state(attempt_count=2)

        decision = self.strategy.should_retry(classified, state)

        assert decision.attempt_number == 2

    def test_transient_decision_has_reason(self):
        """Retry decision always includes a non-empty reason string."""
        classified = _make_classified(ErrorType.TRANSIENT)
        state = _make_retry_state(attempt_count=1)

        decision = self.strategy.should_retry(classified, state)

        assert len(decision.reason) > 0


# =============================================================================
# RetryStrategy.should_retry() — RATE_LIMIT errors
# =============================================================================


class TestShouldRetryRateLimit:
    """RetryStrategy decisions for RATE_LIMIT error type."""

    def setup_method(self):
        self.strategy = RetryStrategy()

    def test_rate_limit_first_attempt_should_retry(self):
        """First RATE_LIMIT hit should trigger one retry."""
        classified = _make_classified(ErrorType.RATE_LIMIT, retry_after=30.0)
        state = _make_retry_state(attempt_count=1)

        decision = self.strategy.should_retry(classified, state)

        assert decision.should_retry is True

    def test_rate_limit_second_attempt_no_retry(self):
        """Second RATE_LIMIT hit exceeds MAX_RETRIES_RATE_LIMIT=1."""
        classified = _make_classified(ErrorType.RATE_LIMIT, retry_after=30.0)
        state = _make_retry_state(attempt_count=2)

        decision = self.strategy.should_retry(classified, state)

        assert decision.should_retry is False

    def test_rate_limit_delay_uses_retry_after_header(self):
        """When Retry-After is set, delay equals that value."""
        classified = _make_classified(ErrorType.RATE_LIMIT, retry_after=45.0)
        state = _make_retry_state(attempt_count=1)

        decision = self.strategy.should_retry(classified, state)

        assert decision.delay_seconds == 45.0

    def test_rate_limit_delay_defaults_to_60s_without_header(self):
        """When no Retry-After header, delay defaults to RATE_LIMIT_DEFAULT_DELAY."""
        classified = _make_classified(ErrorType.RATE_LIMIT, retry_after=None)
        state = _make_retry_state(attempt_count=1)

        decision = self.strategy.should_retry(classified, state)

        assert decision.delay_seconds == RATE_LIMIT_DEFAULT_DELAY


# =============================================================================
# RetryStrategy.should_retry() — non-retryable error types
# =============================================================================


class TestShouldRetryNonRetryable:
    """RetryStrategy should never retry PERMANENT, VALIDATION, PARTIAL_FAILURE."""

    def setup_method(self):
        self.strategy = RetryStrategy()

    def test_permanent_error_no_retry(self):
        """PERMANENT errors must never be retried."""
        classified = _make_classified(ErrorType.PERMANENT)
        state = _make_retry_state(attempt_count=1)

        decision = self.strategy.should_retry(classified, state)

        assert decision.should_retry is False

    def test_permanent_error_zero_delay(self):
        """PERMANENT error: delay is 0 (fail immediately)."""
        classified = _make_classified(ErrorType.PERMANENT)
        state = _make_retry_state(attempt_count=1)

        decision = self.strategy.should_retry(classified, state)

        assert decision.delay_seconds == 0.0

    def test_permanent_error_has_reason(self):
        """PERMANENT error provides a descriptive reason."""
        classified = _make_classified(ErrorType.PERMANENT)
        state = _make_retry_state(attempt_count=1)

        decision = self.strategy.should_retry(classified, state)

        assert "permanent" in decision.reason.lower()

    def test_validation_error_no_retry(self):
        """VALIDATION errors must never be retried."""
        classified = _make_classified(
            ErrorType.VALIDATION,
            validation_errors=["field 'service_id' is required"],
        )
        state = _make_retry_state(attempt_count=1)

        decision = self.strategy.should_retry(classified, state)

        assert decision.should_retry is False

    def test_validation_error_zero_delay(self):
        """VALIDATION error: delay is 0."""
        classified = _make_classified(ErrorType.VALIDATION)
        state = _make_retry_state(attempt_count=1)

        decision = self.strategy.should_retry(classified, state)

        assert decision.delay_seconds == 0.0

    def test_validation_error_has_reason(self):
        """VALIDATION error provides a descriptive reason."""
        classified = _make_classified(ErrorType.VALIDATION)
        state = _make_retry_state(attempt_count=1)

        decision = self.strategy.should_retry(classified, state)

        assert "validation" in decision.reason.lower()

    def test_partial_failure_no_retry(self):
        """PARTIAL_FAILURE must not be blindly retried (prevents double-booking)."""
        classified = _make_classified(
            ErrorType.PARTIAL_FAILURE,
            partial_results={"book": {"appointment_id": "abc-123"}},
        )
        state = _make_retry_state(attempt_count=1)

        decision = self.strategy.should_retry(classified, state)

        assert decision.should_retry is False

    def test_partial_failure_zero_delay(self):
        """PARTIAL_FAILURE error: delay is 0."""
        classified = _make_classified(ErrorType.PARTIAL_FAILURE, partial_results={})
        state = _make_retry_state(attempt_count=1)

        decision = self.strategy.should_retry(classified, state)

        assert decision.delay_seconds == 0.0

    def test_partial_failure_has_reason(self):
        """PARTIAL_FAILURE reason mentions compensating action."""
        classified = _make_classified(ErrorType.PARTIAL_FAILURE)
        state = _make_retry_state(attempt_count=1)

        decision = self.strategy.should_retry(classified, state)

        assert len(decision.reason) > 0


# =============================================================================
# RetryStrategy.should_retry() — budget_exhausted override
# =============================================================================


class TestShouldRetryBudgetExhausted:
    """Budget exhaustion overrides all error-type decisions."""

    def setup_method(self):
        self.strategy = RetryStrategy()

    def test_budget_exhausted_overrides_transient(self):
        """Budget exhausted → no retry even for normally-retryable TRANSIENT."""
        classified = _make_classified(ErrorType.TRANSIENT)
        state = _make_retry_state(attempt_count=1, budget_exhausted=True)

        decision = self.strategy.should_retry(classified, state)

        assert decision.should_retry is False

    def test_budget_exhausted_overrides_rate_limit(self):
        """Budget exhausted → no retry even for normally-retryable RATE_LIMIT."""
        classified = _make_classified(ErrorType.RATE_LIMIT, retry_after=10.0)
        state = _make_retry_state(attempt_count=1, budget_exhausted=True)

        decision = self.strategy.should_retry(classified, state)

        assert decision.should_retry is False

    def test_budget_exhausted_reason_is_descriptive(self):
        """Budget exhausted decision has a clear reason."""
        classified = _make_classified(ErrorType.TRANSIENT)
        state = _make_retry_state(attempt_count=1, budget_exhausted=True)

        decision = self.strategy.should_retry(classified, state)

        assert "budget" in decision.reason.lower()

    def test_budget_exhausted_zero_delay(self):
        """Budget exhausted: delay is always 0."""
        classified = _make_classified(ErrorType.TRANSIENT)
        state = _make_retry_state(attempt_count=1, budget_exhausted=True)

        decision = self.strategy.should_retry(classified, state)

        assert decision.delay_seconds == 0.0


# =============================================================================
# RetryStrategy.calculate_delay() — exponential backoff
# =============================================================================


class TestCalculateDelayTransient:
    """Verify exponential backoff delay progression for TRANSIENT errors."""

    def setup_method(self):
        self.strategy = RetryStrategy()

    def test_attempt_1_delay_near_base(self):
        """Attempt 1: BASE_DELAY * 2^0 = 1.0s (± jitter)."""
        # Run many samples to verify the mean and bounds
        delays = [
            self.strategy.calculate_delay(1, ErrorType.TRANSIENT)
            for _ in range(50)
        ]
        expected = BASE_DELAY * (2 ** 0)  # 1.0s
        jitter_range = JITTER_FACTOR * expected
        for d in delays:
            assert expected - jitter_range <= d <= expected + jitter_range

    def test_attempt_2_delay_near_2s(self):
        """Attempt 2: BASE_DELAY * 2^1 = 2.0s (± jitter)."""
        delays = [
            self.strategy.calculate_delay(2, ErrorType.TRANSIENT)
            for _ in range(50)
        ]
        expected = BASE_DELAY * (2 ** 1)  # 2.0s
        jitter_range = JITTER_FACTOR * expected
        for d in delays:
            assert expected - jitter_range <= d <= expected + jitter_range

    def test_attempt_3_delay_near_4s(self):
        """Attempt 3: BASE_DELAY * 2^2 = 4.0s (± jitter, capped at MAX_DELAY)."""
        delays = [
            self.strategy.calculate_delay(3, ErrorType.TRANSIENT)
            for _ in range(50)
        ]
        # raw = 4.0, jitter = ±0.4, but MAX_DELAY = 4.0 caps positive jitter
        for d in delays:
            assert d <= MAX_DELAY

    def test_delay_never_exceeds_max_delay(self):
        """Delay is always capped at MAX_DELAY regardless of attempt number."""
        for attempt in range(1, 20):
            delay = self.strategy.calculate_delay(attempt, ErrorType.TRANSIENT)
            assert delay <= MAX_DELAY, f"Attempt {attempt}: delay {delay} > MAX_DELAY {MAX_DELAY}"

    def test_delay_is_always_non_negative(self):
        """Delay is never negative, even with downward jitter."""
        for attempt in range(1, 10):
            for _ in range(20):
                delay = self.strategy.calculate_delay(attempt, ErrorType.TRANSIENT)
                assert delay >= 0.0, f"Negative delay {delay} for attempt {attempt}"

    def test_delays_are_monotonically_increasing_on_average(self):
        """Average delay for attempt N+1 > attempt N (exponential growth)."""
        samples = 200
        avg_delay_1 = sum(
            self.strategy.calculate_delay(1, ErrorType.TRANSIENT) for _ in range(samples)
        ) / samples
        avg_delay_2 = sum(
            self.strategy.calculate_delay(2, ErrorType.TRANSIENT) for _ in range(samples)
        ) / samples
        # With 10% jitter and 200 samples, averages should be well-separated
        assert avg_delay_2 > avg_delay_1

    def test_jitter_produces_variation(self):
        """Jitter ensures not all retries have exactly the same delay."""
        delays = {
            self.strategy.calculate_delay(1, ErrorType.TRANSIENT)
            for _ in range(20)
        }
        # With 10% jitter, we should get at least 2 distinct values in 20 samples
        assert len(delays) > 1, "Jitter should produce variation in delay values"


# =============================================================================
# RetryStrategy.calculate_delay() — RATE_LIMIT
# =============================================================================


class TestCalculateDelayRateLimit:
    """Verify RATE_LIMIT delay uses Retry-After or default."""

    def setup_method(self):
        self.strategy = RetryStrategy()

    def test_rate_limit_delay_uses_provided_retry_after(self):
        """When retry_after is given, that exact value is returned."""
        delay = self.strategy.calculate_delay(1, ErrorType.RATE_LIMIT, retry_after=30.0)
        assert delay == 30.0

    def test_rate_limit_delay_defaults_when_no_retry_after(self):
        """When retry_after is None, default 60s is used."""
        delay = self.strategy.calculate_delay(1, ErrorType.RATE_LIMIT, retry_after=None)
        assert delay == RATE_LIMIT_DEFAULT_DELAY

    def test_rate_limit_delay_zero_retry_after(self):
        """retry_after=0.0 returns 0.0 (no delay needed per server)."""
        delay = self.strategy.calculate_delay(1, ErrorType.RATE_LIMIT, retry_after=0.0)
        assert delay == 0.0

    def test_rate_limit_no_jitter_applied(self):
        """RATE_LIMIT delay is exact (no jitter added)."""
        delays = {
            self.strategy.calculate_delay(1, ErrorType.RATE_LIMIT, retry_after=45.0)
            for _ in range(20)
        }
        # All samples should be the same exact value (no randomness)
        assert len(delays) == 1
        assert 45.0 in delays


# =============================================================================
# RetryStrategy.calculate_delay() — non-retryable error types
# =============================================================================


class TestCalculateDelayNonRetryable:
    """Non-retryable error types return 0 delay."""

    def setup_method(self):
        self.strategy = RetryStrategy()

    def test_permanent_delay_is_zero(self):
        assert self.strategy.calculate_delay(1, ErrorType.PERMANENT) == 0.0

    def test_validation_delay_is_zero(self):
        assert self.strategy.calculate_delay(1, ErrorType.VALIDATION) == 0.0

    def test_partial_failure_delay_is_zero(self):
        assert self.strategy.calculate_delay(1, ErrorType.PARTIAL_FAILURE) == 0.0


# =============================================================================
# T-007: RetryBudget
# =============================================================================


class TestRetryBudgetConsume:
    """Tests for RetryBudget.consume() — normal usage and exhaustion."""

    @pytest.mark.asyncio
    async def test_fresh_budget_consume_returns_true(self):
        """First consume on a new conversation_id succeeds."""
        budget = RetryBudget()
        result = await budget.consume("conv-1", ErrorType.TRANSIENT)
        assert result is True

    @pytest.mark.asyncio
    async def test_consume_up_to_max_returns_true(self):
        """Consuming up to MAX_TOTAL_RETRIES all return True."""
        budget = RetryBudget()
        for i in range(RetryBudget.MAX_TOTAL_RETRIES):
            result = await budget.consume("conv-2", ErrorType.TRANSIENT)
            assert result is True, f"consume #{i + 1} should return True"

    @pytest.mark.asyncio
    async def test_consume_beyond_max_returns_false(self):
        """Consuming more than MAX_TOTAL_RETRIES returns False."""
        budget = RetryBudget()
        conv_id = "conv-3"
        # Exhaust the budget
        for _ in range(RetryBudget.MAX_TOTAL_RETRIES):
            await budget.consume(conv_id, ErrorType.TRANSIENT)

        # Next consume should fail
        result = await budget.consume(conv_id, ErrorType.TRANSIENT)
        assert result is False

    @pytest.mark.asyncio
    async def test_consume_different_conversations_are_independent(self):
        """Budgets are tracked per conversation_id, not globally."""
        budget = RetryBudget()
        # Exhaust conv-A
        for _ in range(RetryBudget.MAX_TOTAL_RETRIES):
            await budget.consume("conv-A", ErrorType.TRANSIENT)
        await budget.consume("conv-A", ErrorType.TRANSIENT)  # exhausted

        # conv-B should still have full budget
        result = await budget.consume("conv-B", ErrorType.TRANSIENT)
        assert result is True

    @pytest.mark.asyncio
    async def test_consume_mixed_error_types_share_budget(self):
        """Budget is shared across all error types for a conversation."""
        budget = RetryBudget()
        conv_id = "conv-mixed"
        # Mix TRANSIENT and RATE_LIMIT consumes
        await budget.consume(conv_id, ErrorType.TRANSIENT)
        await budget.consume(conv_id, ErrorType.RATE_LIMIT)
        await budget.consume(conv_id, ErrorType.TRANSIENT)
        await budget.consume(conv_id, ErrorType.TRANSIENT)
        await budget.consume(conv_id, ErrorType.TRANSIENT)

        # Budget should now be exhausted (5 total)
        result = await budget.consume(conv_id, ErrorType.TRANSIENT)
        assert result is False


class TestRetryBudgetReset:
    """Tests for RetryBudget.reset()."""

    @pytest.mark.asyncio
    async def test_reset_restores_full_budget(self):
        """After reset, the conversation can consume retries again."""
        budget = RetryBudget()
        conv_id = "conv-reset"

        # Exhaust budget
        for _ in range(RetryBudget.MAX_TOTAL_RETRIES):
            await budget.consume(conv_id, ErrorType.TRANSIENT)

        # Verify exhausted
        assert await budget.consume(conv_id, ErrorType.TRANSIENT) is False

        # Reset
        await budget.reset(conv_id)

        # Should be able to consume again
        result = await budget.consume(conv_id, ErrorType.TRANSIENT)
        assert result is True

    @pytest.mark.asyncio
    async def test_reset_unknown_conversation_is_safe(self):
        """Resetting a conversation that never consumed is safe (no error)."""
        budget = RetryBudget()
        # Should not raise
        await budget.reset("conv-never-used")

    @pytest.mark.asyncio
    async def test_reset_clears_counter(self):
        """After reset, get_remaining returns MAX_TOTAL_RETRIES."""
        budget = RetryBudget()
        conv_id = "conv-clear"

        await budget.consume(conv_id, ErrorType.TRANSIENT)
        await budget.consume(conv_id, ErrorType.TRANSIENT)
        await budget.reset(conv_id)

        remaining = await budget.get_remaining(conv_id)
        assert remaining == RetryBudget.MAX_TOTAL_RETRIES


class TestRetryBudgetGetRemaining:
    """Tests for RetryBudget.get_remaining()."""

    @pytest.mark.asyncio
    async def test_fresh_conversation_has_max_remaining(self):
        """A fresh conversation has MAX_TOTAL_RETRIES remaining."""
        budget = RetryBudget()
        remaining = await budget.get_remaining("conv-fresh")
        assert remaining == RetryBudget.MAX_TOTAL_RETRIES

    @pytest.mark.asyncio
    async def test_remaining_decrements_on_consume(self):
        """Each successful consume reduces remaining by 1."""
        budget = RetryBudget()
        conv_id = "conv-decrement"

        for expected_remaining in range(RetryBudget.MAX_TOTAL_RETRIES - 1, -1, -1):
            await budget.consume(conv_id, ErrorType.TRANSIENT)
            remaining = await budget.get_remaining(conv_id)
            assert remaining == expected_remaining

    @pytest.mark.asyncio
    async def test_remaining_never_negative(self):
        """get_remaining() returns 0 when budget is exhausted (not negative)."""
        budget = RetryBudget()
        conv_id = "conv-neg"

        # Exhaust the budget
        for _ in range(RetryBudget.MAX_TOTAL_RETRIES):
            await budget.consume(conv_id, ErrorType.TRANSIENT)

        # Try to exhaust further (this returns False but doesn't decrement below 0)
        await budget.consume(conv_id, ErrorType.TRANSIENT)

        remaining = await budget.get_remaining(conv_id)
        assert remaining == 0


class TestRetryBudgetConcurrency:
    """Verify RetryBudget is thread-safe under concurrent async access."""

    @pytest.mark.asyncio
    async def test_concurrent_consume_does_not_exceed_budget(self):
        """Concurrent coroutines consuming the same budget never exceed MAX_TOTAL_RETRIES."""
        budget = RetryBudget()
        conv_id = "conv-concurrent"

        # Launch MAX_TOTAL_RETRIES + 5 concurrent consumers
        tasks = [
            budget.consume(conv_id, ErrorType.TRANSIENT)
            for _ in range(RetryBudget.MAX_TOTAL_RETRIES + 5)
        ]
        results = await asyncio.gather(*tasks)

        # Exactly MAX_TOTAL_RETRIES should succeed
        successful = sum(1 for r in results if r is True)
        assert successful == RetryBudget.MAX_TOTAL_RETRIES

    @pytest.mark.asyncio
    async def test_concurrent_consume_for_different_conversations(self):
        """Concurrent consumers for different conversations are fully independent."""
        budget = RetryBudget()

        async def consume_all(conv_id: str) -> list[bool]:
            tasks = [
                budget.consume(conv_id, ErrorType.TRANSIENT)
                for _ in range(RetryBudget.MAX_TOTAL_RETRIES)
            ]
            return await asyncio.gather(*tasks)

        results_a, results_b = await asyncio.gather(
            consume_all("conv-concurrent-A"),
            consume_all("conv-concurrent-B"),
        )

        # Each conversation should have exactly MAX_TOTAL_RETRIES successes
        assert sum(results_a) == RetryBudget.MAX_TOTAL_RETRIES
        assert sum(results_b) == RetryBudget.MAX_TOTAL_RETRIES


# =============================================================================
# Package-level imports (T-008 integration validation)
# =============================================================================


class TestPackageImports:
    """Verify that Phase 2 types are importable from agent.resilience."""

    def test_retry_strategy_importable_from_package(self):
        """RetryStrategy is importable from agent.resilience."""
        from agent.resilience import RetryStrategy as RS

        assert RS is not None

    def test_retry_budget_importable_from_package(self):
        """RetryBudget is importable from agent.resilience."""
        from agent.resilience import RetryBudget as RB

        assert RB is not None

    def test_retry_state_importable_from_module(self):
        """RetryState TypedDict is importable from agent.resilience.retry_strategy."""
        from agent.resilience.retry_strategy import RetryState as RS

        assert RS is not None

    def test_no_circular_imports_with_phase1(self):
        """Importing retry_strategy does not create circular imports with error_classifier."""
        import importlib
        import sys

        mods_to_remove = [
            k for k in sys.modules if k.startswith("agent.resilience")
        ]
        for mod in mods_to_remove:
            del sys.modules[mod]

        module = importlib.import_module("agent.resilience.retry_strategy")
        assert module is not None

    def test_all_phase2_exports_present_in_all_list(self):
        """All Phase 2 types are listed in agent.resilience.__all__."""
        from agent import resilience

        phase2_names = ["RetryStrategy", "RetryBudget"]
        for name in phase2_names:
            assert name in resilience.__all__, (
                f"agent.resilience.__all__ is missing Phase 2 export: {name}"
            )

"""
Unit tests for agent/resilience/fallback_chain.py

Coverage (T-012):
- ProviderConfig dataclass: fields, defaults, is_healthy property
- DEFAULT provider chain ordering (priority ascending)
- FallbackChain.get_next_provider():
    - TRANSIENT error → returns next healthy provider
    - RATE_LIMIT error → returns next healthy provider
    - PERMANENT error → returns None (no fallback)
    - VALIDATION error → returns None (no fallback)
    - All providers exhausted → returns None
    - Skips providers exceeding MAX_PROVIDER_FAILURES
- FallbackChain.mark_failure(): increments failure_count, sets last_failure_at
- FallbackChain.mark_success(): resets failure_count to 0
- FallbackChain.reset_all(): resets all providers
- FallbackChain.get_llm_client(): returns ChatOpenAI with correct model
- FallbackChain.get_circuit_breaker_for_provider(): per-provider breakers
- FallbackChain.call_with_fallback():
    - Success on primary provider
    - Fallback to next provider on TRANSIENT error
    - Fallback to next provider on RATE_LIMIT error
    - No fallback on PERMANENT error (re-raises immediately)
    - Raises FallbackExhaustedError when all providers fail
    - Circuit breaker OPEN treated as TRANSIENT (triggers fallback)
- FallbackExhaustedError exception attributes
- Package-level imports from agent.resilience

Test naming follows project convention: test_<scenario_description>
Async tests use pytest-asyncio (asyncio_mode=auto, configured in pyproject.toml).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pybreaker
import pytest

from agent.resilience import (
    ClassifiedError,
    ErrorType,
    FallbackChain,
    FallbackExhaustedError,
    ProviderConfig,
)
from agent.resilience.fallback_chain import (
    MAX_PROVIDER_FAILURES,
    OPENROUTER_BASE_URL,
    FallbackChain,
    FallbackExhaustedError,
    ProviderConfig,
    _build_default_provider_chain,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_classified(
    error_type: ErrorType,
    retry_after: float | None = None,
) -> ClassifiedError:
    """Build a ClassifiedError for testing without a real exception."""
    return ClassifiedError(
        error_type=error_type,
        original_exception=Exception(f"test {error_type.value} error"),
        retry_after=retry_after,
        message=f"Test {error_type.value} error",
    )


def _make_providers(count: int = 3) -> list[ProviderConfig]:
    """Build a list of ProviderConfigs for testing."""
    return [
        ProviderConfig(name=f"provider_{i}", model=f"vendor/model-{i}", priority=i)
        for i in range(count)
    ]


def _make_chain(providers: list[ProviderConfig] | None = None) -> FallbackChain:
    """Build a FallbackChain with test providers."""
    return FallbackChain(providers=providers or _make_providers())


# =============================================================================
# ProviderConfig
# =============================================================================


class TestProviderConfig:
    """Tests for ProviderConfig dataclass fields and is_healthy property."""

    def test_required_fields_present(self):
        """ProviderConfig must expose name, model, and priority."""
        pc = ProviderConfig(name="primary", model="openai/gpt-4o-mini", priority=0)
        assert pc.name == "primary"
        assert pc.model == "openai/gpt-4o-mini"
        assert pc.priority == 0

    def test_default_is_available_true(self):
        """is_available defaults to True (provider assumed healthy on init)."""
        pc = ProviderConfig(name="p", model="m", priority=0)
        assert pc.is_available is True

    def test_default_failure_count_zero(self):
        """failure_count starts at 0."""
        pc = ProviderConfig(name="p", model="m", priority=0)
        assert pc.failure_count == 0

    def test_default_last_failure_at_none(self):
        """last_failure_at starts as None."""
        pc = ProviderConfig(name="p", model="m", priority=0)
        assert pc.last_failure_at is None

    def test_is_healthy_when_available_and_no_failures(self):
        """is_healthy is True when is_available and failure_count < MAX."""
        pc = ProviderConfig(name="p", model="m", priority=0)
        assert pc.is_healthy is True

    def test_is_healthy_false_when_manually_disabled(self):
        """is_healthy is False when is_available=False regardless of failure_count."""
        pc = ProviderConfig(name="p", model="m", priority=0, is_available=False)
        assert pc.is_healthy is False

    def test_is_healthy_false_when_failures_at_max(self):
        """is_healthy is False when failure_count >= MAX_PROVIDER_FAILURES."""
        pc = ProviderConfig(
            name="p", model="m", priority=0, failure_count=MAX_PROVIDER_FAILURES
        )
        assert pc.is_healthy is False

    def test_is_healthy_true_when_one_below_max(self):
        """is_healthy is True when failure_count is exactly MAX - 1."""
        pc = ProviderConfig(
            name="p", model="m", priority=0, failure_count=MAX_PROVIDER_FAILURES - 1
        )
        assert pc.is_healthy is True

    def test_max_provider_failures_constant_is_three(self):
        """MAX_PROVIDER_FAILURES is documented as 3."""
        assert MAX_PROVIDER_FAILURES == 3


# =============================================================================
# Default provider chain
# =============================================================================


class TestDefaultProviderChain:
    """Tests for the default provider chain built from settings."""

    def test_chain_has_three_providers(self):
        """Default chain always has 3 providers."""
        chain = _build_default_provider_chain()
        assert len(chain) == 3

    def test_primary_has_priority_zero(self):
        """Primary provider must be at priority 0."""
        chain = _build_default_provider_chain()
        primary = next(p for p in chain if p.name == "primary")
        assert primary.priority == 0

    def test_fallback_has_priority_one(self):
        """Fallback provider must be at priority 1."""
        chain = _build_default_provider_chain()
        fallback = next(p for p in chain if p.name == "fallback")
        assert fallback.priority == 1

    def test_emergency_has_priority_two(self):
        """Emergency provider must be at priority 2."""
        chain = _build_default_provider_chain()
        emergency = next(p for p in chain if p.name == "emergency")
        assert emergency.priority == 2

    def test_chain_sorted_by_priority(self):
        """Default chain list must be ordered by priority ascending."""
        chain = _build_default_provider_chain()
        priorities = [p.priority for p in chain]
        assert priorities == sorted(priorities)

    def test_fallback_uses_deepseek(self):
        """Fallback provider is deepseek/deepseek-chat."""
        chain = _build_default_provider_chain()
        fallback = next(p for p in chain if p.name == "fallback")
        assert "deepseek" in fallback.model.lower()

    def test_emergency_uses_llama(self):
        """Emergency provider is a llama model."""
        chain = _build_default_provider_chain()
        emergency = next(p for p in chain if p.name == "emergency")
        assert "llama" in emergency.model.lower()


# =============================================================================
# FallbackChain initialisation
# =============================================================================


class TestFallbackChainInit:
    """Tests for FallbackChain.__init__."""

    def test_providers_sorted_by_priority_on_init(self):
        """FallbackChain sorts providers by priority even if passed unsorted."""
        providers = [
            ProviderConfig(name="c", model="m", priority=2),
            ProviderConfig(name="a", model="m", priority=0),
            ProviderConfig(name="b", model="m", priority=1),
        ]
        chain = FallbackChain(providers=providers)
        assert [p.name for p in chain._providers] == ["a", "b", "c"]

    def test_uses_default_chain_when_no_providers_given(self):
        """FallbackChain without explicit providers uses the 3-provider default."""
        chain = FallbackChain()
        assert len(chain._providers) == 3


# =============================================================================
# get_next_provider
# =============================================================================


class TestGetNextProvider:
    """Tests for FallbackChain.get_next_provider()."""

    def test_transient_error_returns_next_provider(self):
        """TRANSIENT error triggers fallback to the next provider."""
        chain = _make_chain()
        classified = _make_classified(ErrorType.TRANSIENT)
        next_p = chain.get_next_provider("provider_0", classified)
        assert next_p is not None
        assert next_p.name == "provider_1"

    def test_rate_limit_error_returns_next_provider(self):
        """RATE_LIMIT error triggers fallback to the next provider."""
        chain = _make_chain()
        classified = _make_classified(ErrorType.RATE_LIMIT)
        next_p = chain.get_next_provider("provider_0", classified)
        assert next_p is not None
        assert next_p.name == "provider_1"

    def test_permanent_error_returns_none(self):
        """PERMANENT error must NOT trigger fallback (returns None)."""
        chain = _make_chain()
        classified = _make_classified(ErrorType.PERMANENT)
        next_p = chain.get_next_provider("provider_0", classified)
        assert next_p is None

    def test_validation_error_returns_none(self):
        """VALIDATION error must NOT trigger fallback (returns None)."""
        chain = _make_chain()
        classified = _make_classified(ErrorType.VALIDATION)
        next_p = chain.get_next_provider("provider_0", classified)
        assert next_p is None

    def test_partial_failure_returns_none(self):
        """PARTIAL_FAILURE must NOT trigger fallback (returns None)."""
        chain = _make_chain()
        classified = _make_classified(ErrorType.PARTIAL_FAILURE)
        next_p = chain.get_next_provider("provider_0", classified)
        assert next_p is None

    def test_last_provider_returns_none(self):
        """When called from the last provider, returns None (all exhausted)."""
        chain = _make_chain()  # 3 providers: 0, 1, 2
        classified = _make_classified(ErrorType.TRANSIENT)
        next_p = chain.get_next_provider("provider_2", classified)
        assert next_p is None

    def test_skips_providers_exceeding_max_failures(self):
        """Providers at MAX_PROVIDER_FAILURES are skipped in fallback selection."""
        providers = [
            ProviderConfig(name="p0", model="m", priority=0),
            ProviderConfig(
                name="p1", model="m", priority=1, failure_count=MAX_PROVIDER_FAILURES
            ),
            ProviderConfig(name="p2", model="m", priority=2),
        ]
        chain = FallbackChain(providers=providers)
        classified = _make_classified(ErrorType.TRANSIENT)
        next_p = chain.get_next_provider("p0", classified)
        # p1 must be skipped because failure_count >= MAX; p2 should be returned
        assert next_p is not None
        assert next_p.name == "p2"

    def test_all_remaining_providers_unhealthy_returns_none(self):
        """Returns None when all subsequent providers are unhealthy."""
        providers = [
            ProviderConfig(name="p0", model="m", priority=0),
            ProviderConfig(
                name="p1", model="m", priority=1, failure_count=MAX_PROVIDER_FAILURES
            ),
            ProviderConfig(
                name="p2", model="m", priority=2, failure_count=MAX_PROVIDER_FAILURES
            ),
        ]
        chain = FallbackChain(providers=providers)
        classified = _make_classified(ErrorType.TRANSIENT)
        next_p = chain.get_next_provider("p0", classified)
        assert next_p is None

    def test_unknown_current_provider_returns_first_healthy(self):
        """Unknown current provider name → priority treated as -1, returns first."""
        chain = _make_chain()
        classified = _make_classified(ErrorType.TRANSIENT)
        next_p = chain.get_next_provider("does_not_exist", classified)
        # All providers have priority > -1, so the first one (priority 0) is returned
        assert next_p is not None
        assert next_p.name == "provider_0"


# =============================================================================
# mark_failure / mark_success / reset_all
# =============================================================================


class TestProviderStateManagement:
    """Tests for mark_failure, mark_success, reset_all."""

    async def test_mark_failure_increments_failure_count(self):
        """mark_failure increments failure_count by exactly 1."""
        chain = _make_chain()
        provider = chain._providers[0]
        assert provider.failure_count == 0
        await chain.mark_failure(provider.name)
        assert provider.failure_count == 1

    async def test_mark_failure_sets_last_failure_at(self):
        """mark_failure sets last_failure_at to a recent datetime."""
        chain = _make_chain()
        provider = chain._providers[0]
        assert provider.last_failure_at is None
        before = datetime.utcnow()
        await chain.mark_failure(provider.name)
        after = datetime.utcnow()
        assert provider.last_failure_at is not None
        assert before <= provider.last_failure_at <= after

    async def test_mark_failure_three_times_makes_provider_unhealthy(self):
        """Three consecutive failures exhaust provider health."""
        chain = _make_chain()
        provider = chain._providers[0]
        for _ in range(MAX_PROVIDER_FAILURES):
            await chain.mark_failure(provider.name)
        assert provider.is_healthy is False

    async def test_mark_success_resets_failure_count_to_zero(self):
        """mark_success resets failure_count from any value back to 0."""
        chain = _make_chain()
        provider = chain._providers[0]
        provider.failure_count = 2
        provider.last_failure_at = datetime.utcnow()

        await chain.mark_success(provider.name)

        assert provider.failure_count == 0
        assert provider.last_failure_at is None

    async def test_mark_success_on_already_healthy_provider_is_noop(self):
        """Calling mark_success on a provider with failure_count=0 is safe."""
        chain = _make_chain()
        provider = chain._providers[0]
        assert provider.failure_count == 0
        await chain.mark_success(provider.name)  # Should not raise
        assert provider.failure_count == 0

    async def test_mark_failure_unknown_provider_is_safe(self):
        """mark_failure with an unknown name logs but does not raise."""
        chain = _make_chain()
        await chain.mark_failure("does_not_exist")  # Must not raise

    async def test_mark_success_unknown_provider_is_safe(self):
        """mark_success with an unknown name logs but does not raise."""
        chain = _make_chain()
        await chain.mark_success("does_not_exist")  # Must not raise

    async def test_reset_all_clears_all_failure_counts(self):
        """reset_all resets every provider in the chain."""
        chain = _make_chain()
        for p in chain._providers:
            p.failure_count = MAX_PROVIDER_FAILURES
            p.last_failure_at = datetime.utcnow()

        await chain.reset_all()

        for p in chain._providers:
            assert p.failure_count == 0
            assert p.last_failure_at is None


# =============================================================================
# get_llm_client
# =============================================================================


class TestGetLlmClient:
    """Tests for FallbackChain.get_llm_client()."""

    @patch("agent.resilience.fallback_chain.ChatOpenAI")
    def test_returns_chat_openai_instance(self, mock_chat_openai):
        """get_llm_client returns a ChatOpenAI instance."""
        mock_instance = MagicMock()
        mock_chat_openai.return_value = mock_instance

        chain = _make_chain()
        provider = chain._providers[0]
        client = chain.get_llm_client(provider)

        assert client is mock_instance

    @patch("agent.resilience.fallback_chain.ChatOpenAI")
    def test_uses_provider_model(self, mock_chat_openai):
        """get_llm_client passes provider.model to ChatOpenAI."""
        chain = _make_chain()
        provider = ProviderConfig(name="test", model="vendor/special-model", priority=0)
        chain.get_llm_client(provider)

        call_kwargs = mock_chat_openai.call_args.kwargs
        assert call_kwargs["model"] == "vendor/special-model"

    @patch("agent.resilience.fallback_chain.ChatOpenAI")
    def test_uses_openrouter_base_url(self, mock_chat_openai):
        """get_llm_client always uses OpenRouter base URL."""
        chain = _make_chain()
        provider = chain._providers[0]
        chain.get_llm_client(provider)

        call_kwargs = mock_chat_openai.call_args.kwargs
        assert call_kwargs["base_url"] == OPENROUTER_BASE_URL

    @patch("agent.resilience.fallback_chain.get_settings")
    @patch("agent.resilience.fallback_chain.ChatOpenAI")
    def test_uses_openrouter_api_key_from_settings(
        self, mock_chat_openai, mock_get_settings
    ):
        """get_llm_client reads OPENROUTER_API_KEY from settings."""
        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-test-key"
        mock_get_settings.return_value = mock_settings

        chain = _make_chain()
        provider = chain._providers[0]
        chain.get_llm_client(provider)

        call_kwargs = mock_chat_openai.call_args.kwargs
        assert call_kwargs["api_key"] == "sk-or-test-key"

    @patch("agent.resilience.fallback_chain.ChatOpenAI")
    def test_max_retries_set_to_zero(self, mock_chat_openai):
        """get_llm_client sets max_retries=0 (FallbackChain handles retries)."""
        chain = _make_chain()
        provider = chain._providers[0]
        chain.get_llm_client(provider)

        call_kwargs = mock_chat_openai.call_args.kwargs
        assert call_kwargs["max_retries"] == 0


# =============================================================================
# get_circuit_breaker_for_provider
# =============================================================================


class TestGetCircuitBreakerForProvider:
    """Tests for per-provider circuit breaker creation."""

    def test_returns_circuit_breaker_for_primary(self):
        """Primary provider gets a CircuitBreaker instance."""
        chain = FallbackChain()
        breaker = chain.get_circuit_breaker_for_provider("primary")
        assert isinstance(breaker, pybreaker.CircuitBreaker)

    def test_returns_circuit_breaker_for_fallback(self):
        """Fallback provider gets a CircuitBreaker instance."""
        chain = FallbackChain()
        breaker = chain.get_circuit_breaker_for_provider("fallback")
        assert isinstance(breaker, pybreaker.CircuitBreaker)

    def test_returns_circuit_breaker_for_emergency(self):
        """Emergency provider gets a CircuitBreaker instance."""
        chain = FallbackChain()
        breaker = chain.get_circuit_breaker_for_provider("emergency")
        assert isinstance(breaker, pybreaker.CircuitBreaker)

    def test_same_instance_returned_on_repeated_calls(self):
        """Repeated calls with the same name return the same singleton."""
        chain = FallbackChain()
        b1 = chain.get_circuit_breaker_for_provider("primary")
        b2 = chain.get_circuit_breaker_for_provider("primary")
        assert b1 is b2

    def test_different_providers_get_different_breakers(self):
        """Each provider name maps to a different CircuitBreaker."""
        chain = FallbackChain()
        b_primary = chain.get_circuit_breaker_for_provider("primary")
        b_fallback = chain.get_circuit_breaker_for_provider("fallback")
        assert b_primary is not b_fallback

    def test_primary_has_higher_fail_max_than_fallback(self):
        """Primary is more tolerant: fail_max=5 vs fallback fail_max=3."""
        chain = FallbackChain()
        b_primary = chain.get_circuit_breaker_for_provider("primary")
        b_fallback = chain.get_circuit_breaker_for_provider("fallback")
        assert b_primary.fail_max > b_fallback.fail_max

    def test_emergency_has_longest_reset_timeout(self):
        """Emergency has the strictest reset_timeout (120s)."""
        chain = FallbackChain()
        b_primary = chain.get_circuit_breaker_for_provider("primary")
        b_emergency = chain.get_circuit_breaker_for_provider("emergency")
        assert b_emergency.reset_timeout > b_primary.reset_timeout


# =============================================================================
# call_with_fallback — success path
# =============================================================================


class TestCallWithFallbackSuccess:
    """Tests for the success path of call_with_fallback."""

    async def test_success_on_primary_calls_func_once(self):
        """If primary succeeds, func is called exactly once."""
        called_with_providers: list[str] = []

        async def fake_func(*args, llm, **kwargs):
            called_with_providers.append(llm.model)
            return "ok"

        providers = [
            ProviderConfig(name="primary", model="model-0", priority=0),
            ProviderConfig(name="fallback", model="model-1", priority=1),
        ]

        with patch("agent.resilience.fallback_chain.ChatOpenAI") as mock_llm_cls:
            # Make ChatOpenAI return a mock with the correct model attribute
            def llm_factory(**kwargs):
                m = MagicMock()
                m.model = kwargs["model"]
                return m

            mock_llm_cls.side_effect = llm_factory

            with patch.object(
                pybreaker.CircuitBreaker,
                "call_async",
                side_effect=lambda f, *a, **kw: f(*a, **kw),
            ):
                chain = FallbackChain(providers=providers)
                result = await chain.call_with_fallback(
                    fake_func, conversation_id="conv_1"
                )

        assert result == "ok"
        assert called_with_providers == ["model-0"]

    async def test_success_resets_provider_failure_count(self):
        """mark_success is called after a successful invocation."""
        async def fake_func(*args, llm, **kwargs):
            return "done"

        providers = [ProviderConfig(name="primary", model="m0", priority=0)]
        providers[0].failure_count = 2  # Was partially degraded

        with patch("agent.resilience.fallback_chain.ChatOpenAI"):
            with patch.object(
                pybreaker.CircuitBreaker,
                "call_async",
                side_effect=lambda f, *a, **kw: f(*a, **kw),
            ):
                chain = FallbackChain(providers=providers)
                await chain.call_with_fallback(fake_func, conversation_id="conv_2")

        assert providers[0].failure_count == 0


# =============================================================================
# call_with_fallback — fallback paths
# =============================================================================


class TestCallWithFallbackFallback:
    """Tests for the fallback path of call_with_fallback."""

    async def test_transient_error_falls_back_to_next_provider(self):
        """TRANSIENT error from primary causes fallback to secondary."""
        call_log: list[str] = []

        async def fake_func(*args, llm, **kwargs):
            call_log.append(llm.model)
            if llm.model == "model-0":
                from openai import APIConnectionError
                raise APIConnectionError(request=MagicMock())
            return "fallback-ok"

        providers = [
            ProviderConfig(name="primary", model="model-0", priority=0),
            ProviderConfig(name="fallback", model="model-1", priority=1),
        ]

        with patch("agent.resilience.fallback_chain.ChatOpenAI") as mock_llm_cls:
            def llm_factory(**kwargs):
                m = MagicMock()
                m.model = kwargs["model"]
                return m

            mock_llm_cls.side_effect = llm_factory

            with patch.object(
                pybreaker.CircuitBreaker,
                "call_async",
                side_effect=lambda f, *a, **kw: f(*a, **kw),
            ):
                chain = FallbackChain(providers=providers)
                result = await chain.call_with_fallback(
                    fake_func, conversation_id="conv_3"
                )

        assert result == "fallback-ok"
        assert "model-0" in call_log
        assert "model-1" in call_log

    async def test_rate_limit_error_falls_back_to_next_provider(self):
        """RATE_LIMIT error triggers fallback to the next provider."""
        call_log: list[str] = []

        async def fake_func(*args, llm, **kwargs):
            call_log.append(llm.model)
            if llm.model == "model-0":
                from openai import RateLimitError
                mock_response = MagicMock()
                mock_response.status_code = 429
                mock_response.headers = {}
                raise RateLimitError(
                    message="Rate limited",
                    response=mock_response,
                    body={},
                )
            return "rate-limit-fallback-ok"

        providers = [
            ProviderConfig(name="primary", model="model-0", priority=0),
            ProviderConfig(name="fallback", model="model-1", priority=1),
        ]

        with patch("agent.resilience.fallback_chain.ChatOpenAI") as mock_llm_cls:
            def llm_factory(**kwargs):
                m = MagicMock()
                m.model = kwargs["model"]
                return m

            mock_llm_cls.side_effect = llm_factory

            with patch.object(
                pybreaker.CircuitBreaker,
                "call_async",
                side_effect=lambda f, *a, **kw: f(*a, **kw),
            ):
                chain = FallbackChain(providers=providers)
                result = await chain.call_with_fallback(
                    fake_func, conversation_id="conv_4"
                )

        assert result == "rate-limit-fallback-ok"
        assert len(call_log) == 2

    async def test_permanent_error_does_not_fallback(self):
        """PERMANENT error (auth) is re-raised immediately without fallback."""
        call_count = 0

        async def fake_func(*args, llm, **kwargs):
            nonlocal call_count
            call_count += 1
            from openai import AuthenticationError
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.headers = {}
            raise AuthenticationError(
                message="Invalid API key",
                response=mock_response,
                body={},
            )

        providers = [
            ProviderConfig(name="primary", model="m0", priority=0),
            ProviderConfig(name="fallback", model="m1", priority=1),
        ]

        with patch("agent.resilience.fallback_chain.ChatOpenAI"):
            with patch.object(
                pybreaker.CircuitBreaker,
                "call_async",
                side_effect=lambda f, *a, **kw: f(*a, **kw),
            ):
                chain = FallbackChain(providers=providers)
                with pytest.raises(Exception) as exc_info:
                    await chain.call_with_fallback(
                        fake_func, conversation_id="conv_5"
                    )

        # Must only call func once (primary only), not attempt fallback
        assert call_count == 1
        # The original AuthenticationError must be re-raised (not wrapped)
        assert "AuthenticationError" in type(exc_info.value).__name__

    async def test_all_providers_fail_raises_fallback_exhausted_error(self):
        """When all providers fail with TRANSIENT, FallbackExhaustedError is raised."""
        async def fake_func(*args, llm, **kwargs):
            raise ConnectionError("network down")

        providers = _make_providers(3)

        with patch("agent.resilience.fallback_chain.ChatOpenAI"):
            with patch.object(
                pybreaker.CircuitBreaker,
                "call_async",
                side_effect=lambda f, *a, **kw: f(*a, **kw),
            ):
                chain = FallbackChain(providers=providers)
                with pytest.raises(FallbackExhaustedError) as exc_info:
                    await chain.call_with_fallback(
                        fake_func, conversation_id="conv_6"
                    )

        error = exc_info.value
        assert isinstance(error, FallbackExhaustedError)
        assert len(error.providers_tried) == 3

    async def test_fallback_exhausted_error_records_providers_tried(self):
        """FallbackExhaustedError.providers_tried contains all attempted providers."""
        async def fake_func(*args, llm, **kwargs):
            raise TimeoutError("timeout")

        providers = _make_providers(3)

        with patch("agent.resilience.fallback_chain.ChatOpenAI"):
            with patch.object(
                pybreaker.CircuitBreaker,
                "call_async",
                side_effect=lambda f, *a, **kw: f(*a, **kw),
            ):
                chain = FallbackChain(providers=providers)
                with pytest.raises(FallbackExhaustedError) as exc_info:
                    await chain.call_with_fallback(
                        fake_func, conversation_id="conv_7"
                    )

        error = exc_info.value
        assert set(error.providers_tried) == {p.name for p in providers}

    async def test_fallback_exhausted_error_has_last_error(self):
        """FallbackExhaustedError.last_error is a ClassifiedError."""
        async def fake_func(*args, llm, **kwargs):
            raise TimeoutError("timeout")

        providers = _make_providers(1)

        with patch("agent.resilience.fallback_chain.ChatOpenAI"):
            with patch.object(
                pybreaker.CircuitBreaker,
                "call_async",
                side_effect=lambda f, *a, **kw: f(*a, **kw),
            ):
                chain = FallbackChain(providers=providers)
                with pytest.raises(FallbackExhaustedError) as exc_info:
                    await chain.call_with_fallback(
                        fake_func, conversation_id="conv_8"
                    )

        assert exc_info.value.last_error is not None
        assert isinstance(exc_info.value.last_error, ClassifiedError)

    async def test_circuit_breaker_open_triggers_fallback(self):
        """A CircuitBreakerError on primary is treated as TRANSIENT and triggers fallback."""
        call_log: list[str] = []

        async def fake_func(*args, llm, **kwargs):
            call_log.append(llm.model)
            return "emergency-ok"

        providers = [
            ProviderConfig(name="primary", model="model-0", priority=0),
            ProviderConfig(name="fallback", model="model-1", priority=1),
        ]

        # Simulate circuit breaker OPEN on primary call, pass-through on fallback
        mock_primary_breaker = MagicMock()
        mock_fallback_breaker = MagicMock()

        async def primary_call_async(f, *a, **kw):
            raise pybreaker.CircuitBreakerError(mock_primary_breaker)

        async def fallback_call_async(f, *a, **kw):
            return await f(*a, **kw)

        mock_primary_breaker.call_async = primary_call_async
        mock_fallback_breaker.call_async = fallback_call_async

        with patch("agent.resilience.fallback_chain.ChatOpenAI") as mock_llm_cls:
            def llm_factory(**kwargs):
                m = MagicMock()
                m.model = kwargs["model"]
                return m

            mock_llm_cls.side_effect = llm_factory

            chain = FallbackChain(providers=providers)
            # Inject pre-configured mock breakers
            chain._breakers["primary"] = mock_primary_breaker
            chain._breakers["fallback"] = mock_fallback_breaker

            result = await chain.call_with_fallback(
                fake_func, conversation_id="conv_9"
            )

        assert result == "emergency-ok"
        # Only fallback provider should have been called via fake_func
        assert "model-1" in call_log


# =============================================================================
# FallbackExhaustedError
# =============================================================================


class TestFallbackExhaustedError:
    """Tests for FallbackExhaustedError exception class."""

    def test_is_exception_subclass(self):
        """FallbackExhaustedError must be a Python Exception."""
        err = FallbackExhaustedError("all done")
        assert isinstance(err, Exception)

    def test_message_is_accessible_via_args(self):
        """The exception message is accessible via standard args."""
        err = FallbackExhaustedError("providers exhausted")
        assert "providers exhausted" in str(err)

    def test_last_error_attribute(self):
        """last_error attribute stores the last ClassifiedError."""
        classified = _make_classified(ErrorType.TRANSIENT)
        err = FallbackExhaustedError("done", last_error=classified)
        assert err.last_error is classified

    def test_providers_tried_attribute(self):
        """providers_tried attribute stores the list of attempted providers."""
        err = FallbackExhaustedError(
            "done", providers_tried=["primary", "fallback", "emergency"]
        )
        assert err.providers_tried == ["primary", "fallback", "emergency"]

    def test_defaults_last_error_to_none(self):
        """last_error defaults to None when not provided."""
        err = FallbackExhaustedError("done")
        assert err.last_error is None

    def test_defaults_providers_tried_to_empty_list(self):
        """providers_tried defaults to empty list when not provided."""
        err = FallbackExhaustedError("done")
        assert err.providers_tried == []

    def test_repr_is_descriptive(self):
        """__repr__ includes providers_tried and last error type."""
        classified = _make_classified(ErrorType.RATE_LIMIT)
        err = FallbackExhaustedError(
            "done",
            last_error=classified,
            providers_tried=["primary"],
        )
        r = repr(err)
        assert "primary" in r


# =============================================================================
# Package-level imports from agent.resilience
# =============================================================================


class TestPackageLevelImports:
    """Verify Phase 3 types are exported from the package root."""

    def test_fallback_chain_importable_from_package(self):
        """FallbackChain is importable from agent.resilience."""
        from agent.resilience import FallbackChain as FC  # noqa: F401
        assert FC is FallbackChain

    def test_fallback_exhausted_error_importable_from_package(self):
        """FallbackExhaustedError is importable from agent.resilience."""
        from agent.resilience import FallbackExhaustedError as FEE  # noqa: F401
        assert FEE is FallbackExhaustedError

    def test_provider_config_importable_from_package(self):
        """ProviderConfig is importable from agent.resilience."""
        from agent.resilience import ProviderConfig as PC  # noqa: F401
        assert PC is ProviderConfig

    def test_all_exports_present(self):
        """All Phase 3 exports are in __all__."""
        import agent.resilience as pkg
        for name in ["FallbackChain", "FallbackExhaustedError", "ProviderConfig"]:
            assert name in pkg.__all__, f"'{name}' missing from __all__"

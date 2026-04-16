"""
Multi-Provider Fallback Chain for LLM API resilience.

This module implements the FallbackChain component that manages a prioritized
chain of LLM providers. When the primary provider (OpenRouter/GPT-5.4-mini)
fails with a retryable error, FallbackChain automatically switches to the next
available provider.

Provider priority order (lower number = higher priority):
  0. primary   — openai/gpt-5.4-mini (default, cheapest, fastest)
  1. fallback  — deepseek/deepseek-chat (cheap, capable)
  2. emergency — meta-llama/llama-3.1-8b-instruct (always-on, last resort)

Fallback is ONLY triggered for TRANSIENT and RATE_LIMIT errors.
PERMANENT errors fail immediately (no point trying another provider).

Usage:
    from agent.resilience.fallback_chain import FallbackChain

    chain = FallbackChain()
    result = await chain.call_with_fallback(
        my_llm_func,
        *args,
        conversation_id="conv_123",
        **kwargs,
    )
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import pybreaker
from langchain_openai import ChatOpenAI

from agent.resilience.error_classifier import ClassifiedError, ErrorClassifier, ErrorType
from shared.circuit_breaker import create_provider_breaker, get_circuit_breaker
from shared.config import get_settings

logger = logging.getLogger(__name__)


# =============================================================================
# T-009: Provider configuration
# =============================================================================

# Maximum consecutive failures before a provider is considered unavailable
MAX_PROVIDER_FAILURES: int = 3
"""Number of consecutive failures before a provider is skipped in the chain."""

OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
"""Base URL for OpenRouter API (all providers route through it)."""


@dataclass
class ProviderConfig:
    """
    Configuration for a single LLM provider in the fallback chain.

    Tracks both static configuration (name, model, priority) and runtime
    health state (failure_count, last_failure_at, is_available).

    Attributes:
        name: Unique identifier for this provider (e.g. "primary", "fallback").
        model: OpenRouter model slug (e.g. "openai/gpt-4o-mini").
        priority: Ordering within the chain — lower value = tried first.
        is_available: Manual availability flag (False = skip always).
        failure_count: Consecutive failures since last success.
        last_failure_at: UTC datetime of most recent failure, or None.
    """

    name: str
    model: str
    priority: int
    is_available: bool = True
    failure_count: int = 0
    last_failure_at: datetime | None = None

    @property
    def is_healthy(self) -> bool:
        """
        Return True if this provider should be attempted.

        A provider is unhealthy if it has been manually disabled OR has
        accumulated too many consecutive failures.
        """
        return self.is_available and self.failure_count < MAX_PROVIDER_FAILURES


# =============================================================================
# T-011: FallbackExhaustedError
# =============================================================================


class FallbackExhaustedError(Exception):
    """
    Raised when all providers in the fallback chain have been tried and failed.

    This is the terminal error raised by FallbackChain.call_with_fallback()
    when no more providers remain. Callers should escalate to human agents.

    Attributes:
        last_error: The ClassifiedError from the final provider attempt.
        providers_tried: Names of all providers that were attempted.
    """

    def __init__(
        self,
        message: str,
        last_error: ClassifiedError | None = None,
        providers_tried: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.last_error = last_error
        self.providers_tried: list[str] = providers_tried or []

    def __repr__(self) -> str:
        return (
            f"FallbackExhaustedError("
            f"providers_tried={self.providers_tried!r}, "
            f"last_error_type={self.last_error.error_type if self.last_error else None!r}"
            f")"
        )


# =============================================================================
# T-009 (continued): Default provider chain
# =============================================================================


def _build_default_provider_chain() -> list[ProviderConfig]:
    """
    Build the default provider chain using settings from shared/config.py.

    Called once at module load time (and whenever FallbackChain is reset).
    Using a function instead of a module-level constant avoids import-time
    side effects (get_settings() reads environment variables).

    Returns:
        Ordered list of ProviderConfig sorted by priority ascending.
    """
    settings = get_settings()
    return [
        ProviderConfig(
            name="primary",
            model=settings.LLM_MODEL,  # e.g. "openai/gpt-4o-mini"
            priority=0,
        ),
        ProviderConfig(
            name="fallback",
            model=settings.LLM_FALLBACK_MODEL,  # default: "deepseek/deepseek-chat"
            priority=1,
        ),
        ProviderConfig(
            name="emergency",
            model=settings.LLM_EMERGENCY_MODEL,  # default: "meta-llama/llama-3.1-8b-instruct"
            priority=2,
        ),
    ]


# =============================================================================
# T-010 + T-011: FallbackChain class
# =============================================================================


class FallbackChain:
    """
    Manages a prioritized chain of LLM providers with automatic fallback.

    On a TRANSIENT or RATE_LIMIT error, FallbackChain switches to the next
    available provider in priority order. PERMANENT errors are re-raised
    immediately — no other provider will succeed.

    Each provider is protected by an independent circuit breaker with tuned
    thresholds (primary is more tolerant; emergency is strictest).

    Thread-safety: all provider state mutations use asyncio.Lock. A single
    FallbackChain instance is safe to share across concurrent coroutines.

    Usage:
        chain = FallbackChain()
        result = await chain.call_with_fallback(
            my_llm_coroutine,
            *args,
            conversation_id="conv_abc",
            **kwargs,
        )
    """

    def __init__(self, providers: list[ProviderConfig] | None = None) -> None:
        """
        Initialise the fallback chain.

        Args:
            providers: Optional custom provider list (mostly for testing).
                       Defaults to the production chain from settings.
        """
        self._providers: list[ProviderConfig] = (
            providers if providers is not None else _build_default_provider_chain()
        )
        # Sort by priority (ascending) to ensure consistent ordering
        self._providers.sort(key=lambda p: p.priority)

        # Single lock guards all mutations to _providers list elements
        self._lock: asyncio.Lock = asyncio.Lock()

        # Error classifier for categorising exceptions during call_with_fallback
        self._classifier: ErrorClassifier = ErrorClassifier()

        # Circuit breakers are keyed by provider name
        self._breakers: dict[str, pybreaker.CircuitBreaker] = {}

        logger.info(
            "FallbackChain initialised | providers=%s",
            [p.name for p in self._providers],
        )

    # -------------------------------------------------------------------------
    # T-010: Provider management methods
    # -------------------------------------------------------------------------

    def get_next_provider(
        self,
        current_provider: str,
        classified_error: ClassifiedError,
    ) -> ProviderConfig | None:
        """
        Return the next healthy provider to try after a failure.

        Fallback is only triggered for TRANSIENT and RATE_LIMIT errors.
        For PERMANENT errors (auth, not found, etc.) return None immediately
        because no provider will succeed with the same invalid request.

        Args:
            current_provider: Name of the provider that just failed.
            classified_error: ClassifiedError from the failed call.

        Returns:
            Next ProviderConfig to try, or None if all providers are exhausted
            or the error type does not permit fallback.
        """
        # Only attempt fallback for retryable error types
        if classified_error.error_type not in {ErrorType.TRANSIENT, ErrorType.RATE_LIMIT}:
            logger.info(
                "FallbackChain.get_next_provider: no fallback for %s errors | "
                "current_provider=%s",
                classified_error.error_type.value,
                current_provider,
            )
            return None

        # Find the next healthy provider with higher priority number (lower urgency)
        current_priority = self._get_provider_priority(current_provider)

        for provider in self._providers:
            if provider.priority <= current_priority:
                # Skip providers with equal or higher priority than current
                continue
            if not provider.is_healthy:
                logger.debug(
                    "FallbackChain: skipping unhealthy provider | "
                    "provider=%s | failure_count=%d",
                    provider.name,
                    provider.failure_count,
                )
                continue
            logger.info(
                "FallbackChain: selected fallback provider | "
                "current=%s | next=%s | error_type=%s",
                current_provider,
                provider.name,
                classified_error.error_type.value,
            )
            return provider

        logger.warning(
            "FallbackChain: all providers exhausted | current_provider=%s | "
            "error_type=%s",
            current_provider,
            classified_error.error_type.value,
        )
        return None

    async def mark_failure(self, provider_name: str) -> None:
        """
        Record a failure for a provider (increments failure_count).

        Thread-safe: uses asyncio.Lock to prevent concurrent mutation.

        Args:
            provider_name: The name of the provider that failed.
        """
        async with self._lock:
            provider = self._find_provider(provider_name)
            if provider is None:
                logger.warning(
                    "FallbackChain.mark_failure: unknown provider '%s'", provider_name
                )
                return

            provider.failure_count += 1
            provider.last_failure_at = datetime.utcnow()

            logger.info(
                "FallbackChain.mark_failure: provider=%s | failure_count=%d | "
                "max=%d | is_healthy=%s",
                provider_name,
                provider.failure_count,
                MAX_PROVIDER_FAILURES,
                provider.is_healthy,
            )

    async def mark_success(self, provider_name: str) -> None:
        """
        Record a success for a provider (resets failure_count to 0).

        Thread-safe: uses asyncio.Lock.

        Args:
            provider_name: The name of the provider that succeeded.
        """
        async with self._lock:
            provider = self._find_provider(provider_name)
            if provider is None:
                logger.warning(
                    "FallbackChain.mark_success: unknown provider '%s'", provider_name
                )
                return

            if provider.failure_count > 0:
                logger.info(
                    "FallbackChain.mark_success: resetting provider | "
                    "provider=%s | was_failure_count=%d",
                    provider_name,
                    provider.failure_count,
                )
            provider.failure_count = 0
            provider.last_failure_at = None

    async def reset_all(self) -> None:
        """
        Reset all providers to a healthy state (failure_count=0).

        Primarily used for testing to restore a clean chain between test cases.
        Can also be called at application startup to clear stale state.
        """
        async with self._lock:
            for provider in self._providers:
                provider.failure_count = 0
                provider.last_failure_at = None
            logger.debug(
                "FallbackChain.reset_all: reset %d providers", len(self._providers)
            )

    def get_llm_client(self, provider_config: ProviderConfig) -> ChatOpenAI:
        """
        Build and return a configured ChatOpenAI client for a provider.

        All providers route through OpenRouter using the same API key and
        base URL — only the model slug differs between them.

        Args:
            provider_config: The provider to build a client for.

        Returns:
            Configured ChatOpenAI instance ready for invocation.
        """
        settings = get_settings()
        client = ChatOpenAI(
            model=provider_config.model,
            base_url=OPENROUTER_BASE_URL,
            api_key=settings.OPENROUTER_API_KEY,
            temperature=0.3,
            request_timeout=30.0,
            max_retries=0,  # Retry logic is handled externally by FallbackChain
            default_headers={
                "HTTP-Referer": settings.SITE_URL,
                "X-Title": settings.SITE_NAME,
            },
        )
        logger.debug(
            "FallbackChain.get_llm_client: created client | "
            "provider=%s | model=%s",
            provider_config.name,
            provider_config.model,
        )
        return client

    # -------------------------------------------------------------------------
    # T-011: Circuit breaker integration
    # -------------------------------------------------------------------------

    def get_circuit_breaker_for_provider(
        self, provider_name: str
    ) -> pybreaker.CircuitBreaker:
        """
        Get or create the circuit breaker for a specific provider.

        Delegates to ``create_provider_breaker()`` in shared/circuit_breaker.py,
        which is the single source of truth for provider breaker thresholds:
        - primary:   fail_max=5, reset_timeout=30s  (more tolerant)
        - fallback:  fail_max=3, reset_timeout=60s
        - emergency: fail_max=3, reset_timeout=120s (strictest — last resort)

        Unknown providers receive primary-level defaults.

        Args:
            provider_name: The provider identifier.

        Returns:
            pybreaker.CircuitBreaker singleton for this provider.
        """
        if provider_name not in self._breakers:
            # Use shared factory — avoids duplication of breaker config
            self._breakers[provider_name] = create_provider_breaker(provider_name)
        return self._breakers[provider_name]

    async def call_with_fallback(
        self,
        func: Callable[..., Any],
        *args: Any,
        conversation_id: str,
        **kwargs: Any,
    ) -> Any:
        """
        Call ``func`` with automatic provider fallback on retryable errors.

        Tries providers in priority order. On TRANSIENT or RATE_LIMIT errors,
        switches to the next available provider. On PERMANENT errors, raises
        immediately. Raises FallbackExhaustedError when all providers fail.

        ``func`` receives the LLM client as a keyword argument named ``llm``
        (the provider being tried for this attempt). All other ``*args`` and
        ``**kwargs`` are forwarded as-is.

        Args:
            func: Async callable that accepts ``llm=<ChatOpenAI>`` keyword arg.
            *args: Positional arguments forwarded to func.
            conversation_id: Used for logging/tracing only.
            **kwargs: Keyword arguments forwarded to func (``llm`` will be
                      injected/overridden per provider attempt).

        Returns:
            Whatever ``func`` returns on success.

        Raises:
            FallbackExhaustedError: All providers in the chain have failed.
            Exception: PERMANENT classified errors are re-raised immediately.
        """
        providers_tried: list[str] = []
        last_classified: ClassifiedError | None = None

        # Start with the primary provider (priority=0)
        current_provider = self._providers[0] if self._providers else None

        while current_provider is not None:
            if not current_provider.is_healthy:
                # This provider is degraded — skip to the next immediately
                logger.debug(
                    "FallbackChain.call_with_fallback: skipping unhealthy provider | "
                    "provider=%s | conversation_id=%s",
                    current_provider.name,
                    conversation_id,
                )
                last_classified = ClassifiedError(
                    error_type=ErrorType.TRANSIENT,
                    original_exception=RuntimeError(
                        f"Provider '{current_provider.name}' is unhealthy"
                    ),
                    message=f"Provider '{current_provider.name}' skipped (too many failures)",
                )
                providers_tried.append(current_provider.name)
                current_provider = self.get_next_provider(
                    current_provider.name, last_classified
                )
                continue

            breaker = self.get_circuit_breaker_for_provider(current_provider.name)
            llm_client = self.get_llm_client(current_provider)
            provider_name = current_provider.name
            providers_tried.append(provider_name)

            try:
                logger.info(
                    "FallbackChain.call_with_fallback: attempting provider | "
                    "provider=%s | model=%s | conversation_id=%s",
                    provider_name,
                    current_provider.model,
                    conversation_id,
                )

                # Inject the per-provider LLM client into the call
                result = await breaker.call_async(func, *args, llm=llm_client, **kwargs)

                # Success — reset provider failure count
                await self.mark_success(provider_name)

                logger.info(
                    "FallbackChain.call_with_fallback: success | "
                    "provider=%s | conversation_id=%s",
                    provider_name,
                    conversation_id,
                )
                return result

            except pybreaker.CircuitBreakerError as exc:
                # Circuit is OPEN — treat like TRANSIENT, try next provider
                logger.warning(
                    "FallbackChain.call_with_fallback: circuit OPEN for provider | "
                    "provider=%s | conversation_id=%s",
                    provider_name,
                    conversation_id,
                )
                last_classified = ClassifiedError(
                    error_type=ErrorType.TRANSIENT,
                    original_exception=exc,
                    message=f"Circuit breaker open for provider '{provider_name}'",
                )
                current_provider = self.get_next_provider(provider_name, last_classified)

            except Exception as exc:
                classified = self._classifier.classify(exc)
                last_classified = classified

                logger.warning(
                    "FallbackChain.call_with_fallback: provider failed | "
                    "provider=%s | error_type=%s | conversation_id=%s | error=%s",
                    provider_name,
                    classified.error_type.value,
                    conversation_id,
                    exc,
                )

                # PERMANENT error — no other provider will fix an auth/not-found issue
                if classified.error_type == ErrorType.PERMANENT:
                    logger.error(
                        "FallbackChain.call_with_fallback: PERMANENT error — "
                        "not attempting fallback | provider=%s | conversation_id=%s",
                        provider_name,
                        conversation_id,
                    )
                    await self.mark_failure(provider_name)
                    raise

                # TRANSIENT / RATE_LIMIT — record failure and try next provider
                await self.mark_failure(provider_name)
                current_provider = self.get_next_provider(provider_name, classified)

        # All providers exhausted
        logger.error(
            "FallbackChain.call_with_fallback: all providers exhausted | "
            "providers_tried=%s | conversation_id=%s",
            providers_tried,
            conversation_id,
        )
        raise FallbackExhaustedError(
            f"All LLM providers exhausted after trying: {providers_tried}",
            last_error=last_classified,
            providers_tried=providers_tried,
        )

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _find_provider(self, name: str) -> ProviderConfig | None:
        """Return the ProviderConfig with the given name, or None."""
        for provider in self._providers:
            if provider.name == name:
                return provider
        return None

    def _get_provider_priority(self, name: str) -> int:
        """
        Return the priority of a provider by name.

        If the provider is unknown, return -1 so that ALL providers in the
        chain qualify as "lower priority" (fallback candidates).
        """
        provider = self._find_provider(name)
        return provider.priority if provider is not None else -1

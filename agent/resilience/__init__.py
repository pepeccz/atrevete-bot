"""
Resilience layer for LLM API integration.

This package provides structured error handling, classification, and recovery
mechanisms for all external API calls in the conversational agent.

Phases:
- Phase 1: Error classification system (complete)
- Phase 2: Progressive retry with exponential backoff + retry budget (complete)
- Phase 3: Multi-provider fallback chain (complete)
- Phase 4: Enhanced circuit breaker integration (complete — via FallbackChain)
- Phase 5: Booking domain error recovery

Quick start:
    from agent.resilience import ErrorClassifier, ErrorType, ClassifiedError
    from agent.resilience import RetryStrategy, RetryBudget
    from agent.resilience import FallbackChain, FallbackExhaustedError

    classifier = ErrorClassifier()
    strategy = RetryStrategy()
    budget = RetryBudget()
    chain = FallbackChain()

    classified = classifier.classify(exc)

    if classified.is_retryable:
        state = {
            "attempt_count": 1,
            "last_error_type": classified.error_type,
            "next_retry_at": None,
            "total_retries_used": 0,
            "budget_exhausted": False,
        }
        decision = strategy.should_retry(classified, state)
        if decision.should_retry and await budget.consume(conv_id, classified.error_type):
            await asyncio.sleep(decision.delay_seconds)
            # retry...

    # Or use the full fallback chain (recommended):
    result = await chain.call_with_fallback(
        my_llm_func, *args, conversation_id=conv_id, **kwargs
    )
"""

from agent.resilience.error_classifier import (
    ClassifiedError,
    ErrorClassifier,
    ErrorType,
    FallbackMetrics,
    RetryDecision,
)
from agent.resilience.fallback_chain import (
    FallbackChain,
    FallbackExhaustedError,
    ProviderConfig,
)
from agent.resilience.retry_strategy import (
    RetryBudget,
    RetryStrategy,
)

__all__ = [
    # Core classifier (Phase 1)
    "ErrorClassifier",
    # Types / enums (Phase 1)
    "ErrorType",
    "ClassifiedError",
    "RetryDecision",
    "FallbackMetrics",
    # Retry strategy + budget (Phase 2)
    "RetryStrategy",
    "RetryBudget",
    # Fallback chain + circuit breakers (Phase 3 + 4)
    "FallbackChain",
    "FallbackExhaustedError",
    "ProviderConfig",
]

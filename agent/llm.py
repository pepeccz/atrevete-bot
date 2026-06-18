"""ChatOpenAI factory routed through OpenRouter.

Config mapping (shared/config.py field names):
  - api_key        ← settings.OPENROUTER_API_KEY
  - model          ← settings.LLM_MODEL
  - base_url       ← hardcoded OpenRouter endpoint (no OPENROUTER_BASE_URL in config)
  - HTTP-Referer   ← settings.SITE_URL
  - X-Title        ← settings.SITE_NAME
  - temperature    ← caller-supplied or 0.0 (no OPENAI_TEMPERATURE in config)

Resilience:
  - ResilientChatOpenAI subclass retries TRANSIENT errors that the openai SDK
    does not catch (200-OK responses with error bodies, e.g. OpenRouter 502 wrapped
    in a 200). Uses LLM_TRANSIENT_RETRY_ATTEMPTS + LLM_TRANSIENT_RETRY_BASE_DELAY.
  - LLM_FALLBACK_MODELS enables OpenRouter-level models-fallback routing so a
    single-model outage transparently degrades to the next model in the list.

Important non-coverage note:
  Account-level CREDIT EXHAUSTION ("exceeded your current quota" / insufficient credits)
  is NOT recoverable by any retry or fallback here — all OpenRouter models share the
  same account balance. Handling that requires account auto-topup (out of scope).

When LLM_TRACE_ENABLED=True, a traced httpx.AsyncClient is injected via
http_async_client= to capture all outbound LLM requests and responses to disk.
When False (default), http_async_client=None preserves the LangChain default.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langchain_openai import ChatOpenAI

from agent.tracing.httpx_hooks import _traced_client_singleton
from shared.config import get_settings

logger = logging.getLogger(__name__)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# ---------------------------------------------------------------------------
# Error classification — module-level constants for testability
# ---------------------------------------------------------------------------

# Strings that indicate NON-RECOVERABLE errors. Re-raise immediately; never retry.
# These are account/auth failures that no amount of retrying will fix.
_NONRECOVERABLE_KEYWORDS: tuple[str, ...] = (
    "quota",
    "insufficient",
    "credit",
    "billing",
    "invalid api key",
    "unauthorized",
    "401",
    "403",
    "permission",
)

# Strings that indicate TRANSIENT errors safe to retry.
# These cover rate-limit spikes, 5xx passthrough in 200-OK bodies, timeouts,
# provider-side overload, and transient connection issues.
_TRANSIENT_KEYWORDS: tuple[str, ...] = (
    "rate limit",
    "rate-limit",
    "429",
    "temporarily",
    "timeout",
    "timed out",
    "502",
    "503",
    "504",
    "overloaded",
    "unavailable",
    "connection",
    "reset by peer",
)


def _is_nonrecoverable_llm_error(exc: BaseException) -> bool:
    """Return True when the error is a non-recoverable account/auth failure.

    Non-recoverable errors must NOT be retried — they will never succeed with
    the same credentials/account regardless of how many times we try.
    """
    msg = str(exc).lower()
    return any(kw in msg for kw in _NONRECOVERABLE_KEYWORDS)


def _is_transient_llm_error(exc: BaseException) -> bool:
    """Return True when the error is a transient provider/network failure.

    Transient errors are safe to retry with exponential backoff. Non-recoverable
    errors take priority: if _is_nonrecoverable_llm_error is True, this returns False.
    """
    if _is_nonrecoverable_llm_error(exc):
        return False
    msg = str(exc).lower()
    return any(kw in msg for kw in _TRANSIENT_KEYWORDS)


# ---------------------------------------------------------------------------
# Resilient subclass
# ---------------------------------------------------------------------------


class ResilientChatOpenAI(ChatOpenAI):
    """ChatOpenAI subclass that retries TRANSIENT in-process errors.

    The openai SDK's built-in max_retries handles HTTP-status errors (429, 5xx,
    timeouts at the HTTP transport level). It does NOT retry 200-OK responses
    whose body contains an error dict — OpenRouter frequently uses this pattern
    to surface provider-side 502/503/overload errors. LangChain raises these as
    ValueError(response_dict["error"]) from _create_chat_result.

    This subclass wraps _agenerate to catch those ValueErrors (and any other
    exception) and retry when classified as transient.

    Streaming (_astream) is NOT wrapped — the agent uses ainvoke (non-streaming
    path → _agenerate). If streaming is added later, _astream needs the same
    treatment.

    Sync _generate is NOT wrapped — the agent is fully async. Documented here
    so future maintainers know the gap exists.
    """

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        s = get_settings()
        max_extra_attempts = s.LLM_TRANSIENT_RETRY_ATTEMPTS
        base_delay = s.LLM_TRANSIENT_RETRY_BASE_DELAY

        last_exc: BaseException | None = None

        for attempt in range(max_extra_attempts + 1):  # attempt 0 = first try
            try:
                return await super()._agenerate(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                )
            except Exception as exc:
                last_exc = exc

                if _is_nonrecoverable_llm_error(exc):
                    # Account/auth failure — retrying is pointless, re-raise now.
                    raise

                if not _is_transient_llm_error(exc):
                    # Unknown error type — conservative policy: do not retry unknowns.
                    raise

                # Transient error — retry if we have attempts left.
                if attempt >= max_extra_attempts:
                    # Exhausted all extra attempts.
                    raise

                delay = base_delay * (2**attempt) + 0.1 * attempt
                logger.warning(
                    "LLM transient error (attempt %d/%d), retrying in %.2fs: %s",
                    attempt + 1,
                    max_extra_attempts,
                    delay,
                    str(exc)[:200],
                )
                await asyncio.sleep(delay)

        # Should never reach here, but satisfy the type checker.
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("ResilientChatOpenAI._agenerate: unexpected exit without result")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _build_llm(model: str, temperature: float = 0.0) -> ResilientChatOpenAI:
    """Return ResilientChatOpenAI for the given model slug wired to OpenRouter.

    When LLM_TRACE_ENABLED=True, injects a traced httpx.AsyncClient.
    When False, http_async_client=None uses LangChain's default client.

    When LLM_PROVIDER_ORDER is non-empty, passes an OpenRouter 'provider' routing
    hint so the static prompt prefix stays eligible for cross-turn caching.
    allow_fallbacks=True degrades gracefully to a cold-cache turn on provider outage.

    When LLM_FALLBACK_MODELS is non-empty, passes OpenRouter models-fallback routing
    so a single-model outage degrades to the next model in the list without surfacing
    an error to the customer. The primary model is always first in the list.

    NOTE: account-level credit exhaustion is NOT covered by either fallback mechanism
    because all models share the same OpenRouter account balance.
    """
    s = get_settings()
    traced_client = _traced_client_singleton()

    # Build sticky-provider routing hint for OpenRouter prompt-cache eligibility.
    order = [p.strip() for p in s.LLM_PROVIDER_ORDER.split(",") if p.strip()]
    extra_body: dict[str, Any] = {}
    if order:
        extra_body["provider"] = {"order": order, "allow_fallbacks": True}

    # Build OpenRouter models-fallback list when LLM_FALLBACK_MODELS is configured.
    # "models" + "route": "fallback" tells OpenRouter to try each model in order.
    fallback_slugs = [m.strip() for m in s.LLM_FALLBACK_MODELS.split(",") if m.strip()]
    if fallback_slugs:
        extra_body["models"] = [model, *fallback_slugs]
        extra_body["route"] = "fallback"

    # U2 (Change U): explicit retry and timeout policy.
    # openai SDK retries: 408/409/429/>=500/connection errors (exponential backoff + jitter).
    # Non-transient 4xx (400/401/403/422) are NOT retried — fail fast.
    # Previous implicit SDK defaults: max_retries=2, timeout=600s.
    # Verified against openai SDK source (_base_client.py DEFAULT_MAX_RETRIES=2,
    # DEFAULT_TIMEOUT=httpx.Timeout(600.0, connect=5.0)) installed in this project.
    kwargs: dict = dict(
        model=model,
        temperature=temperature,
        # Pin every tool-calling turn to the non-streaming _agenerate path so the
        # ResilientChatOpenAI retry guarantee is STRUCTURAL — it cannot be silently
        # bypassed if a caller later switches to astream or attaches a streaming
        # callback handler. The agent always binds tools, so this covers every turn.
        disable_streaming="tool_calling",
        api_key=s.OPENROUTER_API_KEY,
        base_url=_OPENROUTER_BASE_URL,
        default_headers={
            "HTTP-Referer": s.SITE_URL,
            "X-Title": s.SITE_NAME,
        },
        http_async_client=traced_client,
        max_retries=s.LLM_MAX_RETRIES,
        timeout=s.LLM_REQUEST_TIMEOUT,
    )
    if extra_body:
        kwargs["extra_body"] = extra_body

    return ResilientChatOpenAI(**kwargs)


def get_llm(
    model: str | None = None,
    temperature: float | None = None,
) -> ResilientChatOpenAI:
    """Return ResilientChatOpenAI wired to OpenRouter with project settings."""
    s = get_settings()
    return _build_llm(
        model=model or s.LLM_MODEL, temperature=temperature if temperature is not None else 0.0
    )


def get_summarizer_llm() -> ResilientChatOpenAI:
    """Return the LLM to use for conversation summarization.

    Uses SUMMARIZER_MODEL when set (cheaper model for summarization tasks).
    Falls back to the main LLM_MODEL when SUMMARIZER_MODEL is empty.
    """
    s = get_settings()
    if s.SUMMARIZER_MODEL:
        return _build_llm(model=s.SUMMARIZER_MODEL)
    return get_llm()

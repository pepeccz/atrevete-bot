"""ChatOpenAI factory routed through OpenRouter.

Config mapping (shared/config.py field names):
  - api_key        ← settings.OPENROUTER_API_KEY
  - model          ← settings.LLM_MODEL
  - base_url       ← hardcoded OpenRouter endpoint (no OPENROUTER_BASE_URL in config)
  - HTTP-Referer   ← settings.SITE_URL
  - X-Title        ← settings.SITE_NAME
  - temperature    ← caller-supplied or 0.0 (no OPENAI_TEMPERATURE in config)

When LLM_TRACE_ENABLED=True, a traced httpx.AsyncClient is injected via
http_async_client= to capture all outbound LLM requests and responses to disk.
When False (default), http_async_client=None preserves the LangChain default.
"""

from langchain_openai import ChatOpenAI

from agent.tracing.httpx_hooks import _traced_client_singleton
from shared.config import get_settings

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _build_llm(model: str, temperature: float = 0.0) -> ChatOpenAI:
    """Return ChatOpenAI for the given model slug wired to OpenRouter.

    When LLM_TRACE_ENABLED=True, injects a traced httpx.AsyncClient.
    When False, http_async_client=None uses LangChain's default client.

    When LLM_PROVIDER_ORDER is non-empty, passes an OpenRouter 'provider' routing
    hint so the static prompt prefix stays eligible for cross-turn caching.
    allow_fallbacks=True degrades gracefully to a cold-cache turn on provider outage.
    """
    s = get_settings()
    traced_client = _traced_client_singleton()

    # Build sticky-provider routing hint for OpenRouter prompt-cache eligibility.
    order = [p.strip() for p in s.LLM_PROVIDER_ORDER.split(",") if p.strip()]
    extra_body = {"provider": {"order": order, "allow_fallbacks": True}} if order else None

    # U2 (Change U): explicit retry and timeout policy.
    # openai SDK retries: 408/409/429/>=500/connection errors (exponential backoff + jitter).
    # Non-transient 4xx (400/401/403/422) are NOT retried — fail fast.
    # Previous implicit SDK defaults: max_retries=2, timeout=600s.
    # Verified against openai SDK source (_base_client.py DEFAULT_MAX_RETRIES=2,
    # DEFAULT_TIMEOUT=httpx.Timeout(600.0, connect=5.0)) installed in this project.
    kwargs: dict = dict(
        model=model,
        temperature=temperature,
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
    if extra_body is not None:
        kwargs["extra_body"] = extra_body

    return ChatOpenAI(**kwargs)


def get_llm(
    model: str | None = None,
    temperature: float | None = None,
) -> ChatOpenAI:
    """Return ChatOpenAI wired to OpenRouter with project settings."""
    s = get_settings()
    return _build_llm(model=model or s.LLM_MODEL, temperature=temperature if temperature is not None else 0.0)


def get_summarizer_llm() -> ChatOpenAI:
    """Return the LLM to use for conversation summarization.

    Uses SUMMARIZER_MODEL when set (cheaper model for summarization tasks).
    Falls back to the main LLM_MODEL when SUMMARIZER_MODEL is empty.
    """
    s = get_settings()
    if s.SUMMARIZER_MODEL:
        return _build_llm(model=s.SUMMARIZER_MODEL)
    return get_llm()

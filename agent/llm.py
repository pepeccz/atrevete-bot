"""ChatOpenAI factory routed through OpenRouter.

Config mapping (shared/config.py field names):
  - api_key        ← settings.OPENROUTER_API_KEY
  - model          ← settings.LLM_MODEL
  - base_url       ← hardcoded OpenRouter endpoint (no OPENROUTER_BASE_URL in config)
  - HTTP-Referer   ← settings.SITE_URL
  - X-Title        ← settings.SITE_NAME
  - temperature    ← caller-supplied or 0.0 (no OPENAI_TEMPERATURE in config)
"""

from langchain_openai import ChatOpenAI

from shared.config import get_settings

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _build_llm(model: str, temperature: float = 0.0) -> ChatOpenAI:
    """Return ChatOpenAI for the given model slug wired to OpenRouter."""
    s = get_settings()
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=s.OPENROUTER_API_KEY,
        base_url=_OPENROUTER_BASE_URL,
        default_headers={
            "HTTP-Referer": s.SITE_URL,
            "X-Title": s.SITE_NAME,
        },
    )


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

"""Unit tests for agent/llm.py — provider routing hint (O1) + retry/timeout policy (U2).

RED phase (O1): these tests fail until _build_llm wires extra_body with the
provider routing hint.

U2: tests assert that _build_llm passes max_retries and timeout (tightened
from implicit SDK defaults: retries 2→3, timeout 600s→60s) sourced from
shared/config.py settings fields LLM_MAX_RETRIES and LLM_REQUEST_TIMEOUT.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_settings(
    provider_order: str = "openai",
    max_retries: int = 3,
    request_timeout: float = 60.0,
):
    s = MagicMock()
    s.OPENROUTER_API_KEY = "sk-or-test"
    s.LLM_MODEL = "openai/gpt-4.1-mini"
    s.SITE_URL = "https://test.example.com"
    s.SITE_NAME = "Test"
    s.LLM_PROVIDER_ORDER = provider_order
    s.LLM_MAX_RETRIES = max_retries
    s.LLM_REQUEST_TIMEOUT = request_timeout
    return s


@patch("agent.llm._traced_client_singleton", return_value=None)
@patch("agent.llm.get_settings")
@patch("agent.llm.ChatOpenAI")
def test_build_llm_includes_provider_routing_hint(mock_chat_openai, mock_settings, _traced):
    """_build_llm passes extra_body with provider order when LLM_PROVIDER_ORDER is set."""
    mock_settings.return_value = _make_settings("openai")

    from agent.llm import _build_llm

    _build_llm("openai/gpt-4.1-mini")

    call_kwargs = mock_chat_openai.call_args.kwargs
    assert "extra_body" in call_kwargs, "_build_llm must pass extra_body to ChatOpenAI"
    provider_block = call_kwargs["extra_body"].get("provider")
    assert provider_block is not None, "extra_body must contain a 'provider' key"
    assert provider_block["order"] == ["openai"], "provider.order must be ['openai']"
    assert provider_block["allow_fallbacks"] is True, "provider.allow_fallbacks must be True"


@patch("agent.llm._traced_client_singleton", return_value=None)
@patch("agent.llm.get_settings")
@patch("agent.llm.ChatOpenAI")
def test_build_llm_omits_extra_body_when_provider_order_empty(
    mock_chat_openai, mock_settings, _traced
):
    """_build_llm must NOT pass extra_body when LLM_PROVIDER_ORDER is empty."""
    mock_settings.return_value = _make_settings("")

    from agent.llm import _build_llm

    _build_llm("openai/gpt-4.1-mini")

    call_kwargs = mock_chat_openai.call_args.kwargs
    assert "extra_body" not in call_kwargs, (
        "extra_body must be omitted when LLM_PROVIDER_ORDER is empty — "
        "sending an empty provider block could cause OpenRouter routing errors"
    )


@patch("agent.llm._traced_client_singleton", return_value=None)
@patch("agent.llm.get_settings")
@patch("agent.llm.ChatOpenAI")
def test_build_llm_multi_provider_order(mock_chat_openai, mock_settings, _traced):
    """_build_llm correctly splits a comma-separated LLM_PROVIDER_ORDER."""
    mock_settings.return_value = _make_settings("openai, anthropic")

    from agent.llm import _build_llm

    _build_llm("openai/gpt-4.1-mini")

    provider_block = mock_chat_openai.call_args.kwargs["extra_body"]["provider"]
    assert provider_block["order"] == ["openai", "anthropic"]


# ---------------------------------------------------------------------------
# U2 — LLM retry/timeout policy
# ---------------------------------------------------------------------------


@patch("agent.llm._traced_client_singleton", return_value=None)
@patch("agent.llm.get_settings")
@patch("agent.llm.ChatOpenAI")
def test_build_llm_passes_max_retries_and_timeout_defaults(
    mock_chat_openai, mock_settings, _traced
):
    """
    U2: _build_llm must pass max_retries=3 and timeout=60.0 to ChatOpenAI
    from settings defaults (LLM_MAX_RETRIES=3, LLM_REQUEST_TIMEOUT=60.0).

    Previous implicit SDK defaults were 2 retries / 600 s timeout.
    This test guards against accidental reversion.
    """
    mock_settings.return_value = _make_settings(max_retries=3, request_timeout=60.0)

    from agent.llm import _build_llm

    _build_llm("openai/gpt-4.1-mini")

    call_kwargs = mock_chat_openai.call_args.kwargs
    assert (
        call_kwargs.get("max_retries") == 3
    ), f"_build_llm must pass max_retries=3; got {call_kwargs.get('max_retries')!r}"
    assert (
        call_kwargs.get("timeout") == 60.0
    ), f"_build_llm must pass timeout=60.0; got {call_kwargs.get('timeout')!r}"


@patch("agent.llm._traced_client_singleton", return_value=None)
@patch("agent.llm.get_settings")
@patch("agent.llm.ChatOpenAI")
def test_build_llm_respects_settings_override_for_retry_and_timeout(
    mock_chat_openai, mock_settings, _traced
):
    """
    U2: _build_llm must source max_retries and timeout from settings, so
    env-var overrides (LLM_MAX_RETRIES=1, LLM_REQUEST_TIMEOUT=30.0) are
    respected without code changes.
    """
    mock_settings.return_value = _make_settings(max_retries=1, request_timeout=30.0)

    from agent.llm import _build_llm

    _build_llm("openai/gpt-4.1-mini")

    call_kwargs = mock_chat_openai.call_args.kwargs
    assert (
        call_kwargs.get("max_retries") == 1
    ), f"Expected max_retries=1 from overridden settings, got {call_kwargs.get('max_retries')!r}"
    assert (
        call_kwargs.get("timeout") == 30.0
    ), f"Expected timeout=30.0 from overridden settings, got {call_kwargs.get('timeout')!r}"

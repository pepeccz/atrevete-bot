"""Unit tests for agent/llm.py — provider routing hint (O1).

RED phase: these tests fail until _build_llm wires extra_body with the
provider routing hint.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_settings(provider_order: str = "openai"):
    s = MagicMock()
    s.OPENROUTER_API_KEY = "sk-or-test"
    s.LLM_MODEL = "openai/gpt-4.1-mini"
    s.SITE_URL = "https://test.example.com"
    s.SITE_NAME = "Test"
    s.LLM_PROVIDER_ORDER = provider_order
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

"""Unit tests for agent/llm.py — LLM resilience layer.

Tests cover:
  - _is_nonrecoverable_llm_error: classification of account/auth failures
  - _is_transient_llm_error: classification of retriable errors
  - ResilientChatOpenAI._agenerate: retry behaviour (transient retry, nonrecoverable
    fail-fast, exhaustion after max attempts)
  - _build_llm extra_body: models-fallback merge, provider key preservation
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(
    provider_order: str = "openai",
    max_retries: int = 3,
    request_timeout: float = 60.0,
    fallback_models: str = "",
    transient_retry_attempts: int = 2,
    transient_retry_base_delay: float = 0.8,
):
    s = MagicMock()
    s.OPENROUTER_API_KEY = "sk-or-test"
    s.LLM_MODEL = "openai/gpt-4.1-mini"
    s.SITE_URL = "https://test.example.com"
    s.SITE_NAME = "Test"
    s.LLM_PROVIDER_ORDER = provider_order
    s.LLM_MAX_RETRIES = max_retries
    s.LLM_REQUEST_TIMEOUT = request_timeout
    s.LLM_FALLBACK_MODELS = fallback_models
    s.LLM_TRANSIENT_RETRY_ATTEMPTS = transient_retry_attempts
    s.LLM_TRANSIENT_RETRY_BASE_DELAY = transient_retry_base_delay
    return s


def _make_chat_result() -> ChatResult:
    """Return a minimal valid ChatResult sentinel."""
    from langchain_core.messages import AIMessage

    return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])


# ---------------------------------------------------------------------------
# _is_nonrecoverable_llm_error
# ---------------------------------------------------------------------------


class TestIsNonrecoverableLlmError:
    def test_quota_exceeded_is_nonrecoverable(self):
        from agent.llm import _is_nonrecoverable_llm_error

        assert _is_nonrecoverable_llm_error(ValueError("exceeded your current quota")) is True

    def test_insufficient_credits_is_nonrecoverable(self):
        from agent.llm import _is_nonrecoverable_llm_error

        assert _is_nonrecoverable_llm_error(ValueError("Insufficient credits")) is True

    def test_invalid_api_key_is_nonrecoverable(self):
        from agent.llm import _is_nonrecoverable_llm_error

        assert _is_nonrecoverable_llm_error(ValueError("Invalid API key provided")) is True

    def test_401_in_message_is_nonrecoverable(self):
        from agent.llm import _is_nonrecoverable_llm_error

        assert _is_nonrecoverable_llm_error(ValueError("HTTP 401 Unauthorized")) is True

    def test_403_in_message_is_nonrecoverable(self):
        from agent.llm import _is_nonrecoverable_llm_error

        assert _is_nonrecoverable_llm_error(ValueError("403 Forbidden")) is True

    def test_rate_limit_is_not_nonrecoverable(self):
        from agent.llm import _is_nonrecoverable_llm_error

        assert _is_nonrecoverable_llm_error(ValueError("rate limit exceeded")) is False

    def test_billing_keyword_is_nonrecoverable(self):
        from agent.llm import _is_nonrecoverable_llm_error

        assert _is_nonrecoverable_llm_error(ValueError("billing issue detected")) is True


# ---------------------------------------------------------------------------
# _is_transient_llm_error
# ---------------------------------------------------------------------------


class TestIsTransientLlmError:
    def test_rate_limit_is_transient(self):
        from agent.llm import _is_transient_llm_error

        assert _is_transient_llm_error(ValueError("rate limit exceeded")) is True

    def test_rate_limit_hyphen_is_transient(self):
        from agent.llm import _is_transient_llm_error

        assert _is_transient_llm_error(ValueError("rate-limit hit")) is True

    def test_503_is_transient(self):
        from agent.llm import _is_transient_llm_error

        assert _is_transient_llm_error(ValueError("503 service unavailable")) is True

    def test_timed_out_is_transient(self):
        from agent.llm import _is_transient_llm_error

        assert _is_transient_llm_error(ValueError("request timed out")) is True

    def test_502_is_transient(self):
        from agent.llm import _is_transient_llm_error

        assert _is_transient_llm_error(ValueError("upstream 502 bad gateway")) is True

    def test_overloaded_is_transient(self):
        from agent.llm import _is_transient_llm_error

        assert _is_transient_llm_error(ValueError("model is overloaded")) is True

    def test_connection_is_transient(self):
        from agent.llm import _is_transient_llm_error

        assert _is_transient_llm_error(ConnectionError("connection reset by peer")) is True

    def test_quota_exceeded_is_not_transient(self):
        """Nonrecoverable errors must NOT be classified as transient."""
        from agent.llm import _is_transient_llm_error

        assert _is_transient_llm_error(ValueError("exceeded your current quota")) is False

    def test_unknown_error_is_not_transient(self):
        from agent.llm import _is_transient_llm_error

        assert _is_transient_llm_error(ValueError("some validation error from pydantic")) is False

    def test_generic_exception_is_not_transient(self):
        from agent.llm import _is_transient_llm_error

        assert _is_transient_llm_error(RuntimeError("unexpected internal error")) is False


# ---------------------------------------------------------------------------
# ResilientChatOpenAI._agenerate retry behaviour
# ---------------------------------------------------------------------------


class TestResilientChatOpenAIAgenerate:
    """Test retry logic by patching ChatOpenAI._agenerate (the super() target)."""

    @pytest.fixture(autouse=True)
    def patch_sleep(self):
        """Prevent actual sleeping in tests."""
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            self.mock_sleep = mock_sleep
            yield mock_sleep

    @pytest.fixture()
    def settings_2_attempts(self):
        return _make_settings(transient_retry_attempts=2, transient_retry_base_delay=0.8)

    @pytest.mark.asyncio
    async def test_retries_transient_twice_then_succeeds(self, settings_2_attempts):
        """Transient error on first two attempts, success on third → returns result."""
        from agent.llm import ResilientChatOpenAI

        sentinel = _make_chat_result()
        call_count = 0

        async def flaky_agenerate(self_inner, messages, stop=None, run_manager=None, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ValueError("rate limit exceeded")
            return sentinel

        with patch("agent.llm.get_settings", return_value=settings_2_attempts):
            with patch.object(ChatOpenAI, "_agenerate", flaky_agenerate):
                llm = ResilientChatOpenAI.__new__(ResilientChatOpenAI)
                result = await llm._agenerate(messages=[])

        assert result is sentinel
        assert call_count == 3  # 2 failures + 1 success
        assert self.mock_sleep.call_count == 2  # slept before attempt 2 and 3

    @pytest.mark.asyncio
    async def test_nonrecoverable_raises_immediately_no_retry(self, settings_2_attempts):
        """Nonrecoverable error → re-raised on first attempt, no retry."""
        from agent.llm import ResilientChatOpenAI

        call_count = 0

        async def quota_error(self_inner, messages, stop=None, run_manager=None, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ValueError("exceeded your current quota")

        with patch("agent.llm.get_settings", return_value=settings_2_attempts):
            with patch.object(ChatOpenAI, "_agenerate", quota_error):
                llm = ResilientChatOpenAI.__new__(ResilientChatOpenAI)
                with pytest.raises(ValueError, match="exceeded your current quota"):
                    await llm._agenerate(messages=[])

        assert call_count == 1  # never retried
        assert self.mock_sleep.call_count == 0

    @pytest.mark.asyncio
    async def test_transient_exhausted_raises_after_max_attempts(self, settings_2_attempts):
        """Transient error every time → raises after LLM_TRANSIENT_RETRY_ATTEMPTS+1 calls."""
        from agent.llm import ResilientChatOpenAI

        call_count = 0

        async def always_fail(self_inner, messages, stop=None, run_manager=None, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ValueError("503 service unavailable")

        with patch("agent.llm.get_settings", return_value=settings_2_attempts):
            with patch.object(ChatOpenAI, "_agenerate", always_fail):
                llm = ResilientChatOpenAI.__new__(ResilientChatOpenAI)
                with pytest.raises(ValueError, match="503 service unavailable"):
                    await llm._agenerate(messages=[])

        # LLM_TRANSIENT_RETRY_ATTEMPTS=2 → 1 initial + 2 retries = 3 total calls
        assert call_count == 3
        assert self.mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_unknown_error_raises_immediately_no_retry(self, settings_2_attempts):
        """Unknown (non-transient, non-nonrecoverable) error → re-raised immediately."""
        from agent.llm import ResilientChatOpenAI

        call_count = 0

        async def unknown_error(self_inner, messages, stop=None, run_manager=None, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("some unexpected internal error")

        with patch("agent.llm.get_settings", return_value=settings_2_attempts):
            with patch.object(ChatOpenAI, "_agenerate", unknown_error):
                llm = ResilientChatOpenAI.__new__(ResilientChatOpenAI)
                with pytest.raises(RuntimeError, match="some unexpected internal error"):
                    await llm._agenerate(messages=[])

        assert call_count == 1
        assert self.mock_sleep.call_count == 0

    @pytest.mark.asyncio
    async def test_zero_extra_attempts_no_retry(self):
        """LLM_TRANSIENT_RETRY_ATTEMPTS=0 → no retry, raise on first transient error."""
        from agent.llm import ResilientChatOpenAI

        settings_0 = _make_settings(transient_retry_attempts=0)
        call_count = 0

        async def transient_error(self_inner, messages, stop=None, run_manager=None, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ValueError("rate limit exceeded")

        with patch("agent.llm.get_settings", return_value=settings_0):
            with patch.object(ChatOpenAI, "_agenerate", transient_error):
                llm = ResilientChatOpenAI.__new__(ResilientChatOpenAI)
                with pytest.raises(ValueError, match="rate limit exceeded"):
                    await llm._agenerate(messages=[])

        assert call_count == 1
        assert self.mock_sleep.call_count == 0


# ---------------------------------------------------------------------------
# _build_llm extra_body: models-fallback merge
# ---------------------------------------------------------------------------


class TestBuildLlmFallbackModels:
    @patch("agent.llm._traced_client_singleton", return_value=None)
    @patch("agent.llm.get_settings")
    @patch("agent.llm.ResilientChatOpenAI")
    def test_fallback_models_adds_models_and_route(self, mock_resilient, mock_settings, _traced):
        """LLM_FALLBACK_MODELS set → extra_body includes models list and route=fallback."""
        mock_settings.return_value = _make_settings(
            provider_order="openai",
            fallback_models="anthropic/claude-3-haiku,mistralai/mistral-7b-instruct",
        )

        from agent.llm import _build_llm

        _build_llm("openai/gpt-4.1-mini")

        call_kwargs = mock_resilient.call_args.kwargs
        extra_body = call_kwargs["extra_body"]

        assert extra_body["models"] == [
            "openai/gpt-4.1-mini",
            "anthropic/claude-3-haiku",
            "mistralai/mistral-7b-instruct",
        ], f"models list must be [primary, *fallbacks], got {extra_body['models']}"
        assert extra_body["route"] == "fallback"

    @patch("agent.llm._traced_client_singleton", return_value=None)
    @patch("agent.llm.get_settings")
    @patch("agent.llm.ResilientChatOpenAI")
    def test_no_fallback_models_omits_models_key(self, mock_resilient, mock_settings, _traced):
        """LLM_FALLBACK_MODELS empty → extra_body must NOT contain 'models' key."""
        mock_settings.return_value = _make_settings(
            provider_order="openai",
            fallback_models="",
        )

        from agent.llm import _build_llm

        _build_llm("openai/gpt-4.1-mini")

        call_kwargs = mock_resilient.call_args.kwargs
        extra_body = call_kwargs.get("extra_body", {})
        assert "models" not in extra_body
        assert "route" not in extra_body

    @patch("agent.llm._traced_client_singleton", return_value=None)
    @patch("agent.llm.get_settings")
    @patch("agent.llm.ResilientChatOpenAI")
    def test_provider_key_preserved_when_fallback_models_set(
        self, mock_resilient, mock_settings, _traced
    ):
        """When both LLM_PROVIDER_ORDER and LLM_FALLBACK_MODELS are set,
        extra_body contains both 'provider' and 'models' keys (neither clobbers the other)."""
        mock_settings.return_value = _make_settings(
            provider_order="openai",
            fallback_models="anthropic/claude-3-haiku",
        )

        from agent.llm import _build_llm

        _build_llm("openai/gpt-4.1-mini")

        call_kwargs = mock_resilient.call_args.kwargs
        extra_body = call_kwargs["extra_body"]

        assert "provider" in extra_body, "provider key must be preserved"
        assert extra_body["provider"]["order"] == ["openai"]
        assert extra_body["provider"]["allow_fallbacks"] is True
        assert "models" in extra_body, "models key must also be present"
        assert extra_body["models"][0] == "openai/gpt-4.1-mini"

    @patch("agent.llm._traced_client_singleton", return_value=None)
    @patch("agent.llm.get_settings")
    @patch("agent.llm.ResilientChatOpenAI")
    def test_no_extra_body_when_both_empty(self, mock_resilient, mock_settings, _traced):
        """When both LLM_PROVIDER_ORDER and LLM_FALLBACK_MODELS are empty,
        extra_body must not be passed at all."""
        mock_settings.return_value = _make_settings(
            provider_order="",
            fallback_models="",
        )

        from agent.llm import _build_llm

        _build_llm("openai/gpt-4.1-mini")

        call_kwargs = mock_resilient.call_args.kwargs
        assert "extra_body" not in call_kwargs

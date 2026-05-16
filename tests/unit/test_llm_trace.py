"""TDD tests for llm-trace-capture feature.

Covers:
  - T-02: TraceContext + ContextVar module (RED → GREEN via T-03)
  - T-04: httpx hooks + _sync_write (RED → GREEN via T-05)
  - T-06: LLMTraceMiddleware (RED → GREEN via T-07)
  - T-08: _build_llm() / get_summarizer_llm() tracing integration (RED → GREEN via T-09)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# T-02: TraceContext + ContextVar module
# ---------------------------------------------------------------------------


def test_contextvar_default_is_none():
    """current_trace_ctx.get() returns None when no context is set."""
    from agent.tracing.context import current_trace_ctx

    assert current_trace_ctx.get() is None


@pytest.mark.asyncio
async def test_contextvar_isolated_across_tasks():
    """Two concurrent asyncio tasks see different TraceContext values (isolation guarantee)."""
    from agent.tracing.context import TraceContext, current_trace_ctx

    results: dict[str, Any] = {}

    async def task_a() -> None:
        ctx = TraceContext(
            conversation_id="conv_a",
            turn_started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        token = current_trace_ctx.set(ctx)
        await asyncio.sleep(0)  # yield control
        results["a"] = current_trace_ctx.get()
        current_trace_ctx.reset(token)

    async def task_b() -> None:
        ctx = TraceContext(
            conversation_id="conv_b",
            turn_started_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        token = current_trace_ctx.set(ctx)
        await asyncio.sleep(0)  # yield control
        results["b"] = current_trace_ctx.get()
        current_trace_ctx.reset(token)

    await asyncio.gather(task_a(), task_b())

    assert results["a"] is not None
    assert results["b"] is not None
    assert results["a"].conversation_id == "conv_a"
    assert results["b"].conversation_id == "conv_b"


def test_safe_conversation_id_replaces_colons():
    """safe_conversation_id('v2:abc') → 'v2__abc'."""
    from agent.tracing.context import safe_conversation_id

    assert safe_conversation_id("v2:abc") == "v2__abc"
    assert safe_conversation_id("plain-id") == "plain-id"
    assert safe_conversation_id("v2:123:extra") == "v2__123__extra"


def test_format_ts_no_colons():
    """format_ts(dt) output contains no ':' characters."""
    from agent.tracing.context import format_ts

    dt = datetime(2026, 5, 16, 14, 32, 1, 123000, tzinfo=timezone.utc)
    result = format_ts(dt)
    assert ":" not in result
    assert "2026" in result
    assert result.endswith("Z")


def test_seq_increments_per_ctx():
    """next(ctx.seq) returns 0, 1, 2 in order on same TraceContext instance."""
    from agent.tracing.context import TraceContext

    ctx = TraceContext(
        conversation_id="test",
        turn_started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert next(ctx.seq) == 0
    assert next(ctx.seq) == 1
    assert next(ctx.seq) == 2


# ---------------------------------------------------------------------------
# T-04: httpx hooks + _sync_write
# ---------------------------------------------------------------------------


def test_sync_write_creates_directory_and_file(tmp_path: Path):
    """_sync_write(path, data) creates parent directories and writes valid JSON."""
    from agent.tracing.httpx_hooks import _sync_write

    target = tmp_path / "a" / "b" / "f.json"
    _sync_write(str(target), {"x": 1, "y": "hello"})

    assert target.exists()
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert parsed == {"x": 1, "y": "hello"}


@pytest.mark.asyncio
async def test_request_hook_noop_when_ctx_none():
    """request_hook with ctx=None writes no file (ContextVar is not set)."""
    from agent.tracing.context import current_trace_ctx
    from agent.tracing.httpx_hooks import request_hook

    # Ensure no context is set
    assert current_trace_ctx.get() is None

    with patch("agent.tracing.httpx_hooks.asyncio") as mock_asyncio:
        req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions",
                            content=b'{"model": "gpt-4"}')
        await request_hook(req)
        # to_thread should NOT have been called
        mock_asyncio.to_thread.assert_not_called()


@pytest.mark.asyncio
async def test_request_hook_writes_req_json(tmp_path: Path):
    """With TraceContext set, request_hook writes *_req.json to correct path."""
    from agent.tracing.context import TraceContext, current_trace_ctx
    from agent.tracing.httpx_hooks import request_hook

    dt = datetime(2026, 5, 16, 14, 32, 1, 123000, tzinfo=timezone.utc)
    ctx = TraceContext(conversation_id="v2:test-123", turn_started_at=dt)
    token = current_trace_ctx.set(ctx)

    body = json.dumps({"model": "openai/gpt-4.1-mini", "messages": []}).encode("utf-8")
    req = httpx.Request(
        "POST",
        "https://openrouter.ai/api/v1/chat/completions",
        content=body,
    )

    written_paths: list[str] = []
    written_data: list[dict] = []

    def fake_sync_write(path: str, data: dict) -> None:
        written_paths.append(path)
        written_data.append(data)

    with patch("agent.tracing.httpx_hooks._sync_write", side_effect=fake_sync_write):
        with patch("agent.tracing.httpx_hooks.settings") as mock_settings:
            mock_settings.LLM_TRACE_DIR = str(tmp_path / "llm_traces")
            await request_hook(req)

    current_trace_ctx.reset(token)

    assert len(written_paths) == 1
    assert "v2__test-123" in written_paths[0]
    assert "_0000_req.json" in written_paths[0]
    assert written_data[0]["model"] == "openai/gpt-4.1-mini"


@pytest.mark.asyncio
async def test_response_hook_pairs_seq_with_request(tmp_path: Path):
    """response_hook reads seq from response.request.extensions and names file _0000_res.json."""
    from agent.tracing.context import TraceContext, current_trace_ctx
    from agent.tracing.httpx_hooks import response_hook

    dt = datetime(2026, 5, 16, 14, 32, 1, 0, tzinfo=timezone.utc)
    ctx = TraceContext(conversation_id="conv-456", turn_started_at=dt)
    token = current_trace_ctx.set(ctx)

    response_body = json.dumps({"choices": [{"message": {"content": "Hello"}}]}).encode("utf-8")

    # Build an httpx.Request and pin _trace_seq = 0 on extensions
    inner_req = httpx.Request(
        "POST",
        "https://openrouter.ai/api/v1/chat/completions",
        content=b"{}",
    )
    inner_req.extensions["_trace_seq"] = 0  # type: ignore[assignment]

    # Build a Response referencing that request
    response = httpx.Response(
        status_code=200,
        content=response_body,
        request=inner_req,
    )

    written_paths: list[str] = []

    def fake_sync_write(path: str, data: dict) -> None:
        written_paths.append(path)

    with patch("agent.tracing.httpx_hooks._sync_write", side_effect=fake_sync_write):
        with patch("agent.tracing.httpx_hooks.settings") as mock_settings:
            mock_settings.LLM_TRACE_DIR = str(tmp_path / "llm_traces")
            await response_hook(response)

    current_trace_ctx.reset(token)

    assert len(written_paths) == 1
    assert "_0000_res.json" in written_paths[0]


@pytest.mark.asyncio
async def test_hook_failure_does_not_raise():
    """When _sync_write raises OSError, hook returns cleanly and WARNING is logged."""
    from agent.tracing.context import TraceContext, current_trace_ctx
    from agent.tracing.httpx_hooks import request_hook

    dt = datetime(2026, 5, 16, 14, 32, 1, 0, tzinfo=timezone.utc)
    ctx = TraceContext(conversation_id="conv-fail", turn_started_at=dt)
    token = current_trace_ctx.set(ctx)

    body = json.dumps({"model": "test"}).encode("utf-8")
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions", content=body)

    with patch("agent.tracing.httpx_hooks._sync_write", side_effect=OSError("disk full")):
        with patch("agent.tracing.httpx_hooks.settings") as mock_settings:
            mock_settings.LLM_TRACE_DIR = "/tmp/llm_traces"
            # Should NOT raise
            await request_hook(req)

    current_trace_ctx.reset(token)


@pytest.mark.asyncio
async def test_unknown_conv_id_fallback(tmp_path: Path):
    """When ContextVar is unset, files are written to _unknown/ and WARNING is logged."""
    from agent.tracing.context import current_trace_ctx
    from agent.tracing.httpx_hooks import request_hook

    assert current_trace_ctx.get() is None  # no context set

    body = json.dumps({"model": "test"}).encode("utf-8")
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions", content=body)

    written_paths: list[str] = []

    def fake_sync_write(path: str, data: dict) -> None:
        written_paths.append(path)

    with patch("agent.tracing.httpx_hooks._sync_write", side_effect=fake_sync_write):
        with patch("agent.tracing.httpx_hooks.settings") as mock_settings:
            mock_settings.LLM_TRACE_DIR = str(tmp_path / "llm_traces")
            mock_settings.LLM_TRACE_ENABLED = True
            await request_hook(req)

    assert len(written_paths) == 1
    assert "_unknown" in written_paths[0]


@pytest.mark.asyncio
async def test_response_double_read_safe():
    """response_hook calling aread() on mocked Response with pre-set _content does not raise."""
    from agent.tracing.context import TraceContext, current_trace_ctx
    from agent.tracing.httpx_hooks import response_hook

    dt = datetime(2026, 5, 16, 14, 32, 1, 0, tzinfo=timezone.utc)
    ctx = TraceContext(conversation_id="conv-double-read", turn_started_at=dt)
    token = current_trace_ctx.set(ctx)

    body = json.dumps({"choices": [{"message": {"content": "test"}}]}).encode("utf-8")
    inner_req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions", content=b"{}")
    inner_req.extensions["_trace_seq"] = 0  # type: ignore[assignment]

    response = httpx.Response(status_code=200, content=body, request=inner_req)

    with patch("agent.tracing.httpx_hooks._sync_write"):
        with patch("agent.tracing.httpx_hooks.settings") as mock_settings:
            mock_settings.LLM_TRACE_DIR = "/tmp/llm_traces"
            # Should not raise
            await response_hook(response)
            # Calling aread() again on same response should still work (body is cached)
            content = await response.aread()
            assert content == body

    current_trace_ctx.reset(token)


# ---------------------------------------------------------------------------
# T-06: LLMTraceMiddleware
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_middleware_sets_contextvar_before_handler():
    """Inside handler, current_trace_ctx.get() is not None and has correct conversation_id."""
    from agent.middleware.llm_trace import LLMTraceMiddleware
    from agent.tracing.context import current_trace_ctx

    captured: dict[str, Any] = {}

    async def fake_handler(request: Any) -> Any:
        ctx = current_trace_ctx.get()
        captured["ctx"] = ctx
        return MagicMock()

    mw = LLMTraceMiddleware()
    request = MagicMock()
    request.state = {"conversation_id": "conv-999"}

    await mw.awrap_model_call(request, fake_handler)

    assert captured["ctx"] is not None
    assert captured["ctx"].conversation_id == "conv-999"


@pytest.mark.asyncio
async def test_middleware_resets_contextvar_after_handler():
    """After awrap_model_call returns, current_trace_ctx.get() is None."""
    from agent.middleware.llm_trace import LLMTraceMiddleware
    from agent.tracing.context import current_trace_ctx

    async def fake_handler(request: Any) -> Any:
        return MagicMock()

    mw = LLMTraceMiddleware()
    request = MagicMock()
    request.state = {"conversation_id": "conv-reset"}

    await mw.awrap_model_call(request, fake_handler)

    assert current_trace_ctx.get() is None


@pytest.mark.asyncio
async def test_middleware_resets_on_exception():
    """Handler raises RuntimeError → middleware re-raises AND resets ContextVar."""
    from agent.middleware.llm_trace import LLMTraceMiddleware
    from agent.tracing.context import current_trace_ctx

    async def failing_handler(request: Any) -> Any:
        raise RuntimeError("boom")

    mw = LLMTraceMiddleware()
    request = MagicMock()
    request.state = {"conversation_id": "conv-exc"}

    with pytest.raises(RuntimeError, match="boom"):
        await mw.awrap_model_call(request, failing_handler)

    # ContextVar MUST be reset even after exception
    assert current_trace_ctx.get() is None


# ---------------------------------------------------------------------------
# T-08: _build_llm() / get_summarizer_llm() tracing integration
# ---------------------------------------------------------------------------


def test_flag_off_returns_none_client():
    """_traced_client_singleton() with LLM_TRACE_ENABLED=False returns None."""
    from agent.tracing.httpx_hooks import _traced_client_singleton

    with patch("agent.tracing.httpx_hooks.settings") as mock_settings:
        mock_settings.LLM_TRACE_ENABLED = False
        result = _traced_client_singleton()
    assert result is None


def test_flag_off_build_llm_no_http_client():
    """_build_llm() with flag off: ChatOpenAI is instantiated without http_async_client or with None."""
    with patch("agent.llm.get_settings") as mock_get_settings:
        mock_s = MagicMock()
        mock_s.OPENROUTER_API_KEY = "sk-test"
        mock_s.SITE_URL = "http://test.com"
        mock_s.SITE_NAME = "Test"
        mock_s.LLM_TRACE_ENABLED = False
        mock_get_settings.return_value = mock_s

        with patch("agent.tracing.httpx_hooks.settings") as mock_trace_settings:
            mock_trace_settings.LLM_TRACE_ENABLED = False

            with patch("agent.llm.ChatOpenAI") as MockChatOpenAI:
                MockChatOpenAI.return_value = MagicMock()
                from agent.llm import _build_llm

                _build_llm(model="openai/gpt-4.1-mini")

                call_kwargs = MockChatOpenAI.call_args[1]
                # http_async_client should be None (or not present) when flag is off
                http_client = call_kwargs.get("http_async_client")
                assert http_client is None


def test_flag_on_build_llm_injects_traced_client():
    """_build_llm() with flag on: ChatOpenAI receives http_async_client=traced_client."""
    import httpx as httpx_module

    fake_client = httpx_module.AsyncClient()

    with patch("agent.llm.get_settings") as mock_get_settings:
        mock_s = MagicMock()
        mock_s.OPENROUTER_API_KEY = "sk-test"
        mock_s.SITE_URL = "http://test.com"
        mock_s.SITE_NAME = "Test"
        mock_s.LLM_TRACE_ENABLED = True
        mock_get_settings.return_value = mock_s

        # Patch _traced_client_singleton where it is imported in agent.llm
        with patch("agent.llm._traced_client_singleton", return_value=fake_client):
            with patch("agent.llm.ChatOpenAI") as MockChatOpenAI:
                MockChatOpenAI.return_value = MagicMock()

                from agent.llm import _build_llm
                _build_llm(model="openai/gpt-4.1-mini")

                assert MockChatOpenAI.call_args is not None
                call_kwargs = MockChatOpenAI.call_args[1]
                http_client = call_kwargs.get("http_async_client")
                assert http_client is fake_client


def test_flag_on_summarizer_llm_injects_traced_client():
    """get_summarizer_llm() with flag on: ChatOpenAI receives http_async_client=traced_client."""
    import httpx as httpx_module

    fake_client = httpx_module.AsyncClient()

    with patch("agent.llm.get_settings") as mock_get_settings:
        mock_s = MagicMock()
        mock_s.OPENROUTER_API_KEY = "sk-test"
        mock_s.SITE_URL = "http://test.com"
        mock_s.SITE_NAME = "Test"
        mock_s.SUMMARIZER_MODEL = "openai/gpt-4.1-nano"
        mock_s.LLM_TRACE_ENABLED = True
        mock_get_settings.return_value = mock_s

        with patch("agent.llm._traced_client_singleton", return_value=fake_client):
            with patch("agent.llm.ChatOpenAI") as MockChatOpenAI:
                MockChatOpenAI.return_value = MagicMock()

                from agent.llm import get_summarizer_llm
                get_summarizer_llm()

                assert MockChatOpenAI.call_args is not None
                call_kwargs = MockChatOpenAI.call_args[1]
                http_client = call_kwargs.get("http_async_client")
                assert http_client is fake_client

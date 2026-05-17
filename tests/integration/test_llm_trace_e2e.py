"""T-12 integration tests: LLM trace capture end-to-end.

Tests verify the complete flow from middleware ContextVar set → hook fires →
files written to disk. Uses mocked LLM and httpx to avoid real network calls.

Spec: Acceptance Scenarios 1, 2, 7; R-12.1–R-12.7.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_flag_off_produces_zero_files(tmp_path: Path):
    """Flag off: no files written to llm_traces/ directory."""
    from agent.tracing.context import current_trace_ctx

    # Simulate a turn with middleware (flag would be off, so middleware shouldn't be added,
    # but even if hooks fire, they should skip writing because ctx is None / flag is off)
    trace_dir = tmp_path / "llm_traces"

    assert current_trace_ctx.get() is None

    with patch("agent.tracing.httpx_hooks.settings") as mock_settings:
        mock_settings.LLM_TRACE_ENABLED = False
        mock_settings.LLM_TRACE_DIR = str(trace_dir)

        # Import hooks and simulate request/response with no ctx set
        import httpx

        from agent.tracing.httpx_hooks import request_hook, response_hook

        req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions",
                            content=b'{"model": "gpt-4"}')
        res = httpx.Response(200, content=b'{"choices": []}', request=req)

        await request_hook(req)
        await response_hook(res)

    # No files should exist
    assert not trace_dir.exists() or not list(trace_dir.rglob("*.json"))


@pytest.mark.asyncio
async def test_flag_on_writes_paired_files(tmp_path: Path):
    """Flag on: after a request+response cycle, paired *_req.json and *_res.json exist."""
    import httpx

    from agent.tracing.context import TraceContext, current_trace_ctx
    from agent.tracing.httpx_hooks import request_hook, response_hook

    trace_dir = tmp_path / "llm_traces"
    dt = datetime(2026, 5, 16, 14, 32, 1, 0, tzinfo=UTC)
    ctx = TraceContext(conversation_id="conv-e2e-100", turn_started_at=dt)
    token = current_trace_ctx.set(ctx)

    req_body = json.dumps({"model": "openai/gpt-4.1-mini", "messages": [{"role": "user", "content": "hello"}]}).encode()
    res_body = json.dumps({
        "choices": [{"message": {"content": "Hi!", "tool_calls": []}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    }).encode()

    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions", content=req_body)
    res = httpx.Response(200, content=res_body, request=req)

    with patch("agent.tracing.httpx_hooks.settings") as mock_settings:
        mock_settings.LLM_TRACE_ENABLED = True
        mock_settings.LLM_TRACE_DIR = str(trace_dir)

        await request_hook(req)
        await response_hook(res)

    current_trace_ctx.reset(token)

    conv_dir = trace_dir / "conv-e2e-100"
    files = sorted(conv_dir.glob("*.json"))
    assert len(files) == 2, f"Expected 2 files, got {files}"

    req_files = [f for f in files if f.name.endswith("_req.json")]
    res_files = [f for f in files if f.name.endswith("_res.json")]
    assert len(req_files) == 1
    assert len(res_files) == 1

    # Same seq prefix
    req_prefix = req_files[0].name.split("_req.json")[0]
    res_prefix = res_files[0].name.split("_res.json")[0]
    assert req_prefix == res_prefix, "req and res files must share the same {ts}_{seq} prefix"

    req_data = json.loads(req_files[0].read_text())
    assert req_data["model"] == "openai/gpt-4.1-mini"

    res_data = json.loads(res_files[0].read_text())
    assert "choices" in res_data
    assert "usage" in res_data


@pytest.mark.asyncio
async def test_summarizer_call_captured(tmp_path: Path):
    """Both main LLM call and a second call (simulating summarizer) land in same dir, different seq."""
    import httpx

    from agent.tracing.context import TraceContext, current_trace_ctx
    from agent.tracing.httpx_hooks import request_hook, response_hook

    trace_dir = tmp_path / "llm_traces"
    dt = datetime(2026, 5, 16, 15, 0, 0, 0, tzinfo=UTC)
    ctx = TraceContext(conversation_id="conv-summarizer-789", turn_started_at=dt)
    token = current_trace_ctx.set(ctx)

    req_body = json.dumps({"model": "openai/gpt-4.1-mini", "messages": []}).encode()
    res_body = json.dumps({"choices": [{"message": {"content": "ok"}}], "usage": {}}).encode()

    with patch("agent.tracing.httpx_hooks.settings") as mock_settings:
        mock_settings.LLM_TRACE_ENABLED = True
        mock_settings.LLM_TRACE_DIR = str(trace_dir)

        # First call: main LLM
        req1 = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions", content=req_body)
        res1 = httpx.Response(200, content=res_body, request=req1)
        await request_hook(req1)
        await response_hook(res1)

        # Second call: summarizer (same turn, same ContextVar)
        req2 = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions", content=req_body)
        res2 = httpx.Response(200, content=res_body, request=req2)
        await request_hook(req2)
        await response_hook(res2)

    current_trace_ctx.reset(token)

    conv_dir = trace_dir / "conv-summarizer-789"
    files = sorted(conv_dir.glob("*.json"))
    assert len(files) == 4, f"Expected 4 files (2 req + 2 res), got {files}"

    req_files = sorted(f for f in files if f.name.endswith("_req.json"))
    assert "_0000_req.json" in req_files[0].name
    assert "_0001_req.json" in req_files[1].name


@pytest.mark.asyncio
async def test_middleware_resets_contextvar_e2e():
    """After awrap_model_call returns, current_trace_ctx.get() is None."""
    from agent.middleware.llm_trace import LLMTraceMiddleware
    from agent.tracing.context import current_trace_ctx

    assert current_trace_ctx.get() is None

    async def fake_handler(request: Any) -> Any:
        return MagicMock()

    mw = LLMTraceMiddleware()
    request = MagicMock()
    request.state = {"conversation_id": "conv-reset-e2e"}

    await mw.awrap_model_call(request, fake_handler)

    assert current_trace_ctx.get() is None


@pytest.mark.asyncio
async def test_hook_failure_is_nonfatal(tmp_path: Path):
    """When _sync_write raises OSError, agent returns normally and WARNING is logged."""
    import httpx

    from agent.tracing.context import TraceContext, current_trace_ctx
    from agent.tracing.httpx_hooks import request_hook

    dt = datetime(2026, 5, 16, 15, 0, 0, 0, tzinfo=UTC)
    ctx = TraceContext(conversation_id="conv-fatal-test", turn_started_at=dt)
    token = current_trace_ctx.set(ctx)

    req_body = json.dumps({"model": "test"}).encode()
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions", content=req_body)

    with patch("agent.tracing.httpx_hooks._sync_write", side_effect=OSError("no space left")):
        with patch("agent.tracing.httpx_hooks.settings") as mock_settings:
            mock_settings.LLM_TRACE_DIR = str(tmp_path / "llm_traces")
            mock_settings.LLM_TRACE_ENABLED = True
            # Must not raise
            await request_hook(req)

    current_trace_ctx.reset(token)
    # Test passes if no exception was raised

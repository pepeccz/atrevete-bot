"""httpx async event hooks for LLM request/response trace capture.

Hooks are registered on a singleton httpx.AsyncClient injected into ChatOpenAI
via the http_async_client= parameter. They read a ContextVar set by
LLMTraceMiddleware and write paired *_req.json / *_res.json files.

Design: ADR-1 (event_hooks), ADR-4 (asyncio.to_thread), ADR-6 (singleton client),
ADR-8 (fail-open hooks).

IMPORTANT: Hooks must NEVER raise. All bodies are wrapped in try/except.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx

from agent.tracing.context import (
    TraceContext,
    current_trace_ctx,
    format_ts,
    safe_conversation_id,
)
from shared.config import get_settings

logger = logging.getLogger(__name__)

# Lazy module-level reference to settings — resolved once on first use.
# Tests can patch `agent.tracing.httpx_hooks.settings` to override.
settings = get_settings()

# Process-singleton traced client — created once, reused across all LLM calls.
_traced_client: httpx.AsyncClient | None = None


def _build_path(ctx: TraceContext, seq: int, kind: str) -> str:
    """Build the full file path for a trace file.

    Format: {LLM_TRACE_DIR}/{safe_conv_id}/{ts}_{seq:04d}_{kind}.json

    Args:
        ctx: The current TraceContext (provides conversation_id and turn_started_at).
        seq: The monotonic sequence number for this HTTP call within the turn.
        kind: Either "req" or "res".

    Returns:
        Absolute or relative path string.
    """
    conv_dir = safe_conversation_id(ctx.conversation_id)
    ts = format_ts(ctx.turn_started_at)
    filename = f"{ts}_{seq:04d}_{kind}.json"
    return str(Path(settings.LLM_TRACE_DIR) / conv_dir / filename)


def _sync_write(path: str, data: dict) -> None:
    """Synchronously write data as pretty-printed JSON to path.

    Creates parent directories as needed. Called via asyncio.to_thread to avoid
    blocking the event loop.

    Args:
        path: File path (may be relative or absolute).
        data: Dict to serialize as JSON.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_or_create_unknown_ctx() -> TraceContext:
    """Return a fallback TraceContext with conversation_id='_unknown'.

    Used when the ContextVar is not set (hook fired outside middleware scope).
    Logs a WARNING per spec R-3.
    """
    from datetime import datetime, timezone

    logger.warning(
        "llm_trace: request/response hook fired with no active TraceContext "
        "(ContextVar unset). Writing to _unknown/. "
        "This happens when LLMTraceMiddleware is not in the middleware stack "
        "or the LLM call happened outside a turn."
    )
    return TraceContext(
        conversation_id="_unknown",
        turn_started_at=datetime.now(tz=timezone.utc),
    )


async def request_hook(request: httpx.Request) -> None:
    """httpx request event hook — captures outbound LLM request body to disk.

    Reads the current ContextVar, pins seq onto request.extensions for pairing
    with the response hook, and writes *_req.json via asyncio.to_thread.

    Fail-open: any exception is caught, WARNING is logged, hook returns cleanly.
    """
    ctx = current_trace_ctx.get()
    use_unknown = ctx is None

    if use_unknown:
        # Only capture if tracing is explicitly enabled (otherwise skip entirely)
        if not settings.LLM_TRACE_ENABLED:
            return
        ctx = _get_or_create_unknown_ctx()

    try:
        payload: dict = {}
        if request.content:
            payload = json.loads(request.content.decode("utf-8"))

        seq = next(ctx.seq)
        # Pin seq onto request so response_hook can retrieve the matching seq
        request.extensions["_trace_seq"] = seq  # type: ignore[index]

        path = _build_path(ctx, seq, kind="req")
        await asyncio.to_thread(_sync_write, path, payload)

    except Exception:
        logger.warning("llm_trace.request_hook: failed to capture request", exc_info=True)


async def response_hook(response: httpx.Response) -> None:
    """httpx response event hook — captures inbound LLM response body to disk.

    Reads ctx from ContextVar, reads seq from response.request.extensions (set by
    request_hook), materialises the response body via aread(), and writes *_res.json.

    Calling aread() is safe: openai re-reads from the cached _content attribute.

    Fail-open: any exception is caught, WARNING is logged, hook returns cleanly.
    """
    ctx = current_trace_ctx.get()
    use_unknown = ctx is None

    if use_unknown:
        if not settings.LLM_TRACE_ENABLED:
            return
        ctx = _get_or_create_unknown_ctx()

    try:
        await response.aread()  # materialise body into response._content (safe re-read)

        payload: dict = {}
        if response.text:
            try:
                payload = json.loads(response.text)
            except json.JSONDecodeError:
                payload = {"_raw": response.text}

        seq = response.request.extensions.get("_trace_seq", 0)  # type: ignore[attr-defined]
        path = _build_path(ctx, seq, kind="res")
        await asyncio.to_thread(_sync_write, path, payload)

    except Exception:
        logger.warning("llm_trace.response_hook: failed to capture response", exc_info=True)


def _traced_client_singleton() -> httpx.AsyncClient | None:
    """Return the process-singleton traced httpx.AsyncClient, or None when disabled.

    Lazy construction on first call when LLM_TRACE_ENABLED=True.
    The client is never explicitly closed — it lives for the process lifetime.

    Design: ADR-6 (singleton client per process).
    """
    global _traced_client

    if not settings.LLM_TRACE_ENABLED:
        return None

    if _traced_client is None:
        _traced_client = httpx.AsyncClient(
            event_hooks={
                "request": [request_hook],
                "response": [response_hook],
            },
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    return _traced_client

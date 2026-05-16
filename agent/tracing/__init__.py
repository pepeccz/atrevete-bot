"""agent.tracing — LLM HTTP-level trace capture package.

Public API:
  - TraceContext: per-turn trace metadata dataclass
  - current_trace_ctx: ContextVar[TraceContext | None]
  - get_traced_client: returns the singleton traced httpx.AsyncClient (or None when disabled)
"""

from agent.tracing.context import TraceContext, current_trace_ctx

__all__ = ["TraceContext", "current_trace_ctx", "get_traced_client"]


def get_traced_client():  # type: ignore[return]
    """Return the process-singleton traced httpx.AsyncClient, or None if tracing is disabled.

    Lazy import to avoid circular imports at package load time.
    """
    from agent.tracing.httpx_hooks import _traced_client_singleton

    return _traced_client_singleton()

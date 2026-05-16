"""LLMTraceMiddleware — sets per-turn TraceContext ContextVar for httpx hook correlation.

Position: FIRST in the middleware list (outermost wrap) so the ContextVar scope
covers ALL middleware including SummarizeMiddleware's internal LLM calls.

Design: ADR-3 (outermost position), ADR-2 (ContextVar over header injection).
Spec: R-5 (adjusted per Design ADR-3 — FIRST, not LAST).

The middleware is conditionally registered in agent_factory.py only when
LLM_TRACE_ENABLED=True. When disabled, zero code runs on the hot path.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import ClassVar

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from agent.tracing.context import TraceContext, current_trace_ctx


class LLMTraceMiddleware(AgentMiddleware):
    """Set per-turn TraceContext on the ContextVar before delegating to the handler.

    The ContextVar is reset in a finally block, ensuring cleanup even when the
    handler raises an exception. This guarantees no ContextVar leak across turns.

    Async-only: the agent runtime dispatches exclusively via ainvoke().
    """

    _allow_single_variant: ClassVar[bool] = True

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Wrap the full turn with a TraceContext ContextVar scope.

        Reads conversation_id from request.state (populated by upstream middleware
        such as CustomerResolveMiddleware). Falls back to "unknown" if not present.
        """
        state = request.state or {}
        conversation_id: str = state.get("conversation_id", "unknown") or "unknown"

        ctx = TraceContext(
            conversation_id=str(conversation_id),
            turn_started_at=datetime.now(tz=UTC),
        )
        token = current_trace_ctx.set(ctx)
        try:
            return await handler(request)
        finally:
            current_trace_ctx.reset(token)

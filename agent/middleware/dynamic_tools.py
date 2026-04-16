"""Filter the bound tool list per model call based on agent state.

Replaces the legacy ``BookingModeNode.get_tools(booking_context)`` +
``_refresh_tools`` machinery used by ``BaseModeNode._run_agentic_loop``. The
filter is parametrised by a callable that inspects state and returns the set
of tool names the model is allowed to use for the next step.

Usage::

    def allowed(state: AgentState) -> set[str]:
        ctx = state.get("booking_context") or {}
        allowed = {"update_booking"}
        if ctx.get("last_services") and ctx.get("last_stylist"):
            allowed.add("check_availability")
        if _booking_complete(ctx):
            allowed.add("book")
        return allowed

    agent = create_agent(
        model=llm,
        tools=[update_booking, check_availability, book],
        middleware=[DynamicToolsMiddleware(allowed)],
    )
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import replace
from typing import Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState, ModelRequest, ModelResponse


class DynamicToolsMiddleware(AgentMiddleware):
    """Restrict the tool list for each model call by consulting a filter callable.

    Args:
        allowed_names: Zero-arg function ``(state) -> Iterable[str]`` returning
            the tool names permitted for the next model step. Tools bound on
            the agent but NOT in the returned set are filtered out of the
            request. If the callable returns an empty iterable, no tools are
            passed — the model is forced to reply with text.
    """

    def __init__(self, allowed_names: Callable[[AgentState], "set[str] | list[str]"]) -> None:
        super().__init__()
        self._allowed_names = allowed_names

    def _apply_filter(self, request: ModelRequest) -> ModelRequest:
        """Return a new ModelRequest with tools filtered to the allowed set."""
        allowed = set(self._allowed_names(request.state))
        filtered = [t for t in request.tools if getattr(t, "name", None) in allowed]
        return replace(request, tools=filtered)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._apply_filter(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._apply_filter(request))


__all__ = ["DynamicToolsMiddleware"]

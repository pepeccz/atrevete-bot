"""Filter the bound tool list per model call via a zero-arg closure over the owning node.

The middleware is initialised with a **zero-arg callable** that returns the list of
tools the current node wants to expose at this exact model call. The middleware then
intersects that list with the tools already bound to the agent, so only tools that are
*both* bound to the agent *and* returned by the closure survive.

Usage::

    class MyModeNode(BaseModeNode):
        def get_tools(self, ctx=None):
            tools = [update_booking]
            if ctx and ctx.get("last_services"):
                tools.append(check_availability)
            return tools

        async def _invoke_create_agent(self, messages, tools, ...):
            middleware = [
                DynamicToolsMiddleware(get_tools_fn=lambda: self.get_tools(self._booking_context)),
                NodeBridgeMiddleware(self),
                ...
            ]
            agent = create_agent(model=self.llm, tools=tools, middleware=middleware)
            ...

The closure reads ``self._booking_context`` (or equivalent) which is set *once per turn*
by ``handle()`` before ``_invoke_create_agent`` is called. Within a single ``ainvoke``
(multi-step reasoning), each model call re-enters ``awrap_model_call`` and the closure
re-reads the live attribute — so mid-loop state mutations (e.g. ``update_booking``
writes a new slot) are visible to the *next* model step without any extra wiring.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.tools import BaseTool


class DynamicToolsMiddleware(AgentMiddleware):
    """Restrict the tool list for each model call via a zero-arg closure over the owning node.

    Args:
        get_tools_fn: Zero-arg callable that returns the list of :class:`BaseTool` instances
            the node wants to expose for the *next* model step. Called on every model call
            so it always reflects the latest node state. Tools not returned by this callable
            are filtered out of ``ModelRequest.tools`` before the LLM sees the request.
            An empty list forces the model to reply with plain text (no tool calls possible).
    """

    def __init__(self, get_tools_fn: Callable[[], list[BaseTool]]) -> None:
        super().__init__()
        self._get_tools_fn = get_tools_fn

    def _apply_filter(self, request: ModelRequest) -> ModelRequest:
        """Return a new ModelRequest with tools filtered to the allowed set."""
        allowed_tools = self._get_tools_fn() or []
        allowed_names = {getattr(t, "name", None) for t in allowed_tools}
        filtered = [t for t in request.tools if getattr(t, "name", None) in allowed_names]
        return request.override(tools=filtered)

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

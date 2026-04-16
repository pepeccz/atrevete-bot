"""Force the model to call a tool when a predicate over state is true.

Replaces the legacy ``BookingModeNode`` behaviour that set ``tool_choice`` on
iteration 0 and cleared it afterwards. Parametrised by a predicate so other
modes can use different policies (e.g. always-required, only-when-no-history).

Usage::

    from langchain_core.messages import HumanMessage
    from agent.middleware.tool_choice import ToolChoiceMiddleware

    def on_first_turn(state) -> bool:
        msgs = state.get("messages") or []
        return bool(msgs) and isinstance(msgs[-1], HumanMessage)

    middleware = [ToolChoiceMiddleware(when=on_first_turn, choice="required")]
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import replace
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState, ModelRequest, ModelResponse


class ToolChoiceMiddleware(AgentMiddleware):
    """Conditionally set ``tool_choice`` on the outgoing model request.

    Args:
        when: Predicate ``(state) -> bool``. When True, the middleware forces
            the configured ``choice``; when False, ``tool_choice`` is cleared
            (``None``) so the model is free to reply with text.
        choice: The ``tool_choice`` value to apply when the predicate matches.
            Defaults to ``"required"`` (call any bound tool). Pass a specific
            tool name or ``"auto"`` / ``"any"`` per provider semantics.
    """

    def __init__(
        self,
        when: Callable[[AgentState], bool],
        choice: Any = "required",
    ) -> None:
        super().__init__()
        self._when = when
        self._choice = choice

    def _apply_choice(self, request: ModelRequest) -> ModelRequest:
        """Return a new ModelRequest with tool_choice applied based on the predicate."""
        tool_choice = self._choice if self._when(request.state) else None
        return replace(request, tool_choice=tool_choice)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._apply_choice(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._apply_choice(request))


__all__ = ["ToolChoiceMiddleware"]

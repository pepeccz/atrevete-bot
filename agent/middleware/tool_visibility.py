"""ToolVisibilityMiddleware — Phase 5.4.

Filters tools visible to the LLM based on the current booking step.

  confirm → [book]
  date, slot → [check_availability]
  all other steps → []

Uses awrap_model_call to replace request.tools before calling handler.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

_STEP_TO_TOOL_NAMES: dict[str | None, set[str]] = {
    "confirm": {"book"},
    "date": {"check_availability"},
    "slot": {"check_availability"},
}


class ToolVisibilityMiddleware(AgentMiddleware):
    """Restricts tool exposure to only tools relevant for the current booking step."""

    def __init__(self, all_tools: list[BaseTool]) -> None:
        self._all_tools_by_name: dict[str, BaseTool] = {t.name: t for t in all_tools}

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        booking = (request.state or {}).get("booking")
        step = booking.get("step") if booking else None

        allowed_names = _STEP_TO_TOOL_NAMES.get(step, set())
        filtered_tools = [t for t in request.tools if getattr(t, "name", None) in allowed_names]

        modified_request = request.override(tools=filtered_tools)
        return await handler(modified_request)

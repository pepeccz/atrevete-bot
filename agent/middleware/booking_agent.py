"""Booking-specific middleware that bridges a ``BookingModeNode`` instance.

``BookingModeNode`` has rich pre/post tool-call logic (context injection, slot
resolution, patch application, completeness gates) that used to run inside
``BaseModeNode._run_agentic_loop``. Rather than duplicate that logic, this
middleware delegates to the node's existing async methods so the class API
(and the extensive test surface) stays intact while the agent loop itself
becomes ``create_agent``.

The middleware expects the wrapping node to expose:

- ``async _pre_tool_call(tool_name, tool_args) -> dict | ToolCallRejection``
- ``async _post_tool_result(tool_name, tool_args, result) -> result``

On a ``ToolCallRejection`` result, the middleware short-circuits the tool
invocation and returns a synthetic ``ToolMessage`` tagged with the rejection's
``error_code`` so ``GateRecoveryMiddleware`` (if present) can count hits.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

if TYPE_CHECKING:
    pass


class BookingAgentMiddleware(AgentMiddleware):
    """Delegate tool-call arg injection and result post-processing to a node.

    Args:
        node: The ``BookingModeNode`` instance whose ``_pre_tool_call`` /
            ``_post_tool_result`` coroutines should run for every tool call.
    """

    def __init__(self, node: Any) -> None:
        super().__init__()
        self._node = node

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage]],
    ) -> ToolMessage:
        from agent.modes.base import ToolCallRejection

        tool_call = request.tool_call
        tool_name = tool_call.get("name", "")
        tool_args = dict(tool_call.get("args") or {})

        pre_result = await self._node._pre_tool_call(tool_name, tool_args)

        if isinstance(pre_result, ToolCallRejection):
            rejection_payload = {
                "rejected": True,
                "error_code": pre_result.error_code,
                "error_message": pre_result.error_message,
            }
            return ToolMessage(
                content=json.dumps(rejection_payload, ensure_ascii=False),
                tool_call_id=tool_call["id"],
                name=tool_name,
                status="error",
            )

        updated_args = pre_result if isinstance(pre_result, dict) else tool_args

        # Build the new tool call payload. Include internal ``_*`` fields
        # because ``update_booking`` expects ``_current_context`` as a tool kwarg.
        from dataclasses import replace

        new_tool_call = {**tool_call, "args": updated_args}
        new_request = replace(request, tool_call=new_tool_call)

        tool_message = await handler(new_request)

        result_payload: Any = tool_message.content
        try:
            parsed = (
                json.loads(result_payload)
                if isinstance(result_payload, str)
                else result_payload
            )
        except (json.JSONDecodeError, ValueError):
            parsed = result_payload

        await self._node._post_tool_result(tool_name, dict(updated_args), parsed)

        return tool_message


__all__ = ["BookingAgentMiddleware"]

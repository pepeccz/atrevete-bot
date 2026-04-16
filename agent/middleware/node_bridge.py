"""Bridge a legacy mode-node class into the ``create_agent`` middleware API.

Modes migrated in M6/M7 still expose async ``_pre_tool_call`` and
``_post_tool_result`` hooks that carry mode-specific logic (context injection,
slot/UUID resolution, patch application). Rather than copy that logic into
middleware classes, this bridge calls the methods back on the node instance
so the loop switches to ``create_agent`` without duplicating domain code.

When ``_pre_tool_call`` returns a ``ToolCallRejection``, the bridge
short-circuits the tool invocation and emits a ``ToolMessage`` tagged with
the rejection's ``error_code`` so ``GateRecoveryMiddleware`` (when present)
can count hits.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage


class NodeBridgeMiddleware(AgentMiddleware):
    """Delegate tool-call arg injection and result post-processing to a node.

    Args:
        node: Any object exposing async ``_pre_tool_call(tool_name, tool_args)``
            and ``_post_tool_result(tool_name, tool_args, result)`` methods.
            Used by both ``BookingModeNode`` (M6) and
            ``AppointmentManagementMode`` (M7).
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


__all__ = ["NodeBridgeMiddleware"]

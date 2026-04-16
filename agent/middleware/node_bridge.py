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

Implementation note (pinned to langchain==1.2.x):
    ``langchain.agents.factory`` composes the middleware's ``wrap_tool_call``
    AND ``awrap_tool_call`` into BOTH the sync and async tool chains
    (``_chain_tool_call_wrappers`` + ``_chain_async_tool_call_wrappers``) as
    soon as EITHER method is overridden. If only the async version is defined
    and the agent is driven by ``ainvoke``, the inner ``ToolNode`` still picks
    up the composed chain but the base-class ``awrap_tool_call`` raises
    ``NotImplementedError("Asynchronous implementation of awrap_tool_call is
    not available")`` — which is exactly the production failure we observed
    for BOOKING mode on WhatsApp. To be invocable from both ``invoke`` AND
    ``ainvoke`` contexts this middleware defines BOTH hooks:

    - ``wrap_tool_call`` (sync) runs the node's async coroutines via
      ``asyncio.new_event_loop().run_until_complete`` (pure sync caller) or
      marshals to the captured running loop when the sync hook is dispatched
      from a worker thread under an active loop.
    - ``awrap_tool_call`` (async) awaits the coroutines directly.

    Keeping both keeps the domain logic (rejection handling, arg patching,
    result parsing) defined exactly once, in ``_process_tool_call``.
"""

from __future__ import annotations

import asyncio
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
        # Capture the running loop at construction time. ``_invoke_create_agent``
        # is an async method being awaited, so we are on the main event loop.
        # Sync ``wrap_tool_call`` may later be dispatched from a worker thread
        # (when the outer caller uses ``ainvoke``) — from that thread we
        # marshal coroutines back to THIS loop via ``run_coroutine_threadsafe``.
        try:
            self._loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            # No loop running — pure sync ``invoke()`` caller (tests, smoke
            # scripts). We will create a fresh loop per coroutine.
            self._loop = None

    def _run_coro_sync(self, coro: Awaitable[Any]) -> Any:
        """Bridge a coroutine from sync context to an awaitable result.

        Used by the sync ``wrap_tool_call`` hook. Priority:
        1. A running loop captured at construction — marshal via
           ``asyncio.run_coroutine_threadsafe``. Thread-safe, blocks the
           worker thread while the main loop advances the coroutine.
        2. No loop captured — run to completion on a fresh loop via
           ``asyncio.run``.
        """
        if self._loop is not None and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return future.result()
        return asyncio.run(coro)

    # ------------------------------------------------------------------
    # Shared domain logic (rejection / arg patching / result parsing).
    # Both wrap_tool_call and awrap_tool_call delegate here so behaviour
    # stays identical between sync and async drivers.
    # ------------------------------------------------------------------

    def _build_rejection_message(
        self,
        tool_call: dict[str, Any],
        tool_name: str,
        rejection: Any,
    ) -> ToolMessage:
        payload = {
            "rejected": True,
            "error_code": rejection.error_code,
            "error_message": rejection.error_message,
        }
        return ToolMessage(
            content=json.dumps(payload, ensure_ascii=False),
            tool_call_id=tool_call["id"],
            name=tool_name,
            status="error",
        )

    def _patch_request(
        self,
        request: ToolCallRequest,
        tool_call: dict[str, Any],
        pre_result: Any,
        tool_args: dict[str, Any],
    ) -> tuple[ToolCallRequest, dict[str, Any]]:
        updated_args = pre_result if isinstance(pre_result, dict) else tool_args
        new_tool_call = {**tool_call, "args": updated_args}
        new_request = replace(request, tool_call=new_tool_call)
        return new_request, dict(updated_args)

    def _parse_result_payload(self, tool_message: ToolMessage) -> Any:
        result_payload: Any = tool_message.content
        try:
            return (
                json.loads(result_payload)
                if isinstance(result_payload, str)
                else result_payload
            )
        except (json.JSONDecodeError, ValueError):
            return result_payload

    # ------------------------------------------------------------------
    # Sync hook — dispatched under ``invoke`` OR from a worker thread
    # when the outer caller is ``ainvoke`` (LangChain 1.2.x composes both
    # sync and async chains, so this hook MUST exist alongside the async
    # one; see module docstring).
    # ------------------------------------------------------------------

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage],
    ) -> ToolMessage:
        from agent.modes.base import ToolCallRejection

        tool_call = request.tool_call
        tool_name = tool_call.get("name", "")
        tool_args = dict(tool_call.get("args") or {})

        pre_result = self._run_coro_sync(
            self._node._pre_tool_call(tool_name, tool_args)
        )

        if isinstance(pre_result, ToolCallRejection):
            return self._build_rejection_message(tool_call, tool_name, pre_result)

        new_request, updated_args = self._patch_request(
            request, tool_call, pre_result, tool_args
        )
        tool_message = handler(new_request)
        parsed = self._parse_result_payload(tool_message)

        self._run_coro_sync(
            self._node._post_tool_result(tool_name, updated_args, parsed)
        )
        return tool_message

    # ------------------------------------------------------------------
    # Async hook — dispatched under ``ainvoke``. Awaits the node coroutines
    # directly; no thread-bridging needed.
    # ------------------------------------------------------------------

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
            return self._build_rejection_message(tool_call, tool_name, pre_result)

        new_request, updated_args = self._patch_request(
            request, tool_call, pre_result, tool_args
        )
        tool_message = await handler(new_request)
        parsed = self._parse_result_payload(tool_message)

        await self._node._post_tool_result(tool_name, updated_args, parsed)
        return tool_message


__all__ = ["NodeBridgeMiddleware"]

"""Short-circuit duplicate tool calls within a single agent run.

Rebuilds the (tool_name, sorted_args) cache from prior ``ToolMessage``s in
message history, so we don't need a custom state field. If the same tool is
invoked with identical args again within the run, the cached result is
returned without re-executing the tool body.

Replaces the ``seen_tool_calls`` guard formerly inside
``BaseModeNode._run_agentic_loop``.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage


def _tool_call_key(tool_call: dict[str, Any]) -> str:
    """Canonical key for a tool call: ``name::sorted(args.items())``."""
    name = tool_call.get("name", "")
    args = tool_call.get("args") or {}
    return f"{name}::{sorted(args.items())}"


class DedupToolCallMiddleware(AgentMiddleware):
    """Cache tool results within a run and short-circuit duplicates.

    Lookup strategy — reconstruct the cache from state on every ``wrap_tool_call``:

    1. Walk ``state['messages']`` looking for prior ``AIMessage.tool_calls``.
    2. Index their IDs to the call payloads.
    3. For each subsequent ``ToolMessage``, look up the originating call by
       ``tool_call_id`` and compute its cache key.
    4. If the current request's key matches a prior ``ToolMessage``, return a
       new ``ToolMessage`` with the same content and the current call's id.

    No state field required — this works as long as the agent keeps prior
    ``ToolMessage`` objects in ``messages`` (``create_agent`` does).
    """

    def _dedup_lookup(self, request: ToolCallRequest) -> ToolMessage | None:
        """Return a cached ToolMessage if an identical call was already executed.

        Reconstructs the (tool_name, sorted_args) cache from prior ToolMessages
        in state['messages'] and returns a new ToolMessage with the current call's
        id on a hit, or None on a miss.
        """
        tool_call = request.tool_call
        key = _tool_call_key(tool_call)

        messages = (request.state or {}).get("messages", []) or []
        origin_by_id: dict[str, dict[str, Any]] = {}

        for msg in messages:
            if isinstance(msg, AIMessage):
                for prev in msg.tool_calls or []:
                    pid = prev.get("id")
                    if pid:
                        origin_by_id[pid] = prev
            elif isinstance(msg, ToolMessage):
                origin = origin_by_id.get(msg.tool_call_id)
                if origin and _tool_call_key(origin) == key:
                    return ToolMessage(
                        content=str(msg.content),
                        tool_call_id=tool_call["id"],
                        name=tool_call.get("name", ""),
                    )

        return None

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage],
    ) -> ToolMessage:
        return self._dedup_lookup(request) or handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage]],
    ) -> ToolMessage:
        return self._dedup_lookup(request) or await handler(request)


__all__ = ["DedupToolCallMiddleware", "_tool_call_key"]

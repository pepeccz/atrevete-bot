"""Abort the agent with a fixed recovery text when N tool rejections accumulate.

Counts ``ToolMessage`` results whose content contains a configurable rejection
marker. Once the count reaches the configured threshold AND the model tries to
call yet another tool, the middleware overwrites the last ``AIMessage`` with
the recovery text (no tool calls) and jumps to the end of the graph via
``jump_to: "end"``.

Replaces the ``ToolCallRejection`` gate-recovery counter that lived inside
``BaseModeNode._run_agentic_loop`` and the ``rejection_counts`` dict it
maintained in-memory.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.runtime import Runtime


class GateRecoveryMiddleware(AgentMiddleware):
    """Abort with ``recovery_text`` once ``threshold`` rejection markers appear.

    Args:
        marker: Substring that identifies a rejection in a ``ToolMessage``'s
            content (e.g. ``"GATE_REJECTED"`` or the service-level error code
            the tool emits). Matched case-sensitively.
        recovery_text: Assistant text returned to the user when the middleware
            fires. Written by overwriting the offending ``AIMessage`` in place
            and setting ``tool_calls=[]``.
        threshold: Number of rejection markers required to trigger the abort.
            Defaults to 2 (matches the legacy ``BaseModeNode`` behaviour —
            one warning to the LLM, then bail).
    """

    def __init__(
        self,
        marker: str,
        recovery_text: str,
        threshold: int = 2,
    ) -> None:
        super().__init__()
        self._marker = marker
        self._recovery_text = recovery_text
        self._threshold = threshold

    def after_model(
        self,
        state: AgentState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        messages = state.get("messages") or []
        if not messages:
            return None
        last = messages[-1]
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return None

        hits = sum(
            1
            for msg in messages
            if isinstance(msg, ToolMessage) and self._marker in str(msg.content)
        )
        if hits < self._threshold:
            return None

        replacement = AIMessage(
            id=last.id,
            content=self._recovery_text,
            tool_calls=[],
        )
        return {"messages": [replacement], "jump_to": "end"}


__all__ = ["GateRecoveryMiddleware"]

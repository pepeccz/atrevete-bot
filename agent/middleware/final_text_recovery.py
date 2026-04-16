"""Inject a fallback assistant message when the loop ends on an empty AIMessage.

If the LLM emits an ``AIMessage`` with tool calls and an empty content string
AND no further handler produces a final response, ``create_agent`` can end the
run with nothing for the user. This middleware replaces such an empty
``AIMessage`` (preserving its id so ``add_messages`` overwrites in place) with
a synthetic assistant reply containing the configured fallback text, clearing
the tool calls so the agent terminates cleanly.

Replaces the ``_post_loop_final_text_recovery`` path formerly at the tail end
of ``BaseModeNode._run_agentic_loop``.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime


class FinalTextRecoveryMiddleware(AgentMiddleware):
    """Overwrite empty-content tool-call-only AIMessages with a fallback reply.

    Args:
        fallback_text: The assistant text to send to the user when the loop
            ends with an empty ``AIMessage``. Typically a safe, short, mode-
            appropriate error string (e.g. ``"Perdoná, tuve un problema
            procesando tu mensaje. ¿Podés repetirlo?"``).
    """

    def __init__(self, fallback_text: str) -> None:
        super().__init__()
        self._fallback = fallback_text

    def after_model(
        self,
        state: AgentState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        messages = state.get("messages") or []
        if not messages:
            return None
        last = messages[-1]
        if not isinstance(last, AIMessage):
            return None
        if not last.tool_calls:
            return None

        content = last.content
        if isinstance(content, str) and content.strip():
            return None
        if isinstance(content, list) and content:
            return None

        replacement = AIMessage(
            id=last.id,
            content=self._fallback,
            tool_calls=[],
        )
        return {"messages": [replacement]}


__all__ = ["FinalTextRecoveryMiddleware"]

"""Inject a fallback assistant message when the agent ENDS on an empty AIMessage.

If the agent loop terminates with an ``AIMessage`` whose content is empty (and
no more tool results will arrive), the user would receive nothing. This
middleware fires at ``after_agent`` time — i.e. once, when the loop exits —
and replaces such a message with a fixed fallback text.

Why ``after_agent`` and NOT ``after_model``: every tool call cycle starts with
an ``AIMessage`` that has tool_calls and empty content (that's how tool
invocations are represented). Running at ``after_model`` therefore fires on
every single tool round and hijacks the very first tool call the LLM attempts,
breaking the entire booking flow. ``after_agent`` only runs when the agent
has decided it's done; at that point an empty AIMessage is a real failure.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime


class FinalTextRecoveryMiddleware(AgentMiddleware):
    """Overwrite an empty terminal ``AIMessage`` with ``fallback_text``.

    Args:
        fallback_text: The assistant text to substitute when the agent loop
            ends with an empty AIMessage. Typically a safe, short, mode-
            appropriate error string.
    """

    def __init__(self, fallback_text: str) -> None:
        super().__init__()
        self._fallback = fallback_text

    def after_agent(
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

        content = last.content
        if isinstance(content, str) and content.strip():
            return None
        if isinstance(content, list) and content:
            # Non-empty rich content — leave alone.
            return None

        # Empty terminal AIMessage: overwrite in place (matching id so the
        # ``add_messages`` reducer treats this as an update, not an append).
        replacement = AIMessage(
            id=last.id,
            content=self._fallback,
            tool_calls=[],
        )
        return {"messages": [replacement]}


__all__ = ["FinalTextRecoveryMiddleware"]

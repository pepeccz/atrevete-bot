"""Token tracking middleware for create_agent-based mode nodes.

This middleware hooks into ``create_agent`` via the ``after_model`` hook and
fires ``agent.services.token_tracking.record_token_usage`` after every model
turn. It is the direct replacement for ``BaseModeNode._track_token_usage``
and is reused by every mode that migrates to ``create_agent``.

Usage::

    from langchain.agents import create_agent
    from agent.middleware.token_tracking import TokenTrackingMiddleware

    agent = create_agent(
        model=llm,
        tools=[],
        system_prompt="...",
        middleware=[TokenTrackingMiddleware(mode_name="GREETING")],
    )

Behaviour:

* Reads ``usage_metadata`` first (LangChain native dict), falls back to
  ``response_metadata.token_usage`` (OpenAI format) for models that only
  populate the raw provider metadata.
* Calls ``record_token_usage`` fire-and-forget — tracking failures never
  propagate into the agent loop.
* ``turn_count`` is derived from the number of messages in state at the
  time ``after_model`` fires (message pairs ≈ turns). Matches the old
  ``BaseModeNode._track_token_usage`` heuristic.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


def _extract_token_counts(message: AIMessage) -> tuple[int, int]:
    """Return ``(input_tokens, output_tokens)`` from a LangChain AIMessage.

    Supports both ``usage_metadata`` (LangChain canonical shape) and
    ``response_metadata.token_usage`` (OpenAI raw shape). Returns ``(0, 0)``
    when neither is populated.
    """
    usage = getattr(message, "usage_metadata", None)
    if isinstance(usage, dict):
        return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)

    resp_meta = getattr(message, "response_metadata", None)
    if isinstance(resp_meta, dict):
        token_usage = resp_meta.get("token_usage") or {}
        if token_usage:
            return (
                int(token_usage.get("prompt_tokens") or 0),
                int(token_usage.get("completion_tokens") or 0),
            )
    return 0, 0


class TokenTrackingMiddleware(AgentMiddleware):
    """Record LLM token usage after every model call.

    Args:
        mode_name: Active mode label (e.g. ``"GREETING"``, ``"BOOKING"``).
            Forwarded to ``record_token_usage`` so budget alerts report the
            mode that triggered them.
    """

    def __init__(self, mode_name: str = "") -> None:
        super().__init__()
        self.mode_name = mode_name

    async def aafter_model(
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

        input_tokens, output_tokens = _extract_token_counts(last)
        if input_tokens <= 0 and output_tokens <= 0:
            return None

        # Approximate turn count from message history length (matches the
        # legacy BaseModeNode._track_token_usage heuristic).
        turn_count = len(messages) // 2

        try:
            from agent.services.token_tracking import record_token_usage

            await record_token_usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                mode_name=self.mode_name,
                turn_count=turn_count,
            )
        except Exception as exc:  # fire-and-forget
            logger.debug("TokenTrackingMiddleware: record_token_usage failed: %s", exc)

        return None

"""SummarizeMiddleware — collapse long conversation histories before model call.

Hook: awrap_model_call
Logic:
  - Gate 1: If len(state.messages) <= window, pass through unchanged.
  - Gate 2: If new messages since last compaction < SUMMARIZE_NEW_MSG_THRESHOLD, skip LLM.
  - Compact: summarize old messages, write cursor = len(compacted) = 1 + keep_tail.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import ClassVar

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AnyMessage, SystemMessage

from agent.llm import get_summarizer_llm
from shared.config import get_settings

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = (
    "Eres un asistente que resume conversaciones en español. "
    "Resume los siguientes mensajes de forma concisa y fiel, "
    "conservando todos los datos importantes (servicios, fechas, nombres). "
    "Responde SOLO con el resumen, sin comentarios adicionales."
)


async def _summarize_messages(messages: list[AnyMessage], llm=None) -> str:
    """Call a one-shot LLM to summarize a list of messages."""
    if llm is None:
        llm = get_summarizer_llm()
    conversation_text = "\n".join(
        f"{getattr(m, 'type', 'unknown').upper()}: {m.content}" for m in messages
    )
    prompt = f"{_SUMMARY_PROMPT}\n\n{conversation_text}"
    response = await llm.ainvoke(prompt)
    return str(response.content)


class SummarizeMiddleware(AgentMiddleware):
    """Collapse old messages into a summary when history grows too long.

    Async-only: the summarizer calls ``llm.ainvoke()`` against the auxiliary
    LLM. A sync variant would require a sync LLM client that the runtime
    never uses. Opt out of the parity guardrail.

    Cursor semantics (post-trim):
        cursor = len(compacted) = 1 + keep_tail
    This is invariant under the add_messages reducer; subsequent appends
    make total - cursor directly measure fresh messages added since last compaction.
    """

    _allow_single_variant: ClassVar[bool] = True

    def __init__(self, window: int = 20, keep_tail: int = 10) -> None:
        self.window = window
        self.keep_tail = keep_tail

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        state = request.state or {}
        messages: list[AnyMessage] = state.get("messages") or []
        total = len(messages)

        # Gate 1: below window — nothing to do
        if total <= self.window:
            return await handler(request)

        # Gate 2: idempotency — skip if not enough new messages since last compaction
        cursor: int | None = state.get("last_summarized_msg_count")
        new_since = total - (cursor or 0)
        settings = get_settings()
        if new_since < settings.SUMMARIZE_NEW_MSG_THRESHOLD:
            return await handler(request)

        # Gate 3: compact
        tail_messages = messages[-self.keep_tail :]
        old_messages = messages[: -self.keep_tail]

        try:
            llm = get_summarizer_llm()
            summary_text = await _summarize_messages(old_messages, llm=llm)
            summary_msg = SystemMessage(content=f"[Resumen previo]: {summary_text}")
            compacted = [summary_msg] + tail_messages

            # Cursor stored as post-trim length (invariant under add_messages reducer)
            new_cursor = len(compacted)  # = 1 + keep_tail
            new_state = {
                **state,
                "messages": compacted,
                "conversation_summary": summary_text,
                "last_summarized_msg_count": new_cursor,
            }
            modified_request = request.override(state=new_state)
            return await handler(modified_request)

        except Exception as exc:
            logger.warning("SummarizeMiddleware failed, passing original state: %s", exc)
            return await handler(request)

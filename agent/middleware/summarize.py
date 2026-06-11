"""SummarizeMiddleware — collapse long conversation histories before model call.

Hook: awrap_model_call
Logic:
  - Gate 1: If len(state.messages) <= window, pass through unchanged.
  - Gate 2: If new messages since last compaction < SUMMARIZE_NEW_MSG_THRESHOLD,
            rebuild the LLM context window from the persisted summary (LLM-free).
  - Gate 3: Compact: summarize old messages, persist cursor + summary to checkpoint.

Cursor semantics (ADR-2):
    last_summarized_msg_count = count of raw messages folded into the summary
                               = total − keep_tail  (at compaction time)
    total_at_last_compaction  = cursor + keep_tail

Gate 2 idempotency formula:
    new_since = total − (cursor + keep_tail)
             = total − total_at_last_compaction
             = messages added to checkpoint AFTER the last compaction

This correctly measures only truly new messages (turns since last summary), not
the keep_tail messages that were retained but already included in the summary context.
When new_since < threshold, Gate 2 fires and no new summarizer LLM call is needed.

The old cursor definition (len(compacted) = 1 + keep_tail) was wrong for two reasons:
1. It counted the post-trim compacted list length, not the raw messages absorbed.
2. The old formula `new_since = total − cursor` overcounts by keep_tail, causing
   redundant compaction on every turn (bug #4) even when only a few new messages arrived.

ADR-2 fix: cursor = total − keep_tail. Gate 2 check: new_since = total − (cursor + keep_tail).
When new_since < threshold, overlay is rebuilt LLM-free from the persisted summary.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import ClassVar

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AnyMessage, SystemMessage

from agent.llm import get_summarizer_llm
from agent.middleware._persistence import persist_to_checkpoint
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

    Cursor semantics (ADR-2, post-fix):
        last_summarized_msg_count = total − keep_tail  (at compaction time)
        total_at_last_compaction  = cursor + keep_tail

    Gate 2 new_since formula: total − (cursor + keep_tail).
    This measures only messages added after the last compaction (truly new turns),
    not the keep_tail messages already included in the summary context.
    When new_since < SUMMARIZE_NEW_MSG_THRESHOLD, overlay is rebuilt LLM-free.
    This fixes bug #4 (redundant compaction every turn when cursor was overlay-only).
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

        # Gate 2: idempotency — cursor set + few new messages since last compaction.
        # Rebuild the LLM context window LLM-free from the persisted summary.
        # ADR-2: new_since = total - cursor measures raw messages added since compaction.
        cursor: int | None = state.get("last_summarized_msg_count")
        settings = get_settings()

        if cursor is not None:
            # ADR-2: cursor = total - keep_tail at compaction time, so (cursor + keep_tail)
            # equals the checkpoint total at last summarization. new_since measures only
            # messages added AFTER that point — i.e. truly new turns since last summary.
            new_since = total - (cursor + self.keep_tail)
            if new_since < settings.SUMMARIZE_NEW_MSG_THRESHOLD:
                # Rebuild overlay from persisted summary, no new summarizer LLM call.
                # ADR-2: Gate 2 = request.override ONLY — no persist. Cursor stays stable
                # so new_since accumulates across turns and Gate 3 re-fires every ~threshold
                # new messages. Persisting here would freeze new_since at 0 forever and
                # cause summarizer starvation (verified: 26/51 messages lost in 15-turn repro).
                prev_summary = state.get("conversation_summary") or ""
                summary_msg = SystemMessage(content=f"[Resumen previo]: {prev_summary}")
                overlay_messages = [summary_msg] + messages[cursor:]
                new_state = {**state, "messages": overlay_messages}
                return await handler(request.override(state=new_state))

        # Gate 3: compact — summarize old messages, persist cursor + summary
        tail_messages = messages[-self.keep_tail :]
        old_messages = messages[: -self.keep_tail]

        try:
            llm = get_summarizer_llm()
            summary_text = await _summarize_messages(old_messages, llm=llm)
            summary_msg = SystemMessage(content=f"[Resumen previo]: {summary_text}")
            compacted = [summary_msg] + tail_messages

            # ADR-2: cursor = total - keep_tail (count of raw messages folded into summary)
            # This ensures Gate 2 fires correctly on subsequent turns when new_since
            # (= total_checkpoint - cursor) remains below the threshold.
            new_cursor = total - self.keep_tail
            new_state = {
                **state,
                "messages": compacted,
                "conversation_summary": summary_text,
                "last_summarized_msg_count": new_cursor,
            }
            modified_request = request.override(state=new_state)
            response = await handler(modified_request)

            # Persist scalar fields to LangGraph checkpoint via Command(update=...).
            # REQ-S1-6: last_summarized_msg_count and conversation_summary MUST reach
            # the checkpoint so Gate 2 can read them on the next turn. Without this,
            # cursor is only in the per-turn overlay and evaporates after the turn —
            # causing redundant compaction on every turn (bug #4).
            # REQ-S1-7: "messages" is intentionally excluded — see _persistence.py guard.
            return persist_to_checkpoint(
                response,
                {
                    "conversation_summary": summary_text,
                    "last_summarized_msg_count": new_cursor,
                },
            )

        except Exception:
            # fail-open: summarizer LLM unavailable → pass original request through.
            # REQ-S2-6: upgrade from warning to error with exc_info=True.
            conversation_id = state.get("conversation_id", "unknown")
            logger.error(
                "fail-open: summarize.compact failed (conversation_id=%s) — "
                "passing original state through",
                conversation_id,
                exc_info=True,
            )
            return await handler(request)

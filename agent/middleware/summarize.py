"""SummarizeMiddleware — collapse long conversation histories before model call.

Hook: awrap_model_call
Logic:
  - If len(state.messages) > window (default 20):
      1. Take messages[:-keep_tail] (the "old" chunk).
      2. Call an auxiliary LLM to summarize them in Spanish.
      3. Replace old chunk with a single SystemMessage("[Resumen previo]: …").
      4. Pass keep_tail recent messages verbatim.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import ClassVar

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AnyMessage, SystemMessage

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = (
    "Eres un asistente que resume conversaciones en español. "
    "Resume los siguientes mensajes de forma concisa y fiel, "
    "conservando todos los datos importantes (servicios, fechas, nombres). "
    "Responde SOLO con el resumen, sin comentarios adicionales."
)


async def _summarize_messages(messages: list[AnyMessage]) -> str:
    """Call a one-shot LLM to summarize a list of messages."""
    from agent.llm import get_llm

    llm = get_llm()
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

        if len(messages) <= self.window:
            return await handler(request)

        # Split: old messages to summarize + recent tail to keep
        tail_messages = messages[-self.keep_tail :]
        old_messages = messages[: -self.keep_tail]

        try:
            summary_text = await _summarize_messages(old_messages)
            summary_msg = SystemMessage(content=f"[Resumen previo]: {summary_text}")
            compacted = [summary_msg] + tail_messages

            new_state = {**state, "messages": compacted}
            modified_request = request.override(state=new_state)
            return await handler(modified_request)

        except Exception as exc:
            logger.warning("SummarizeMiddleware failed, passing original state: %s", exc)
            return await handler(request)

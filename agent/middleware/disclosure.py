"""DisclosureMiddleware — prepend EU AI Act disclosure on the first assistant turn.

Condition: no AIMessage with non-empty text content exists in state["messages"]
before the handler runs (first turn of the conversation, including tool-loop passes
on that turn).
Action: prepend DISCLOSURE_TEXT to the first AIMessage in the response that has
non-empty content.

Hook: awrap_model_call — intercepts after model produces response.

Design: ADR-1 (booking-disambiguation-hardening).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import ClassVar

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage

DISCLOSURE_TEXT = "¡Hola! Soy Maite, asistenta virtual con IA de Atrévete 🌸"


def _has_textual_ai_message(msgs: list) -> bool:
    """Return True if any AIMessage in msgs has non-empty stripped content.

    Tool-call-only AIMessages (empty or whitespace content) are NOT counted.
    This predicate is the canonical "assistant has already spoken" signal.
    """
    return any(isinstance(m, AIMessage) and (m.content or "").strip() for m in msgs)


class DisclosureMiddleware(AgentMiddleware):
    """Prepend EU AI Act disclosure text on the first turn only.

    Async-only: the agent runtime invokes this middleware exclusively via
    ``ainvoke()``. Implementing a sync ``wrap_model_call`` variant would be
    dead code (no sync dispatch path exists in production). Opt out of the
    parity guardrail via ``_allow_single_variant``.
    """

    _allow_single_variant: ClassVar[bool] = True

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        # Snapshot BEFORE handler runs — this is the canonical prior-messages view.
        prior_messages = list((request.state or {}).get("messages", []))
        is_first_turn = not _has_textual_ai_message(prior_messages)

        response: ModelResponse = await handler(request)

        if not is_first_turn:
            return response

        # Prepend disclosure to the first AIMessage in result that has non-empty content.
        new_result = []
        prepended = False
        for msg in response.result:
            if not prepended and isinstance(msg, AIMessage) and (msg.content or "").strip():
                new_content = DISCLOSURE_TEXT + "\n\n" + msg.content
                new_result.append(AIMessage(content=new_content))
                prepended = True
            else:
                new_result.append(msg)

        # If no textual AIMessage was found in result, return as-is (tool-loop pass).
        return ModelResponse(result=new_result)

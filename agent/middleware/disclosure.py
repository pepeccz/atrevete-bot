"""DisclosureMiddleware — prepend EU AI Act disclosure on the first assistant turn.

Condition: state["messages"] is empty (first turn of the conversation).
Action: prepend DISCLOSURE_TEXT to the AIMessage content returned by the model.

Hook: awrap_model_call — intercepts after model produces response.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage

DISCLOSURE_TEXT = (
    "Soy Maite, un asistente de inteligencia artificial de Atrévete. "
    "Puedo ayudarte a reservar citas y responder tus preguntas, pero soy una IA, no una persona. "
    "En cualquier momento puedes pedir hablar con alguien del equipo. 💕"
)


class DisclosureMiddleware(AgentMiddleware):
    """Prepend EU AI Act disclosure text on the first turn only."""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        response: ModelResponse = await handler(request)

        # First turn: state has no prior messages (only the incoming human message
        # is already in request.messages, but state["messages"] reflects history).
        messages = (request.state or {}).get("messages", [])
        is_first_turn = len(messages) == 0

        if not is_first_turn:
            return response

        # Prepend disclosure to the first AIMessage in result
        new_result = []
        prepended = False
        for msg in response.result:
            if not prepended and isinstance(msg, AIMessage):
                new_content = DISCLOSURE_TEXT + "\n\n" + msg.content
                new_result.append(AIMessage(content=new_content))
                prepended = True
            else:
                new_result.append(msg)

        if not prepended and response.result:
            # No AIMessage found — prepend disclosure as a standalone AIMessage
            new_result = [AIMessage(content=DISCLOSURE_TEXT)] + list(response.result)

        return ModelResponse(result=new_result)

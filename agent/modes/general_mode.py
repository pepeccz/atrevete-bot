"""
General Mode — v6.0 Mode-Based Architecture.

Handles informational queries: FAQs, service information, salon hours, policies.
Uses only read-only tools (query_info, search_services) — no booking risk.

This is the default mode after GREETING completes and whenever the user asks
an informational question during an active BOOKING flow.
"""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.modes.base import BaseModeNode
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)

_GENERAL_SYSTEM = """Eres Maite, asistenta virtual de Atrévete Peluquería en Alcobendas.

Tu misión: responder preguntas sobre servicios, horarios, precios y políticas del salón de forma concisa y amigable.

Reglas:
- Responde en 2-4 frases máximo (a menos que sea una lista de servicios).
- Sé cálida y usa emojis ocasionalmente (no en exceso).
- Si el cliente quiere reservar una cita, anímale a hacerlo pero NO reserves en este modo.
- Para información de servicios, usa la herramienta query_info.
- Para buscar servicios específicos, usa search_services.

Idioma: español (tutear al cliente, estilo Rioplatense si el cliente lo usa)."""


class GeneralMode(BaseModeNode):
    """
    Mode node for informational queries (FAQs, services, hours, policies).

    Uses query_info and search_services tools — read-only, no booking mutations.
    Always stays in GENERAL mode (mode transitions are handled by router_node).
    """

    @property
    def mode_name(self) -> str:
        return "GENERAL"

    async def handle(self, state: ConversationState, intent: object) -> dict:
        """
        Handle an informational query using read-only tools.

        Args:
            state: Current conversation state
            intent: IntentResult from router (not used directly — LLM decides tools)

        Returns:
            Partial state update dict with assistant response appended
        """
        from agent.tools.info_tools import query_info
        from agent.tools.search_services import search_services

        customer_name = state.get("customer_name", "")
        messages_history = state.get("messages", [])

        # Build system message with optional customer context
        system_content = _GENERAL_SYSTEM
        if customer_name:
            system_content += f"\n\nEl cliente se llama {customer_name}."
        if state.get("conversation_summary"):
            system_content += f"\n\nContexto previo de la conversación:\n{state['conversation_summary']}"

        # Build LangChain message list from recent history (last 8 messages)
        langchain_messages: list = [SystemMessage(content=system_content)]
        for msg in messages_history[-8:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                langchain_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                langchain_messages.append(AIMessage(content=content))

        # Run agentic loop with read-only tools
        result = await self._run_agentic_loop(
            langchain_messages,
            tools=[query_info, search_services],
        )

        self.logger.info(
            "GeneralMode.handle | conversation=%s | has_error=%s",
            state.get("conversation_id", "unknown"),
            bool(result.error),
        )

        return {
            **add_message(state, "assistant", result.response_text),
            "last_node": "general",
            "user_message": None,
        }

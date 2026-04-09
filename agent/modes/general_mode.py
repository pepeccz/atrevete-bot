"""
General Mode — v6.0 Mode-Based Architecture.

Handles informational queries: FAQs, service information, salon hours, policies.
Routes to BOOKING for service requests. Uses escalate as the only tool.

This is the default mode after GREETING completes and whenever the user asks
an informational question during an active BOOKING flow.
"""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.modes.base import BaseModeNode
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)


class GeneralMode(BaseModeNode):
    """
    Mode node for informational queries (FAQs, services, hours, policies).

    Responds directly from LLM knowledge + system prompt — no data tools.
    Routes the user to BOOKING mode for service/appointment requests.
    Escalation is handled via the ESCALATION mode transition.
    """

    @property
    def mode_name(self) -> str:
        return "GENERAL"

    def get_tools(self):
        return []

    async def handle(self, state: ConversationState, intent: object) -> dict:
        """
        Handle an informational query.

        Args:
            state: Current conversation state
            intent: IntentResult from router (not used directly — LLM decides tools)

        Returns:
            Partial state update dict with assistant response appended
        """
        mode_context = state.get("mode_context") or {}

        langchain_messages: list[SystemMessage | HumanMessage | AIMessage]

        if self._use_optimized_prompts():
            langchain_messages = list(
                await self._build_layered_messages(
                    state,
                    mode_context,
                    step_name="general_query",
                    include_history=True,
                    history_limit=8,
                )
            )
        else:
            messages_history = state.get("messages", [])

            system_content = (
                "Eres Maite, asistenta virtual de Atrévete Peluquería en Alcobendas. "
                "Respondé dudas sobre servicios, horarios, precios y políticas del salón "
                "de forma breve, cálida y útil."
            )
            conversation_summary = state.get("conversation_summary")
            if conversation_summary:
                system_content += f"\n\nContexto previo de la conversación:\n{conversation_summary}"

            langchain_messages = [SystemMessage(content=system_content)]
            for msg in messages_history[-8:]:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    langchain_messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    langchain_messages.append(AIMessage(content=content))

        # Run agentic loop with escalation tool only
        result = await self._run_agentic_loop(
            langchain_messages,
            tools=self.get_tools(),
        )

        self.logger.info(
            "GeneralMode.handle | conversation=%s | has_error=%s",
            state.get("conversation_id", "unknown"),
            bool(result.error),
        )

        final_response, disclosure_sent = self._maybe_prepend_intro(
            result.response_text,
            state,
        )

        updates = {
            **add_message(state, "assistant", final_response),
            "mode_context": mode_context,
            "last_node": "general",
            "user_message": None,
        }
        if disclosure_sent:
            updates["ai_disclosure_sent"] = True
        return updates

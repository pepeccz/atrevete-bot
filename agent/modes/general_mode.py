"""
General Mode — v6.0 Mode-Based Architecture.

Handles informational queries: FAQs, service information, salon hours, policies.
Uses only read-only tools (query_info, search_services) — no booking risk.

This is the default mode after GREETING completes and whenever the user asks
an informational question during an active BOOKING flow.
"""

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.modes.base import BaseModeNode
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)


class GeneralMode(BaseModeNode):
    """
    Mode node for informational queries (FAQs, services, hours, policies).

    Uses query_info and search_services tools — read-only, no booking mutations.
    Always stays in GENERAL mode (mode transitions are handled by router_node).
    """

    @property
    def mode_name(self) -> str:
        return "GENERAL"

    @staticmethod
    def _extract_booking_handoff(tool_results: dict[str, Any]) -> dict[str, Any] | None:
        raw = tool_results.get("search_services")
        # Normalize: _run_agentic_loop stores results as lists (one entry per call)
        if isinstance(raw, list):
            if not raw:
                return None
            envelope = raw[-1]  # take the most recent call result
        elif isinstance(raw, dict):
            envelope = raw  # legacy/test shape
        else:
            return None

        if not isinstance(envelope, dict):
            return None

        if isinstance(envelope.get("resolved_service"), dict):
            return {"resolved_service": dict(envelope["resolved_service"])}

        if isinstance(envelope.get("clarification_needed"), dict):
            clarification = envelope["clarification_needed"]
            return {
                "pending_clarifications": [
                    {
                        "axis": clarification.get("axis", ""),
                        "question_hint": clarification.get("question_hint", ""),
                        "options": clarification.get("options", []),
                    }
                ]
            }

        services = envelope.get("services")
        if isinstance(services, list):
            return {
                "candidate_services": [service for service in services if isinstance(service, dict)]
            }

        return None

    async def handle(self, state: ConversationState, intent: object) -> dict:
        """
        Handle an informational query using read-only tools.

        Args:
            state: Current conversation state
            intent: IntentResult from router (not used directly — LLM decides tools)

        Returns:
            Partial state update dict with assistant response appended
        """
        from agent.tools.escalation_tools import escalate_to_human
        from agent.tools.info_tools import query_info
        from agent.tools.search_services import search_services

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

        # Run agentic loop with read-only tools + escalation
        result = await self._run_agentic_loop(
            langchain_messages,
            tools=[query_info, search_services, escalate_to_human],
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
            "mode_context": {
                **mode_context,
                "general_booking_handoff": self._extract_booking_handoff(result.tool_results),
            },
            "last_node": "general",
            "user_message": None,
        }
        if disclosure_sent:
            updates["ai_disclosure_sent"] = True
        # Propagate escalation if escalate_to_human was called
        if result.tool_results.get("escalate_to_human"):
            updates["escalation_triggered"] = True

        return updates

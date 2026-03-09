"""
GeneralMode — Handles FAQs, service info, hours, and all non-booking queries (v6.0).

This mode is the default "conversational" mode for the bot. When a customer is
not actively booking an appointment, GeneralMode handles all informational queries:
- Service catalog questions
- Business hours
- Location / address
- General FAQs
- Appointment cancellations (existing ones, not booking new ones)

Tools available:
- query_info: Services list, FAQs, hours, location
- search_services: Fuzzy search for specific services

Mode transitions:
- intent="book" → BOOKING mode
- intent="escalate" → ESCALATION mode
- Everything else → Stay in GENERAL (LLM responds with tools)

Architecture note:
    GeneralMode uses the LLM with tool-binding (agent loop). The LLM can call
    query_info / search_services as needed to answer the question, then produce
    a final text response. This is similar to the old NonBookingHandler but
    cleaner and scoped only to this mode's tools.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from agent.modes.base import BaseModeNode
from agent.routing.intent_router import IntentResult
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState, transition_mode
from agent.tools.info_tools import query_info, list_stylists
from agent.tools.search_services import search_services

logger = logging.getLogger(__name__)


# ============================================================================
# System prompt for GENERAL mode
# ============================================================================

_GENERAL_SYSTEM_PROMPT = """Eres Maite, asistenta virtual de Atrévete Peluquería en Alcobendas.

## Reglas críticas
1. **NO narres acciones**: Llama herramientas silenciosamente, luego responde con los datos.
2. **Usa herramientas SIEMPRE** antes de responder sobre servicios, horarios, o ubicación.
3. Si el cliente pregunta por servicios específicos → usa `search_services`
4. Si el cliente pide ver todos los servicios o categorías → usa `query_info(type="services")`
5. Si pregunta horarios → usa `query_info(type="hours")`
6. Si pregunta ubicación → usa `query_info(type="location")`
7. Si pregunta FAQs generales → usa `query_info(type="faqs")`
8. Mensajes concisos: 2-4 frases, máximo 150 palabras.
9. Español natural y conversacional, tono cálido (tú), emojis: 1-2 máximo.

## Formato WhatsApp
- *Negrita*: `*texto*`
- Listas informativas: guiones (-)
- Listas de opciones: números (1., 2., 3.)

## Cuándo NO usar herramientas
- Saludos simples → responde directamente sin herramienta
- Confirmaciones de conversación → responde directamente

Responde SOLO al último mensaje del usuario. No repitas información ya dada."""


# Maximum tool call iterations to prevent infinite loops
_MAX_TOOL_ITERATIONS = 5


class GeneralMode(BaseModeNode):
    """
    Mode node for the GENERAL conversation phase.

    Handles all informational queries via LLM + tool binding (agentic loop).
    Transitions to BOOKING or ESCALATION when appropriate intent is detected.

    Tools: query_info, search_services, list_stylists
    """

    @property
    def mode_name(self) -> str:
        return "GENERAL"

    async def handle(
        self,
        state: ConversationState,
        intent: IntentResult,
    ) -> dict:
        """
        Process a turn in GENERAL mode.

        1. Check intent — if "book" → transition to BOOKING
        2. Check intent — if "escalate" → transition to ESCALATION
        3. Otherwise → LLM agentic loop with tools to answer the question

        Args:
            state: Current ConversationState (read-only).
            intent: Classified intent from IntentRouter.

        Returns:
            Partial state update dict for LangGraph reducers.
        """
        conversation_id = state.get("conversation_id", "unknown")
        customer_name = state.get("customer_name")

        logger.info(
            "GeneralMode.handle | conversation_id=%s | intent=%s | confidence=%.2f",
            conversation_id,
            intent.intent,
            intent.confidence,
        )

        # ── Mode transition: book ──────────────────────────────────────────────
        if intent.intent == "book":
            logger.info(
                "GeneralMode: booking intent detected, transitioning to BOOKING | "
                "conversation_id=%s",
                conversation_id,
            )
            transition = transition_mode(state, "BOOKING")
            # Don't add a message — the BOOKING mode will handle its first turn
            return transition

        # ── Mode transition: escalate ──────────────────────────────────────────
        if intent.intent == "escalate":
            logger.info(
                "GeneralMode: escalate intent detected, transitioning to ESCALATION | "
                "conversation_id=%s",
                conversation_id,
            )
            transition = transition_mode(state, "ESCALATION")
            return transition

        # ── Default: LLM agentic loop with tools ───────────────────────────────
        tools = [query_info, search_services, list_stylists]
        response_text = await self._run_agentic_loop(state, tools, customer_name)

        if not response_text:
            response_text = (
                "Lo siento, tuve un problema procesando tu consulta. "
                "¿Puedo ayudarte con algo más? 💕"
            )

        return add_message(state, "assistant", response_text)

    async def _run_agentic_loop(
        self,
        state: ConversationState,
        tools: list,
        customer_name: str | None,
    ) -> str:
        """
        Run an LLM + tool loop until a final text response is produced.

        The loop:
        1. Build messages from state + system prompt
        2. Call LLM with tool binding
        3. If LLM returns tool calls → execute tools → feed results back → repeat
        4. If LLM returns plain text → return it as final response
        5. If max iterations exceeded → return generic fallback

        Args:
            state: Current conversation state.
            tools: List of LangChain tools to bind.
            customer_name: Customer's name for personalization.

        Returns:
            Final assistant response text.
        """
        conversation_id = state.get("conversation_id", "unknown")

        # Build the tool name → callable mapping
        tool_map: dict[str, Any] = {t.name: t for t in tools}

        # Prepare system prompt (personalized if name known)
        system_prompt = _GENERAL_SYSTEM_PROMPT
        if customer_name:
            system_prompt = (
                f"El nombre del cliente es: {customer_name}\n\n" + system_prompt
            )

        # Build initial LangChain messages from state
        lc_messages = self._build_messages(state, system_prompt)

        for iteration in range(_MAX_TOOL_ITERATIONS):
            # Call LLM (with tool binding)
            llm_result = await self._call_llm(lc_messages, tools=tools)

            if llm_result is None:
                logger.error(
                    "GeneralMode._run_agentic_loop: LLM returned None | "
                    "conversation_id=%s | iteration=%d",
                    conversation_id,
                    iteration,
                )
                return ""

            # Check if LLM wants to call tools
            tool_calls = getattr(llm_result, "tool_calls", None) or []

            if not tool_calls:
                # LLM produced a final text response
                response = (
                    llm_result.content
                    if hasattr(llm_result, "content")
                    else str(llm_result)
                )
                logger.info(
                    "GeneralMode._run_agentic_loop: final response | "
                    "conversation_id=%s | iterations=%d | length=%d",
                    conversation_id,
                    iteration + 1,
                    len(response),
                )
                return response

            # Execute tool calls
            logger.info(
                "GeneralMode._run_agentic_loop: executing %d tool calls | "
                "conversation_id=%s | iteration=%d | tools=%s",
                len(tool_calls),
                conversation_id,
                iteration,
                [tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "?") for tc in tool_calls],
            )

            # Add AI message with tool calls to context
            lc_messages.append(llm_result)

            # Execute each tool call and append ToolMessage
            for tool_call in tool_calls:
                # Handle both dict and object tool_call formats
                if isinstance(tool_call, dict):
                    tc_name = tool_call.get("name", "")
                    tc_args = tool_call.get("args", {})
                    tc_id = tool_call.get("id", "tool_call_0")
                else:
                    tc_name = getattr(tool_call, "name", "")
                    tc_args = getattr(tool_call, "args", {})
                    tc_id = getattr(tool_call, "id", "tool_call_0")

                tool_fn = tool_map.get(tc_name)
                if tool_fn is None:
                    logger.warning(
                        "GeneralMode: unknown tool '%s' requested | conversation_id=%s",
                        tc_name,
                        conversation_id,
                    )
                    tool_output = f"(herramienta '{tc_name}' no disponible en este modo)"
                else:
                    try:
                        raw_result = await tool_fn.ainvoke(tc_args)
                        tool_output = self._format_tool_response(raw_result)
                    except Exception as exc:
                        logger.error(
                            "GeneralMode: tool '%s' raised exception | "
                            "conversation_id=%s | error=%s",
                            tc_name,
                            conversation_id,
                            exc,
                        )
                        tool_output = f"(error al ejecutar herramienta '{tc_name}')"

                lc_messages.append(
                    ToolMessage(content=tool_output, tool_call_id=tc_id)
                )

        # Max iterations reached — return a fallback
        logger.warning(
            "GeneralMode._run_agentic_loop: max iterations (%d) reached | "
            "conversation_id=%s",
            _MAX_TOOL_ITERATIONS,
            conversation_id,
        )
        return (
            "Lo siento, tuve dificultades obteniendo la información. "
            "¿Te puedo ayudar con algo más? 💕"
        )

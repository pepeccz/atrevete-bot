"""
Booking Handler - Prescriptive booking flow with FSM-prescribed tools.

This module implements the prescriptive booking flow where the FSM decides
which tools to call and the LLM only formats responses naturally.

Key components:
- BookingHandler: Executes FSM-prescribed actions for booking intents
- ResponseFormatter: Formats responses using Jinja2 templates + LLM creativity

Flow:
1. FSM.get_required_action() → FSMAction
2. Execute prescribed tools (no LLM decision)
3. Format response with template + tool results
4. Return personalized natural language response
"""

import json
import logging
from typing import Any

from jinja2 import Template
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.fsm import BookingFSM
from agent.fsm.models import ActionType, FSMAction, Intent
from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)


class ResponseFormatter:
    """
    Formats responses using Jinja2 templates with optional LLM enhancement.

    Balances structure (templates prevent hallucinations) with personality
    (LLM can rephrase naturally while preserving data).
    """

    @staticmethod
    async def format_with_template(
        template_str: str,
        template_vars: dict[str, Any],
        allow_creativity: bool,
        llm: ChatOpenAI,
    ) -> str:
        """
        Render Jinja2 template and optionally enhance with LLM creativity.

        Args:
            template_str: Jinja2 template string (with {% %} and {{ }} syntax)
            template_vars: Variables to inject into template
            allow_creativity: If True, LLM can rephrase; if False, use template exactly
            llm: LLM client for creative enhancement

        Returns:
            Final response text (template-rendered or LLM-enhanced)

        Example:
            >>> template = "Services: {% for s in services %}{{ s.name }}{% endfor %}"
            >>> vars = {"services": [{"name": "Corte"}, {"name": "Tinte"}]}
            >>> await format_with_template(template, vars, allow_creativity=True, llm)
            "¡Perfecto! 🌸 Estos son nuestros servicios:\\n- Corte\\n- Tinte"
        """
        # Render base template
        jinja_template = Template(template_str)
        base_response = jinja_template.render(**template_vars)

        if not allow_creativity:
            # Strict mode: use template exactly (no LLM enhancement)
            logger.info("ResponseFormatter | strict mode (no creativity)")
            return base_response

        # Creative mode: LLM enhances while preserving structure
        logger.info("ResponseFormatter | creative mode (LLM enhancement)")

        prompt = f"""Tienes esta respuesta estructurada:

{base_response}

TAREA: Reescribe la respuesta manteniendo TODA la información estructurada
(números, listas, datos específicos) pero haciéndola más natural y personalizada.

REGLAS ESTRICTAS:
- MANTÉN todos los números, horarios, nombres, listas intactas
- MANTÉN la estructura general (listas numeradas, secciones)
- Puedes agregar saludos, emojis (🌸 💐 ✨), frases amigables
- Puedes variar la redacción para sonar más natural
- NO inventes información nueva
- NO omitas información de la respuesta original
- Tono: Amigable, profesional, cercano (asistente de peluquería)

Respuesta natural:"""

        messages = [
            SystemMessage(
                content="Eres Maite, asistente virtual amigable de la Peluquería Atrévete."
            ),
            HumanMessage(content=prompt),
        ]

        response = await llm.ainvoke(messages)
        return response.content


class BookingHandler:
    """
    Handle booking intents using prescriptive FSM actions.

    FSM prescribes exact tools to call, LLM only formats response.
    """

    def __init__(self, fsm: BookingFSM, state: ConversationState, llm: ChatOpenAI):
        """
        Initialize BookingHandler.

        Args:
            fsm: BookingFSM instance with current state + collected_data
            state: Conversation state
            llm: LLM client for response formatting
        """
        self.fsm = fsm
        self.state = state
        self.llm = llm
        self.formatter = ResponseFormatter()

    async def handle(self, intent: Intent) -> str:
        """
        Handle booking intent using prescriptive flow.

        Flow:
        1. FSM prescribes action (tools + template)
        2. Execute prescribed tools
        3. LLM formats response using template + tool results

        Args:
            intent: User intent (already validated by FSM transition)

        Returns:
            Assistant response text
        """
        logger.info(
            f"BookingHandler.handle | intent={intent.type.value} | "
            f"fsm_state={self.fsm.state.value}"
        )

        # Get prescriptive action from FSM
        action = self.fsm.get_required_action()

        logger.info(
            f"Prescriptive action | type={action.action_type.value} | "
            f"tools={[tc.name for tc in action.tool_calls]} | "
            f"has_template={action.response_template is not None}"
        )

        # Execute prescribed tools (if any)
        tool_results = {}
        if action.action_type == ActionType.CALL_TOOLS_SEQUENCE:
            tool_results = await self._execute_tools(action.tool_calls)

        # Format response using template + tool results
        if action.response_template:
            template_vars = {**action.template_vars, **tool_results}

            try:
                response = await self.formatter.format_with_template(
                    template_str=action.response_template,
                    template_vars=template_vars,
                    allow_creativity=action.allow_llm_creativity,
                    llm=self.llm,
                )
            except Exception as e:
                # Template rendering error (syntax error, missing vars, LLM failure)
                logger.error(
                    f"Template rendering failed | "
                    f"template_length={len(action.response_template)} | "
                    f"vars={list(template_vars.keys())} | "
                    f"error={str(e)}",
                    exc_info=True,
                )

                # Fallback to safe response generation
                logger.warning("Falling back to safe response generation")
                response = await self._generate_fallback_response(tool_results)
        else:
            # No template - generate from scratch (rare, for complex states)
            response = await self._generate_fallback_response(tool_results)

        return response

    async def _execute_tools(self, tool_calls: list) -> dict[str, Any]:
        """
        Execute prescribed tools and return results.

        Args:
            tool_calls: List of ToolCall specifications from FSMAction

        Returns:
            Dict of tool results keyed by tool name
        """
        # Import tools here to avoid circular imports
        from agent.tools import (
            book,
            check_availability,
            find_next_available,
            search_services,
        )

        # Map tool names to implementations
        tool_map = {
            "search_services": search_services,
            "find_next_available": find_next_available,
            "check_availability": check_availability,
            "book": book,
        }

        results = {}

        for tool_call in tool_calls:
            try:
                # Get tool implementation
                tool = tool_map.get(tool_call.name)
                if not tool:
                    error_msg = f"Tool not found: {tool_call.name}"
                    logger.error(error_msg)
                    if tool_call.required:
                        raise ValueError(error_msg)
                    results[tool_call.name] = {"error": error_msg}
                    continue

                # Execute tool
                logger.info(
                    f"Executing FSM-prescribed tool | name={tool_call.name} | "
                    f"args={json.dumps(tool_call.args, default=str, ensure_ascii=False)}"
                )
                result = await tool.ainvoke(tool_call.args)

                # Store result
                results[tool_call.name] = result

                logger.info(
                    f"Tool executed | name={tool_call.name} | "
                    f"success={not result.get('error')} | "
                    f"result_keys={list(result.keys()) if isinstance(result, dict) else 'non-dict'}"
                )

            except Exception as e:
                logger.error(
                    f"Tool execution failed | name={tool_call.name} | error={str(e)}",
                    exc_info=True,
                )
                if tool_call.required:
                    # Required tool failed - re-raise to fail fast
                    raise
                else:
                    # Optional tool failed - log and continue
                    results[tool_call.name] = {"error": str(e)}

        return results

    async def _generate_fallback_response(self, tool_results: dict[str, Any]) -> str:
        """
        Generate fallback response when no template provided.

        This is a safety fallback - should rarely be used since FSM action builders
        should always provide templates.

        Args:
            tool_results: Results from executed tools

        Returns:
            Generated response text
        """
        logger.warning(
            f"Generating fallback response (no template) | "
            f"fsm_state={self.fsm.state.value} | "
            f"tools_executed={list(tool_results.keys())}"
        )

        # Build context for LLM
        context = {
            "fsm_state": self.fsm.state.value,
            "collected_data": self.fsm.collected_data,
            "tool_results": tool_results,
        }

        prompt = f"""Genera una respuesta natural para el usuario basándote en esta información:

ESTADO FSM: {context['fsm_state']}
DATOS RECOPILADOS: {json.dumps(context['collected_data'], ensure_ascii=False, indent=2)}
RESULTADOS DE TOOLS: {json.dumps(context['tool_results'], ensure_ascii=False, indent=2)}

INSTRUCCIONES:
- Responde en español de forma natural y amigable
- Usa la información proporcionada para guiar al usuario en el proceso de reserva
- Si hay resultados de tools, preséntalo de forma clara
- Mantén el tono profesional pero cercano (asistente de peluquería)
- NO inventes datos que no estén en la información proporcionada

Respuesta:"""

        messages = [
            SystemMessage(
                content="Eres Maite, asistente virtual amigable de la Peluquería Atrévete."
            ),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)
        return response.content

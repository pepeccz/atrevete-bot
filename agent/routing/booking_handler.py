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
from datetime import datetime
from typing import Any

from jinja2 import Template
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.fsm import BookingFSM
from agent.fsm.booking_fsm import BookingState
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
- NO agregues saludos como "¡Hola!" - el saludo inicial ya se envió al inicio de la conversación
- Puedes usar emojis (🌸 💐 ✨) y frases amigables para dar calidez
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
            Dict of tool results with FLATTENED structure for template access.

            Example: If search_services returns {"services": [...], "count": 5},
            this method returns:
            {
                "search_services": {"services": [...], "count": 5},  # Full result
                "services": [...],  # Flattened for direct template access
                "count": 5          # Flattened for direct template access
            }
        """
        # Import tools here to avoid circular imports
        from agent.tools import (
            book,
            check_availability,
            find_next_available,
            list_stylists,
            search_services,
        )

        # Map tool names to implementations
        tool_map = {
            "search_services": search_services,
            "list_stylists": list_stylists,
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

                # Store full result under tool name
                results[tool_call.name] = result

                # FLATTEN: Extract nested keys for direct template access
                # This allows templates to use {% for service in services %}
                # instead of {% for service in search_services.services %}
                if isinstance(result, dict):
                    for key, value in result.items():
                        # Don't overwrite existing keys (preserves tool-specific data)
                        if key not in results:
                            results[key] = value
                            logger.debug(
                                f"Flattened key '{key}' from tool '{tool_call.name}'"
                            )

                    # Special handling for find_next_available:
                    # It returns {"available_stylists": [{"slots": [...]}]}
                    # We need to flatten all slots into a single "slots" list
                    if tool_call.name == "find_next_available":
                        all_slots = []
                        available_stylists = result.get("available_stylists", [])
                        for stylist_data in available_stylists:
                            stylist_slots = stylist_data.get("slots", [])
                            all_slots.extend(stylist_slots)

                        # Format dates in Spanish for better UX
                        # Convert "2025-12-09" to "9 de diciembre"
                        month_names = [
                            "enero", "febrero", "marzo", "abril", "mayo", "junio",
                            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
                        ]
                        for slot in all_slots:
                            if "date" in slot and isinstance(slot["date"], str):
                                try:
                                    date_obj = datetime.strptime(slot["date"], "%Y-%m-%d")
                                    slot["date"] = f"{date_obj.day} de {month_names[date_obj.month - 1]}"
                                except ValueError:
                                    pass  # Keep original format if parsing fails

                        results["slots"] = all_slots
                        logger.info(
                            f"Flattened {len(all_slots)} slots from "
                            f"{len(available_stylists)} stylists"
                        )

                logger.info(
                    f"Tool executed | name={tool_call.name} | "
                    f"success={not result.get('error')} | "
                    f"result_keys={list(result.keys()) if isinstance(result, dict) else 'non-dict'} | "
                    f"flattened_keys={[k for k in results.keys() if k != tool_call.name]}"
                )

                # Reset FSM to IDLE after successful booking
                # This allows users to start a new booking naturally
                if tool_call.name == "book" and not result.get("error"):
                    customer_id = self.fsm.collected_data.get("customer_id")
                    self.fsm._state = BookingState.IDLE
                    self.fsm._collected_data = {"customer_id": customer_id} if customer_id else {}
                    logger.info(
                        f"FSM reset to IDLE after successful booking | customer_id={customer_id}"
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

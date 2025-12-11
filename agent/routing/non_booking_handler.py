"""
Non-Booking Handler - Conversational flow for FAQ, greetings, escalation.

This module implements the conversational flow for intents that DON'T affect
booking state. LLM handles these freely with a whitelist of safe tools.

Key difference from BookingHandler:
- BookingHandler: FSM prescribes tools (prescriptive)
- NonBookingHandler: LLM decides tools from whitelist (conversational)

Safe tools:
- query_info: Read-only information queries (FAQs, hours, policies)
- search_services: Read-only service search
- escalate_to_human: Human handoff

No booking tools available → no hallucination risk
"""

import logging
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from agent.fsm.models import Intent

if TYPE_CHECKING:
    from agent.fsm import BookingFSM
    from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)


class NonBookingHandler:
    """
    Handle non-booking intents conversationally with safe tools.

    For FAQ, greetings, escalation - LLM decides tools from whitelist.
    No booking tools available → no booking hallucination risk.
    """

    def __init__(self, state: "ConversationState", llm: ChatOpenAI, fsm: "BookingFSM"):
        """
        Initialize NonBookingHandler.

        Args:
            state: Conversation state (for history, context)
            llm: LLM client for conversational responses
            fsm: BookingFSM (for context about current booking state, if any)
        """
        self.state = state
        self.llm = llm
        self.fsm = fsm

    async def handle(self, intent: Intent) -> str:
        """
        Handle non-booking intent conversationally.

        LLM can call query_info, search_services, escalate_to_human.
        No booking tools available → no hallucination risk.

        Args:
            intent: User intent (GREETING, FAQ, ESCALATE, UNKNOWN)

        Returns:
            Assistant response text
        """
        logger.info(
            f"NonBookingHandler.handle | intent={intent.type.value} | "
            f"fsm_state={self.fsm.state.value}"
        )

        # Import safe tools (no booking tools, but manage_customer for name updates)
        from agent.tools import escalate_to_human, manage_customer, query_info, search_services

        # Bind safe tools only - no booking tools available
        # manage_customer is needed to update customer name when they provide it
        SAFE_TOOLS = [query_info, search_services, manage_customer, escalate_to_human]
        llm_with_tools = self.llm.bind_tools(SAFE_TOOLS)

        # Build message history with FSM context
        messages = self._build_messages(intent)

        # Invoke LLM with safe tools
        response = await llm_with_tools.ainvoke(messages)

        # Execute tool calls if any
        if response.tool_calls:
            messages.append(response)
            for tool_call in response.tool_calls:
                result = await self._execute_tool(tool_call)
                messages.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))

            # Get final response after tool execution
            final_response = await llm_with_tools.ainvoke(messages)
            return final_response.content

        return response.content

    def _build_messages(self, intent: Intent) -> list:
        """
        Build message history for LLM with FSM context.

        Args:
            intent: User intent

        Returns:
            List of LangChain messages (SystemMessage, HumanMessage, AIMessage)
        """
        # Build FSM context for system message
        fsm_context = ""
        if self.fsm.state.value != "idle":
            # User has an active booking in progress
            fsm_context = f"""
CONTEXTO DE RESERVA ACTUAL:
- Estado del booking: {self.fsm.state.value}
- Datos recopilados: {self.fsm.collected_data}

IMPORTANTE: El usuario tiene una reserva en progreso. Si responde preguntas no relacionadas
con el booking, mantén el contexto y recuérdale suavemente que puede continuar con su reserva
cuando esté listo.
"""

        # Build first interaction context
        is_first_interaction = self.state.get("is_first_interaction", False)
        customer_needs_name = self.state.get("customer_needs_name", False)
        customer_first_name = self.state.get("customer_first_name")
        customer_phone = self.state.get("customer_phone", "")

        first_interaction_context = f"""
DATOS DEL CLIENTE:
- Teléfono: {customer_phone}
- Nombre actual: {customer_first_name or "(sin nombre)"}
- is_first_interaction: {is_first_interaction}
- customer_needs_name: {customer_needs_name}

REGLAS DE SALUDO:
"""
        if is_first_interaction:
            if customer_needs_name:
                first_interaction_context += """
⚠️ PRIMERA INTERACCIÓN - NOMBRE NO LEGIBLE
El nombre de WhatsApp del usuario contiene números o emojis, no es un nombre real.
DEBES:
1. Presentarte como Maite
2. Preguntar: "¿Con quién tengo el gusto de hablar?"
3. NO ofrecer servicios aún, espera a que te dé su nombre
4. Cuando te dé su nombre, usa manage_customer para actualizarlo

Ejemplo de respuesta:
"¡Hola! 🌸 Soy Maite, la asistente virtual de Atrévete Peluquería.
¿Con quién tengo el gusto de hablar?"
"""
            else:
                first_interaction_context += f"""
⚠️ PRIMERA INTERACCIÓN - NOMBRE LEGIBLE
El nombre de WhatsApp parece legible: {customer_first_name}
DEBES:
1. Presentarte como Maite
2. Confirmar el nombre: "¿Puedo llamarte *{customer_first_name}*?"
3. Preguntar en qué puedes ayudar

Ejemplo de respuesta:
"¡Hola! 🌸 Soy Maite, la asistente virtual de Atrévete Peluquería.
¿Puedo llamarte *{customer_first_name}*? ¿En qué puedo ayudarte hoy?"
"""
        else:
            first_interaction_context += f"""
✅ CLIENTE RECURRENTE
El usuario ya ha interactuado antes. Nombre: {customer_first_name or "Cliente"}
Saluda de forma natural: "¡Hola de nuevo, {customer_first_name or 'amigo'}! 😊 ¿En qué puedo ayudarte?"
"""

        # System message with role and context
        system_prompt = f"""Eres Maite, asistente virtual amigable de la Peluquería Atrévete.

{first_interaction_context}

RESPONSABILIDADES:
- Responder preguntas sobre servicios, horarios, políticas (usa query_info)
- Buscar servicios específicos si el usuario pregunta (usa search_services)
- Escalar a humano si es necesario (usa escalate_to_human)
- ACTUALIZAR NOMBRE: Si el usuario te dice su nombre, usa manage_customer con action="update"

IMPORTANTE:
- NO puedes hacer reservas directamente (eso requiere intención de booking)
- Si el usuario quiere reservar, guíalo amablemente al flujo de booking
- Mantén un tono profesional pero cercano
- Responde siempre en español

{fsm_context}"""

        messages = [SystemMessage(content=system_prompt)]

        # Add recent conversation history (last 5 messages for context)
        conversation_messages = self.state.get("messages", [])
        recent_messages = conversation_messages[-5:] if len(conversation_messages) > 5 else conversation_messages

        for msg in recent_messages:
            role = msg.get("role")
            content = msg.get("content", "")

            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))

        # Add current user message
        messages.append(HumanMessage(content=intent.raw_message))

        return messages

    async def _execute_tool(self, tool_call: dict) -> str:
        """
        Execute a single tool call from LLM.

        Args:
            tool_call: Tool call dict from LLM response

        Returns:
            Tool result as JSON string
        """
        import json

        from agent.tools import escalate_to_human, manage_customer, query_info, search_services

        # Map tool names to implementations
        tool_map = {
            "query_info": query_info,
            "search_services": search_services,
            "manage_customer": manage_customer,
            "escalate_to_human": escalate_to_human,
        }

        tool_name = tool_call.get("name", "")
        tool_args = tool_call.get("args", {})

        logger.info(
            f"Executing safe tool | name={tool_name} | "
            f"args={json.dumps(tool_args, default=str, ensure_ascii=False)}"
        )

        try:
            tool = tool_map.get(tool_name)
            if not tool:
                error_msg = f"Tool not found: {tool_name}"
                logger.error(error_msg)
                return json.dumps({"error": error_msg}, ensure_ascii=False)

            # Execute tool
            result = await tool.ainvoke(tool_args)

            logger.info(
                f"Safe tool executed | name={tool_name} | "
                f"success={not result.get('error') if isinstance(result, dict) else True}"
            )

            # Return result as JSON string for ToolMessage
            if isinstance(result, dict):
                return json.dumps(result, ensure_ascii=False)
            else:
                return str(result)

        except Exception as e:
            logger.error(
                f"Safe tool execution failed | name={tool_name} | error={str(e)}",
                exc_info=True,
            )
            return json.dumps({"error": str(e)}, ensure_ascii=False)

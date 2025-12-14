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

from agent.fsm.models import Intent, IntentType

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

        # Handle appointment confirmation/decline intents (48h confirmation flow)
        if intent.type in (IntentType.CONFIRM_APPOINTMENT, IntentType.DECLINE_APPOINTMENT):
            return await self._handle_appointment_confirmation(intent)

        # Handle UPDATE_NAME intent explicitly to ensure name is updated
        if intent.type == IntentType.UPDATE_NAME:
            return await self._handle_update_name(intent)

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
"¡Hola! 🌸 Soy Maite, la asistente virtual con IA de Atrévete Peluquería.
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
"¡Hola! 🌸 Soy Maite, la asistente virtual con IA de Atrévete Peluquería.
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

        For escalate_to_human, injects conversation context (conversation_id,
        customer_phone, recent messages) so the escalation service can:
        1. Disable bot in Chatwoot
        2. Create notification with full context

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

            # Inject conversation context for escalate_to_human
            # This enables the escalation service to disable bot in Chatwoot
            # and create notification with full context
            if tool_name == "escalate_to_human":
                tool_args["_conversation_id"] = self.state.get("conversation_id")
                tool_args["_customer_phone"] = self.state.get("customer_phone")
                # Get last 5 messages for context
                messages = self.state.get("messages", [])
                tool_args["_conversation_context"] = messages[-5:] if messages else []
                logger.info(
                    f"Injecting escalation context | conversation_id={tool_args['_conversation_id']} | "
                    f"customer_phone={tool_args['_customer_phone']}"
                )

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

    async def _handle_update_name(self, intent: Intent) -> str:
        """
        Handle UPDATE_NAME intent - update customer name in database.

        This is called when user says "Llamame X", "Mi nombre es Y", "Soy Z" in IDLE state.
        Directly updates the database via manage_customer tool.

        Args:
            intent: Intent with entities containing first_name (and optionally last_name)

        Returns:
            Confirmation response with updated name
        """
        from agent.tools import manage_customer

        first_name = intent.entities.get("first_name", "").strip()
        last_name = intent.entities.get("last_name", "").strip()
        customer_id = self.state.get("customer_id")
        customer_phone = self.state.get("customer_phone", "")

        if not first_name:
            logger.warning("UPDATE_NAME intent without first_name entity, falling back to LLM")
            # Fall back to standard conversational handling
            return await self._handle_fallback(intent)

        if not customer_id or not customer_phone:
            logger.warning(
                f"UPDATE_NAME intent missing state data | "
                f"customer_id={customer_id} | customer_phone={customer_phone}"
            )
            return "Lo siento, ha habido un problema al actualizar tu nombre. ¿Puedes intentarlo de nuevo?"

        logger.info(
            f"Handling UPDATE_NAME | customer_id={customer_id} | "
            f"first_name={first_name} | last_name={last_name or '(none)'}"
        )

        # Call manage_customer to update the database
        try:
            update_data = {
                "customer_id": customer_id,
                "first_name": first_name,
            }
            if last_name:
                update_data["last_name"] = last_name

            result = await manage_customer.ainvoke({
                "action": "update",
                "phone": customer_phone,
                "data": update_data,
            })

            if isinstance(result, dict) and result.get("error"):
                logger.error(f"manage_customer update failed: {result.get('error')}")
                return f"Lo siento, no pude actualizar tu nombre. ¿Puedes intentarlo de nuevo?"

            logger.info(f"Customer name updated successfully: {first_name}")

            # Generate friendly confirmation response
            display_name = f"{first_name} {last_name}".strip() if last_name else first_name
            return f"¡Perfecto, {display_name}! 😊 ¿En qué puedo ayudarte?"

        except Exception as e:
            logger.error(f"Error updating customer name: {e}", exc_info=True)
            return "Lo siento, ha habido un problema al actualizar tu nombre. ¿Puedes intentarlo de nuevo?"

    async def _handle_appointment_confirmation(self, intent: Intent) -> str:
        """
        Handle appointment confirmation/decline responses (48h confirmation flow).

        Processes customer responses to confirmation requests sent 48h before appointments.
        - CONFIRM_APPOINTMENT: Customer confirms attendance → update status to CONFIRMED
        - DECLINE_APPOINTMENT: Customer says can't attend → update status to CANCELLED

        Args:
            intent: Intent with type CONFIRM_APPOINTMENT or DECLINE_APPOINTMENT

        Returns:
            Response text (template or LLM-generated based on message complexity)
        """
        from agent.services.confirmation_service import handle_confirmation_response

        customer_phone = self.state.get("customer_phone", "")

        if not customer_phone:
            logger.warning("Confirmation intent without customer_phone in state")
            return "Lo siento, ha habido un problema. Por favor, intenta de nuevo."

        logger.info(
            f"Handling appointment confirmation | intent={intent.type.value} | "
            f"customer_phone={customer_phone}"
        )

        try:
            # Process the confirmation response
            result = await handle_confirmation_response(
                customer_phone=customer_phone,
                intent_type=intent.type,
                message_text=intent.raw_message,
            )

            if not result.success:
                # No pending appointment or other error
                logger.info(
                    f"Confirmation handling failed | error={result.error_message}"
                )
                return result.error_message or "Lo siento, no pude procesar tu respuesta."

            # Check response type
            if result.response_type == "template" and result.response_text:
                # Simple message - use pre-generated template response
                logger.info(
                    f"Confirmation processed (template) | appointment_id={result.appointment_id} | "
                    f"intent={intent.type.value}"
                )
                return result.response_text

            # Complex message - generate LLM response with context
            logger.info(
                f"Confirmation processed (LLM) | appointment_id={result.appointment_id} | "
                f"intent={intent.type.value}"
            )
            return await self._generate_confirmation_response(intent, result)

        except Exception as e:
            logger.exception(f"Error handling appointment confirmation: {e}")
            return "Lo siento, ha habido un problema al procesar tu respuesta. Por favor, intenta de nuevo."

    async def _generate_confirmation_response(self, intent: Intent, result) -> str:
        """
        Generate LLM response for complex confirmation messages.

        When the customer's message is more than a simple "sí" or "no",
        we let the LLM generate a contextual response.

        Args:
            intent: User intent
            result: ConfirmationResult with appointment data

        Returns:
            LLM-generated response text
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        # Build context for LLM
        action = "confirmada" if intent.type == IntentType.CONFIRM_APPOINTMENT else "cancelada"

        system_prompt = f"""Eres Maite, asistente virtual de Peluquería Atrévete.

El cliente acaba de responder a una solicitud de confirmación de cita.

CONTEXTO DE LA CITA:
- Fecha: {result.appointment_date}
- Hora: {result.appointment_time}
- Estilista: {result.stylist_name}
- Servicios: {result.service_names}
- Estado: La cita ha sido {action}

INSTRUCCIONES:
- Responde de forma natural al mensaje del cliente
- Confirma que la cita ha sido {action}
- Si la cita fue cancelada, ofrece ayuda para reservar otra fecha
- Mantén un tono profesional pero cercano
- Responde en español
- NO uses emojis excesivamente, máximo 1-2
"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=intent.raw_message),
        ]

        response = await self.llm.ainvoke(messages)
        return response.content

    async def _handle_fallback(self, intent: Intent) -> str:
        """
        Fallback to standard LLM handling when explicit handler cannot process.

        Args:
            intent: User intent

        Returns:
            LLM-generated response
        """
        from agent.tools import escalate_to_human, manage_customer, query_info, search_services

        SAFE_TOOLS = [query_info, search_services, manage_customer, escalate_to_human]
        llm_with_tools = self.llm.bind_tools(SAFE_TOOLS)

        messages = self._build_messages(intent)
        response = await llm_with_tools.ainvoke(messages)

        if response.tool_calls:
            messages.append(response)
            for tool_call in response.tool_calls:
                result = await self._execute_tool(tool_call)
                messages.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))

            final_response = await llm_with_tools.ainvoke(messages)
            return final_response.content

        return response.content

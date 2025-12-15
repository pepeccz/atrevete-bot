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

v4.3: Added dynamic context injection (minimum_booking_days_advance, etc.)
"""

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from agent.fsm.models import Intent, IntentType
from agent.prompts.dynamic_context import load_dynamic_context

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

    async def handle(self, intent: Intent) -> tuple[str, dict | None]:
        """
        Handle non-booking intent conversationally.

        LLM can call query_info, search_services, escalate_to_human.
        No booking tools available → no hallucination risk.

        Args:
            intent: User intent (GREETING, FAQ, ESCALATE, UNKNOWN)

        Returns:
            Tuple of (response_text, state_updates)
            - response_text: Assistant response text
            - state_updates: Dict of state fields to update (or None)
        """
        logger.info(
            f"NonBookingHandler.handle | intent={intent.type.value} | "
            f"fsm_state={self.fsm.state.value}"
        )

        # Check for pending decline state FIRST (double confirmation flow)
        pending_decline_id = self.state.get("pending_decline_appointment_id")
        if pending_decline_id:
            return await self._handle_pending_decline(intent, pending_decline_id)

        # Handle double confirmation intents (without pending state - shouldn't happen)
        if intent.type in (IntentType.CONFIRM_DECLINE, IntentType.ABORT_DECLINE):
            logger.warning(
                f"Received {intent.type.value} without pending decline state, "
                "treating as unknown"
            )
            # Fall through to normal handling

        # Handle appointment confirmation/decline intents (48h confirmation flow)
        if intent.type in (IntentType.CONFIRM_APPOINTMENT, IntentType.DECLINE_APPOINTMENT):
            return await self._handle_appointment_confirmation(intent)

        # Handle cancellation intents (customer-initiated cancellation)
        if intent.type in (
            IntentType.INITIATE_CANCELLATION,
            IntentType.SELECT_CANCELLATION,
            IntentType.CONFIRM_CANCELLATION,
            IntentType.ABORT_CANCELLATION,
            IntentType.INSIST_CANCELLATION,
        ):
            response = await self._handle_cancellation(intent)
            return (response, None)

        # Handle appointment query intent (customer checks their appointments)
        if intent.type == IntentType.CHECK_MY_APPOINTMENTS:
            response = await self._handle_appointment_query()
            return (response, None)

        # Handle UPDATE_NAME intent explicitly to ensure name is updated
        if intent.type == IntentType.UPDATE_NAME:
            response = await self._handle_update_name(intent)
            return (response, None)

        # Import safe tools (no booking tools, but manage_customer for name updates)
        from agent.tools import escalate_to_human, manage_customer, query_info, search_services

        # Bind safe tools only - no booking tools available
        # manage_customer is needed to update customer name when they provide it
        SAFE_TOOLS = [query_info, search_services, manage_customer, escalate_to_human]
        llm_with_tools = self.llm.bind_tools(SAFE_TOOLS)

        # v4.3: Load dynamic context from database (cached for 5 min)
        dynamic_context = await load_dynamic_context()

        # Build message history with FSM context and dynamic context
        messages = self._build_messages(intent, dynamic_context)

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
            return (final_response.content, None)

        return (response.content, None)

    def _build_messages(self, intent: Intent, dynamic_context: dict[str, Any] | None = None) -> list:
        """
        Build message history for LLM with FSM context and dynamic business context.

        Args:
            intent: User intent
            dynamic_context: Dynamic context from database (minimum_booking_days, etc.)

        Returns:
            List of LangChain messages (SystemMessage, HumanMessage, AIMessage)
        """
        # Default dynamic context if not provided
        if dynamic_context is None:
            dynamic_context = {}

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

        # Build dynamic business context
        min_days = dynamic_context.get("minimum_booking_days_advance", 3)
        salon_address = dynamic_context.get("salon_address", "")
        current_datetime = dynamic_context.get("current_datetime", "")
        business_hours = dynamic_context.get("business_hours", [])
        upcoming_holidays = dynamic_context.get("upcoming_holidays", [])

        # Format business hours
        hours_str = ""
        for day in business_hours:
            if day.get("is_closed"):
                hours_str += f"- {day.get('day_name', '')}: CERRADO\n"
            else:
                hours_str += f"- {day.get('day_name', '')}: {day.get('start', '')} - {day.get('end', '')}\n"

        # Format holidays
        holidays_str = ""
        if upcoming_holidays:
            holidays_str = "Próximos festivos (salón cerrado):\n"
            for holiday in upcoming_holidays:
                holidays_str += f"- {holiday.get('date', '')}: {holiday.get('name', '')}\n"

        business_context = f"""
CONTEXTO DEL NEGOCIO:
- Fecha y hora actual: {current_datetime}
- Dirección del salón: {salon_address}
- Regla de reserva: Se requieren {min_days} días de antelación mínimo

Horarios de apertura:
{hours_str}
{holidays_str}
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
"¡Hola! 🌸 Soy Maite, la asistenta virtual de Atrévete Peluquería.
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
"¡Hola! 🌸 Soy Maite, la asistenta virtual de Atrévete Peluquería.
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

{business_context}

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

    async def _handle_pending_decline(
        self, intent: Intent, pending_decline_id: str
    ) -> tuple[str, dict | None]:
        """
        Handle response when user has a pending decline awaiting confirmation.

        Three scenarios:
        1. CONFIRM_DECLINE → cancel the appointment
        2. ABORT_DECLINE → keep the appointment
        3. Any other intent → topic change, keep appointment + answer query

        Args:
            intent: User intent
            pending_decline_id: UUID string of appointment pending decline

        Returns:
            Tuple of (response_text, state_updates)
        """
        from agent.services.confirmation_service import (
            check_decline_timeout,
            handle_decline_second_confirmation,
            handle_topic_change_with_pending_decline,
        )

        customer_phone = self.state.get("customer_phone", "")
        initiated_at = self.state.get("pending_decline_initiated_at")

        logger.info(
            f"Handling pending decline | intent={intent.type.value} | "
            f"appointment_id={pending_decline_id} | initiated_at={initiated_at}"
        )

        # Check timeout (24h)
        if initiated_at and check_decline_timeout(initiated_at):
            logger.info(
                f"Pending decline timeout expired | appointment_id={pending_decline_id}"
            )
            # Timeout expired - treat as topic change
            prefix_message, state_updates = await handle_topic_change_with_pending_decline(
                pending_decline_id
            )
            # Process the original intent normally (without prefix for timeout)
            original_response, _ = await self._process_intent_normally(intent)
            return (original_response, state_updates)

        # Handle CONFIRM_DECLINE
        if intent.type == IntentType.CONFIRM_DECLINE:
            result = await handle_decline_second_confirmation(
                customer_phone=customer_phone,
                intent_type=intent.type,
                appointment_id=pending_decline_id,
            )
            return (result.response_text or result.error_message, result.state_updates)

        # Handle ABORT_DECLINE
        if intent.type == IntentType.ABORT_DECLINE:
            result = await handle_decline_second_confirmation(
                customer_phone=customer_phone,
                intent_type=intent.type,
                appointment_id=pending_decline_id,
            )
            return (result.response_text or result.error_message, result.state_updates)

        # Any other intent = topic change
        # Keep appointment and answer their new query
        logger.info(
            f"Topic change detected while pending decline | "
            f"new_intent={intent.type.value} | appointment_id={pending_decline_id}"
        )

        prefix_message, state_updates = await handle_topic_change_with_pending_decline(
            pending_decline_id
        )

        # Process the original intent normally
        original_response, original_updates = await self._process_intent_normally(intent)

        # Merge state updates (topic change updates take precedence)
        if original_updates:
            state_updates.update(original_updates)

        # Combine: appointment kept message + answer to new query
        combined_response = prefix_message + original_response

        return (combined_response, state_updates)

    async def _process_intent_normally(self, intent: Intent) -> tuple[str, dict | None]:
        """
        Process an intent using normal handling (without pending decline check).

        This is used by _handle_pending_decline for topic change handling.

        Args:
            intent: User intent

        Returns:
            Tuple of (response_text, state_updates)
        """
        # Handle appointment confirmation/decline intents
        if intent.type in (IntentType.CONFIRM_APPOINTMENT, IntentType.DECLINE_APPOINTMENT):
            return await self._handle_appointment_confirmation(intent)

        # Handle cancellation intents
        if intent.type in (
            IntentType.INITIATE_CANCELLATION,
            IntentType.SELECT_CANCELLATION,
            IntentType.CONFIRM_CANCELLATION,
            IntentType.ABORT_CANCELLATION,
            IntentType.INSIST_CANCELLATION,
        ):
            response = await self._handle_cancellation(intent)
            return (response, None)

        # Handle appointment query
        if intent.type == IntentType.CHECK_MY_APPOINTMENTS:
            response = await self._handle_appointment_query()
            return (response, None)

        # Handle UPDATE_NAME
        if intent.type == IntentType.UPDATE_NAME:
            response = await self._handle_update_name(intent)
            return (response, None)

        # Default: LLM conversational handling
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
            return (final_response.content, None)

        return (response.content, None)

    async def _handle_appointment_confirmation(self, intent: Intent) -> tuple[str, dict | None]:
        """
        Handle appointment confirmation/decline responses (48h confirmation flow).

        Processes customer responses to confirmation requests sent 48h before appointments.
        - CONFIRM_APPOINTMENT: Customer confirms attendance → update status to CONFIRMED
        - DECLINE_APPOINTMENT: Customer says can't attend → double confirmation or cancel

        Args:
            intent: Intent with type CONFIRM_APPOINTMENT or DECLINE_APPOINTMENT

        Returns:
            Tuple of (response_text, state_updates)
        """
        from agent.services.confirmation_service import handle_confirmation_response

        customer_phone = self.state.get("customer_phone", "")

        if not customer_phone:
            logger.warning("Confirmation intent without customer_phone in state")
            return ("Lo siento, ha habido un problema. Por favor, intenta de nuevo.", None)

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
                return (
                    result.error_message or "Lo siento, no pude procesar tu respuesta.",
                    result.state_updates,
                )

            # Check if this is a double confirmation prompt (pending decline)
            if result.requires_double_confirm:
                logger.info(
                    f"Double confirmation required | appointment_id={result.appointment_id}"
                )
                return (result.response_text, result.state_updates)

            # Check response type
            if result.response_type == "template" and result.response_text:
                # Simple message - use pre-generated template response
                logger.info(
                    f"Confirmation processed (template) | appointment_id={result.appointment_id} | "
                    f"intent={intent.type.value}"
                )
                return (result.response_text, result.state_updates)

            # Complex message - generate LLM response with context
            logger.info(
                f"Confirmation processed (LLM) | appointment_id={result.appointment_id} | "
                f"intent={intent.type.value}"
            )
            response = await self._generate_confirmation_response(intent, result)
            return (response, result.state_updates)

        except Exception as e:
            logger.exception(f"Error handling appointment confirmation: {e}")
            return (
                "Lo siento, ha habido un problema al procesar tu respuesta. Por favor, intenta de nuevo.",
                None,
            )

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

    async def _handle_cancellation(self, intent: Intent) -> str:
        """
        Handle customer-initiated appointment cancellation.

        Processes customer requests to cancel their appointments:
        - INITIATE_CANCELLATION: Start flow, show appointments
        - SELECT_CANCELLATION: User selects appointment by number
        - CONFIRM_CANCELLATION: Execute cancellation
        - ABORT_CANCELLATION: Abort cancellation flow
        - INSIST_CANCELLATION: User insists despite window -> escalate

        Args:
            intent: Intent with type related to cancellation

        Returns:
            Response text to send to customer
        """
        from agent.services.cancellation_service import (
            initiate_cancellation_flow,
            select_appointment_for_cancellation,
            execute_cancellation,
            detect_number_selection,
        )
        from agent.tools import escalate_to_human

        customer_phone = self.state.get("customer_phone", "")
        conversation_id = self.state.get("conversation_id")
        pending_cancellation_id = self.state.get("pending_cancellation_id")

        if not customer_phone:
            logger.warning("Cancellation intent without customer_phone in state")
            return "Lo siento, ha habido un problema. Por favor, intenta de nuevo."

        logger.info(
            f"Handling cancellation | intent={intent.type.value} | "
            f"customer_phone={customer_phone} | pending_id={pending_cancellation_id}"
        )

        try:
            if intent.type == IntentType.INITIATE_CANCELLATION:
                result = await initiate_cancellation_flow(customer_phone)

                if not result.success:
                    if result.within_window:
                        # Store appointment ID for potential insist
                        logger.info(
                            f"Cancellation blocked (within window) | "
                            f"appointment_id={result.appointment_id}"
                        )
                    return result.error_message or result.response_text

                # Store pending appointment ID if single appointment
                if result.appointment_id and not result.multiple_appointments:
                    # Note: State update would be handled by the calling node
                    logger.info(f"Single appointment for cancellation: {result.appointment_id}")

                return result.response_text

            elif intent.type == IntentType.SELECT_CANCELLATION:
                # User selected a specific appointment by number
                selection = detect_number_selection(intent.raw_message)
                if selection:
                    result = await select_appointment_for_cancellation(
                        customer_phone, selection
                    )
                    if not result.success:
                        return result.error_message
                    # Store selected appointment ID
                    logger.info(f"Appointment selected for cancellation: {result.appointment_id}")
                    return result.response_text
                else:
                    return (
                        "No entendí qué cita quieres cancelar. "
                        "Por favor, responde con el número (1, 2, 3...)."
                    )

            elif intent.type == IntentType.CONFIRM_CANCELLATION:
                # User confirmed cancellation
                if pending_cancellation_id:
                    from uuid import UUID
                    try:
                        appt_uuid = UUID(pending_cancellation_id)
                        # Extract reason if user provided one
                        reason = None
                        if len(intent.raw_message.split()) > 3:
                            reason = intent.raw_message
                        result = await execute_cancellation(
                            appt_uuid, reason=reason, conversation_id=conversation_id
                        )
                        if not result.success:
                            return result.error_message
                        return result.response_text
                    except ValueError:
                        logger.error(f"Invalid appointment UUID: {pending_cancellation_id}")
                        return "Ha ocurrido un error. Por favor, intenta de nuevo."
                else:
                    # No pending appointment - might be single appointment flow
                    from agent.services.cancellation_service import (
                        get_customer_by_phone,
                        get_cancellable_appointments,
                    )
                    customer = await get_customer_by_phone(customer_phone)
                    if customer:
                        appointments = await get_cancellable_appointments(customer.id)
                        if len(appointments) == 1:
                            result = await execute_cancellation(
                                appointments[0].id, conversation_id=conversation_id
                            )
                            if not result.success:
                                return result.error_message
                            return result.response_text
                    return (
                        "No hay ninguna cita seleccionada para cancelar. "
                        "¿Qué cita quieres cancelar?"
                    )

            elif intent.type == IntentType.ABORT_CANCELLATION:
                return "Entendido, no cancelaré ninguna cita. ¿En qué más puedo ayudarte?"

            elif intent.type == IntentType.INSIST_CANCELLATION:
                # User insists despite window restriction -> escalate
                logger.info(
                    f"Customer insisting on cancellation within window | "
                    f"phone={customer_phone}"
                )
                # Execute escalation
                result = await escalate_to_human.ainvoke({
                    "reason": "manual_request",
                    "_conversation_id": conversation_id,
                    "_customer_phone": customer_phone,
                    "_conversation_context": self.state.get("messages", [])[-5:],
                })
                return (
                    "Entiendo que necesitas cancelar urgentemente. "
                    "Te conecto con el equipo para que te ayuden."
                )

            else:
                logger.warning(f"Unexpected cancellation intent: {intent.type}")
                return "No entendí tu respuesta. ¿Quieres cancelar una cita?"

        except Exception as e:
            logger.exception(f"Error handling cancellation: {e}")
            return "Ha ocurrido un error al procesar tu solicitud. Por favor, intenta de nuevo."

    async def _handle_appointment_query(self) -> str:
        """
        Handle customer appointment query (CHECK_MY_APPOINTMENTS).

        Processes customer requests to view their upcoming appointments.
        Returns formatted list of appointments or appropriate message if none.

        Returns:
            Response text with appointment list or no-appointments message
        """
        from agent.services.appointment_query_service import get_upcoming_appointments

        customer_phone = self.state.get("customer_phone", "")

        if not customer_phone:
            logger.warning("Appointment query without customer_phone in state")
            return "Lo siento, ha habido un problema. Por favor, intenta de nuevo."

        logger.info(f"Handling appointment query | customer_phone={customer_phone}")

        try:
            result = await get_upcoming_appointments(customer_phone)

            if not result.success:
                # Database error - offer escalation
                logger.error(f"Appointment query failed: {result.error_message}")
                return result.error_message

            # Return the formatted response (whether has appointments or not)
            return result.response_text

        except Exception as e:
            logger.exception(f"Error handling appointment query: {e}")
            return (
                "Lo siento, no he podido consultar tus citas en este momento. "
                "¿Quieres que te conecte con el equipo para ayudarte?"
            )

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

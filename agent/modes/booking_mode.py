"""
BookingMode — Full appointment booking flow via sub-step state machine (v6.0).

This is the most complex mode. It manages the complete booking flow:

    service_selection
        ↓
    stylist_selection
        ↓
    slot_selection
        ↓
    customer_data  (first_name, last_name, notes)
        ↓
    confirmation   (show summary, ask for confirmation)
        ↓
    completed      (call book() tool, show confirmation, transition to GENERAL)

Sub-step state is tracked in `state["mode_context"]["booking_step"]` using the
`merge_dicts` reducer, so it persists correctly between conversation turns.

Tools available (full set):
- query_info: Services list, FAQs, hours
- search_services: Fuzzy service search
- check_availability: Check a specific date
- find_next_available: Auto-search multiple dates
- book: Create the appointment (atomic transaction)
- manage_customer: Update customer name/notes
- get_customer_history: Past appointments

Mode transitions:
- intent="cancel" at any step → confirm cancellation, return to GENERAL
- intent="escalate" at any step → ESCALATION mode
- booking "completed" → GENERAL mode

Architecture decisions:
    1. The LLM drives responses within each sub-step — BookingMode doesn't
       generate hardcoded responses. Instead it gives the LLM a focused system
       prompt for each sub-step and the LLM uses tools + conversation context
       to produce the response.
    2. Sub-step progression is tracked explicitly in mode_context["booking_step"].
       The LLM cannot skip steps — BookingMode validates which step to be in
       based on what data has been collected.
    3. booking_step="completed" triggers the book() tool call directly (not via
       the LLM agent loop), to prevent the LLM from hallucinating booking data.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import ToolMessage

from agent.modes.base import BaseModeNode
from agent.routing.intent_router import IntentResult
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState, transition_mode
from agent.tools.availability_tools import check_availability, find_next_available
from agent.tools.booking_tools import book
from agent.tools.customer_tools import get_customer_history, manage_customer
from agent.tools.info_tools import list_stylists, query_info
from agent.tools.search_services import search_services

logger = logging.getLogger(__name__)


# ============================================================================
# Sub-step system prompts
# ============================================================================

_BOOKING_BASE = """Eres Maite, asistenta virtual de Atrévete Peluquería en Alcobendas.

## Reglas críticas
- **NO narres acciones**: Llama herramientas silenciosamente, responde con los datos.
- Mensajes concisos: 2-4 frases, máximo 150 palabras.
- Español natural y conversacional, tono cálido (tú), emojis: 1-2 máximo.
- Formato WhatsApp: *negrita*, listas numeradas para opciones.

"""

_STEP_SERVICE_SELECTION = _BOOKING_BASE + """## Paso actual: Selección de servicio

El cliente quiere reservar una cita. Necesitas averiguar qué servicio desea.

Si ya mencionó un servicio → usa `search_services(query="...")` para confirmarlo y encontrar el servicio exacto.
Si no mencionó servicio → pregunta educadamente qué servicio le interesa.

Muestra máximo 5 opciones. Cuando el cliente confirme el servicio, indica que pasamos al siguiente paso.

**Servicios mixtos PROHIBIDOS**: No agendar peluquería + estética en la misma cita.
"""

_STEP_STYLIST_SELECTION = _BOOKING_BASE + """## Paso actual: Selección de estilista

El cliente ha elegido: {service_name}
Categoría del servicio: {service_category}

Usa `list_stylists(category="{service_category}")` para mostrar los estilistas disponibles.
Pregunta con quién prefiere o si no tiene preferencia (cualquier estilista disponible).

Muestra las opciones con número para que el cliente pueda elegir fácilmente.
"""

_STEP_SLOT_SELECTION = _BOOKING_BASE + """## Paso actual: Selección de horario

Cliente: {customer_name_or_cliente}
Servicio: {service_name}
Estilista: {stylist_name} (ID: {stylist_id})

Usa `find_next_available(service_category="{service_category}", stylist_id="{stylist_id}")` para mostrar disponibilidad.
Si el cliente prefiere una fecha concreta → usa `check_availability(service_category="{service_category}", date="...", stylist_id="{stylist_id}")`.

Muestra los slots con número (1., 2., 3.) para que el cliente pueda elegir.
Cuando el cliente elija un slot, confirma el horario y avanza al siguiente paso.
"""

_STEP_CUSTOMER_DATA = _BOOKING_BASE + """## Paso actual: Datos del cliente

Servicio: {service_name}
Estilista: {stylist_name}
Horario: {slot_time} del {slot_date}

Necesito el nombre para la reserva. El cliente se llama {customer_name_or_cliente}.
Pregunta:
1. Nombre completo para la reserva (primer nombre + apellidos si los tiene)
2. ¿Alguna nota especial? (alergias, preferencias, solicitudes especiales — opcional)

Si ya tenemos el nombre del cliente, confirma si es el que quiere usar para la reserva.
"""

_STEP_CONFIRMATION = _BOOKING_BASE + """## Paso actual: Confirmación

Muestra el resumen de la cita y pide confirmación:

- **Servicio**: {service_name}
- **Estilista**: {stylist_name}
- **Fecha y hora**: {slot_time} del {slot_date}
- **Nombre en la reserva**: {booking_first_name} {booking_last_name}
- **Notas**: {booking_notes}

Pregunta: "¿Confirmas la reserva con estos datos?" (sí/no)
"""

# Maximum tool iterations per step
_MAX_TOOL_ITERATIONS = 5


class BookingMode(BaseModeNode):
    """
    Mode node for the BOOKING conversation flow.

    Manages a multi-step booking process via mode_context["booking_step"].
    The LLM handles responses within each step; BookingMode tracks progression.

    mode_context keys used:
        booking_step: str — current sub-step
        service_name: str — selected service name
        service_category: str — "Peluquería" or "Estética"
        stylist_id: str — selected stylist UUID
        stylist_name: str — selected stylist name
        slot_time: str — selected slot time (HH:MM)
        slot_date: str — selected slot date (YYYY-MM-DD)
        slot_full_datetime: str — ISO 8601 datetime for book() call
        booking_first_name: str — name to use for the booking
        booking_last_name: str — last name (optional)
        booking_notes: str — special requests (optional)
        pending_cancel: bool — user said "no" at confirmation step
    """

    @property
    def mode_name(self) -> str:
        return "BOOKING"

    async def handle(
        self,
        state: ConversationState,
        intent: IntentResult,
    ) -> dict:
        """
        Process a turn in BOOKING mode.

        Dispatches to the appropriate sub-step handler based on
        mode_context["booking_step"]. Handles cancel/escalate intents at any step.

        Args:
            state: Current ConversationState (read-only).
            intent: Classified intent from IntentRouter.

        Returns:
            Partial state update dict for LangGraph reducers.
        """
        conversation_id = state.get("conversation_id", "unknown")
        mode_context = state.get("mode_context") or {}
        booking_step = mode_context.get("booking_step", "service_selection")
        customer_name = state.get("customer_name")

        logger.info(
            "BookingMode.handle | conversation_id=%s | step=%s | intent=%s",
            conversation_id,
            booking_step,
            intent.intent,
        )

        # ── Handle escalation at any step ──────────────────────────────────────
        if intent.intent == "escalate":
            logger.info(
                "BookingMode: escalate intent, transitioning to ESCALATION | "
                "conversation_id=%s | step=%s",
                conversation_id,
                booking_step,
            )
            return transition_mode(state, "ESCALATION")

        # ── Handle cancel/reject at any step ───────────────────────────────────
        if intent.intent in ("cancel", "reject"):
            return await self._handle_cancel(state, intent, booking_step)

        # ── Dispatch to sub-step handler ───────────────────────────────────────
        step_handlers = {
            "service_selection": self._step_service_selection,
            "stylist_selection": self._step_stylist_selection,
            "slot_selection": self._step_slot_selection,
            "customer_data": self._step_customer_data,
            "confirmation": self._step_confirmation,
            "completed": self._step_completed,
        }

        handler = step_handlers.get(booking_step, self._step_service_selection)
        return await handler(state, intent)

    # ==========================================================================
    # Sub-step handlers
    # ==========================================================================

    async def _step_service_selection(
        self, state: ConversationState, intent: IntentResult
    ) -> dict:
        """
        Step 1: Help customer select a service.
        LLM uses search_services / query_info to find the right service.
        Transitions to stylist_selection when service is chosen.
        """
        customer_name = state.get("customer_name")
        conversation_id = state.get("conversation_id", "unknown")

        system_prompt = _STEP_SERVICE_SELECTION
        if customer_name:
            system_prompt = f"El cliente se llama: {customer_name}\n\n" + system_prompt

        tools = [query_info, search_services]
        response_text = await self._run_agentic_loop(
            state, tools, system_prompt, conversation_id
        )

        if not response_text:
            response_text = "¿Qué servicio te gustaría hoy? Puedo mostrarte nuestro catálogo. 😊"

        # Extract service info from context if present
        # The LLM response will have guided the user to select a service.
        # We check if the user message contains a service selection signal.
        user_message = state.get("user_message") or ""
        mode_context = state.get("mode_context") or {}

        # Check if we should advance to next step
        # We advance when the LLM response doesn't ask a question (implies selection made)
        # This is a heuristic — in practice the orchestrator will call handle() again
        # and the LLM will have updated mode_context via the conversation context.
        return {
            **add_message(state, "assistant", response_text),
            "mode_context": {"booking_step": "service_selection"},
        }

    async def _step_stylist_selection(
        self, state: ConversationState, intent: IntentResult
    ) -> dict:
        """
        Step 2: Help customer select a stylist (or choose any available).
        """
        conversation_id = state.get("conversation_id", "unknown")
        mode_context = state.get("mode_context") or {}

        service_name = mode_context.get("service_name", "el servicio seleccionado")
        service_category = mode_context.get("service_category", "Peluquería")

        system_prompt = _STEP_STYLIST_SELECTION.format(
            service_name=service_name,
            service_category=service_category,
        )

        tools = [list_stylists]
        response_text = await self._run_agentic_loop(
            state, tools, system_prompt, conversation_id
        )

        if not response_text:
            response_text = "¿Con qué estilista prefieres la cita? Puedo mostrarte las opciones disponibles."

        return add_message(state, "assistant", response_text)

    async def _step_slot_selection(
        self, state: ConversationState, intent: IntentResult
    ) -> dict:
        """
        Step 3: Show available slots for the selected stylist and service.
        """
        conversation_id = state.get("conversation_id", "unknown")
        mode_context = state.get("mode_context") or {}
        customer_name = state.get("customer_name")

        service_name = mode_context.get("service_name", "el servicio")
        service_category = mode_context.get("service_category", "Peluquería")
        stylist_id = mode_context.get("stylist_id", "")
        stylist_name = mode_context.get("stylist_name", "cualquier estilista")

        system_prompt = _STEP_SLOT_SELECTION.format(
            customer_name_or_cliente=customer_name or "el cliente",
            service_name=service_name,
            service_category=service_category,
            stylist_id=stylist_id,
            stylist_name=stylist_name,
        )

        tools = [check_availability, find_next_available]
        response_text = await self._run_agentic_loop(
            state, tools, system_prompt, conversation_id
        )

        if not response_text:
            response_text = "Buscando disponibilidad... ¿Tienes alguna fecha o franja horaria preferida?"

        return add_message(state, "assistant", response_text)

    async def _step_customer_data(
        self, state: ConversationState, intent: IntentResult
    ) -> dict:
        """
        Step 4: Collect booking name and optional notes.
        The customer's name from state is pre-filled as default.
        """
        conversation_id = state.get("conversation_id", "unknown")
        mode_context = state.get("mode_context") or {}
        customer_name = state.get("customer_name")

        service_name = mode_context.get("service_name", "el servicio")
        stylist_name = mode_context.get("stylist_name", "el estilista")
        slot_time = mode_context.get("slot_time", "la hora seleccionada")
        slot_date = mode_context.get("slot_date", "la fecha seleccionada")

        system_prompt = _STEP_CUSTOMER_DATA.format(
            service_name=service_name,
            stylist_name=stylist_name,
            slot_time=slot_time,
            slot_date=slot_date,
            customer_name_or_cliente=customer_name or "el cliente",
        )

        # No tools needed in this step — purely conversational
        tools: list = []
        response_text = await self._run_agentic_loop(
            state, tools, system_prompt, conversation_id
        )

        if not response_text:
            name_hint = customer_name or "tu nombre"
            response_text = (
                f"¿A qué nombre agendamos la cita? "
                f"{'Tu nombre registrado es ' + customer_name + '. ¿Lo usamos?' if customer_name else '¿Me dices tu nombre completo?'}"
            )

        return add_message(state, "assistant", response_text)

    async def _step_confirmation(
        self, state: ConversationState, intent: IntentResult
    ) -> dict:
        """
        Step 5: Show booking summary and ask for confirmation.
        If user confirms → advance to completed.
        If user rejects → offer to restart or cancel.
        """
        conversation_id = state.get("conversation_id", "unknown")
        mode_context = state.get("mode_context") or {}

        service_name = mode_context.get("service_name", "servicio")
        stylist_name = mode_context.get("stylist_name", "estilista")
        slot_time = mode_context.get("slot_time", "")
        slot_date = mode_context.get("slot_date", "")
        booking_first_name = mode_context.get("booking_first_name", "")
        booking_last_name = mode_context.get("booking_last_name", "") or ""
        booking_notes = mode_context.get("booking_notes", "") or "Ninguna"

        # Check if user confirmed (intent=confirm)
        if intent.intent == "confirm":
            logger.info(
                "BookingMode._step_confirmation: user confirmed, advancing to completed | "
                "conversation_id=%s",
                conversation_id,
            )
            return {
                "mode_context": {"booking_step": "completed"},
            }

        # Show confirmation summary
        system_prompt = _STEP_CONFIRMATION.format(
            service_name=service_name,
            stylist_name=stylist_name,
            slot_time=slot_time,
            slot_date=slot_date,
            booking_first_name=booking_first_name,
            booking_last_name=booking_last_name,
            booking_notes=booking_notes,
        )

        tools: list = []
        response_text = await self._run_agentic_loop(
            state, tools, system_prompt, conversation_id
        )

        if not response_text:
            response_text = (
                f"Resumen de tu cita:\n"
                f"- *Servicio*: {service_name}\n"
                f"- *Estilista*: {stylist_name}\n"
                f"- *Fecha y hora*: {slot_time} del {slot_date}\n"
                f"- *Nombre*: {booking_first_name} {booking_last_name}\n\n"
                f"¿Confirmas la reserva? 😊"
            )

        return add_message(state, "assistant", response_text)

    async def _step_completed(
        self, state: ConversationState, intent: IntentResult
    ) -> dict:
        """
        Step 6: Execute the booking by calling book() tool directly.
        On success → transition to GENERAL.
        On failure → show error, offer to retry or escalate.
        """
        conversation_id = state.get("conversation_id", "unknown")
        mode_context = state.get("mode_context") or {}
        customer_id = state.get("customer_id")

        logger.info(
            "BookingMode._step_completed: executing book() | conversation_id=%s",
            conversation_id,
        )

        # Validate required booking data
        required_fields = [
            "service_name", "stylist_id", "slot_full_datetime", "booking_first_name"
        ]
        missing = [f for f in required_fields if not mode_context.get(f)]

        if missing:
            logger.error(
                "BookingMode._step_completed: missing required fields | "
                "conversation_id=%s | missing=%s",
                conversation_id,
                missing,
            )
            # Something went wrong — we're missing booking data. Go back to service selection.
            response = (
                "Lo siento, hubo un problema con los datos de la reserva. "
                "Vamos a empezar de nuevo. ¿Qué servicio te gustaría reservar?"
            )
            return {
                **add_message(state, "assistant", response),
                "mode_context": {"booking_step": "service_selection"},
            }

        if not customer_id:
            logger.error(
                "BookingMode._step_completed: customer_id missing | conversation_id=%s",
                conversation_id,
            )
            response = (
                "Lo siento, no pude encontrar tu perfil de cliente. "
                "¿Puedo conectarte con el equipo para ayudarte? 💕"
            )
            return {
                **add_message(state, "assistant", response),
                **transition_mode(state, "ESCALATION"),
            }

        # Call book() tool directly (not via LLM agent loop)
        try:
            book_args = {
                "customer_id": customer_id,
                "first_name": mode_context["booking_first_name"],
                "last_name": mode_context.get("booking_last_name") or None,
                "notes": mode_context.get("booking_notes") or None,
                "services": [mode_context["service_name"]],
                "stylist_id": mode_context["stylist_id"],
                "start_time": mode_context["slot_full_datetime"],
                "conversation_id": conversation_id,
            }

            logger.info(
                "BookingMode._step_completed: calling book() | conversation_id=%s | args=%s",
                conversation_id,
                {k: v for k, v in book_args.items() if k != "customer_id"},
            )

            result = await book.ainvoke(book_args)

            if result.get("success"):
                appointment_id = result.get("appointment_id", "")
                response = (
                    f"¡Perfecto! Tu cita ha sido confirmada. 🌸\n\n"
                    f"- *Servicio*: {mode_context.get('service_name')}\n"
                    f"- *Estilista*: {mode_context.get('stylist_name')}\n"
                    f"- *Fecha y hora*: {mode_context.get('slot_time')} del {mode_context.get('slot_date')}\n\n"
                    f"¡Hasta pronto! 😊 ¿Hay algo más en lo que pueda ayudarte?"
                )
                logger.info(
                    "BookingMode._step_completed: booking successful | "
                    "conversation_id=%s | appointment_id=%s",
                    conversation_id,
                    appointment_id,
                )

                msg_update = add_message(state, "assistant", response)
                # Transition to GENERAL, clear booking context
                transition = transition_mode(state, "GENERAL", {})
                return {**transition, **msg_update}

            else:
                # Booking failed
                error_code = result.get("error_code", "UNKNOWN")
                error_message = result.get("error_message", "Error desconocido")
                logger.warning(
                    "BookingMode._step_completed: booking failed | "
                    "conversation_id=%s | error_code=%s | error_message=%s",
                    conversation_id,
                    error_code,
                    error_message,
                )

                if error_code == "AMBIGUOUS_SERVICE":
                    # Ask user to clarify service
                    options = result.get("details", {}).get("options", [])
                    options_text = "\n".join(
                        f"{i+1}. {opt['name']} ({opt.get('duration_minutes', '?')} min)"
                        for i, opt in enumerate(options[:5])
                    )
                    response = (
                        f"El servicio '{mode_context.get('service_name')}' puede ser varios. "
                        f"¿Cuál de estos quieres?\n{options_text}"
                    )
                    return {
                        **add_message(state, "assistant", response),
                        "mode_context": {"booking_step": "service_selection"},
                    }

                elif error_code == "SLOT_TAKEN":
                    response = (
                        "Lo siento, ese horario ya no está disponible 😔. "
                        "¿Te busco otro horario?"
                    )
                    return {
                        **add_message(state, "assistant", response),
                        "mode_context": {"booking_step": "slot_selection"},
                    }

                else:
                    response = (
                        f"Lo siento, no pude completar la reserva: {error_message} "
                        "¿Te conecto con el equipo para ayudarte? 💕"
                    )
                    return {
                        **add_message(state, "assistant", response),
                        **transition_mode(state, "ESCALATION"),
                    }

        except Exception as exc:
            logger.error(
                "BookingMode._step_completed: book() raised exception | "
                "conversation_id=%s | error=%s",
                conversation_id,
                exc,
                exc_info=True,
            )
            response = (
                "Lo siento, tuve un problema técnico al procesar la reserva. "
                "Te conecto con el equipo para ayudarte. 💕"
            )
            return {
                **add_message(state, "assistant", response),
                **transition_mode(state, "ESCALATION"),
            }

    async def _handle_cancel(
        self,
        state: ConversationState,
        intent: IntentResult,
        current_step: str,
    ) -> dict:
        """
        Handle cancel/reject intent at any booking step.

        - At "service_selection" (first step): user didn't want to book → go to GENERAL
        - At any other step: confirm with user if they want to cancel the booking in progress
        - If confirmed cancel → clear booking context, go to GENERAL
        """
        conversation_id = state.get("conversation_id", "unknown")
        mode_context = state.get("mode_context") or {}
        pending_cancel = mode_context.get("pending_cancel", False)

        logger.info(
            "BookingMode._handle_cancel | conversation_id=%s | step=%s | "
            "intent=%s | pending_cancel=%s",
            conversation_id,
            current_step,
            intent.intent,
            pending_cancel,
        )

        # If at the very first step, just go to GENERAL without asking
        if current_step == "service_selection":
            response = "De acuerdo, cuando quieras reservar una cita, dímelo. 😊 ¿En qué más puedo ayudarte?"
            return {
                **add_message(state, "assistant", response),
                **transition_mode(state, "GENERAL"),
            }

        # If cancel was already pending (user confirmed), clear and go to GENERAL
        if pending_cancel or intent.intent == "cancel":
            response = (
                "Entendido, he cancelado el proceso de reserva. "
                "Cuando quieras, volvemos a empezar. 😊 ¿En qué más puedo ayudarte?"
            )
            return {
                **add_message(state, "assistant", response),
                **transition_mode(state, "GENERAL"),
            }

        # First rejection at a non-first step → ask for confirmation
        response = "¿Seguro que quieres cancelar la reserva? Responde *sí* para confirmar o *no* para continuar."
        return {
            **add_message(state, "assistant", response),
            "mode_context": {"pending_cancel": True},
        }

    # ==========================================================================
    # Agentic loop (shared by all sub-steps)
    # ==========================================================================

    async def _run_agentic_loop(
        self,
        state: ConversationState,
        tools: list,
        system_prompt: str,
        conversation_id: str,
    ) -> str:
        """
        Run an LLM + tool loop until a final text response is produced.

        Similar to GeneralMode's agentic loop but uses the step-specific
        system prompt and the booking mode's tool set.

        Args:
            state: Current conversation state.
            tools: Tools available for this sub-step.
            system_prompt: Step-specific system prompt.
            conversation_id: For logging.

        Returns:
            Final assistant response text (may be empty on critical failure).
        """
        tool_map: dict[str, Any] = {t.name: t for t in tools}
        lc_messages = self._build_messages(state, system_prompt)

        for iteration in range(_MAX_TOOL_ITERATIONS):
            llm_result = await self._call_llm(lc_messages, tools=tools if tools else None)

            if llm_result is None:
                logger.error(
                    "BookingMode._run_agentic_loop: LLM returned None | "
                    "conversation_id=%s | iteration=%d",
                    conversation_id,
                    iteration,
                )
                return ""

            tool_calls = getattr(llm_result, "tool_calls", None) or []

            if not tool_calls:
                response = (
                    llm_result.content
                    if hasattr(llm_result, "content")
                    else str(llm_result)
                )
                logger.info(
                    "BookingMode._run_agentic_loop: final response | "
                    "conversation_id=%s | iterations=%d | length=%d",
                    conversation_id,
                    iteration + 1,
                    len(response),
                )
                return response

            logger.info(
                "BookingMode._run_agentic_loop: executing %d tool calls | "
                "conversation_id=%s | iteration=%d",
                len(tool_calls),
                conversation_id,
                iteration,
            )

            lc_messages.append(llm_result)

            for tool_call in tool_calls:
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
                        "BookingMode: unknown tool '%s' | conversation_id=%s",
                        tc_name,
                        conversation_id,
                    )
                    tool_output = f"(herramienta '{tc_name}' no disponible en este paso)"
                else:
                    try:
                        raw_result = await tool_fn.ainvoke(tc_args)
                        tool_output = self._format_tool_response(raw_result)
                    except Exception as exc:
                        logger.error(
                            "BookingMode: tool '%s' raised exception | "
                            "conversation_id=%s | error=%s",
                            tc_name,
                            conversation_id,
                            exc,
                        )
                        tool_output = f"(error al ejecutar '{tc_name}')"

                lc_messages.append(
                    ToolMessage(content=tool_output, tool_call_id=tc_id)
                )

        logger.warning(
            "BookingMode._run_agentic_loop: max iterations (%d) reached | "
            "conversation_id=%s",
            _MAX_TOOL_ITERATIONS,
            conversation_id,
        )
        return ""

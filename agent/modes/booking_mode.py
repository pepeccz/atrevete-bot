"""
Booking Mode — v6.0 Mode-Based Architecture.

Handles the full multi-step appointment booking flow. This mode is isolated from
GREETING — it never asks for the customer name, eliminating the infinite loop bug.

Sub-steps (stored in mode_context["booking_step"]):
1. service_selection — user selects a service
2. stylist_selection — user selects a stylist (or any/no preference)
3. slot_selection — user picks a date/time slot
4. customer_data — collect first_name and optional notes
5. confirmation — show summary, ask user to confirm
6. completed — call book() tool, appointment created

Routing between steps is handled by _determine_step() and _advance_step().
Step transitions are conservative: only advance when we have enough data.

Tools used per step:
- service_selection: [query_info, search_services]
- stylist_selection: [list_stylists]
- slot_selection: [check_availability, find_next_available]
- customer_data: [] (no tools — just conversation)
- confirmation: [] (no tools — show summary)
- completed: call book() directly (not via agentic loop)
"""

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.modes.base import AgenticLoopResult, BaseModeNode
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)

# ── Booking sub-steps ─────────────────────────────────────────────────────────
STEP_SERVICE_SELECTION = "service_selection"
STEP_STYLIST_SELECTION = "stylist_selection"
STEP_SLOT_SELECTION = "slot_selection"
STEP_CUSTOMER_DATA = "customer_data"
STEP_CONFIRMATION = "confirmation"
STEP_COMPLETED = "completed"

# Ordered sequence of steps
_STEP_ORDER = [
    STEP_SERVICE_SELECTION,
    STEP_STYLIST_SELECTION,
    STEP_SLOT_SELECTION,
    STEP_CUSTOMER_DATA,
    STEP_CONFIRMATION,
    STEP_COMPLETED,
]

# ── System prompts per step ───────────────────────────────────────────────────

_SYSTEM_SERVICE_SELECTION = """Eres Maite, asistenta de Atrévete Peluquería.
El cliente quiere reservar una cita. Ayúdale a elegir el servicio.
- Usa query_info para mostrar categorías de servicios disponibles.
- Usa search_services si el cliente menciona un servicio específico.
- Sé concisa (2-4 frases). No preguntes por fecha ni estilista todavía.
- Una vez el cliente elija un servicio, confírmalo."""

_SYSTEM_STYLIST_SELECTION = """Eres Maite, asistenta de Atrévete Peluquería.
El cliente ya eligió el servicio: {service_name}.
Ahora debe elegir una estilista o indicar que no tiene preferencia.
- Usa list_stylists para mostrar las estilistas disponibles.
- Sé concisa. Pregunta si tiene preferencia o si cualquiera está bien."""

_SYSTEM_SLOT_SELECTION = """Eres Maite, asistenta de Atrévete Peluquería.
Servicio: {service_name} | Estilista: {stylist_name}
Ahora el cliente debe elegir fecha y hora.
- Usa find_next_available para mostrar los próximos huecos disponibles.
- Usa check_availability si el cliente pide una fecha específica.
- Sé concisa. Muestra máximo 5 opciones."""

_SYSTEM_CUSTOMER_DATA = """Eres Maite, asistenta de Atrévete Peluquería.
Necesitamos el nombre del cliente para la reserva.
Servicio: {service_name} | Estilista: {stylist_name} | Fecha: {slot_summary}
Pide amablemente:
1. Nombre (obligatorio)
2. Alguna nota especial para la cita (opcional)
No uses herramientas. Solo conversa."""

_SYSTEM_CONFIRMATION = """Eres Maite, asistenta de Atrévete Peluquería.
Muestra el resumen de la reserva y pide confirmación:

📋 Resumen:
- Servicio: {service_name}
- Estilista: {stylist_name}
- Fecha/Hora: {slot_summary}
- Nombre: {first_name}
{notes_line}

¿Confirmas la reserva? (Sí/No)"""

_SYSTEM_COMPLETED = """Eres Maite, asistenta de Atrévete Peluquería.
La reserva ha sido creada exitosamente. Informa al cliente con entusiasmo.
Detalles: {booking_details}
Despídete amablemente y pregunta si necesita algo más."""

_SYSTEM_ERROR = """Eres Maite, asistenta de Atrévete Peluquería.
Ha habido un problema al crear la reserva. Disculpa al cliente y ofrece alternativas:
1. Intentar de nuevo
2. Contactar con el equipo directamente
Sé empática y concisa."""


class BookingMode(BaseModeNode):
    """
    Mode node for the full booking flow.

    Sub-steps progress from service_selection through to completed.
    State is stored in mode_context dict (reset on mode transitions).
    """

    @property
    def mode_name(self) -> str:
        return "BOOKING"

    async def handle(self, state: ConversationState, intent: object) -> dict:
        """
        Handle the current booking sub-step.

        Determines which step we're on, handles cancel/escalate intents early,
        then runs the appropriate agentic loop for the current step.

        Cancel/escalate rules:
        - intent=escalate → always transition to ESCALATION
        - intent=cancel → always go directly to GENERAL (no confirmation)
        - intent=reject at service_selection (first step) → go to GENERAL (no confirmation)
        - intent=reject at any other step (with no pending_cancel) → ask confirmation, set pending_cancel=True
        - intent=reject when pending_cancel=True (confirmed cancellation) → go to GENERAL

        Args:
            state: Current conversation state
            intent: IntentResult from router (used for cancel/confirm detection)

        Returns:
            Partial state update dict
        """
        from agent.state.schemas import transition_mode

        conversation_id = state.get("conversation_id", "unknown")
        mode_context = state.get("mode_context") or {}

        current_step = self._determine_step(mode_context)
        intent_signal = getattr(intent, "intent", "") if intent else ""

        self.logger.info(
            "BookingMode.handle | conversation=%s | step=%s | intent=%s | context_keys=%s",
            conversation_id,
            current_step,
            intent_signal,
            list(mode_context.keys()),
        )

        # ── Early exit: escalate intent → always ESCALATION ────────────────
        if intent_signal == "escalate":
            self.logger.info("BookingMode: escalate intent → transitioning to ESCALATION")
            return {
                **transition_mode(state, "ESCALATION"),
                "last_node": "booking",
                "user_message": None,
            }

        # ── Early exit: cancel/reject handling ─────────────────────────────
        pending_cancel = mode_context.get("pending_cancel", False)

        if intent_signal == "cancel":
            # 'cancel' always goes directly to GENERAL (no confirmation dialog)
            self.logger.info("BookingMode: cancel intent → transitioning to GENERAL")
            return {
                **transition_mode(state, "GENERAL"),
                **add_message(state, "assistant", "De acuerdo, he cancelado la reserva. ¿En qué más puedo ayudarte?"),
                "last_node": "booking",
                "user_message": None,
            }

        if intent_signal == "reject":
            if current_step == STEP_SERVICE_SELECTION or pending_cancel:
                # At the first step OR confirmed cancellation → go to GENERAL directly
                self.logger.info(
                    "BookingMode: reject intent (step=%s, pending_cancel=%s) → GENERAL",
                    current_step, pending_cancel,
                )
                return {
                    **transition_mode(state, "GENERAL"),
                    **add_message(state, "assistant", "De acuerdo, he cancelado la reserva. ¿En qué más puedo ayudarte?"),
                    "last_node": "booking",
                    "user_message": None,
                }
            else:
                # At a non-initial step with no pending confirmation → ask to confirm
                self.logger.info("BookingMode: reject intent at mid-step → asking confirmation")
                updated_context = {**mode_context, "last_intent": intent_signal, "pending_cancel": True}
                return {
                    **add_message(state, "assistant", "¿Seguro que quieres cancelar la reserva? Responde 'no' para cancelar o continúa con la reserva."),
                    "mode_context": updated_context,
                    "last_node": "booking",
                    "user_message": None,
                }

        # Store intent signal in mode_context for confirmation step
        mode_context = {**mode_context, "last_intent": str(intent_signal)}

        # Dispatch to step handler
        handler_map = {
            STEP_SERVICE_SELECTION: self._handle_service_selection,
            STEP_STYLIST_SELECTION: self._handle_stylist_selection,
            STEP_SLOT_SELECTION: self._handle_slot_selection,
            STEP_CUSTOMER_DATA: self._handle_customer_data,
            STEP_CONFIRMATION: self._handle_confirmation,
            STEP_COMPLETED: self._handle_completed,
        }

        handler = handler_map.get(current_step, self._handle_service_selection)
        return await handler(state, mode_context)

    # ── Step handlers ─────────────────────────────────────────────────────────

    async def _handle_service_selection(
        self, state: ConversationState, mode_context: dict
    ) -> dict:
        """Step 1: Help customer select a service."""
        from agent.tools.info_tools import query_info
        from agent.tools.search_services import search_services

        if self._use_optimized_prompts():
            messages = await self._build_layered_messages(
                state, mode_context, step_name=STEP_SERVICE_SELECTION
            )
        else:
            messages = self._build_messages(state, _SYSTEM_SERVICE_SELECTION)
        result = await self._run_agentic_loop(
            messages, tools=[query_info, search_services]
        )

        # Check if a service was identified
        next_step, updated_context = self._advance_step(
            result, STEP_SERVICE_SELECTION, mode_context
        )

        return {
            **add_message(state, "assistant", result.response_text),
            "mode_context": {**updated_context, "booking_step": next_step},
            "last_node": "booking",
            "user_message": None,
        }

    async def _handle_stylist_selection(
        self, state: ConversationState, mode_context: dict
    ) -> dict:
        """Step 2: Help customer select a stylist."""
        from agent.tools.info_tools import list_stylists

        service_name = mode_context.get("service_name", "el servicio solicitado")

        if self._use_optimized_prompts():
            messages = await self._build_layered_messages(
                state, mode_context, step_name=STEP_STYLIST_SELECTION
            )
        else:
            system = _SYSTEM_STYLIST_SELECTION.format(service_name=service_name)
            messages = self._build_messages(state, system)
        result = await self._run_agentic_loop(messages, tools=[list_stylists])

        next_step, updated_context = self._advance_step(
            result, STEP_STYLIST_SELECTION, mode_context
        )

        return {
            **add_message(state, "assistant", result.response_text),
            "mode_context": {**updated_context, "booking_step": next_step},
            "last_node": "booking",
            "user_message": None,
        }

    async def _handle_slot_selection(
        self, state: ConversationState, mode_context: dict
    ) -> dict:
        """Step 3: Help customer select a date/time slot."""
        from agent.tools.availability_tools import check_availability, find_next_available

        if self._use_optimized_prompts():
            messages = await self._build_layered_messages(
                state, mode_context, step_name=STEP_SLOT_SELECTION
            )
        else:
            service_name = mode_context.get("service_name", "el servicio")
            stylist_name = mode_context.get("stylist_name", "cualquier estilista")
            system = _SYSTEM_SLOT_SELECTION.format(
                service_name=service_name,
                stylist_name=stylist_name,
            )
            messages = self._build_messages(state, system)
        result = await self._run_agentic_loop(
            messages, tools=[check_availability, find_next_available]
        )

        next_step, updated_context = self._advance_step(
            result, STEP_SLOT_SELECTION, mode_context
        )

        return {
            **add_message(state, "assistant", result.response_text),
            "mode_context": {**updated_context, "booking_step": next_step},
            "last_node": "booking",
            "user_message": None,
        }

    async def _handle_customer_data(
        self, state: ConversationState, mode_context: dict
    ) -> dict:
        """Step 4: Collect customer name and optional notes."""
        if self._use_optimized_prompts():
            messages = await self._build_layered_messages(
                state, mode_context, step_name=STEP_CUSTOMER_DATA
            )
        else:
            service_name = mode_context.get("service_name", "el servicio")
            stylist_name = mode_context.get("stylist_name", "la estilista")
            slot_summary = mode_context.get("slot_summary", "la fecha seleccionada")
            system = _SYSTEM_CUSTOMER_DATA.format(
                service_name=service_name,
                stylist_name=stylist_name,
                slot_summary=slot_summary,
            )
            messages = self._build_messages(state, system)
        result = await self._run_agentic_loop(messages, tools=[])

        # Extract name/notes from latest user message
        updated_context = self._extract_customer_data(state, mode_context)

        next_step, updated_context = self._advance_step(
            result, STEP_CUSTOMER_DATA, updated_context
        )

        return {
            **add_message(state, "assistant", result.response_text),
            "mode_context": {**updated_context, "booking_step": next_step},
            "last_node": "booking",
            "user_message": None,
        }

    async def _handle_confirmation(
        self, state: ConversationState, mode_context: dict
    ) -> dict:
        """Step 5: Show booking summary and wait for confirmation."""
        if self._use_optimized_prompts():
            messages = await self._build_layered_messages(
                state, mode_context, step_name=STEP_CONFIRMATION
            )
        else:
            service_name = mode_context.get("service_name", "el servicio")
            stylist_name = mode_context.get("stylist_name", "la estilista")
            slot_summary = mode_context.get("slot_summary", "la fecha")
            first_name = mode_context.get("first_name", "Cliente")
            notes = mode_context.get("notes", "")
            notes_line = f"- Notas: {notes}" if notes else ""

            system = _SYSTEM_CONFIRMATION.format(
                service_name=service_name,
                stylist_name=stylist_name,
                slot_summary=slot_summary,
                first_name=first_name,
                notes_line=notes_line,
            )
            messages = self._build_messages(state, system)
        result = await self._run_agentic_loop(messages, tools=[])

        next_step, updated_context = self._advance_step(
            result, STEP_CONFIRMATION, mode_context
        )

        return {
            **add_message(state, "assistant", result.response_text),
            "mode_context": {**updated_context, "booking_step": next_step},
            "last_node": "booking",
            "user_message": None,
        }

    async def _handle_completed(
        self, state: ConversationState, mode_context: dict
    ) -> dict:
        """Step 6: Execute book() tool and confirm booking."""
        from agent.tools.booking_tools import book

        service_name = mode_context.get("service_name", "")
        service_id = mode_context.get("service_id")
        stylist_id = mode_context.get("stylist_id")
        selected_slot = mode_context.get("selected_slot", {})
        first_name = mode_context.get("first_name", "")
        notes = mode_context.get("notes", "")
        customer_phone = state.get("customer_phone", "")

        booking_result: dict[str, Any] = {}
        error_text: str | None = None

        try:
            booking_result = await book.ainvoke({
                "service_name": service_name,
                "service_id": service_id,
                "stylist_id": stylist_id,
                "start_time": selected_slot.get("start_time", ""),
                "customer_phone": customer_phone,
                "first_name": first_name,
                "notes": notes,
            })

            if "error" in booking_result:
                error_text = booking_result["error"]
        except Exception as exc:
            self.logger.error(
                "BookingMode._handle_completed: book() failed: %s", exc
            )
            error_text = str(exc)

        if error_text:
            if self._use_optimized_prompts():
                messages = await self._build_layered_messages(
                    state, mode_context, step_name="error"
                )
            else:
                messages = self._build_messages(state, _SYSTEM_ERROR)
            result = await self._run_agentic_loop(messages, tools=[])
            return {
                **add_message(state, "assistant", result.response_text),
                "mode_context": {**mode_context, "booking_step": STEP_CONFIRMATION},  # go back
                "last_node": "booking",
                "user_message": None,
            }

        # Success
        if self._use_optimized_prompts():
            messages = await self._build_layered_messages(
                state, mode_context, step_name=STEP_COMPLETED
            )
        else:
            booking_details = str(booking_result)
            system = _SYSTEM_COMPLETED.format(booking_details=booking_details)
            messages = self._build_messages(state, system)
        result = await self._run_agentic_loop(messages, tools=[])

        return {
            **add_message(state, "assistant", result.response_text),
            "mode_context": {**mode_context, "booking_step": STEP_COMPLETED, "booked": True},
            "appointment_created": True,
            "last_node": "booking",
            "user_message": None,
        }

    # ── Helper methods ────────────────────────────────────────────────────────

    def _determine_step(self, mode_context: dict) -> str:
        """
        Determine the current booking sub-step from mode_context.

        Returns the booking_step value or defaults to service_selection.
        """
        step = mode_context.get("booking_step", STEP_SERVICE_SELECTION)
        if step not in _STEP_ORDER:
            self.logger.warning(
                "BookingMode: unknown step %r, defaulting to service_selection", step
            )
            return STEP_SERVICE_SELECTION
        return step

    def _advance_step(
        self,
        result: AgenticLoopResult,
        current_step: str,
        mode_context: dict,
    ) -> tuple[str, dict]:
        """
        Decide whether to advance to the next step based on what was collected.

        Conservative rules — only advance when we have clear evidence:
        - service_selection → stylist_selection: service_name in mode_context
        - stylist_selection → slot_selection: stylist_id in mode_context
        - slot_selection → customer_data: selected_slot in mode_context
        - customer_data → confirmation: first_name in mode_context
        - confirmation → completed: last_intent is "confirm"
        - completed → completed (terminal state)

        Also extracts service/stylist info from tool results when available.

        Returns:
            Tuple of (next_step, updated_mode_context)
        """
        updated_context = dict(mode_context)
        tool_results = result.tool_results

        # Extract service from tool results if single result
        if "search_services" in tool_results:
            services = tool_results["search_services"]
            if isinstance(services, list) and len(services) == 1:
                svc = services[0]
                updated_context.setdefault("service_name", svc.get("name", ""))
                updated_context.setdefault("service_id", svc.get("id"))
                updated_context.setdefault("service_category", svc.get("category", ""))
            elif isinstance(services, dict) and "name" in services:
                updated_context.setdefault("service_name", services.get("name", ""))
                updated_context.setdefault("service_id", services.get("id"))

        # Extract stylist from tool results if single result
        if "list_stylists" in tool_results:
            stylists = tool_results["list_stylists"]
            if isinstance(stylists, list) and len(stylists) == 1:
                stylist = stylists[0]
                updated_context.setdefault("stylist_id", str(stylist.get("id", "")))
                updated_context.setdefault("stylist_name", stylist.get("name", ""))

        # Extract slot from tool results
        for slot_tool in ("check_availability", "find_next_available"):
            if slot_tool in tool_results:
                slots = tool_results[slot_tool]
                if isinstance(slots, list) and slots:
                    first_slot = slots[0]
                    updated_context.setdefault("selected_slot", first_slot)
                    updated_context.setdefault(
                        "slot_summary",
                        first_slot.get("start_time", "fecha seleccionada")
                    )
                elif isinstance(slots, dict) and "start_time" in slots:
                    updated_context.setdefault("selected_slot", slots)
                    updated_context.setdefault(
                        "slot_summary",
                        slots.get("start_time", "fecha seleccionada")
                    )

        # Apply advancement rules
        if current_step == STEP_SERVICE_SELECTION:
            if updated_context.get("service_name"):
                return STEP_STYLIST_SELECTION, updated_context

        elif current_step == STEP_STYLIST_SELECTION:
            if updated_context.get("stylist_id"):
                return STEP_SLOT_SELECTION, updated_context

        elif current_step == STEP_SLOT_SELECTION:
            if updated_context.get("selected_slot"):
                return STEP_CUSTOMER_DATA, updated_context

        elif current_step == STEP_CUSTOMER_DATA:
            # Accept both "first_name" and "booking_first_name" as the name key
            if updated_context.get("first_name") or updated_context.get("booking_first_name"):
                return STEP_CONFIRMATION, updated_context

        elif current_step == STEP_CONFIRMATION:
            last_intent = str(updated_context.get("last_intent", "")).lower()
            if last_intent in ("confirm", "confirmación", "sí", "si", "yes"):
                return STEP_COMPLETED, updated_context

        # No advancement — stay at current step
        return current_step, updated_context

    def _extract_customer_data(
        self, state: ConversationState, mode_context: dict
    ) -> dict:
        """
        Extract first_name and notes from the most recent user message.

        Simple heuristic: treat the user message as the name if it's short (≤ 4 words)
        or look for known patterns like "me llamo", "soy", "mi nombre es".

        Returns updated mode_context with first_name and/or notes set.
        """
        updated_context = dict(mode_context)

        # Find last user message
        user_message = ""
        for msg in reversed(state.get("messages", [])):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break
        if not user_message:
            user_message = state.get("user_message") or ""

        if not user_message.strip():
            return updated_context

        # If we don't have a name yet, try to extract it
        if not updated_context.get("first_name"):
            words = user_message.strip().split()
            filler = {"me", "llamo", "soy", "mi", "nombre", "es", "el", "la"}
            name_words = [w for w in words if w.lower() not in filler]
            if name_words and len(name_words) <= 4:
                candidate = name_words[0].capitalize()
                if len(candidate) > 1:
                    updated_context["first_name"] = candidate

        # If name is already set, treat new message as notes
        elif not updated_context.get("notes") and len(user_message.strip()) > 3:
            # Ignore simple affirmative/negative words as notes
            if user_message.strip().lower() not in {"no", "si", "sí", "nada", "ninguna"}:
                updated_context["notes"] = user_message.strip()

        return updated_context

    def _build_messages(self, state: ConversationState, system_content: str) -> list:
        """
        Build a LangChain message list for the LLM call.

        Includes:
        1. SystemMessage with the step-specific prompt
        2. Optional conversation summary as context
        3. Recent 6 messages from history
        """
        system = system_content
        if state.get("conversation_summary"):
            system += f"\n\nContexto previo:\n{state['conversation_summary']}"

        messages: list = [SystemMessage(content=system)]

        for msg in state.get("messages", [])[-6:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))

        return messages

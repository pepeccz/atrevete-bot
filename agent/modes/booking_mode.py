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
- Si search_services devuelve "clarification_needed": transmite la "question_hint" al cliente
  y espera su respuesta antes de avanzar. No inventes opciones — usa las que vienen en "options".
- Si search_services devuelve "resolved_service": confirma el servicio y avanza.
- Si search_services devuelve "services" (lista): si hay 1 resultado confírmalo; si hay varios
  preséntaselos al cliente para que elija.
- Sé concisa (2-4 frases). No preguntes por fecha ni estilista todavía."""

_SYSTEM_STYLIST_SELECTION = """Eres Maite, asistenta de Atrévete Peluquería.
El cliente ya eligió el servicio: {service_name}.
Ahora debe elegir una estilista o indicar que no tiene preferencia.
- Usa list_stylists para mostrar las estilistas disponibles.
- Sé concisa. Pregunta si tiene preferencia o si cualquiera está bien."""

_SYSTEM_SLOT_SELECTION = """Eres Maite, asistenta de Atrévete Peluquería.
Servicio: {service_name} | Estilista: {stylist_name}{duration_hint}
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

        # BUG-1D FIX: If there's a pending clarification, try to parse the user's
        # answer before running the agentic loop. If we can resolve it directly
        # from the options list, skip the LLM search_services call entirely.
        original_clarification = mode_context.get("pending_clarification")
        if original_clarification:
            user_message = self._get_last_user_message(state)
            if user_message:
                axis, resolved_value = self._parse_clarification_answer(
                    user_message, original_clarification
                )
                if axis and resolved_value:
                    # Find the matching option to extract service metadata directly
                    options = original_clarification.get("options", [])
                    matched_option = next(
                        (opt for opt in options if opt.get("value") == resolved_value),
                        None,
                    )
                    if matched_option:
                        self.logger.info(
                            "BookingMode._handle_service_selection: clarification resolved "
                            "axis=%s value=%s service=%s (no LLM call needed)",
                            axis,
                            resolved_value,
                            matched_option.get("service_name"),
                        )
                        # Build a minimal LLM response to confirm the selection
                        confirmed_context = {
                            **mode_context,
                            "service_name": matched_option.get("service_name", ""),
                            "service_id": matched_option.get("service_id"),
                            "service_duration_minutes": matched_option.get("duration_minutes"),
                        }
                        # Run LLM with just the confirmation system prompt (no tools needed)
                        service_name = confirmed_context["service_name"]
                        confirm_system = (
                            f"Eres Maite, asistenta de Atrévete Peluquería. "
                            f"El cliente eligió el servicio: {service_name}. "
                            f"Confírmale brevemente (1-2 frases) y dile que ahora "
                            f"elegiréis la estilista."
                        )
                        if self._use_optimized_prompts():
                            confirm_messages = await self._build_layered_messages(
                                state, confirmed_context, step_name=STEP_SERVICE_SELECTION
                            )
                        else:
                            confirm_messages = self._build_messages(state, confirm_system)
                        result = await self._run_agentic_loop(confirm_messages, tools=[])

                        next_step, updated_context = self._advance_step(
                            result, STEP_SERVICE_SELECTION, confirmed_context
                        )
                        return {
                            **add_message(state, "assistant", result.response_text),
                            "mode_context": {**updated_context, "booking_step": next_step},
                            "last_node": "booking",
                            "user_message": None,
                        }

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
            duration_minutes = mode_context.get("service_duration_minutes")
            duration_hint = (
                f" | Duración aprox.: {duration_minutes} min" if duration_minutes else ""
            )
            system = _SYSTEM_SLOT_SELECTION.format(
                service_name=service_name,
                stylist_name=stylist_name,
                duration_hint=duration_hint,
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
        stylist_id = mode_context.get("stylist_id")
        selected_slot = mode_context.get("selected_slot", {})
        first_name = mode_context.get("first_name", "")
        notes = mode_context.get("notes", "")

        customer_id = state.get("customer_id") or ""
        conversation_id = state.get("conversation_id") or None

        booking_result: dict[str, Any] = {}
        error_text: str | None = None

        # Build services list: prefer resolved service_name, fallback to empty list
        services_list: list[str] = [service_name] if service_name else []

        try:
            booking_result = await book.ainvoke({
                "customer_id": customer_id,
                "first_name": first_name,
                "last_name": None,
                "notes": notes if notes else None,
                "services": services_list,
                "stylist_id": stylist_id or "",
                "start_time": selected_slot.get("start_time", ""),
                "conversation_id": conversation_id,
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

    def _get_last_user_message(self, state: ConversationState) -> str:
        """Return the most recent user message content from state, or empty string."""
        for msg in reversed(state.get("messages", [])):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return state.get("user_message") or ""

    @staticmethod
    def _parse_clarification_answer(
        message: str,
        pending_clarification: dict,
    ) -> tuple[str | None, str | None]:
        """
        Try to match a user's free-text answer to one of the clarification options.

        BUG-1D FIX: When the user replies to a clarification question (e.g., "Dama",
        "1", "caballero"), this method resolves their answer to a concrete option
        value so the booking flow can bypass the looping LLM search_services call.

        Matching strategy (in priority order):
        1. Numeric index — "1" → options[0]["value"], "2" → options[1]["value"]
        2. Label substring — message contains option["label"] (case-insensitive)
        3. Value substring — message contains option["value"] (case-insensitive)

        Args:
            message: Raw user message text.
            pending_clarification: Dict with keys "axis", "options", "question_hint".
                Each option has at least {"value": str, "label": str}.

        Returns:
            (axis, resolved_value) if a match is found, (None, None) otherwise.
        """
        if not pending_clarification:
            return None, None

        axis: str = pending_clarification.get("axis", "")
        options: list[dict] = pending_clarification.get("options", [])

        if not options:
            return None, None

        msg_stripped = message.strip()
        if not msg_stripped:
            return None, None

        msg_lower = msg_stripped.lower()

        # Strategy 1: Numeric index ("1", "2", etc.)
        if msg_stripped.isdigit():
            idx = int(msg_stripped) - 1  # 1-based → 0-based
            if 0 <= idx < len(options):
                return axis, options[idx]["value"]
            return None, None

        # Strategy 2: Label substring match (bidirectional, requires non-empty msg)
        for opt in options:
            label_lower = opt.get("label", "").lower()
            if label_lower and (label_lower in msg_lower or msg_lower in label_lower):
                return axis, opt["value"]

        # Strategy 3: Value substring match (bidirectional, requires non-empty msg)
        for opt in options:
            value_lower = opt.get("value", "").lower()
            if value_lower and (value_lower in msg_lower or msg_lower in value_lower):
                return axis, opt["value"]

        return None, None

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
        # BUG-1A FIX: always clear stale pending_clarification at start of each turn
        updated_context.pop("pending_clarification", None)
        tool_results = result.tool_results

        # Extract service from tool results — handle 3-shape envelope from search_services
        if "search_services" in tool_results:
            envelope = tool_results["search_services"]

            if isinstance(envelope, dict):
                if "resolved_service" in envelope:
                    # Shape 1: single unambiguous metadata-backed match
                    svc = envelope["resolved_service"]
                    updated_context.setdefault("service_name", svc.get("name", ""))
                    updated_context.setdefault("service_id", svc.get("id"))
                    updated_context.setdefault("service_category", svc.get("category", ""))
                    updated_context.setdefault(
                        "service_duration_minutes", svc.get("duration_minutes")
                    )
                    updated_context.setdefault("service_family", svc.get("family"))
                    # Clear any stale clarification now that we have a resolved service
                    updated_context.pop("pending_clarification", None)

                elif "clarification_needed" in envelope:
                    # Shape 2: metadata-driven clarification needed — do NOT advance step
                    clarification = envelope["clarification_needed"]
                    updated_context["pending_clarification"] = {
                        "axis": clarification.get("axis", ""),
                        "question_hint": clarification.get("question_hint", ""),
                        "options": clarification.get("options", []),
                    }

                elif "services" in envelope:
                    # Shape 3: ranked fuzzy matches (fallback)
                    services = envelope["services"]
                    if isinstance(services, list) and len(services) == 1:
                        svc = services[0]
                        updated_context.setdefault("service_name", svc.get("name", ""))
                        updated_context.setdefault("service_id", svc.get("id"))
                        updated_context.setdefault("service_category", svc.get("category", ""))
                        updated_context.setdefault(
                            "service_duration_minutes", svc.get("duration_minutes")
                        )
                        updated_context.pop("pending_clarification", None)
                    # Multiple services → LLM presents options, no auto-advance
            elif isinstance(envelope, list):
                # Legacy list response — kept for backwards compatibility
                if len(envelope) == 1:
                    svc = envelope[0]
                    updated_context.setdefault("service_name", svc.get("name", ""))
                    updated_context.setdefault("service_id", svc.get("id"))
                    updated_context.setdefault("service_category", svc.get("category", ""))

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
            # Do not advance if clarification is still pending
            if updated_context.get("pending_clarification"):
                return STEP_SERVICE_SELECTION, updated_context
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

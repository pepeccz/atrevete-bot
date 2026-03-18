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
import unicodedata
from datetime import date, datetime
from typing import Any, Mapping, cast

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.modes.booking_context import (
    ALLOWED_TRANSITIONS,
    BookingDraftContext,
    BookingSubstep,
    InterpretationReason,
    SlotInterpretation,
    normalize_booking_substep,
    preserve_booking_context,
    validate_booking_context,
)
from agent.modes.base import AgenticLoopResult, BaseModeNode
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)

_BOOKING_CONTENT_TOKENS: frozenset[str] = frozenset({
    "mujer",
    "hombre",
    "nino",
    "nina",
    "dama",
    "caballero",
    "corte",
    "tinte",
    "color",
    "peluqueria",
    "adulta",
    "adulto",
})

# ── Booking sub-steps ─────────────────────────────────────────────────────────
STEP_SERVICE_SELECTION = BookingSubstep.SERVICE_SELECTION.value
STEP_ADD_ONS = BookingSubstep.ADD_ONS.value
STEP_STYLIST_SELECTION = BookingSubstep.STYLIST_SELECTION.value
STEP_SLOT_SELECTION = BookingSubstep.SLOT_SELECTION.value
STEP_CUSTOMER_NAME = BookingSubstep.CUSTOMER_NAME.value
STEP_NOTES = BookingSubstep.NOTES.value
STEP_CUSTOMER_DATA = STEP_NOTES
STEP_CONFIRMATION = BookingSubstep.CONFIRMATION.value
STEP_COMPLETED = BookingSubstep.COMPLETED.value

# Ordered sequence of steps
_STEP_ORDER = [substep.value for substep in BookingSubstep]

# ── System prompts per step ───────────────────────────────────────────────────

_SYSTEM_SERVICE_SELECTION = """Eres Maite, asistenta de Atrévete Peluquería.
La clienta quiere reservar una cita. Ayúdala a elegir el servicio.
- Usa query_info para mostrar categorías de servicios disponibles.
- Usa search_services si el cliente menciona un servicio específico.
- Si search_services devuelve "clarification_needed": transmite la "question_hint" al cliente
  y espera su respuesta antes de avanzar. No inventes opciones — usa las que vienen en "options".
- Si search_services devuelve "resolved_service": confirma el servicio y avanza.
- Si search_services devuelve "services" (lista): si hay 1 resultado confírmalo; si hay varios
  preséntaselos al cliente para que elija.
- Usa un tono cálido e informal con "te"/"tu", nunca "usted".
- Sé concisa (2-4 frases). No preguntes por fecha ni estilista todavía."""

_SYSTEM_STYLIST_SELECTION = """Eres Maite, asistenta de Atrévete Peluquería.
La clienta ya eligió el servicio: {service_name}.
Categoría del servicio: {service_category}.
Ahora puede elegir una estilista o decirte que no tiene preferencia.
- Usa list_stylists con la categoría del servicio para mostrar solo las estilistas disponibles.
- Si hay estilista recurrente, ofrécela primero de forma cálida.
- Ofrece también la opción de cualquier profesional disponible.
- Usa un tono cálido e informal con "te"/"tu", nunca "usted".
- Sé concisa. Pregunta si tiene preferencia o si cualquiera está bien."""

_SYSTEM_SLOT_SELECTION = """Eres Maite, asistenta de Atrévete Peluquería.
Servicio: {service_name} | Estilista: {stylist_name}{duration_hint}
Ahora la clienta debe elegir fecha y hora.
- Usa find_next_available para mostrar los próximos huecos disponibles cuando no haya rango pedido.
- Usa check_availability si la clienta pide una fecha, rango o franja específica.
- Si el contexto indica substitution_made=True, explica que la fecha solicitada fue ajustada antes de ofrecer horarios.
- Si substitution_reason es minimum_days_rule y tienes min_valid_date, aclara la regla de anticipación mínima y menciona la primera fecha válida.
- Si el contexto indica no_slots_for_stylist=True, ofrece ampliar rango o cambiar de estilista. No cambies de paso automáticamente.
- Nunca inventes disponibilidad: usa únicamente los resultados de las tools.
- Usa un tono cálido e informal con "te"/"tu", nunca "usted".
- Sé concisa. Muestra máximo 5 opciones."""

_SYSTEM_NOTES = """Eres Maite, asistenta de Atrévete Peluquería.
Servicio: {service_name} | Estilista: {stylist_name} | Fecha: {slot_summary}
Ya conocemos los datos de la clienta. No pidas su nombre ni teléfono.
Pregunta solo si quiere dejar alguna nota o pedido especial para la cita.
Si dice que no, avanza igual. No uses herramientas."""

_SYSTEM_CONFIRMATION = """Eres Maite, asistenta de Atrévete Peluquería.
Muestra el resumen de la reserva y pide confirmación con tono cálido e informal:

📋 Resumen:
- Servicio: {service_name}
- Estilista: {stylist_name}
- Fecha/Hora: {slot_summary}
{notes_line}

¿Te va bien así? (Sí/No)"""

_SYSTEM_COMPLETED = """Eres Maite, asistenta de Atrévete Peluquería.
La reserva ha sido creada exitosamente. Informa a la clienta con entusiasmo.
Detalles: {booking_details}
Despídete amablemente y pregunta si necesita algo más, sin usar "usted"."""

_SYSTEM_ERROR = """Eres Maite, asistenta de Atrévete Peluquería.
Ha habido un problema al crear la reserva. Disculpa al cliente y ofrece alternativas:
1. Intentar de nuevo
2. Contactar con el equipo directamente
Usa un tono cálido e informal con "te"/"tu". Sé empática y concisa."""


class BookingMode(BaseModeNode):
    """
    Mode node for the full booking flow.

    Sub-steps progress from service_selection through to completed.
    State is stored in mode_context dict (reset on mode transitions).
    """

    @property
    def mode_name(self) -> str:
        return "BOOKING"

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        raw = (value or "").strip().lower()
        normalized = unicodedata.normalize("NFKD", raw)
        return "".join(char for char in normalized if not unicodedata.combining(char))

    @classmethod
    def _message_starts_over(cls, message: str) -> bool:
        normalized = cls._normalize_text(message)
        return any(
            phrase in normalized
            for phrase in ("empecemos de nuevo", "empezar de nuevo", "cancelar todo", "arranquemos de nuevo")
        )

    @classmethod
    def _message_requests_backtrack(cls, message: str) -> bool:
        normalized = cls._normalize_text(message)
        return any(token in normalized for token in ("volver", "volvamos", "atras", "para atras", "retroceder"))

    @classmethod
    def _message_declines_recommendations(cls, message: str) -> bool:
        normalized = cls._normalize_text(message)
        return normalized in {
            "no",
            "no gracias",
            "no, gracias",
            "solo eso",
            "solo eso gracias",
            "con eso estoy",
        }

    @classmethod
    def _has_booking_content(cls, message: str) -> bool:
        normalized = cls._normalize_text(message)
        return any(token in normalized for token in _BOOKING_CONTENT_TOKENS)

    @classmethod
    def _message_is_explicit_cancellation(cls, message: str) -> bool:
        normalized = cls._normalize_text(message)
        return any(
            phrase in normalized
            for phrase in (
                "no quiero",
                "cancelar",
                "cancelalo",
                "cancelala",
                "cancela",
                "anular",
                "anulalo",
                "anulala",
                "mejor no",
            )
        )

    @classmethod
    def _recommended_services_from_message(
        cls,
        message: str,
        recommendations: list[str] | None,
    ) -> list[str]:
        normalized = cls._normalize_text(message)
        matches: list[str] = []
        for recommendation in recommendations or []:
            if cls._normalize_text(recommendation) in normalized:
                matches.append(recommendation)
        return matches

    @classmethod
    def _extract_time_range(cls, message: str) -> str | None:
        normalized = cls._normalize_text(message)
        if any(token in normalized for token in ("por la tarde", "a la tarde", "tarde")):
            return "afternoon"
        if any(token in normalized for token in ("por la manana", "a la manana", "manana temprano", "morning")):
            return "morning"
        return None

    @classmethod
    def _extract_start_date_hint(cls, message: str) -> str | None:
        normalized = cls._normalize_text(message)
        if "entre " in normalized:
            return message.strip()
        for token in ("hoy", "manana", "pasado manana", "esta semana", "proxima semana"):
            if token in normalized:
                return token
        return None

    @staticmethod
    def _previous_substep(current_step: BookingSubstep) -> BookingSubstep:
        if current_step == BookingSubstep.COMPLETED:
            return BookingSubstep.CONFIRMATION
        if current_step == BookingSubstep.CONFIRMATION:
            return BookingSubstep.NOTES
        if current_step == BookingSubstep.NOTES:
            return BookingSubstep.CUSTOMER_NAME
        if current_step == BookingSubstep.CUSTOMER_NAME:
            return BookingSubstep.SLOT_SELECTION
        if current_step == BookingSubstep.SLOT_SELECTION:
            return BookingSubstep.STYLIST_SELECTION
        if current_step == BookingSubstep.STYLIST_SELECTION:
            return BookingSubstep.ADD_ONS
        if current_step == BookingSubstep.ADD_ONS:
            return BookingSubstep.SERVICE_SELECTION
        return BookingSubstep.SERVICE_SELECTION

    def _rewind_context(
        self,
        mode_context: Mapping[str, Any],
        target: BookingSubstep,
    ) -> BookingDraftContext:
        candidate = dict(mode_context)
        if target == BookingSubstep.SERVICE_SELECTION:
            for key in (
                "stylist_id",
                "stylist_name",
                "recurrent_stylist_id",
                "recurrent_stylist_name",
                "recurrent_stylist_slot_summary",
                "selected_slot",
                "slot_summary",
                "availability_start_date",
                "availability_time_range",
                "add_ons_options",
                "add_ons_declined",
                "customer_name",
                "recommendations_shown",
                "pending_cancel",
            ):
                candidate.pop(key, None)
        elif target == BookingSubstep.ADD_ONS:
            for key in (
                "stylist_id",
                "stylist_name",
                "recurrent_stylist_id",
                "recurrent_stylist_name",
                "recurrent_stylist_slot_summary",
                "selected_slot",
                "slot_summary",
                "availability_start_date",
                "availability_time_range",
                "add_ons_options",
                "add_ons_declined",
                "customer_name",
            ):
                candidate.pop(key, None)
        elif target == BookingSubstep.STYLIST_SELECTION:
            for key in ("selected_slot", "slot_summary", "availability_start_date", "availability_time_range"):
                candidate.pop(key, None)
        elif target == BookingSubstep.SLOT_SELECTION:
            candidate.pop("selected_slot", None)
            candidate.pop("slot_summary", None)
        elif target == BookingSubstep.CUSTOMER_NAME:
            candidate.pop("customer_name", None)
        return self._finalize_mode_context(candidate, target, target)

    def _message_changes_service(self, current_step: BookingSubstep, message: str) -> bool:
        if current_step == BookingSubstep.SERVICE_SELECTION:
            return False
        normalized = self._normalize_text(message)
        service_tokens = (
            "corte",
            "cortar",
            "peinado",
            "barro",
            "mechas",
            "color",
            "tinte",
            "tratamiento",
            "oleo",
        )
        return ("mejor" in normalized or "cambiar" in normalized or "quiero" in normalized) and any(
            token in normalized for token in service_tokens
        )

    def _message_changes_stylist(self, current_step: BookingSubstep, message: str, mode_context: Mapping[str, Any]) -> bool:
        if current_step not in {BookingSubstep.SLOT_SELECTION, BookingSubstep.NOTES, BookingSubstep.CONFIRMATION}:
            return False
        normalized = self._normalize_text(message)
        current_stylist = self._normalize_text(str(mode_context.get("stylist_name") or ""))
        return "con " in normalized and "quiero" in normalized and current_stylist not in normalized

    def _message_changes_slot(self, current_step: BookingSubstep, message: str) -> bool:
        if current_step not in {BookingSubstep.NOTES, BookingSubstep.CONFIRMATION}:
            return False
        normalized = self._normalize_text(message)
        slot_tokens = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo", ":", "hora", "manana", "tarde")
        return ("cambiar" in normalized or "mejor" in normalized or "otro horario" in normalized) and any(
            token in normalized for token in slot_tokens
        )

    @staticmethod
    def _build_recommendation_follow_up(mode_context: Mapping[str, Any]) -> str:
        recommendations = [str(item) for item in mode_context.get("pending_recommendations") or [] if str(item).strip()]
        if not recommendations:
            return ""
        joined = ", ".join(recommendations)
        return f"\n\nSi te copa, también puedo sumarte algo relacionado: {joined}. ¿Te gustaría agregar alguno?"

    def _selected_services(self, mode_context: Mapping[str, Any]) -> list[str]:
        services = [str(item) for item in mode_context.get("selected_services") or [] if str(item).strip()]
        if services:
            return services
        primary = str(mode_context.get("service_name") or "").strip()
        return [primary] if primary else []

    def _response_updates(self, state: ConversationState, response_text: str) -> dict[str, Any]:
        final_response, disclosure_sent = self._maybe_prepend_intro(response_text, state)
        updates: dict[str, Any] = add_message(state, "assistant", final_response)
        if disclosure_sent:
            updates["ai_disclosure_sent"] = True
        return updates

    async def _resolve_add_on_names(
        self, names: list[str], category: str | None
    ) -> list[dict]:
        """
        Resolve combo_recommendations service names to real Service DB records.
        Uses fuzzy name matching (case-insensitive substring). Returns up to 3 results.
        Gracefully returns [] on any DB error.
        """
        from sqlalchemy import select

        from database.connection import get_async_session
        from database.models import Service, ServiceCategory

        if not names:
            return []

        results = []
        try:
            async with get_async_session() as session:
                db_query = select(Service).where(Service.is_active == True)
                if category:
                    if "peluc" in category.lower() or category.upper() == "HAIRDRESSING":
                        db_query = db_query.where(
                            Service.category == ServiceCategory.HAIRDRESSING
                        )
                    elif "estet" in category.lower() or category.upper() == "AESTHETICS":
                        db_query = db_query.where(
                            Service.category == ServiceCategory.AESTHETICS
                        )
                all_services = (await session.execute(db_query)).scalars().all()

            name_lower_map = {s.name.lower(): s for s in all_services}
            for name in names:
                name_l = name.lower().strip()
                match = name_lower_map.get(name_l)
                if not match:
                    match = next(
                        (
                            s
                            for s in all_services
                            if name_l in s.name.lower() or s.name.lower() in name_l
                        ),
                        None,
                    )
                if match:
                    results.append(
                        {
                            "id": str(match.id),
                            "name": match.name,
                            "description": match.description or "",
                            "duration_minutes": match.duration_minutes,
                        }
                    )
                if len(results) >= 3:
                    break
        except Exception as exc:
            self.logger.warning("_resolve_add_on_names failed: %s", exc)
            return []

        return results

    async def _populate_recurrent_stylist(self, state: ConversationState, mode_context: dict[str, Any]) -> dict[str, Any]:
        if mode_context.get("recurrent_stylist_id") or not state.get("customer_id"):
            return mode_context

        from agent.services.availability_service import get_stylist_by_id
        from agent.tools.customer_tools import get_customer_history
        from agent.tools.availability_tools import find_next_available

        customer_id = state.get("customer_id")
        if not customer_id:
            return mode_context

        history = await get_customer_history.ainvoke({"customer_id": customer_id, "limit": 2})
        appointments = history.get("appointments") or []
        if len(appointments) < 2:
            return mode_context

        first_stylist = appointments[0].get("stylist_id")
        if not first_stylist or any(appointment.get("stylist_id") != first_stylist for appointment in appointments[:2]):
            return mode_context

        stylist = await get_stylist_by_id(first_stylist)
        if not stylist:
            return mode_context

        updated_context = dict(mode_context)
        updated_context["recurrent_stylist_id"] = str(stylist.id)
        updated_context["recurrent_stylist_name"] = stylist.name

        category = updated_context.get("service_category") or "Peluquería"
        slots = await find_next_available.ainvoke(
            {
                "service_category": category,
                "stylist_id": str(stylist.id),
                "service_duration_minutes": updated_context.get("service_duration_minutes"),
                "max_days_to_search": 7,
            }
        )
        selected_slots = slots.get("selected_stylist_slots") or []
        if selected_slots:
            slot = selected_slots[0]
            updated_context["recurrent_stylist_slot_summary"] = (
                f"{slot.get('day_name', slot.get('date', 'próximamente'))} a las {slot.get('time', '')}".strip()
            )

        return updated_context

    async def _prefetch_stylist_options(
        self, mode_context: dict
    ) -> dict:
        """
        Pre-fetch stylist list and next available slots before LLM call.

        Calls list_stylists + find_next_available in Python so the LLM
        receives data directly without needing to call tools itself.

        Returns updated mode_context dict with:
          - prefetched_stylists: list of {name, id, next_slot_summary}
          - soonest_any_slot: str summary of the absolute earliest slot
        """
        try:
            from agent.tools.availability_tools import find_next_available
            from agent.tools.info_tools import list_stylists

            service_category = mode_context.get("service_category") or ""
            service_duration_minutes = mode_context.get("service_duration_minutes")

            stylists_result = await list_stylists.ainvoke({"category": service_category})
            availability_result = await find_next_available.ainvoke(
                {
                    "service_category": service_category,
                    "service_duration_minutes": service_duration_minutes,
                    "max_days_to_search": 7,
                }
            )

            available_by_name = {
                str(stylist.get("stylist_name") or ""): stylist
                for stylist in availability_result.get("available_stylists") or []
                if isinstance(stylist, dict)
            }

            def _format_slot_summary(slot: Mapping[str, Any]) -> str:
                day_name = str(slot.get("day_name") or "").strip()
                slot_date = str(slot.get("date") or "").strip()
                slot_time = str(slot.get("time") or "").strip()
                if day_name and slot_date and slot_time:
                    return f"{day_name} {slot_date} a las {slot_time}"
                if day_name and slot_time:
                    return f"{day_name} a las {slot_time}"
                if slot_date and slot_time:
                    return f"{slot_date} a las {slot_time}"
                if slot_time:
                    return f"A las {slot_time}"
                return "Sin disponibilidad próxima"

            prefetched_stylists: list[dict[str, Any]] = []
            soonest_slot: tuple[datetime, str] | None = None

            for stylist in stylists_result.get("stylists") or []:
                stylist_name = str(stylist.get("name") or "")
                availability_entry = available_by_name.get(stylist_name, {})
                slots = availability_entry.get("slots") or []
                first_slot = slots[0] if slots else None
                slot_summary = "Sin disponibilidad próxima"

                if isinstance(first_slot, dict):
                    slot_summary = _format_slot_summary(first_slot)
                    full_datetime = first_slot.get("full_datetime")
                    parsed_datetime: datetime | None = None
                    if isinstance(full_datetime, datetime):
                        parsed_datetime = full_datetime
                    elif isinstance(full_datetime, str):
                        try:
                            parsed_datetime = datetime.fromisoformat(full_datetime)
                        except ValueError:
                            parsed_datetime = None

                    if parsed_datetime is not None:
                        soonest_summary = f"{slot_summary} con {stylist_name}".strip()
                        if soonest_slot is None or parsed_datetime < soonest_slot[0]:
                            soonest_slot = (parsed_datetime, soonest_summary)

                prefetched_stylists.append(
                    {
                        "name": stylist_name,
                        "id": stylist.get("id"),
                        "next_slot_summary": slot_summary,
                    }
                )

            return {
                **mode_context,
                "prefetched_stylists": prefetched_stylists,
                "soonest_any_slot": soonest_slot[1] if soonest_slot else None,
            }
        except Exception as exc:
            self.logger.warning("BookingMode._prefetch_stylist_options failed: %s", exc)
            return mode_context

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
        mode_context = self._hydrate_mode_context(state.get("mode_context") or {})

        current_step = self._determine_step(mode_context)
        intent_signal = getattr(intent, "intent", "") if intent else ""
        user_message = self._get_last_user_message(state)

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
            transition_update = transition_mode(state, "ESCALATION")
            draft_contexts = dict(transition_update.get("draft_contexts") or {})
            draft_contexts["BOOKING"] = preserve_booking_context(mode_context, "ESCALATION")
            return {
                **transition_update,
                "draft_contexts": draft_contexts,
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
                **self._response_updates(
                    state,
                    "De acuerdo, he cancelado la reserva. ¿En qué más puedo ayudarte?",
                ),
                "last_node": "booking",
                "user_message": None,
            }

        if intent_signal == "reject":
            if current_step == STEP_SERVICE_SELECTION and self._has_booking_content(user_message):
                self.logger.warning(
                    "BookingMode: reject intent ignored at service_selection due to booking content | message=%r",
                    user_message,
                )
                return {
                    **self._response_updates(
                        state,
                        "Entiendo. Para seguir bien, decime si buscás un corte, color o si es para mujer, hombre, niño o niña.",
                    ),
                    "mode_context": {**mode_context, "last_intent": "ambiguous"},
                    "last_node": "booking",
                    "user_message": None,
                }

            if current_step == STEP_CONFIRMATION and self._message_is_explicit_cancellation(user_message):
                self.logger.info(
                    "BookingMode: explicit cancellation detected at confirmation -> GENERAL"
                )
                return {
                    **transition_mode(state, "GENERAL"),
                    **self._response_updates(
                        state,
                        "De acuerdo, he cancelado la reserva. ¿En qué más puedo ayudarte?",
                    ),
                    "last_node": "booking",
                    "user_message": None,
                }

            if current_step == STEP_SERVICE_SELECTION or pending_cancel:
                # At the first step OR confirmed cancellation → go to GENERAL directly
                self.logger.info(
                    "BookingMode: reject intent (step=%s, pending_cancel=%s) → GENERAL",
                    current_step, pending_cancel,
                )
                return {
                    **transition_mode(state, "GENERAL"),
                    **self._response_updates(
                        state,
                        "De acuerdo, he cancelado la reserva. ¿En qué más puedo ayudarte?",
                    ),
                    "last_node": "booking",
                    "user_message": None,
                }
            else:
                # At a non-initial step with no pending confirmation → ask to confirm
                self.logger.info("BookingMode: reject intent at mid-step → asking confirmation")
                updated_context = {**mode_context, "last_intent": intent_signal, "pending_cancel": True}
                return {
                    **self._response_updates(
                        state,
                        "¿Seguro que quieres cancelar la reserva? Responde 'no' para cancelar o continúa con la reserva.",
                    ),
                    "mode_context": updated_context,
                    "last_node": "booking",
                    "user_message": None,
                }

        if self._message_starts_over(user_message):
            reset_context = self._finalize_mode_context({}, BookingSubstep.SERVICE_SELECTION, None)
            return {
                **self._response_updates(
                    state,
                    "¡Listo! Empezamos de nuevo. ¿Qué servicio querés agendar?",
                ),
                "mode_context": reset_context,
                "last_node": "booking",
                "user_message": None,
            }

        if self._message_requests_backtrack(user_message) and current_step != BookingSubstep.SERVICE_SELECTION:
            previous_step = self._previous_substep(current_step)
            rewound_context = self._rewind_context(mode_context, previous_step)
            return {
                **self._response_updates(
                    state,
                    f"Dale, volvamos un paso. Retomemos desde {previous_step.value.replace('_', ' ')}.",
                ),
                "mode_context": rewound_context,
                "last_node": "booking",
                "user_message": None,
            }

        if self._message_changes_service(current_step, user_message):
            rewound_context = self._rewind_context(mode_context, BookingSubstep.SERVICE_SELECTION)
            for key in ("service_id", "service_name", "service_category", "service_duration_minutes", "service_family"):
                rewound_context.pop(key, None)
            rewound_context["selected_services"] = []
            rewound_context["pending_recommendations"] = []
            rewound_context["recommendations_shown"] = False
            rewound_context["booking_step"] = BookingSubstep.SERVICE_SELECTION.value
            return {
                **self._response_updates(
                    state,
                    "Perfecto, cambiamos el servicio. Contame cuál querés ahora.",
                ),
                "mode_context": rewound_context,
                "last_node": "booking",
                "user_message": None,
            }

        if self._message_changes_stylist(current_step, user_message, mode_context):
            rewound_context = self._rewind_context(mode_context, BookingSubstep.STYLIST_SELECTION)
            rewound_context.pop("stylist_id", None)
            rewound_context.pop("stylist_name", None)
            rewound_context["booking_step"] = BookingSubstep.STYLIST_SELECTION.value
            return {
                **self._response_updates(
                    state,
                    "Perfecto, cambiamos de profesional. Decime con quién te gustaría atenderte.",
                ),
                "mode_context": rewound_context,
                "last_node": "booking",
                "user_message": None,
            }

        if self._message_changes_slot(current_step, user_message):
            rewound_context = self._rewind_context(mode_context, BookingSubstep.SLOT_SELECTION)
            rewound_context["booking_step"] = BookingSubstep.SLOT_SELECTION.value
            return {
                **self._response_updates(
                    state,
                    "Perfecto, buscamos otro horario. Decime qué día o franja te viene mejor.",
                ),
                "mode_context": rewound_context,
                "last_node": "booking",
                "user_message": None,
            }

        # Store intent signal in mode_context for confirmation step
        mode_context = {**mode_context, "last_intent": str(intent_signal)}

        # Dispatch to step handler
        handler_map: dict[BookingSubstep, Any] = {
            BookingSubstep.SERVICE_SELECTION: self._handle_service_selection,
            BookingSubstep.ADD_ONS: self._handle_add_ons,
            BookingSubstep.STYLIST_SELECTION: self._handle_stylist_selection,
            BookingSubstep.SLOT_SELECTION: self._handle_slot_selection,
            BookingSubstep.CUSTOMER_NAME: self._handle_customer_name,
            BookingSubstep.NOTES: self._handle_notes,
            BookingSubstep.CONFIRMATION: self._handle_confirmation,
            BookingSubstep.COMPLETED: self._handle_completed,
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
                            "service_category": matched_option.get(
                                "category", mode_context.get("service_category", "")
                            ),
                            "service_family": matched_option.get(
                                "family", mode_context.get("service_family")
                            ),
                            "pending_recommendations": matched_option.get("combo_recommendations")
                            or mode_context.get("pending_recommendations")
                            or [],
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
                            result, BookingSubstep.SERVICE_SELECTION, confirmed_context
                        )
                        return {
                            **self._response_updates(state, result.response_text),
                            "mode_context": self._finalize_mode_context(
                                updated_context,
                                next_step,
                                BookingSubstep.SERVICE_SELECTION,
                            ),
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
            result, BookingSubstep.SERVICE_SELECTION, mode_context
        )

        response_text = result.response_text
        if next_step == BookingSubstep.STYLIST_SELECTION and updated_context.get("pending_recommendations"):
            response_text += self._build_recommendation_follow_up(updated_context)
            updated_context["recommendations_shown"] = True

        return {
            **self._response_updates(state, response_text),
            "mode_context": self._finalize_mode_context(
                updated_context,
                next_step,
                BookingSubstep.SERVICE_SELECTION,
            ),
            "last_node": "booking",
            "user_message": None,
        }

    async def _handle_add_ons(
        self, state: ConversationState, mode_context: dict
    ) -> dict:
        """
        Step 2: Offer complementary add-on services from same category.
        Auto-skips if no add_ons_options resolved.
        """
        add_ons_options = mode_context.get("add_ons_options")
        if add_ons_options is None:
            pending = [
                str(x)
                for x in (mode_context.get("pending_recommendations") or [])
                if str(x).strip()
            ]
            category = mode_context.get("service_category")
            add_ons_options = await self._resolve_add_on_names(pending, category)
            mode_context = {**mode_context, "add_ons_options": add_ons_options}

        if not add_ons_options:
            self.logger.info(
                "BookingMode._handle_add_ons: no add-ons available, auto-advancing to stylist_selection"
            )
            next_context = {
                **mode_context,
                "add_ons_options": [],
                "add_ons_declined": False,
                "booking_step": BookingSubstep.STYLIST_SELECTION.value,
            }
            return await self._handle_stylist_selection(state, next_context)

        if self._use_optimized_prompts():
            messages = await self._build_layered_messages(
                state, mode_context, step_name=STEP_ADD_ONS
            )
        else:
            service_name = mode_context.get("service_name", "el servicio")
            options_text = "\n".join(
                f"{i + 1}. {opt['name']} ({opt['duration_minutes']} min) - {opt['description']}"
                for i, opt in enumerate(add_ons_options)
            )
            system = (
                f"Eres Maite, asistenta de Atrévete Peluquería.\n"
                f"La clienta eligió: {service_name}.\n"
                f"Ofrecé estos servicios adicionales disponibles:\n{options_text}\n"
                f"Preguntá si quiere agregar alguno. No insistas si dice que no."
            )
            messages = self._build_messages(state, system)

        result = await self._run_agentic_loop(messages, tools=[])

        user_message = self._get_last_user_message(state)
        declined = self._message_declines_recommendations(user_message)

        updated_context = {
            **mode_context,
            "add_ons_options": add_ons_options,
            "add_ons_declined": declined,
        }

        if not declined:
            user_message_lower = user_message.lower()
            for opt in add_ons_options:
                if opt["name"].lower() in user_message_lower:
                    selected = self._selected_services(updated_context)
                    if opt["name"] not in selected:
                        selected.append(opt["name"])
                    updated_context["selected_services"] = selected

        next_step = BookingSubstep.STYLIST_SELECTION if (
            declined or updated_context.get("stylist_id")
        ) else BookingSubstep.ADD_ONS

        if any(opt["name"].lower() in user_message.lower() for opt in add_ons_options):
            next_step = BookingSubstep.STYLIST_SELECTION
        elif declined:
            next_step = BookingSubstep.STYLIST_SELECTION

        final_context = self._finalize_mode_context(
            updated_context, next_step, BookingSubstep.ADD_ONS
        )

        return {
            **self._response_updates(state, result.response_text),
            "mode_context": final_context,
            "last_node": "booking",
            "user_message": None,
        }

    async def _handle_stylist_selection(
        self, state: ConversationState, mode_context: dict
    ) -> dict:
        """Step 2: Help customer select a stylist."""
        service_name = mode_context.get("service_name", "el servicio solicitado")
        service_category = mode_context.get("service_category") or ""
        user_message = self._get_last_user_message(state)
        updated_context = dict(mode_context)
        if service_category:
            updated_context["service_category"] = service_category
        recommended_from_reply = self._recommended_services_from_message(
            user_message,
            cast(list[str] | None, updated_context.get("pending_recommendations")),
        )

        if recommended_from_reply:
            selected_services = self._selected_services(updated_context)
            for recommendation in recommended_from_reply:
                if recommendation not in selected_services:
                    selected_services.append(recommendation)
            updated_context["selected_services"] = selected_services
            updated_context["pending_recommendations"] = [
                item
                for item in cast(list[str], updated_context.get("pending_recommendations") or [])
                if item not in recommended_from_reply
            ]

        if updated_context.get("pending_recommendations") and self._message_declines_recommendations(user_message):
            updated_context["pending_recommendations"] = []

        updated_context = await self._populate_recurrent_stylist(state, updated_context)
        updated_context = await self._prefetch_stylist_options(updated_context)

        if self._use_optimized_prompts():
            messages = await self._build_layered_messages(
                state, updated_context, step_name=STEP_STYLIST_SELECTION
            )
        else:
            system = _SYSTEM_STYLIST_SELECTION.format(
                service_name=service_name,
                service_category=service_category or "sin categoria informada",
            )
            messages = self._build_messages(state, system)
        result = await self._run_agentic_loop(messages, tools=[])

        next_step, updated_context = self._advance_step(
            result, BookingSubstep.STYLIST_SELECTION, updated_context
        )

        return {
            **self._response_updates(state, result.response_text),
            "mode_context": self._finalize_mode_context(
                updated_context,
                next_step,
                BookingSubstep.STYLIST_SELECTION,
            ),
            "last_node": "booking",
            "user_message": None,
        }

    async def _handle_slot_selection(
        self, state: ConversationState, mode_context: dict
    ) -> dict:
        """Step 3: Help customer select a date/time slot."""
        from agent.tools.availability_tools import check_availability, find_next_available

        user_message = self._get_last_user_message(state)
        updated_context = dict(mode_context)
        time_range = self._extract_time_range(user_message)
        start_date_hint = self._extract_start_date_hint(user_message)
        if time_range:
            updated_context["availability_time_range"] = time_range
        if start_date_hint:
            updated_context["availability_start_date"] = start_date_hint

        if self._use_optimized_prompts():
            messages = await self._build_layered_messages(
                state, updated_context, step_name=STEP_SLOT_SELECTION
            )
        else:
            service_name = updated_context.get("service_name", "el servicio")
            stylist_name = updated_context.get("stylist_name", "cualquier estilista")
            duration_minutes = updated_context.get("service_duration_minutes")
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
            result, BookingSubstep.SLOT_SELECTION, updated_context
        )

        return {
            **self._response_updates(state, result.response_text),
            "mode_context": self._finalize_mode_context(
                updated_context,
                next_step,
                BookingSubstep.SLOT_SELECTION,
            ),
            "last_node": "booking",
            "user_message": None,
        }

    async def _handle_customer_name(
        self, state: ConversationState, mode_context: dict
    ) -> dict:
        """
        Step 5 (conditional): Collect customer name if not already known.
        Auto-skips if customer_name already in state or mode_context.
        """
        existing_name = self._resolve_customer_name(state, mode_context)
        if existing_name and existing_name != "Cliente":
            customer_id = await self._create_customer_if_needed(state, existing_name)
            self.logger.info(
                "BookingMode._handle_customer_name: name already known (%s), auto-advancing to notes",
                existing_name,
            )
            next_context = self._finalize_mode_context(
                {**mode_context, "customer_name": existing_name},
                BookingSubstep.NOTES,
                BookingSubstep.CUSTOMER_NAME,
            )
            updates: dict[str, Any] = {
                "customer_name": existing_name,
                "mode_context": next_context,
                "last_node": "booking",
                "user_message": None,
            }
            if customer_id:
                updates["customer_id"] = customer_id
            return updates

        if self._use_optimized_prompts():
            messages = await self._build_layered_messages(
                state, mode_context, step_name=STEP_CUSTOMER_NAME
            )
        else:
            messages = self._build_messages(
                state,
                "Eres Maite, asistenta de Atrévete Peluquería. "
                "Preguntá a qué nombre se agenda la cita. Una sola pregunta, concisa e informal.",
            )

        result = await self._run_agentic_loop(messages, tools=[])

        user_message = self._get_last_user_message(state)
        customer_name = user_message.strip() if user_message.strip() else None

        updated_context = {**mode_context}
        if customer_name:
            updated_context["customer_name"] = customer_name
            customer_id = await self._create_customer_if_needed(state, customer_name)
            next_step = BookingSubstep.NOTES
        else:
            customer_id = None
            next_step = BookingSubstep.CUSTOMER_NAME

        final_context = self._finalize_mode_context(
            updated_context, next_step, BookingSubstep.CUSTOMER_NAME
        )

        updates: dict[str, Any] = {
            **self._response_updates(state, result.response_text),
            "mode_context": final_context,
            "last_node": "booking",
            "user_message": None,
        }
        if customer_name:
            updates["customer_name"] = customer_name
        if customer_id:
            updates["customer_id"] = customer_id
        return updates

    async def _handle_notes(
        self, state: ConversationState, mode_context: dict
    ) -> dict:
        """Step 4: Collect optional booking notes without asking for the name."""
        if self._use_optimized_prompts():
            messages = await self._build_layered_messages(
                state, mode_context, step_name=STEP_NOTES
            )
        else:
            service_name = mode_context.get("service_name", "el servicio")
            stylist_name = mode_context.get("stylist_name", "la estilista")
            slot_summary = mode_context.get("slot_summary", "la fecha seleccionada")
            system = _SYSTEM_NOTES.format(
                service_name=service_name,
                stylist_name=stylist_name,
                slot_summary=slot_summary,
            )
            messages = self._build_messages(state, system)
        result = await self._run_agentic_loop(messages, tools=[])

        updated_context = self._extract_notes(state, mode_context)

        next_step, updated_context = self._advance_step(
            result, BookingSubstep.NOTES, updated_context, state=state
        )

        return {
            **self._response_updates(state, result.response_text),
            "mode_context": self._finalize_mode_context(
                updated_context,
                next_step,
                BookingSubstep.NOTES,
            ),
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
            notes = mode_context.get("notes", "")
            notes_line = f"- Notas: {notes}" if notes else ""

            system = _SYSTEM_CONFIRMATION.format(
                service_name=service_name,
                stylist_name=stylist_name,
                slot_summary=slot_summary,
                notes_line=notes_line,
            )
            messages = self._build_messages(state, system)
        result = await self._run_agentic_loop(messages, tools=[])

        next_step, updated_context = self._advance_step(
            result, BookingSubstep.CONFIRMATION, mode_context
        )

        return {
            **self._response_updates(state, result.response_text),
            "mode_context": self._finalize_mode_context(
                updated_context,
                next_step,
                BookingSubstep.CONFIRMATION,
            ),
            "last_node": "booking",
            "user_message": None,
        }

    async def _handle_completed(
        self, state: ConversationState, mode_context: dict
    ) -> dict:
        """Step 6: Execute book() tool and confirm booking."""
        from agent.tools.booking_tools import book
        from agent.state.schemas import transition_mode

        service_name = mode_context.get("service_name", "")
        stylist_id = mode_context.get("stylist_id")
        selected_slot = mode_context.get("selected_slot", {})
        first_name = self._resolve_customer_name(state, mode_context)
        notes = mode_context.get("notes", "")

        customer_id = state.get("customer_id") or ""
        conversation_id = state.get("conversation_id") or None

        booking_result: dict[str, Any] = {}
        error_text: str | None = None

        # Build services list: prefer resolved service_name, fallback to empty list
        services_list = self._selected_services(mode_context)

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
                **self._response_updates(state, result.response_text),
                "mode_context": self._finalize_mode_context(
                    mode_context,
                    BookingSubstep.CONFIRMATION,
                    BookingSubstep.COMPLETED,
                ),
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

        transition_update = transition_mode(state, "GENERAL")
        draft_contexts = dict(transition_update.get("draft_contexts") or {})
        draft_contexts.pop("BOOKING", None)

        return {
            **transition_update,
            "draft_contexts": draft_contexts,
            **self._response_updates(state, result.response_text),
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

    def _determine_step(self, mode_context: Mapping[str, Any]) -> BookingSubstep:
        """
        Determine the current booking sub-step from mode_context.

        Returns the booking_step value or defaults to service_selection.
        """
        step = mode_context.get("booking_step", STEP_SERVICE_SELECTION)
        try:
            return normalize_booking_substep(step)
        except ValueError:
            self.logger.warning(
                "BookingMode: unknown step %r, defaulting to service_selection", step
            )
            return BookingSubstep.SERVICE_SELECTION

    def _advance_step(
        self,
        result: AgenticLoopResult,
        current_step: BookingSubstep | str,
        mode_context: dict,
        *,
        state: ConversationState | None = None,
    ) -> tuple[BookingSubstep, BookingDraftContext]:
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
        current_substep = normalize_booking_substep(current_step)
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
                    selected_services = self._selected_services(updated_context)
                    if svc.get("name") and svc.get("name") not in selected_services:
                        selected_services = [svc.get("name"), *selected_services]
                    updated_context["selected_services"] = selected_services
                    recommendations = [
                        str(item) for item in svc.get("combo_recommendations", []) if str(item).strip()
                    ]
                    if recommendations:
                        updated_context["pending_recommendations"] = recommendations
                        updated_context["recommendations_shown"] = False
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
                    if isinstance(services, list):
                        updated_context["candidate_services"] = services
                        updated_context["candidate_service_ids"] = [
                            svc.get("id") for svc in services if svc.get("id")
                        ]
                    if isinstance(services, list) and len(services) == 1:
                        svc = services[0]
                        updated_context.setdefault("service_name", svc.get("name", ""))
                        updated_context.setdefault("service_id", svc.get("id"))
                        updated_context.setdefault("service_category", svc.get("category", ""))
                        updated_context.setdefault(
                            "service_duration_minutes", svc.get("duration_minutes")
                        )
                        updated_context["selected_services"] = self._selected_services(updated_context)
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
            if isinstance(stylists, dict):
                stylists = stylists.get("stylists", [])
            if isinstance(stylists, list) and len(stylists) == 1:
                stylist = stylists[0]
                updated_context.setdefault("stylist_id", str(stylist.get("id", "")))
                updated_context.setdefault("stylist_name", stylist.get("name", ""))

        slot_interpretation = self._interpret_slot_tool_results(tool_results, updated_context)

        if slot_interpretation.get("has_slots") and not updated_context.get("selected_slot"):
            available_slots = slot_interpretation.get("available_slots") or []
            first_slot = available_slots[0] if available_slots else None
            if isinstance(first_slot, dict):
                updated_context.setdefault("selected_slot", first_slot)
                updated_context.setdefault(
                    "slot_summary",
                    first_slot.get("start_time")
                    or first_slot.get("full_datetime")
                    or (f"{first_slot.get('date', '')} {first_slot.get('time', '')}".strip() or "fecha seleccionada")
                )

        if current_substep == BookingSubstep.NOTES:
            if "customer_name" not in updated_context:
                updated_context["customer_name"] = self._resolve_customer_name(state, updated_context)

        # Apply advancement rules
        next_substep = current_substep

        if current_substep == BookingSubstep.SERVICE_SELECTION:
            # Do not advance if clarification is still pending
            if updated_context.get("pending_clarification"):
                next_substep = BookingSubstep.SERVICE_SELECTION
            elif updated_context.get("service_name"):
                next_substep = BookingSubstep.ADD_ONS

        elif current_substep == BookingSubstep.ADD_ONS:
            if (
                not updated_context.get("pending_recommendations")
                or updated_context.get("recommendations_shown")
            ):
                next_substep = BookingSubstep.STYLIST_SELECTION

        elif current_substep == BookingSubstep.STYLIST_SELECTION:
            if updated_context.get("stylist_id"):
                next_substep = BookingSubstep.SLOT_SELECTION

        elif current_substep == BookingSubstep.SLOT_SELECTION:
            if slot_interpretation.get("substitution_made"):
                updated_context["substitution_made"] = True
                updated_context["substitution_reason"] = slot_interpretation.get("substitution_reason")

                date_requested = slot_interpretation.get("date_requested")
                if isinstance(date_requested, date):
                    updated_context["date_requested"] = date_requested.isoformat()

                date_substituted = slot_interpretation.get("date_substituted")
                if isinstance(date_substituted, date):
                    updated_context["date_substituted"] = date_substituted.isoformat()

                min_valid_date = slot_interpretation.get("min_valid_date")
                if isinstance(min_valid_date, date):
                    updated_context["min_valid_date"] = min_valid_date.isoformat()
            else:
                for key in (
                    "substitution_made",
                    "substitution_reason",
                    "date_requested",
                    "date_substituted",
                    "min_valid_date",
                ):
                    updated_context.pop(key, None)

            if slot_interpretation.get("no_slots_for_chosen_stylist"):
                updated_context["no_slots_for_stylist"] = True
            else:
                updated_context.pop("no_slots_for_stylist", None)

            if updated_context.get("selected_slot") and slot_interpretation.get("has_slots"):
                next_substep = BookingSubstep.CUSTOMER_NAME
            elif slot_interpretation.get("no_slots_for_chosen_stylist"):
                next_substep = BookingSubstep.SLOT_SELECTION

        elif current_substep == BookingSubstep.CUSTOMER_NAME:
            customer_name = (
                updated_context.get("customer_name")
                or (state.get("customer_name") if state else None)
                or (state.get("customer_first_name") if state else None)
            )
            if customer_name:
                updated_context["customer_name"] = customer_name
                next_substep = BookingSubstep.NOTES

        elif current_substep == BookingSubstep.NOTES:
            if state and self._has_user_reply(state):
                next_substep = BookingSubstep.CONFIRMATION

        elif current_substep == BookingSubstep.CONFIRMATION:
            last_intent = str(updated_context.get("last_intent", "")).lower()
            if last_intent in ("confirm", "confirmación", "sí", "si", "yes"):
                next_substep = BookingSubstep.COMPLETED

        return next_substep, self._finalize_mode_context(
            updated_context,
            next_substep,
            current_substep,
        )

    @staticmethod
    def _coerce_slot_date(value: Any) -> date | None:
        """Convert tool payload date values into `date` objects when possible."""

        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        return None

    def _interpret_slot_tool_results(
        self,
        tool_results: dict[str, Any],
        mode_context: Mapping[str, Any],
    ) -> SlotInterpretation:
        """Convert raw availability tool payloads into semantic slot interpretation.

        Args:
            tool_results: Raw tool outputs keyed by tool name. Supports current
                semantic payloads and legacy `find_next_available` list responses.
            mode_context: Current booking context, used to detect whether the
                customer already chose a stylist and to preserve stylist-specific
                UX semantics.

        Returns:
            A `SlotInterpretation` that summarizes whether slots exist, whether a
            requested date was adjusted, and whether only the chosen stylist is
            unavailable.

        Example:
            A `find_next_available` payload with `soonest_any`, no
            `selected_stylist_slots`, and an existing `stylist_id` returns an
            interpretation with `no_slots_for_chosen_stylist=True` so the flow
            stays in `slot_selection` instead of backtracking automatically.
        """

        interpretation: SlotInterpretation = {
            "has_slots": False,
            "substitution_made": False,
            "date_requested": None,
            "date_substituted": None,
            "substitution_reason": None,
            "min_valid_date": None,
            "no_slots_for_chosen_stylist": False,
            "no_slots_for_any_stylist": False,
            "stylist_name": None,
            "available_slots": None,
        }

        chosen_stylist_id = mode_context.get("stylist_id")

        for tool_name in ("check_availability", "find_next_available"):
            payload = tool_results.get(tool_name)
            if tool_name == "find_next_available" and isinstance(payload, list):
                slot_list = [slot for slot in payload if isinstance(slot, dict)]
                if slot_list:
                    interpretation["available_slots"] = slot_list
                    interpretation["has_slots"] = True
                else:
                    interpretation["no_slots_for_chosen_stylist"] = bool(chosen_stylist_id)
                    interpretation["no_slots_for_any_stylist"] = not bool(chosen_stylist_id)
                return interpretation
            if not isinstance(payload, dict):
                continue

            interpretation["date_requested"] = self._coerce_slot_date(payload.get("date_requested"))
            interpretation["date_substituted"] = self._coerce_slot_date(payload.get("date_substituted"))
            interpretation["min_valid_date"] = self._coerce_slot_date(payload.get("min_valid_date"))

            substitution_reason = payload.get("substitution_reason")
            if isinstance(substitution_reason, str) and substitution_reason:
                interpretation["substitution_reason"] = substitution_reason

            if interpretation.get("date_substituted") or payload.get("substitution_made"):
                interpretation["substitution_made"] = True
            elif payload.get("date_too_soon"):
                interpretation["substitution_made"] = True
                interpretation["substitution_reason"] = (
                    interpretation.get("substitution_reason")
                    or InterpretationReason.MINIMUM_DAYS_RULE.value
                )

            if tool_name == "check_availability":
                available_slots = payload.get("available_slots")
                slot_list = available_slots if isinstance(available_slots, list) else []
                interpretation["available_slots"] = slot_list
                interpretation["has_slots"] = bool(slot_list)
                if not slot_list:
                    if chosen_stylist_id:
                        interpretation["no_slots_for_chosen_stylist"] = True
                    else:
                        interpretation["no_slots_for_any_stylist"] = True
                return interpretation

            selected_slots = payload.get("selected_stylist_slots")
            selected_slot_list = selected_slots if isinstance(selected_slots, list) else []
            available_dates = payload.get("available_dates")
            available_date_list = available_dates if isinstance(available_dates, list) else []
            soonest_any = payload.get("soonest_any")
            soonest_any_slot = soonest_any if isinstance(soonest_any, dict) else None
            selected_stylist_name = payload.get("selected_stylist_name")
            if isinstance(selected_stylist_name, str) and selected_stylist_name:
                interpretation["stylist_name"] = selected_stylist_name

            if chosen_stylist_id:
                if selected_slot_list:
                    interpretation["available_slots"] = selected_slot_list
                    interpretation["has_slots"] = True
                elif soonest_any_slot and soonest_any_slot.get("is_different_stylist"):
                    interpretation["no_slots_for_chosen_stylist"] = True
                elif soonest_any_slot:
                    interpretation["available_slots"] = [soonest_any_slot]
                    interpretation["has_slots"] = True
                else:
                    interpretation["no_slots_for_chosen_stylist"] = True
            elif available_date_list:
                interpretation["available_slots"] = available_date_list
                interpretation["has_slots"] = True
            elif soonest_any_slot:
                interpretation["available_slots"] = [soonest_any_slot]
                interpretation["has_slots"] = True
            else:
                interpretation["no_slots_for_any_stylist"] = True

            return interpretation

        return interpretation

    def _extract_notes(self, state: ConversationState, mode_context: dict) -> dict:
        """
        Extract optional booking notes from the latest user message.

        Returns updated mode_context with notes normalized and customer name preserved.
        """
        updated_context = dict(mode_context)
        updated_context["customer_name"] = self._resolve_customer_name(state, updated_context)

        user_message = self._get_last_user_message(state).strip()

        if not user_message:
            return updated_context

        normalized = user_message.lower()
        skip_tokens = {
            "no",
            "no gracias",
            "no, gracias",
            "no, nada mas",
            "no, nada más",
            "nada",
            "nada mas",
            "nada más",
            "todo bien",
            "ninguna",
        }
        if normalized in skip_tokens:
            updated_context["notes"] = None
            return updated_context

        updated_context["notes"] = user_message

        return updated_context

    def _resolve_customer_name(self, state: ConversationState | None, mode_context: dict) -> str:
        """Resolve the customer name from mode context or state without re-asking."""

        if mode_context.get("customer_name"):
            return str(mode_context["customer_name"])
        if not state:
            return "Cliente"
        for field_name in ("customer_first_name", "customer_name"):
            value = state.get(field_name)
            if value:
                return str(value)
        return "Cliente"

    async def _create_customer_if_needed(
        self,
        state: ConversationState,
        confirmed_name: str,
    ) -> str | None:
        """Create a customer record when booking reaches the confirmed-name step."""

        from agent.tools.customer_tools import manage_customer

        existing_customer_id = state.get("customer_id")
        if existing_customer_id:
            return str(existing_customer_id)

        customer_phone = state.get("customer_phone", "")
        if not customer_phone:
            self.logger.warning("BookingMode: no customer_phone in state - skipping DB creation")
            return None

        try:
            result = await manage_customer.ainvoke({
                "action": "create",
                "phone": customer_phone,
                "data": {"first_name": confirmed_name},
            })
        except Exception as exc:
            self.logger.error(
                "BookingMode: customer creation failed | name=%s | error=%s",
                confirmed_name,
                exc,
            )
            return None

        if not isinstance(result, dict):
            self.logger.warning(
                "BookingMode: manage_customer returned unexpected non-dict result: %s",
                result,
            )
            return None

        customer_id = result.get("id") or result.get("customer_id")
        if customer_id and "error" not in result:
            customer_id_str = str(customer_id)
            self.logger.info(
                "BookingMode: customer resolved | id=%s | name=%s | phone=%s",
                customer_id_str,
                confirmed_name,
                customer_phone,
            )
            return customer_id_str

        self.logger.warning(
            "BookingMode: manage_customer returned no customer id for phone=%s | result=%s",
            customer_phone,
            result,
        )
        return None

    def _has_user_reply(self, state: ConversationState) -> bool:
        """Return True when the current turn contains user text."""

        return bool(self._get_last_user_message(state).strip())

    def _hydrate_mode_context(self, mode_context: dict[str, Any]) -> BookingDraftContext:
        """Normalize persisted booking context before dispatching handlers."""

        candidate = dict(mode_context)
        current_substep = self._determine_step(candidate)
        candidate["booking_step"] = current_substep.value
        try:
            return validate_booking_context(candidate)
        except ValueError as exc:
            self.logger.warning("BookingMode: continuing with partial context: %s", exc)
            return cast(BookingDraftContext, candidate)

    def _finalize_mode_context(
        self,
        mode_context: Mapping[str, Any],
        next_substep: BookingSubstep | str,
        previous_substep: BookingSubstep | str | None,
    ) -> BookingDraftContext:
        """Persist the next booking substep and validate the resulting draft."""

        target = normalize_booking_substep(next_substep)
        candidate = dict(mode_context)
        candidate["booking_step"] = target.value

        if previous_substep is not None:
            previous = normalize_booking_substep(previous_substep)
            if previous == BookingSubstep.COMPLETED and target == BookingSubstep.COMPLETED:
                return cast(BookingDraftContext, candidate)
            if target not in ALLOWED_TRANSITIONS[previous]:
                raise ValueError(f"Invalid booking transition: {previous.value} -> {target.value}")
            try:
                return validate_booking_context(candidate, previous_substep=previous)
            except ValueError as exc:
                self.logger.warning("BookingMode: partial context after transition: %s", exc)
                return cast(BookingDraftContext, candidate)

        try:
            return validate_booking_context(candidate)
        except ValueError as exc:
            self.logger.warning("BookingMode: partial context without validation: %s", exc)
            return cast(BookingDraftContext, candidate)

    def _build_messages(self, state: ConversationState, system_content: str) -> list:
        """
        Build a LangChain message list for the LLM call.

        Includes:
        1. SystemMessage with the step-specific prompt
        2. Optional conversation summary as context
        3. Recent 6 messages from history
        """
        system = system_content
        summary = state.get("conversation_summary")
        if summary:
            system += f"\n\nContexto previo:\n{summary}"

        messages: list = [SystemMessage(content=system)]

        for msg in state.get("messages", [])[-6:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))

        return messages

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
import re
import unicodedata
from datetime import date, datetime
from typing import Any, Literal, Mapping, TypedDict, cast

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

# ── ADR-1: Slot Invalid-Input Recovery Guard ──────────────────────────────────
# Maximum consecutive invalid slot selections before falling through to LLM loop
SLOT_INVALID_INPUT_MAX = 3

# ── ADR-2: Bounded retry for book() ──────────────────────────────────────────
_BOOK_MAX_ATTEMPTS = 2


# ── PrefetchResult discriminated union ────────────────────────────────────────


class PrefetchOk(TypedDict):
    """Successful prefetch: stylist list + availability data."""

    status: Literal["ok"]
    prefetched_stylists: list[dict[str, Any]]
    soonest_any_slot: str | None
    soonest_any_slot_candidate: dict[str, Any] | None


class PrefetchNoAvailability(TypedDict):
    """Prefetch completed but no slots available for any stylist."""

    status: Literal["no_availability"]
    error_detail: str


class PrefetchToolError(TypedDict):
    """Prefetch failed due to a tool/infrastructure error."""

    status: Literal["tool_error"]
    error_detail: str


PrefetchResult = PrefetchOk | PrefetchNoAvailability | PrefetchToolError

# ─────────────────────────────────────────────────────────────────────────────

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

    def _contains_customer_name_token(
        self,
        response_text: str,
        customer_name: str,
    ) -> bool:
        """
        Returns True if any meaningful token from customer_name appears as a
        word-boundary match (case+accent insensitive) in response_text.

        Tokens shorter than 3 chars (prepositions, articles) are skipped
        to avoid false positives on common words.

        Accent normalization: NFD decomposition drops combining marks so
        "María" matches "Maria" and vice-versa.
        """

        def _nfd_lower(text: str) -> str:
            return "".join(
                c for c in unicodedata.normalize("NFD", text.lower())
                if unicodedata.category(c) != "Mn"
            )

        normalized_response = _nfd_lower(response_text)
        tokens = re.split(r"\W+", customer_name)
        for token in tokens:
            if len(token) < 3:
                continue
            normalized_token = _nfd_lower(token)
            pattern = rf"\b{re.escape(normalized_token)}\b"
            if re.search(pattern, normalized_response):
                return True
        return False

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
    def _is_addon_decline(cls, message: str) -> bool:
        """
        Return True when the message declines add-on recommendations but is NOT
        a booking cancellation. Alias for test-friendly API.

        Accepts: "no gracias", "solo eso", "con eso estoy", etc.
        Rejects: "cancelar la cita", "si agrega peinado", etc.
        """
        if cls._message_is_explicit_cancellation(message):
            return False
        normalized = cls._normalize_text(message)
        decline_phrases = {
            "no",
            "no gracias",
            "no, gracias",
            "solo eso",
            "solo eso gracias",
            "con eso estoy",
            "solo lo que elegi",
            "solo lo que elegí",
            "nada mas",
            "nada más",
        }
        if normalized in decline_phrases:
            return True
        # Check "peinado no, barro tampoco" patterns — all recommendations declined
        return False

    @classmethod
    def _resolve_add_on_intent(
        cls,
        message: str,
        pending_recommendations: list[str],
    ) -> str:
        """
        Classify user reply to an add-on offer.

        Returns one of:
        - "decline": user declines all add-ons
        - "accept": user accepts at least one add-on
        - "cancel": user wants to cancel the booking entirely
        - "unknown": cannot be classified deterministically
        """
        # Explicit booking cancel takes priority
        if cls._message_is_explicit_cancellation(message):
            return "cancel"

        normalized = cls._normalize_text(message)

        # Check for affirmative intent with a specific recommendation
        affirmative_words = ("si", "sí", "agrega", "añade", "anade", "quiero", "también", "tambien")
        has_affirmative = any(word in normalized for word in affirmative_words)
        for rec in pending_recommendations or []:
            rec_norm = cls._normalize_text(rec)
            if rec_norm in normalized and has_affirmative:
                return "accept"

        # Check for "X no, Y tampoco" pattern → decline all listed recommendations
        negation_tokens = ("tampoco", "no,", " no ")
        has_negation = any(pat in normalized for pat in negation_tokens)
        if has_negation:
            all_mentioned = all(
                cls._normalize_text(rec) in normalized
                for rec in (pending_recommendations or [])
            )
            if all_mentioned and pending_recommendations:
                return "decline"

        # Decline prefix phrases (message starts with or contains decline phrases)
        decline_phrases = {
            "no", "no gracias", "no, gracias", "solo eso", "solo eso gracias",
            "con eso estoy", "solo lo que elegi", "nada mas", "nada más",
            "no gracias solo",
        }
        if normalized in decline_phrases:
            return "decline"

        # "no gracias, solo el X" — starts with decline phrase
        decline_prefixes = ("no gracias", "no, gracias", "no ")
        if any(normalized.startswith(prefix) for prefix in decline_prefixes):
            # Ensure there's no affirmative add-on selection
            if not has_affirmative:
                return "decline"

        # "Solo quiero lo que elegí" pattern
        solo_patterns = ("solo quiero", "solo lo que", "solo eso")
        if any(pat in normalized for pat in solo_patterns):
            return "decline"

        # Check positive add-on selection without full affirmative context
        # but skip if the message looks like a question (no affirmative signal)
        question_tokens = ("?", "cuanto", "cuánto", "como", "cómo", "que es", "qué es")
        is_question = any(tok in normalized for tok in question_tokens) or "?" in message
        if not is_question:
            for rec in pending_recommendations or []:
                rec_norm = cls._normalize_text(rec)
                if rec_norm in normalized:
                    return "accept"

        return "unknown"

    @classmethod
    def _is_explicit_booking_cancel(cls, message: str) -> bool:
        """
        Return True when message contains an explicit booking cancellation phrase.
        Alias for _message_is_explicit_cancellation.

        Accepts: "cancelar", "cancelalo", "anular", etc.
        Rejects: "no gracias" (which is an add-on decline, not a booking cancel).
        """
        normalized = cls._normalize_text(message)
        return any(
            phrase in normalized
            for phrase in (
                "cancelar",
                "cancelalo",
                "cancelala",
                "cancela",
                "anular",
                "anulalo",
                "anulala",
            )
        )

    @classmethod
    def _is_non_cancel_booking_qualifier(cls, message: str) -> bool:
        """
        Return True when message is a valid booking substep qualifier that should
        NOT be treated as a booking cancellation.

        Matches no-preference and qualifier phrases that are safe to receive at
        STYLIST_SELECTION, NOTES, or CONFIRMATION substeps.

        Explicit cancellation phrases always return False (cancel takes priority).
        Bare "no" alone does NOT match — it should trigger clarification instead.

        Examples that return True:
            "no tengo preferencia", "sin preferencia", "cualquiera",
            "no importa", "nada mas", "nada más"
        Examples that return False:
            "no" (bare), "quiero cancelar", "cancelar mi cita"
        """
        if cls._message_is_explicit_cancellation(message):
            return False
        normalized = cls._normalize_text(message)
        _QUALIFIER_PHRASES = (
            "no tengo preferencia",
            "sin preferencia",
            "cualquiera",
            "no importa",
            "nada mas",
            "nada más",
        )
        return any(phrase in normalized for phrase in _QUALIFIER_PHRASES)

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
    def _resolve_slot_from_message(cls, message: str, offered_slots: list[dict]) -> dict | None:
        """
        Try to resolve a user message to a specific slot from offered_slots.

        Matching strategy:
        1. Numeric index: "1" → offered_slots[0], "2" → offered_slots[1], etc.
        2. Returns None if the message cannot be matched to any slot.

        Args:
            message: Raw user message text.
            offered_slots: List of slot dicts with at least {"id", "date", "time"}.

        Returns:
            The matched slot dict, or None if no match.
        """
        if not offered_slots:
            return None

        normalized = cls._normalize_text(message).strip()

        # Strategy 1: numeric index
        if normalized.isdigit():
            idx = int(normalized) - 1
            if 0 <= idx < len(offered_slots):
                return offered_slots[idx]

        # Strategy 2: partial time match ("10:00", "12:30")
        for slot in offered_slots:
            slot_time = str(slot.get("time", ""))
            slot_date = str(slot.get("date", ""))
            if slot_time and slot_time in message:
                return slot
            if slot_date and slot_date in message:
                return slot

        return None

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
        from agent.utils.date_parser import parse_natural_date

        normalized = cls._normalize_text(message)
        if "entre " in normalized:
            return message.strip()

        # Detect "el lunes/martes/..." weekday patterns BEFORE the token loop
        # so that "el viernes" on Friday resolves to NEXT Friday, not today.
        _weekday_match = re.search(
            r"\bel\s+(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b",
            normalized,
        )
        if _weekday_match:
            weekday_token = _weekday_match.group(1)
            try:
                resolved_dt = parse_natural_date(weekday_token)
                return resolved_dt.date().isoformat()
            except ValueError:
                pass  # fall through to token loop

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
        # Check for customer name token leak before processing response
        customer_name = state.get("customer_name") or state.get("pending_whatsapp_name")
        if response_text and customer_name:
            if self._contains_customer_name_token(response_text, customer_name):
                self.logger.warning(
                    "BookingMode: LLM leaked customer name token in response, using fallback"
                )
                response_text = "De acuerdo, continuemos con tu reserva. 🙏"

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
    ) -> PrefetchResult:
        """
        Pre-fetch stylist list and next available slots before LLM call.

        Calls list_stylists + find_next_available in Python so the LLM
        receives data directly without needing to call tools itself.

        Returns a PrefetchResult discriminated union (NOT a merged context dict):
          - PrefetchOk: prefetched_stylists, soonest_any_slot, soonest_any_slot_candidate
          - PrefetchNoAvailability: no slots found for any stylist
          - PrefetchToolError: infrastructure/tool failure (includes Python exceptions)

        Callers are responsible for merging PrefetchOk data into their context dict.
        """
        try:
            from agent.tools.availability_tools import find_next_available
            from agent.tools.info_tools import list_stylists

            service_category = mode_context.get("service_category") or ""
            service_duration_minutes = mode_context.get("service_duration_minutes")

            stylists_result = await list_stylists.ainvoke({"category": service_category})

            # Task 2.1: check error field on list_stylists result
            if stylists_result.get("error"):
                self.logger.warning(
                    "BookingMode._prefetch_stylist_options: list_stylists soft error=%s",
                    stylists_result["error"],
                )
                return PrefetchToolError(
                    status="tool_error",
                    error_detail=str(stylists_result["error"]),
                )

            availability_result = await find_next_available.ainvoke(
                {
                    "service_category": service_category,
                    "service_duration_minutes": service_duration_minutes,
                    "max_days_to_search": 7,
                }
            )

            # Task 2.2: check error field on find_next_available result
            available_stylists_raw = availability_result.get("available_stylists") or []
            if availability_result.get("error") and not available_stylists_raw:
                self.logger.warning(
                    "BookingMode._prefetch_stylist_options: find_next_available soft error=%s",
                    availability_result["error"],
                )
                return PrefetchNoAvailability(
                    status="no_availability",
                    error_detail=str(availability_result["error"]),
                )

            available_by_name = {
                str(stylist.get("stylist_name") or ""): stylist
                for stylist in available_stylists_raw
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

            # Build structured candidate for "cualquiera" resolution
            soonest_any_slot_candidate: dict[str, Any] | None = None
            if soonest_slot is not None:
                # Locate the stylist entry that owns the soonest slot
                soonest_dt, soonest_summary = soonest_slot
                for stylist in stylists_result.get("stylists") or []:
                    stylist_name = str(stylist.get("name") or "")
                    availability_entry = available_by_name.get(stylist_name, {})
                    slots = availability_entry.get("slots") or []
                    first_slot = slots[0] if slots else None
                    if not isinstance(first_slot, dict):
                        continue
                    full_datetime = first_slot.get("full_datetime")
                    parsed_dt: datetime | None = None
                    if isinstance(full_datetime, datetime):
                        parsed_dt = full_datetime
                    elif isinstance(full_datetime, str):
                        try:
                            parsed_dt = datetime.fromisoformat(full_datetime)
                        except ValueError:
                            parsed_dt = None
                    if parsed_dt is not None and parsed_dt == soonest_dt:
                        slot_summary_str = _format_slot_summary(first_slot)
                        soonest_any_slot_candidate = {
                            "stylist_id": str(stylist.get("id") or ""),
                            "stylist_name": stylist_name,
                            "slot_datetime": soonest_dt.isoformat(),
                            "slot_summary": slot_summary_str,
                        }
                        break

            self.logger.info(
                "BookingMode._prefetch_stylist_options: fetched %d stylists | soonest_slot=%s | candidate=%s",
                len(prefetched_stylists),
                soonest_slot[1] if soonest_slot else "none",
                soonest_any_slot_candidate.get("stylist_name") if soonest_any_slot_candidate else "none",
            )
            # Task 2.3: return typed PrefetchOk (not merged dict)
            return PrefetchOk(
                status="ok",
                prefetched_stylists=prefetched_stylists,
                soonest_any_slot=soonest_slot[1] if soonest_slot else None,
                soonest_any_slot_candidate=soonest_any_slot_candidate,
            )
        except Exception as exc:
            # Task 2.4: map Python exceptions to PrefetchToolError
            self.logger.error(
                "BookingMode._prefetch_stylist_options failed: %s", exc, exc_info=True
            )
            return PrefetchToolError(status="tool_error", error_detail=str(exc))

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

        # ── Substep-first qualifier guard ───────────────────────────────────
        # STYLIST_SELECTION, NOTES, and CONFIRMATION can receive "no preference"
        # / qualifier phrases that must NOT trigger cancel/reject early exits.
        # If the current substep is one of those and the message is a booking
        # qualifier (not an explicit cancellation), treat intent as "ambiguous"
        # and let the step handler resolve it.
        _SUBSTEP_QUALIFIER_OK = {STEP_STYLIST_SELECTION, STEP_NOTES, STEP_CONFIRMATION}
        if (
            intent_signal in ("cancel", "reject")
            and current_step.value in _SUBSTEP_QUALIFIER_OK
            and self._is_non_cancel_booking_qualifier(user_message)
        ):
            self.logger.info(
                "BookingMode: qualifier phrase at step=%s overrides %s intent → ambiguous",
                current_step,
                intent_signal,
            )
            intent_signal = "ambiguous"

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

            # ADD_ONS step: "no" / "no es necesario" means declining the add-on,
            # NOT cancelling the booking.  Advance to the next step instead.
            if current_step == STEP_ADD_ONS:
                self.logger.info(
                    "BookingMode: reject intent at ADD_ONS → declining add-on, advancing step"
                )
                advanced_context = self._finalize_mode_context(
                    {**mode_context, "add_ons_declined": True},
                    BookingSubstep.STYLIST_SELECTION,
                    None,
                )
                # Fall through to the regular step handler instead of cancelling
                mode_context = advanced_context
                current_step = self._determine_step(mode_context)
                intent_signal = "ambiguous"
                # (continues to normal step handling below)

            elif current_step == STEP_CONFIRMATION and self._message_is_explicit_cancellation(user_message):
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

            elif current_step == STEP_SERVICE_SELECTION or pending_cancel:
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
                        "¿Seguro que quieres cancelar la reserva? Responde 'sí' para cancelar o 'no' para continuar con tu cita.",
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

        # BUG-NEW-2 FIX: If service_query + service_audience_hint are in context,
        # call search_services directly with the audience parameter instead of
        # relying on the LLM tool loop (which lacks audience parameter support).
        service_query = mode_context.get("service_query")
        service_audience_hint = mode_context.get("service_audience_hint")
        if service_query and not mode_context.get("service_name"):
            self.logger.info(
                "BookingMode._handle_service_selection: direct search_services call "
                "with query=%r audience=%r",
                service_query,
                service_audience_hint,
            )
            search_result = await search_services.ainvoke({
                "query": service_query,
                "category": None,
                "audience": service_audience_hint,
            })
            # Apply the search result to mode_context and then run the agentic loop
            # to generate the LLM response
            updated_context = dict(mode_context)
            if isinstance(search_result, dict):
                if "resolved_service" in search_result:
                    svc = search_result["resolved_service"]
                    updated_context["service_name"] = svc.get("name", "")
                    updated_context["service_id"] = svc.get("id")
                    updated_context["service_category"] = svc.get("category", "")
                    updated_context["service_duration_minutes"] = svc.get("duration_minutes")
                    updated_context["service_family"] = svc.get("family")
                    updated_context["pending_recommendations"] = svc.get("combo_recommendations") or []
                    updated_context.pop("service_query", None)
                elif "clarification_needed" in search_result:
                    updated_context["pending_clarification"] = search_result["clarification_needed"]
                    updated_context.pop("service_query", None)
                elif "services" in search_result:
                    updated_context["candidate_services"] = search_result.get("services", [])
                    updated_context.pop("service_query", None)

            if self._use_optimized_prompts():
                messages = await self._build_layered_messages(
                    state, updated_context, step_name=STEP_SERVICE_SELECTION
                )
            else:
                messages = self._build_messages(state, _SYSTEM_SERVICE_SELECTION)
            result = await self._run_agentic_loop(messages, tools=[])

            next_step, final_context = self._advance_step(
                result, BookingSubstep.SERVICE_SELECTION, updated_context
            )
            return {
                **self._response_updates(state, result.response_text),
                "mode_context": self._finalize_mode_context(
                    final_context,
                    next_step,
                    BookingSubstep.SERVICE_SELECTION,
                ),
                "last_node": "booking",
                "user_message": None,
            }

        # Intent carry-over: consume opening_booking_request as implicit_service_hint (once only)
        opening_booking_request = mode_context.get("opening_booking_request")
        if opening_booking_request and not mode_context.get("service_name"):
            mode_context = {
                **mode_context,
                "implicit_service_hint": opening_booking_request,
                "opening_booking_request": None,  # consume — once only
            }

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
                            "pending_clarification": None,  # BUG FIX: Clear after resolving
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
        add_on_names = [opt["name"] for opt in add_ons_options]

        # Use the semantic resolver instead of exact-match decline check
        add_on_intent = self._resolve_add_on_intent(user_message, add_on_names)

        # Implicit decline: reply shifts to date/time/stylist without naming an add-on
        if add_on_intent == "unknown" and (
            self._looks_like_stylist_or_slot_reply(user_message)
            and not self._mentions_add_on_name(user_message, add_ons_options)
        ):
            self.logger.info(
                "BookingMode._handle_add_ons: implicit decline via topic shift | message=%r",
                user_message,
            )
            add_on_intent = "decline"

        updated_context = {
            **mode_context,
            "add_ons_options": add_ons_options,
        }

        if add_on_intent == "accept":
            selected = self._selected_services(updated_context)
            for opt in add_ons_options:
                if self._normalize_text(opt["name"]) in self._normalize_text(user_message):
                    if opt["name"] not in selected:
                        selected.append(opt["name"])
            updated_context["selected_services"] = selected
            updated_context["add_ons_declined"] = False
            next_step = BookingSubstep.STYLIST_SELECTION
        elif add_on_intent == "decline":
            updated_context["add_ons_declined"] = True
            next_step = BookingSubstep.STYLIST_SELECTION
        elif add_on_intent == "cancel":
            # Explicit booking cancel — transition to GENERAL
            from agent.state.schemas import transition_mode
            self.logger.info("BookingMode._handle_add_ons: cancel intent → GENERAL")
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
            # "unknown" — stay at ADD_ONS
            updated_context["add_ons_declined"] = False
            next_step = BookingSubstep.ADD_ONS if not updated_context.get("stylist_id") else BookingSubstep.STYLIST_SELECTION

        final_context = self._finalize_mode_context(
            updated_context, next_step, BookingSubstep.ADD_ONS
        )

        return {
            **self._response_updates(state, result.response_text),
            "mode_context": final_context,
            "last_node": "booking",
            "user_message": None,
        }

    @classmethod
    def _looks_like_stylist_or_slot_reply(cls, message: str) -> bool:
        """
        Return True when the message looks like a stylist selection or slot
        (date/time) reply rather than a genuine add-on response.

        Used in _handle_add_ons to detect implicit decline via topic shift.
        """
        normalized = cls._normalize_text(message)
        _SLOT_OR_STYLIST_TOKENS = (
            "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo",
            "manana", "pasado", "hoy", "esta semana", "proxima semana",
            "por la tarde", "por la manana",
            "cualquiera", "no importa", "sin preferencia", "no tengo preferencia",
            "a las", ":",  # time patterns like "10:00"
        )
        return any(token in normalized for token in _SLOT_OR_STYLIST_TOKENS)

    @classmethod
    def _mentions_add_on_name(cls, message: str, add_ons_options: list[dict]) -> bool:
        """Return True when the message contains at least one add-on service name."""
        normalized = cls._normalize_text(message)
        return any(cls._normalize_text(opt.get("name", "")) in normalized for opt in add_ons_options)

    def _resolve_stylist_from_message(
        self,
        user_message: str,
        prefetched_stylists: list[dict[str, Any]],
        soonest_any_slot_candidate: dict[str, Any] | None,
    ) -> dict[str, str] | None:
        """
        Deterministic pre-LLM resolver for stylist selection.

        Resolution order:
          1. "cualquiera" / "no importa" / "sin preferencia" / "primer horario" /
             "el que sea" / "no tengo preferencia" / "el más temprano" →
             pick soonest_any_slot_candidate's stylist.
          2. Ordinal/numeric ("el 1", "la primera", "el 2", "la segunda") →
             positional index into prefetched_stylists.
          3. Case-insensitive NFD-normalized name substring →
             prefetched_stylists[*]["name"].

        Returns {"stylist_id": str, "stylist_name": str} if resolved, else None.
        """

        def _normalize(text: str) -> str:
            """Strip accents and lowercase."""
            return "".join(
                c for c in unicodedata.normalize("NFD", text.lower())
                if unicodedata.category(c) != "Mn"
            )

        normalized_msg = _normalize(user_message)

        # ── 1. No-preference phrases → soonest available stylist ─────────────
        _NO_PREF_PHRASES = (
            "cualquiera",
            "cualquier",
            "no importa",
            "sin preferencia",
            "no tengo preferencia",
            "no me importa",
            "el que sea",
            "la que sea",
            "primer horario",
            "primer horario disponible",
            "el mas temprano",
            "lo antes posible",
            "antes posible",
            "no tengo preferencia",
        )
        if any(phrase in normalized_msg for phrase in _NO_PREF_PHRASES):
            if soonest_any_slot_candidate and soonest_any_slot_candidate.get("stylist_id"):
                self.logger.info(
                    "BookingMode._resolve_stylist_from_message: no-preference → stylist=%s",
                    soonest_any_slot_candidate["stylist_name"],
                )
                return {
                    "stylist_id": soonest_any_slot_candidate["stylist_id"],
                    "stylist_name": soonest_any_slot_candidate["stylist_name"],
                }
            return None

        # ── 2. Ordinal / numeric pick ─────────────────────────────────────────
        import re

        _ORDINAL_MAP: dict[str, int] = {
            "primer": 0, "primero": 0, "primera": 0, "1": 0, "uno": 0, "una": 0,
            "segundo": 1, "segunda": 1, "2": 1, "dos": 1,
            "tercer": 2, "tercero": 2, "tercera": 2, "3": 2, "tres": 2,
            "cuarto": 3, "cuarta": 3, "4": 3, "cuatro": 3,
            "quinto": 4, "quinta": 4, "5": 4, "cinco": 4,
        }
        for token, idx in _ORDINAL_MAP.items():
            pattern = rf"\b{re.escape(token)}\b"
            if re.search(pattern, normalized_msg) and idx < len(prefetched_stylists):
                stylist = prefetched_stylists[idx]
                stylist_id = str(stylist.get("id") or "")
                stylist_name = str(stylist.get("name") or "")
                if stylist_id:
                    self.logger.info(
                        "BookingMode._resolve_stylist_from_message: ordinal '%s' → stylist=%s",
                        token,
                        stylist_name,
                    )
                    return {"stylist_id": stylist_id, "stylist_name": stylist_name}

        # ── 3. Name substring match (accent-normalized, case-insensitive) ─────
        for stylist in prefetched_stylists:
            stylist_name = str(stylist.get("name") or "")
            if not stylist_name:
                continue
            # Check each token of the stylist name individually (≥3 chars)
            name_tokens = [t for t in re.split(r"\W+", stylist_name) if len(t) >= 3]
            for token in name_tokens:
                if _normalize(token) in normalized_msg:
                    stylist_id = str(stylist.get("id") or "")
                    if stylist_id:
                        self.logger.info(
                            "BookingMode._resolve_stylist_from_message: name match '%s' → stylist=%s",
                            token,
                            stylist_name,
                        )
                        return {"stylist_id": stylist_id, "stylist_name": stylist_name}

        self.logger.debug(
            "BookingMode._resolve_stylist_from_message: no match for message=%r", user_message[:80]
        )
        return None

    async def _handle_stylist_selection(
        self, state: ConversationState, mode_context: dict
    ) -> dict:
        """Step 2: Help customer select a stylist.

        Flow:
          1. Populate recurrent stylist data.
          2. Prefetch stylist options → PrefetchResult (typed union).
          3. Branch on prefetch_result["status"]:
             - "tool_error"      → return hardcoded Spanish error, stay STYLIST_SELECTION (Path D)
             - "no_availability" → return hardcoded no-avail message, stay STYLIST_SELECTION (Path C)
             - "ok"              → merge data into context, run resolver:
                 * resolver match → same-turn handoff to _handle_slot_selection (Path A/E)
                 * resolver no match → LLM call with stylist data in context (Path B/F)
        """
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

        # Task 3.1: call prefetch and branch on status
        prefetch_result = await self._prefetch_stylist_options(updated_context)

        # Task 3.2: Path D — tool error: hardcoded fallback, no LLM call
        if prefetch_result["status"] == "tool_error":
            self.logger.warning(
                "BookingMode._handle_stylist_selection: tool_error path, detail=%s",
                prefetch_result.get("error_detail"),
            )
            error_context = {
                **updated_context,
                "prefetch_error": True,
                "prefetch_error_type": "tool_error",
                "prefetch_error_detail": prefetch_result.get("error_detail", ""),
            }
            return {
                **self._response_updates(
                    state,
                    "Tenemos un problema técnico. Por favor intentá de nuevo en un momento.",
                ),
                "mode_context": self._finalize_mode_context(
                    error_context,
                    BookingSubstep.STYLIST_SELECTION,
                    BookingSubstep.STYLIST_SELECTION,
                ),
                "last_node": "booking",
                "user_message": None,
            }

        # Task 3.3: Path C — no availability: hardcoded fallback, no LLM call
        if prefetch_result["status"] == "no_availability":
            self.logger.warning(
                "BookingMode._handle_stylist_selection: no_availability path, detail=%s",
                prefetch_result.get("error_detail"),
            )
            no_avail_context = {
                **updated_context,
                "prefetch_error": True,
                "prefetch_error_type": "no_availability",
                "prefetch_error_detail": prefetch_result.get("error_detail", ""),
            }
            return {
                **self._response_updates(
                    state,
                    "Lamentablemente no hay disponibilidad en este momento. ¿Querés intentar en otro día?",
                ),
                "mode_context": self._finalize_mode_context(
                    no_avail_context,
                    BookingSubstep.STYLIST_SELECTION,
                    BookingSubstep.STYLIST_SELECTION,
                ),
                "last_node": "booking",
                "user_message": None,
            }

        # Task 3.4: Path ok — merge PrefetchOk data into context
        updated_context.update({
            "prefetched_stylists": prefetch_result["prefetched_stylists"],
            "soonest_any_slot": prefetch_result["soonest_any_slot"],
            "soonest_any_slot_candidate": prefetch_result["soonest_any_slot_candidate"],
        })

        # ── Pre-LLM deterministic stylist resolver ────────────────────────────
        if not updated_context.get("stylist_id"):
            resolved = self._resolve_stylist_from_message(
                user_message,
                cast(list[dict[str, Any]], updated_context.get("prefetched_stylists") or []),
                cast(dict[str, Any] | None, updated_context.get("soonest_any_slot_candidate")),
            )
            if resolved:
                updated_context["stylist_id"] = resolved["stylist_id"]
                updated_context["stylist_name"] = resolved["stylist_name"]
                self.logger.info(
                    "BookingMode._handle_stylist_selection: pre-resolved stylist_id=%s name=%s — same-turn handoff",
                    resolved["stylist_id"],
                    resolved["stylist_name"],
                )
                # Task 3.5: Path A/E — same-turn handoff (mirrors _handle_add_ons:1023)
                # booking_step will be set to SLOT_SELECTION inside _handle_slot_selection
                updated_context["booking_step"] = BookingSubstep.SLOT_SELECTION.value
                return await self._handle_slot_selection(state, updated_context)
        # ─────────────────────────────────────────────────────────────────────

        # Task 3.6: Path B/F — no resolver match → LLM call with stylist data in context
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

        # Provide list_stylists as a fallback tool in case the prefetch data
        # doesn't contain what the LLM needs.
        from agent.tools.info_tools import list_stylists
        result = await self._run_agentic_loop(messages, tools=[list_stylists])

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

        # ADR-1: Slot Invalid-Input Recovery Guard
        # When offered_slots are in context, try to resolve the user's reply
        # to a specific slot before falling through to the LLM loop.
        offered_slots = updated_context.get("offered_slots")
        if offered_slots:
            resolved_slot = self._resolve_slot_from_message(user_message, offered_slots)
            if resolved_slot:
                # Valid slot selected — clear the invalid counter and advance
                slot_summary = (
                    resolved_slot.get("start_time")
                    or f"{resolved_slot.get('date', '')} {resolved_slot.get('time', '')}".strip()
                    or "fecha seleccionada"
                )
                updated_context["selected_slot"] = resolved_slot
                updated_context["slot_summary"] = slot_summary
                updated_context.pop("slot_invalid_count", None)  # clear counter

                # Advance deterministically to CUSTOMER_NAME (slot resolved, has_slots=True)
                # We bypass _advance_step to avoid requiring tool_results["slot_interpretation"]
                next_step = BookingSubstep.CUSTOMER_NAME

                # Generate LLM confirmation for the selected slot
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
                result = await self._run_agentic_loop(messages, tools=[])

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
            else:
                # Could not resolve — invalid selection
                invalid_count = updated_context.get("slot_invalid_count", 0) + 1
                if invalid_count < SLOT_INVALID_INPUT_MAX:
                    # Below cap: rephrase deterministically, do NOT increment no_progress_turns
                    updated_context["slot_invalid_count"] = invalid_count
                    updated_context["booking_step"] = BookingSubstep.SLOT_SELECTION.value
                    rephrase_msg = (
                        "¿Podés escribir el número del horario? "
                        "Por ejemplo, '1' para el primer horario, '2' para el segundo, etc."
                    )
                    return {
                        **self._response_updates(state, rephrase_msg),
                        "mode_context": updated_context,
                        "last_node": "booking",
                        "user_message": None,
                    }
                # At/above cap: fall through to LLM loop for genuine confusion handling

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

        # FIX BUG-001: If user confirmed and we advanced to COMPLETED step,
        # execute booking immediately in the same turn instead of deferring to next turn.
        # This prevents phantom confirmations where user sees "confirmada" but appointment isn't created.
        if next_step == BookingSubstep.COMPLETED:
            return await self._handle_completed(state, updated_context)

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

        # T2.1: Defensive guard — resolve customer_id before calling book()
        # Use raw mode_context["first_name"] (not the _resolve_customer_name fallback "Cliente")
        # so the fallback chain: first_name → pending_whatsapp_name → customer_first_name → "Cliente"
        # behaves correctly when no name is available in mode_context.
        updates: dict[str, Any] = {}
        if not customer_id:
            resolved_name = (
                mode_context.get("first_name")
                or state.get("pending_whatsapp_name")
                or state.get("customer_first_name")
                or "Cliente"
            )
            new_id = await self._create_customer_if_needed(state, resolved_name)
            if new_id:
                customer_id = new_id
                updates["customer_id"] = customer_id
            else:
                self.logger.error(
                    "_handle_completed: could not resolve customer_id, booking will fail"
                )

        booking_result: dict[str, Any] = {}
        error_text: str | None = None

        # Build services list: prefer resolved service_name, fallback to empty list
        services_list = self._selected_services(mode_context)

        # ADR-2: Bounded retry — attempt book() up to _BOOK_MAX_ATTEMPTS times
        book_payload = {
            "customer_id": customer_id,
            "first_name": first_name,
            "last_name": None,
            "notes": notes if notes else None,
            "services": services_list,
            "stylist_id": stylist_id or "",
            "start_time": selected_slot.get("start_time", ""),
            "conversation_id": conversation_id,
        }
        last_exc: Exception | None = None
        for attempt in range(_BOOK_MAX_ATTEMPTS):
            try:
                booking_result = await book.ainvoke(book_payload)

                # ADR-2 idempotency: if attempt ≥ 1 and error is SLOT_TAKEN/already booked,
                # treat as success (attempt 1 committed, response was lost)
                if attempt >= 1:
                    exc_str = str(last_exc or "")
                    if any(
                        token in exc_str.upper()
                        for token in ("SLOT_TAKEN", "ALREADY BOOKED", "ALREADY_BOOKED")
                    ):
                        # Booking already exists — treat as success
                        self.logger.warning(
                            "_handle_completed: idempotency guard triggered on attempt %d "
                            "(SLOT_TAKEN → treating as success)",
                            attempt + 1,
                        )
                        error_text = None
                        break

                # Check both explicit error key and success=False
                if not booking_result.get("success", True):
                    error_text = booking_result.get("error") or (
                        f"Booking failed (code={booking_result.get('error_code', 'unknown')})"
                    )
                elif "error" in booking_result:
                    error_text = booking_result["error"]
                else:
                    error_text = None

                if not error_text:
                    break  # Success — exit retry loop

                self.logger.warning(
                    "_handle_completed: book() returned error on attempt %d: %s",
                    attempt + 1, error_text
                )
                last_exc = Exception(error_text)

            except Exception as exc:
                last_exc = exc
                self.logger.warning(
                    "_handle_completed: book() raised exception on attempt %d: %s",
                    attempt + 1, exc
                )
                # ADR-2 idempotency: if retry exception contains SLOT_TAKEN, treat as success
                exc_str = str(exc).upper()
                if any(
                    token in exc_str
                    for token in ("SLOT_TAKEN", "ALREADY BOOKED", "ALREADY_BOOKED")
                ):
                    self.logger.warning(
                        "_handle_completed: idempotency guard triggered (SLOT_TAKEN exception) "
                        "on attempt %d — treating as success",
                        attempt + 1,
                    )
                    error_text = None
                    booking_result = {}
                    break
                error_text = str(exc)

        if error_text:
            # Both attempts failed — user-safe error message (ADR-2)
            safe_msg = "Hubo un problema al confirmar tu turno. Por favor intentá de nuevo en un momento."
            if self._use_optimized_prompts():
                messages = await self._build_layered_messages(
                    state, mode_context, step_name="error"
                )
                result = await self._run_agentic_loop(messages, tools=[])
                response_text = result.response_text
            else:
                response_text = safe_msg
            # T2.2: Preserve mode_context with last_error (no raw error in prompt — ADR-2)
            return {
                **updates,
                **self._response_updates(state, response_text),
                "mode_context": {
                    **mode_context,
                    "booking_step": BookingSubstep.CONFIRMATION.value,
                    "last_error": "booking_failed",  # sanitized flag, not raw error text
                },
                "error_count": state.get("error_count", 0) + 1,
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
                    # T2.4: Skip audience/variant clarification when variant is inferable:
                    # (a) service_audience_hint already set in context → auto-resolve
                    # (b) single-option clarification → auto-pick the only option
                    # (c) returning client with bookings in same service category
                    clarification = envelope["clarification_needed"]
                    clarification_options = clarification.get("options", [])
                    audience_hint = updated_context.get("service_audience_hint")
                    prior_bookings_category = updated_context.get("prior_bookings_category")

                    _auto_resolved_value: str | None = None
                    _auto_resolved_opt: dict | None = None

                    if audience_hint and clarification_options:
                        # Find the option whose label or value matches the hint
                        hint_norm = self._normalize_text(str(audience_hint))
                        for opt in clarification_options:
                            if (
                                hint_norm in self._normalize_text(opt.get("label", ""))
                                or hint_norm in self._normalize_text(opt.get("value", ""))
                                or self._normalize_text(opt.get("value", "")) in hint_norm
                            ):
                                _auto_resolved_value = opt.get("value")
                                _auto_resolved_opt = opt
                                break

                    if _auto_resolved_value is None and len(clarification_options) == 1:
                        # Single variant — no ambiguity
                        _auto_resolved_value = clarification_options[0].get("value")
                        _auto_resolved_opt = clarification_options[0]

                    if _auto_resolved_value is None and prior_bookings_category and clarification_options:
                        # Returning client: pick option whose value matches prior category
                        cat_norm = self._normalize_text(str(prior_bookings_category))
                        for opt in clarification_options:
                            if self._normalize_text(opt.get("value", "")) in cat_norm or cat_norm in self._normalize_text(opt.get("value", "")):
                                _auto_resolved_value = opt.get("value")
                                _auto_resolved_opt = opt
                                break

                    if _auto_resolved_value is not None:
                        # Skip clarification: store auto-resolved audience and clear clarification
                        self.logger.info(
                            "BookingMode._advance_step: variant clarification skipped "
                            "| auto_resolved=%s axis=%s",
                            _auto_resolved_value,
                            clarification.get("axis"),
                        )
                        updated_context["service_audience_hint"] = _auto_resolved_value
                        updated_context.pop("pending_clarification", None)
                        # Write canonical service fields so _advance_step() can
                        # progress from service_selection → ADD_ONS.
                        # Without these, service_name is absent and the flow
                        # stays locked in service_selection forever (T2.4 regression).
                        if _auto_resolved_opt is not None:
                            updated_context.setdefault(
                                "service_id", _auto_resolved_opt.get("service_id")
                            )
                            updated_context.setdefault(
                                "service_name", _auto_resolved_opt.get("service_name", "")
                            )
                            updated_context.setdefault(
                                "service_duration_minutes",
                                _auto_resolved_opt.get("duration_minutes"),
                            )
                    else:
                        updated_context["pending_clarification"] = {
                            "axis": clarification.get("axis", ""),
                            "question_hint": clarification.get("question_hint", ""),
                            "options": clarification_options,
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

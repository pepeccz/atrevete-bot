"""
Booking Mode — Simplified LLM-Driven Booking Architecture.

~380 lines. Python retains ONLY what the LLM cannot do:
  - UUID injection (slot_index → stylist_id/start_time)
  - Code-rendered confirmations (F-8 path)
  - mode_context update from tool results

Tool surface: check_availability, book, escalate_to_human (3 tools).
The service catalog is in the prompt — no separate catalog lookup needed.
The LLM guides the booking flow; Python enforces data-integrity gates only.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from agent.config import get_booking_config, ToolChoicePolicy
from agent.modes.base import AgenticLoopResult, BaseModeNode, ToolCallRejection
from agent.prompts.loader import build_layered_messages
from agent.state.helpers import add_message, get_last_user_message
from agent.state.schemas import ConversationState, transition_mode

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

_HISTORY_LIMIT = 8

# ============================================================================
# Module-level helpers
# ============================================================================

_AFFIRMATIVE_PATTERN = re.compile(
    r"^(?:s[ií]|ok|dale|vale|claro|perfecto|confirmo|correcto|exacto|"
    r"de acuerdo|acepto|listo|hecho|va|venga)$",
    re.IGNORECASE,
)

# Matches time expressions: "a las 11", "las 9:00", "a las 9 y media", "11:00", "a las 11:40"
_TIME_PATTERN = re.compile(
    r"(?:a\s+)?las?\s+(\d{1,2})(?::(\d{2})|\s+y\s+media)?|^(\d{1,2}):(\d{2})$",
    re.IGNORECASE,
)

# Matches ordinal expressions: "la primera", "la segunda", "el último", etc.
_ORDINAL_PATTERN = re.compile(
    r"(?:la|el)\s+(primer[ao]?|segund[ao]|tercer[ao]?|cuart[ao]|quint[ao]|últim[ao])",
    re.IGNORECASE,
)

# Maps ordinal stem (first 5 chars lowercased) → 0-based index (-1 means last)
_ORDINAL_STEM_MAP: dict[str, int] = {
    "prime": 0,
    "segun": 1,
    "terce": 2,
    "cuart": 3,
    "quint": 4,
    "últim": -1,
}

_NO_PREFERENCE_PATTERNS = re.compile(
    r"(?:sin\s+preferencia|me\s+da\s+igual|cualquiera|no\s+tengo\s+preferencia|"
    r"da\s+lo\s+mismo|no\s+me\s+importa|la\s+que\s+sea|el\s+que\s+sea|"
    r"la\s+primera\s+disponible)",
    re.IGNORECASE,
)


def _is_spanish_affirmative(text: str) -> bool:
    """Return True if text is a bare Spanish affirmative (e.g. 'sí', 'dale', 'ok')."""
    return bool(_AFFIRMATIVE_PATTERN.match(text.strip()))


# ============================================================================
# BookingModeNode
# ============================================================================


class BookingModeNode(BaseModeNode):
    """Simplified LLM-driven booking mode — 3 tools, flat dict mode_context.

    Python retains only what the LLM cannot do:
    - UUID injection (slot_index → stylist_id/start_time)
    - Code-rendered confirmations (F-8 path)
    - mode_context updates from tool results
    """

    @property
    def mode_name(self) -> str:
        return "BOOKING"

    def get_tools(self) -> list:
        """Return the 3 booking tools for the agentic loop."""
        from agent.tools.availability_tools import check_availability
        from agent.tools.booking_tools import book
        from agent.tools.escalation_tools import escalate_to_human

        return [check_availability, book, escalate_to_human]

    # ──────────────────────────────────────────────────────────────────────
    # Booking step computation — pure function, idempotent
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_step(ctx: dict) -> str:
        """Return current booking step based on BookingContext fields. Pure function.

        Idempotent: re-evaluates from the current state of ctx fields.
        Steps progress from service_selection → stylist_selection → datetime_selection
        → name_collection → notes_collection → confirmation.

        Args:
            ctx: BookingContext dict (or any dict with the same fields).

        Returns:
            String literal representing the current booking step.
        """
        if not ctx.get("last_services"):
            return "service_selection"
        if not ctx.get("last_stylist") and not ctx.get("no_preference_stylist"):
            return "stylist_selection"
        if not ctx.get("selected_slot"):
            return "datetime_selection"
        if not ctx.get("customer_name"):
            return "name_collection"
        if not ctx.get("notes_asked"):
            return "notes_collection"
        return "confirmation"

    @staticmethod
    def _compute_booking_step(mode_context: dict) -> str:
        """Backward-compat alias — delegates to _compute_step(). Do not add new callers."""
        return BookingModeNode._compute_step(mode_context)

    # ──────────────────────────────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────────────────────────────

    async def handle(self, state: ConversationState, intent: Any) -> dict:
        """Process one turn of the booking conversation.

        Flow:
        1. Load booking_context (typed, replace-reducer) + routing mode_context
        2. Cross-mode customer handoff
        3. Compute tool_choice (forced only on blank-slate turns)
        4. Build messages with dynamic context
        5. Run agentic loop
        6. Build response (F-8 override for completed bookings)

        State contract:
        - booking_context: ALL booking-specific fields (services, stylist, slots, etc.)
                           Returned as a FULL REPLACE via replace_booking_context reducer.
        - mode_context: ONLY routing metadata (last_intent, last_intent_confidence, awaiting_human).
                        NOT used for booking data.
        """
        # Routing metadata only (last_intent, awaiting_human, etc.)
        mode_context = dict(state.get("mode_context") or {})

        # Fast-path: awaiting human escalation
        if mode_context.get("awaiting_human"):
            return {
                **transition_mode(state, "ESCALATION"),
                **add_message(state, "assistant", "Te paso con una persona del equipo. 🙏"),
                "last_node": "booking",
                "user_message": None,
            }

        # Load booking_context — the single source of truth for all booking data.
        # We always start from the persisted checkpoint value and return a full replace.
        booking_context: dict[str, Any] = dict(state.get("booking_context") or {})

        # 1. Resolve pending selection: map numbered/text user reply → last_services/last_stylist/selected_slot
        self._resolve_pending_selection(state, booking_context)

        # 1c. Compute booking step (idempotent — re-evaluated each turn after resolution)
        booking_context["booking_step"] = self._compute_step(booking_context)

        # 2. Cross-mode customer handoff
        self._resolve_customer_from_state(state, booking_context)

        # 3. tool_choice: config-driven policy (default: never force)
        config = await get_booking_config()
        tool_choice: str | None = None
        if config.tool_choice_policy == ToolChoicePolicy.ALWAYS_FORCE:
            tool_choice = "required"
            logger.info("BookingModeNode: tool_choice='required' (always_force policy)")
        elif config.tool_choice_policy == ToolChoicePolicy.FORCE_AFTER_SERVICE:
            if booking_context.get("last_services") and not booking_context.get("offered_slots"):
                tool_choice = "required"
                logger.info("BookingModeNode: tool_choice='required' (service known, no slots yet)")
        # else: NEVER_FORCE — tool_choice stays None (LLM decides freely)

        # Store for _pre_tool_call / _post_tool_result / _refresh_dynamic_context access.
        # _booking_context is the canonical store; _mode_context is kept as an alias
        # so that both attributes resolve to the same dict (defensive programming).
        self._booking_context = booking_context
        self._mode_context = booking_context  # alias: both point to booking_context
        self._current_state = state

        # 4. Build messages with dynamic context
        messages = await self._build_messages(state, booking_context)

        # 5. Run agentic loop — LLM calls tools freely
        result = await self._run_agentic_loop(
            messages, tools=self.get_tools(), tool_choice=tool_choice
        )

        # 6. Build response (F-8 override for confirmed bookings)
        response_text = self._build_response(result, booking_context)
        response_text, disclosure_sent = self._maybe_prepend_intro(response_text, state)

        # Build routing mode_context update — only routing metadata, no booking data
        routing_context = {
            k: v
            for k, v in mode_context.items()
            if k in ("last_intent", "last_intent_confidence", "awaiting_human")
        }

        updates: dict[str, Any] = {
            **add_message(state, "assistant", response_text),
            "booking_context": booking_context,  # full replace via replace_booking_context reducer
            "mode_context": routing_context,  # only routing metadata
            "last_node": "booking",
            "user_message": None,
        }
        if disclosure_sent:
            updates["ai_disclosure_sent"] = True

        # Propagate customer name to top-level state if discovered
        customer_name = booking_context.get("customer_name")
        if customer_name and not state.get("customer_name"):
            updates["customer_name"] = customer_name

        # F-8: transition to GENERAL after successful booking
        # Note: booking_context persists independently — no need to restore after transition_mode
        if booking_context.get("_booking_completed"):
            updates["appointment_created"] = True
            updates.update(transition_mode(state, "GENERAL"))
            # booking_context persists via its own field (replace_booking_context reducer)
            # — do NOT re-inject into mode_context after transition_mode
            updates["booking_context"] = booking_context  # ensure booking_context survives

        return updates

    # ──────────────────────────────────────────────────────────────────────
    # _pre_tool_call — 2 gates only
    # ──────────────────────────────────────────────────────────────────────

    async def _pre_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> dict[str, Any] | ToolCallRejection:
        """Intercept tool calls before execution.

        2 categories:
        (a) book(): slot_index→UUID injection + services injection
        (b) check_availability: stylist guard
        (c) Everything else: pass through unchanged
        """
        mode_context: dict = getattr(self, "_booking_context", getattr(self, "_mode_context", {}))

        # ── check_availability: stylist guard ───────────
        if tool_name == "check_availability":
            # Accept stylist_name from tool_args — LLM resolved it from conversation.
            # This prevents STYLIST_NOT_RESOLVED deadlock when the LLM provides the
            # stylist directly in args before last_stylist is set in mode_context.
            stylist_from_args = tool_args.get("stylist_name")
            if stylist_from_args and not mode_context.get("last_stylist"):
                mode_context["last_stylist"] = stylist_from_args
            # Guard: stylist must be resolved before availability check
            if not mode_context.get("last_stylist") and not mode_context.get(
                "no_preference_stylist"
            ):
                return ToolCallRejection(
                    name="check_availability",
                    error_code="STYLIST_NOT_RESOLVED",
                    error_message=(
                        "Antes de buscar disponibilidad, preguntá al cliente "
                        "qué estilista prefiere (o si le da igual). "
                        "El cliente puede responder con el nombre, un número o 'sin preferencia'."
                    ),
                )
            return tool_args

        # ── book(): slot resolution → confirmation gate → injection ───────────
        if tool_name == "book":
            # Step A: slot_index → UUID resolution (runs BEFORE confirmation gate)
            # Persists selected_slot even when later gates reject the call.
            slot_index = tool_args.get("slot_index")
            offered_slots = mode_context.get("offered_slots") or []
            if slot_index is not None and offered_slots:
                try:
                    idx = int(slot_index)
                    if 1 <= idx <= len(offered_slots):
                        slot = offered_slots[idx - 1]
                        tool_args["stylist_id"] = slot.get("stylist_id")
                        tool_args["start_time"] = slot.get("start_time") or slot.get(
                            "full_datetime"
                        )
                        mode_context["selected_slot"] = slot
                        # Update last_stylist from slot if not already set
                        if not mode_context.get("last_stylist") and slot.get("stylist_name"):
                            mode_context["last_stylist"] = slot["stylist_name"]
                    else:
                        return ToolCallRejection(
                            name="book",
                            error_code="INVALID_SLOT_INDEX",
                            error_message=(
                                f"slot_index {idx} fuera de rango "
                                f"(1-{len(offered_slots)}). Mostrá la lista de nuevo."
                            ),
                        )
                except (ValueError, TypeError):
                    return ToolCallRejection(
                        name="book",
                        error_code="INVALID_SLOT_INDEX",
                        error_message="slot_index debe ser un número entero.",
                    )

            # Step A.2: customer_name extraction from tool args
            if not mode_context.get("customer_name"):
                first = (tool_args.get("customer_first_name") or "").strip()
                if first:
                    last = (tool_args.get("customer_last_name") or "").strip()
                    full_name = f"{first} {last}" if last else first
                    mode_context["customer_name"] = full_name
                    logger.info(
                        "_pre_tool_call: extracted customer_name=%s from book() args",
                        full_name,
                    )

            # Step C: inject services from mode_context if LLM didn't provide them
            if not tool_args.get("services") and mode_context.get("last_services"):
                tool_args["services"] = mode_context["last_services"]

            return tool_args

        # ── All other tools: pass through ──────────────────────────────────────
        return tool_args

    # ──────────────────────────────────────────────────────────────────────
    # _post_tool_result — update mode_context from tool results mid-loop
    # ──────────────────────────────────────────────────────────────────────

    async def _post_tool_result(
        self,
        tool_name: str,
        tool_args: dict,
        result: Any,
    ) -> Any:
        """Update booking_context from tool results before next LLM turn."""
        mode_context: dict = getattr(self, "_booking_context", getattr(self, "_mode_context", {}))

        # Parse result if it's a JSON string
        result_dict: dict = {}
        if isinstance(result, str):
            try:
                result_dict = json.loads(result)
            except (json.JSONDecodeError, ValueError):
                pass
        elif isinstance(result, dict):
            result_dict = result

        if tool_name == "check_availability":
            # Store offered slots from availability result
            slots = result_dict.get("available_slots") or result_dict.get("slots") or []
            if slots:
                # Clear stale slot state ONLY when new slots arrive successfully.
                # Previously in _pre_tool_call — eager wipe caused SLOT_NOT_RESOLVED.
                mode_context.pop("selected_slot", None)
                mode_context["offered_slots"] = slots
                logger.info(
                    "_post_tool_result[check_availability]: cleared stale state, stored %d offered_slots",
                    len(slots),
                )
            # Capture service names from args (list)
            svc_names = tool_args.get("service_names") or []
            if svc_names and not mode_context.get("last_services"):
                mode_context["last_services"] = svc_names
            # Capture total duration from result
            total_dur = result_dict.get("total_duration_minutes")
            if total_dur:
                mode_context["last_total_duration_minutes"] = total_dur
            # Capture stylist name from args
            stylist_name = tool_args.get("stylist_name")
            if stylist_name and not mode_context.get("last_stylist"):
                mode_context["last_stylist"] = stylist_name

        elif tool_name == "book":
            status = result_dict.get("status")
            if status == "ok" or result_dict.get("appointment_id"):
                mode_context["_booking_completed"] = True
                logger.info("_post_tool_result[book]: booking completed successfully")

        return result

    # ──────────────────────────────────────────────────────────────────────
    # Response building — F-8 only
    # ──────────────────────────────────────────────────────────────────────

    def _build_response(self, result: AgenticLoopResult, mode_context: dict) -> str:
        """Build the final response text.

        F-8: code-render a structured confirmation block after successful booking.
        Everything else: return LLM text as-is (via _sanitize_response).
        """
        response_text = result.response_text or ""

        # F-8: code-rendered confirmation after successful booking
        if mode_context.get("_booking_completed") and mode_context.get("selected_slot"):
            return self._render_booking_confirmation(mode_context)

        return self._sanitize_response(response_text)

    def _render_booking_confirmation(self, mode_context: dict) -> str:
        """Code-render the post-booking confirmation block (F-8 path)."""
        slot = mode_context.get("selected_slot") or {}
        day = slot.get("day_label", "?")
        time_ = slot.get("time", "?")
        stylist = mode_context.get("last_stylist") or "?"
        last_services = mode_context.get("last_services") or ["?"]
        service_label = " + ".join(last_services)
        return (
            f"✅ ¡Reserva confirmada!\n\n"
            f"📅 {day} a las {time_}\n"
            f"💇 {stylist}\n"
            f"✨ {service_label}\n\n"
            f"Te esperamos 🌸"
        )

    # ──────────────────────────────────────────────────────────────────────
    # Message construction
    # ──────────────────────────────────────────────────────────────────────

    async def _build_messages(self, state: ConversationState, mode_context: dict) -> list:
        """Build the complete message list for the agentic loop via layered assembly.

        Structure:
        1. SystemMessage: Cached shared prompt (identity + critical_rules)
        2. SystemMessage: Booking mode overlay (booking.md)
        3. Conversation history (last _HISTORY_LIMIT messages)
        4. SystemMessage: Dynamic context (collected/missing data, slots) — LAST
        """
        dynamic_context = self._build_dynamic_context(mode_context, state)

        messages, dynamic_context_index = await build_layered_messages(
            state=state,
            mode_context=mode_context,
            mode_name="BOOKING",
            dynamic_context_override=dynamic_context,
            include_history=True,
            history_limit=_HISTORY_LIMIT,
        )

        # Store index for potential mid-loop refresh (inherited hook)
        self._dynamic_context_index = dynamic_context_index
        self._dynamic_context_state = state

        return messages

    def _build_dynamic_context(self, mode_context: dict, state: ConversationState) -> str:
        """Build the dynamic context XML section injected as the last SystemMessage.

        Contains: temporal context, phone, conversation summary, collected data,
        missing data, offered slots, confirmation status.
        """
        parts: list[str] = []

        # Current time
        now = datetime.now(ZoneInfo("Europe/Madrid"))
        parts.append(
            f"Fecha y hora actual: {now.strftime('%A %d de %B de %Y, %H:%M')} (Europa/Madrid)"
        )

        # Phone
        phone = state.get("customer_phone", "")
        if phone:
            parts.append(f"Teléfono del cliente: {phone}")

        # Conversation summary
        summary = state.get("conversation_summary", "")
        if summary:
            parts.append(f"<conversation_summary>\n{summary}\n</conversation_summary>")

        # Minimum valid date for appointments (3-day rule)
        from agent.validators.transaction_validators import MINIMUM_DAYS

        _DAY_NAMES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        _MONTH_NAMES = [
            "enero",
            "febrero",
            "marzo",
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
            "septiembre",
            "octubre",
            "noviembre",
            "diciembre",
        ]
        min_date = (now + timedelta(days=MINIMUM_DAYS)).date()
        min_day_name = _DAY_NAMES[min_date.weekday()]
        min_date_label = f"{min_day_name} {min_date.day} de {_MONTH_NAMES[min_date.month - 1]}"

        # Booking context XML block
        parts.append("<booking_context>")
        parts.append(f"<min_valid_date>{min_date_label} ({min_date.isoformat()})</min_valid_date>")

        # Current booking step and next action hint
        _STEP_ACTIONS = {
            "service_selection": "Identificar el servicio del catálogo",
            "stylist_selection": "Preguntar preferencia de estilista (número, nombre o 'sin preferencia')",
            "datetime_selection": "Buscar disponibilidad con check_availability",
            "name_collection": "Pedir nombre del cliente",
            "notes_collection": "Preguntar si hay algo que tener en cuenta para la cita",
            "confirmation": "Mostrar resumen y pedir confirmación",
        }
        step = mode_context.get("booking_step", "service_selection")
        next_action = _STEP_ACTIONS.get(step, "")
        parts.append(f"<current_step>{step}</current_step>")
        parts.append(f"<next_action>{next_action}</next_action>")

        # Audience hint from greeting handoff
        audience_hint = mode_context.get("service_audience_hint")
        if audience_hint:
            _HINT_LABELS = {
                "adult_male": "Caballero",
                "adult_female": "Señora",
                "child_male": "Niño",
                "child_female": "Niña",
                "baby": "Bebé",
            }
            hint_label = _HINT_LABELS.get(audience_hint, audience_hint)
            parts.append(
                f"<audience_hint>El cliente indicó que la cita es para: {hint_label}</audience_hint>"
            )

        collected = self._build_collected_summary(mode_context)
        if collected:
            parts.append(f"<collected_data>\n{collected}\n</collected_data>")

        missing = self._build_missing_summary(mode_context)
        if missing:
            parts.append(f"<missing_data>\n{missing}\n</missing_data>")

        offered_slots = mode_context.get("offered_slots") or []
        if offered_slots:
            slot_lines = "\n".join(
                f"{i + 1}. {s.get('day_label', '?')} a las {s.get('time', '?')}"
                f" con {s.get('stylist_name', '?')}"
                for i, s in enumerate(offered_slots)
            )
            parts.append(f"<offered_slots>\n{slot_lines}\n</offered_slots>")

        parts.append("</booking_context>")

        return "\n".join(parts)

    def _build_collected_summary(self, mode_context: dict) -> str:
        """Build collected_data summary from flat mode_context dict."""
        lines: list[str] = []

        last_services = mode_context.get("last_services") or []
        if last_services:
            total_dur = mode_context.get("last_total_duration_minutes")
            if len(last_services) == 1:
                dur_str = f" ({total_dur}min)" if total_dur else ""
                lines.append(f"✅ Servicio: {last_services[0]}{dur_str}")
            else:
                dur_str = f" ({total_dur}min total)" if total_dur else ""
                lines.append(f"✅ Servicios: {', '.join(last_services)}{dur_str}")

        last_stylist = mode_context.get("last_stylist")
        if last_stylist:
            lines.append(f"✅ Estilista: {last_stylist}")

        selected_slot = mode_context.get("selected_slot")
        if selected_slot:
            slot_date = selected_slot.get("date", "")
            slot_time = selected_slot.get("time", "")
            lines.append(f"✅ Horario: {slot_date} a las {slot_time}")

        customer_name = mode_context.get("customer_name")
        if customer_name:
            lines.append(f"✅ Nombre: {customer_name}")

        customer_id = mode_context.get("customer_id")
        if customer_id:
            lines.append(f"✅ Customer ID: {customer_id}")

        notes = mode_context.get("notes")
        if notes:
            lines.append(f"✅ Notas: {notes}")

        return "\n".join(lines) if lines else "(ningún dato recogido todavía)"

    def _build_missing_summary(self, mode_context: dict) -> str:
        """Build missing_data summary from flat mode_context dict."""
        missing: list[str] = []

        last_services = mode_context.get("last_services") or []
        if not last_services:
            missing.append("❌ Servicio: pendiente")

        if last_services and not mode_context.get("last_stylist"):
            missing.append("❌ Estilista: pendiente")

        selected_slot = mode_context.get("selected_slot")
        offered_slots = mode_context.get("offered_slots") or []
        if selected_slot is None:
            if offered_slots:
                missing.append("⏳ Horario: elige uno de los ofrecidos")
            else:
                missing.append("❌ Fecha/hora: pendiente")

        service_known = bool(last_services)
        if (
            not mode_context.get("customer_name")
            and service_known
            and mode_context.get("last_stylist")
            and selected_slot is not None
        ):
            missing.append("❌ Nombre: pendiente")

        return "\n".join(missing)

    # ──────────────────────────────────────────────────────────────────────
    # Pending selection helpers (Tasks 2.1 / 2.2)
    # ──────────────────────────────────────────────────────────────────────

    def _resolve_pending_selection(self, state: ConversationState, mode_context: dict) -> None:
        """Resolve deterministic state-machine transitions from user input.

        Handles only what the LLM cannot do deterministically:
        - "Sin preferencia" detection → sets no_preference_stylist flag
        - Notes skip detection → marks notes_asked at notes_collection step
        - Slot acceptance: digit/time/ordinal/affirmative against offered_slots

        Service and stylist selection from numbered lists is handled by the LLM,
        which can read its own conversation history.

        Called at the top of handle(), BEFORE the agentic loop.
        """
        user_message = get_last_user_message(state).strip()
        if not user_message:
            return

        # "Sin preferencia" recognition: detect no-preference phrases and set the flag
        # so the LLM sees it in dynamic context without needing to re-parse.
        if _NO_PREFERENCE_PATTERNS.search(user_message) and not mode_context.get("last_stylist"):
            mode_context["no_preference_stylist"] = True
            mode_context["last_stylist"] = "Sin preferencia"
            logger.info("_resolve_pending_selection: no-preference detected from %r", user_message)
            return  # No further resolution needed for stylists

        # Notes skip logic: detect negative responses at the notes_collection step
        # "no", "nada", "ninguna", "sin notas" → mark step done, notes stays None
        _NOTES_SKIP_PATTERNS = re.compile(
            r"^(?:no|nada|ninguna|sin\s+notas?|no\s+hay\s+nada|no\s+tengo\s+nada)$",
            re.IGNORECASE,
        )
        if mode_context.get("booking_step") == "notes_collection" and _NOTES_SKIP_PATTERNS.match(
            user_message.strip()
        ):
            mode_context["notes_asked"] = True
            mode_context["notes"] = None
            logger.info(
                "_resolve_pending_selection: notes skipped (negative response: %r)", user_message
            )
            return

        # Slot acceptance transition: offered_slots + digit/time/ordinal/affirmative → selected_slot
        # Covers the deterministic state transition:
        #   bot proposes slots → user says "2", "a las 11", "la primera", "Sí" → selected_slot set
        offered_slots: list[dict] = mode_context.get("offered_slots") or []
        if offered_slots and not mode_context.get("selected_slot"):
            slot_resolved: dict | None = None
            msg_lower = user_message.strip().lower()

            # 1. Try bare digit (1-indexed)
            try:
                digit = int(user_message.strip())
                if 1 <= digit <= len(offered_slots):
                    slot_resolved = offered_slots[digit - 1]
                    logger.info(
                        "_resolve_pending_selection: slot resolved by digit %d → %r",
                        digit,
                        slot_resolved,
                    )
            except (ValueError, TypeError):
                pass

            # 2. Try time pattern ("a las 11", "las 9:00", "11:00", "a las 9 y media")
            if slot_resolved is None:
                time_match = _TIME_PATTERN.search(user_message)
                if time_match:
                    # Group layout: (1,2) from "las N[:MM]", (3,4) from "^HH:MM$"
                    raw_hour = time_match.group(1) or time_match.group(3)
                    raw_minute = time_match.group(2) or time_match.group(4)
                    if raw_hour is not None:
                        hour = int(raw_hour)
                        if raw_minute is not None:
                            minute = int(raw_minute)
                        elif "media" in msg_lower:
                            minute = 30
                        else:
                            minute = 0
                        target_time = f"{hour:02d}:{minute:02d}"
                        matches = [s for s in offered_slots if s.get("time", "") == target_time]
                        if len(matches) == 1:
                            slot_resolved = matches[0]
                            logger.info(
                                "_resolve_pending_selection: slot resolved by time %r → %r",
                                target_time,
                                slot_resolved,
                            )
                        # 0 matches or ambiguous → fall through (LLM handles it)

            # 3. Try ordinal ("la primera", "el último", "la segunda", etc.)
            if slot_resolved is None:
                ordinal_match = _ORDINAL_PATTERN.search(user_message)
                if ordinal_match:
                    stem = ordinal_match.group(1)[:5].lower()
                    idx = _ORDINAL_STEM_MAP.get(stem)
                    if idx is not None:
                        # Normalize -1 to actual last index
                        resolved_idx = idx if idx >= 0 else len(offered_slots) + idx
                        if 0 <= resolved_idx < len(offered_slots):
                            slot_resolved = offered_slots[resolved_idx]
                            logger.info(
                                "_resolve_pending_selection: slot resolved by ordinal %r (idx=%d) → %r",
                                ordinal_match.group(1),
                                resolved_idx,
                                slot_resolved,
                            )

            # 4. Try affirmative ("Sí", "Dale", "Ok") → only when exactly one slot offered
            if (
                slot_resolved is None
                and len(offered_slots) == 1
                and _is_spanish_affirmative(user_message)
            ):
                slot_resolved = offered_slots[0]
                logger.info(
                    "_resolve_pending_selection: slot resolved by affirmative %r → slot[0]=%r",
                    user_message,
                    slot_resolved,
                )

            if slot_resolved is not None:
                mode_context["selected_slot"] = slot_resolved
                mode_context["booking_step"] = "confirmation"
                # Also update last_stylist from slot if not already set
                if not mode_context.get("last_stylist") and slot_resolved.get("stylist_name"):
                    mode_context["last_stylist"] = slot_resolved["stylist_name"]
                logger.info(
                    "_resolve_pending_selection: selected_slot=%r, booking_step→confirmation",
                    slot_resolved,
                )

    # ──────────────────────────────────────────────────────────────────────
    # Mid-loop dynamic context refresh
    # ──────────────────────────────────────────────────────────────────────

    def _refresh_dynamic_context(self, working_messages: list) -> None:
        """Rebuild the dynamic context SystemMessage so the LLM sees fresh state.

        Called by the agentic loop after each tool round. Replaces the
        SystemMessage at _dynamic_context_index with an updated version
        reflecting any mode_context changes from tool results.
        """
        from langchain_core.messages import SystemMessage

        idx = getattr(self, "_dynamic_context_index", None)
        mode_context = getattr(self, "_mode_context", None)
        state = getattr(self, "_dynamic_context_state", None)
        if idx is None or mode_context is None or state is None:
            return
        if idx >= len(working_messages):
            return

        refreshed = self._build_dynamic_context(mode_context, state)
        working_messages[idx] = SystemMessage(content=refreshed)

    # ──────────────────────────────────────────────────────────────────────
    # Context helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_customer_from_state(state: ConversationState, mode_context: dict) -> None:
        """Inject customer name and ID from state if not already in mode_context.

        Handles returning customers whose data was collected in GREETING mode.
        Priority: customer_first_name > customer_name from state.
        """
        if not mode_context.get("customer_name"):
            state_name = state.get("customer_first_name") or state.get("customer_name")
            if state_name:
                mode_context["customer_name"] = str(state_name)

        if not mode_context.get("customer_id"):
            state_id = state.get("customer_id")
            if state_id:
                mode_context["customer_id"] = str(state_id)

        # Propagate service_audience_hint from greeting handoff (safety net)
        if not mode_context.get("service_audience_hint"):
            state_hint = (state.get("mode_context") or {}).get("service_audience_hint")
            if state_hint:
                mode_context["service_audience_hint"] = state_hint


# Backward-compat alias — conversation_flow.py imports BookingMode by name
BookingMode = BookingModeNode

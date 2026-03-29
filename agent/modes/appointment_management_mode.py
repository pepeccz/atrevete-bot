"""
Appointment Management Mode — LLM-Driven Appointment Management.

Handles querying, cancelling, and rescheduling appointments for the
APPOINTMENT_MANAGEMENT mode (v6.0 mode-based architecture).

Architecture (AD-1): Single agentic loop + AppointmentContext bag.
There is NO step enum, NO transition table, NO FSM. The LLM drives the
conversation based on collected/missing data injected as SystemMessage.

Core principle: Python only does:
1. Pre-resolvers (deterministic): detect action from intent, resolve
   selected_appointment_id from user number input, detect confirmation
2. Safety gates (_pre_tool_call): block cancel/reschedule without pending_confirmation
3. Post-processing (_post_tool_result): extract tool results into context mid-loop
"""

import json
import logging
import re
import unicodedata
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.tools import StructuredTool

from agent.modes.appointment_context import AppointmentContext
from agent.modes.base import BaseModeNode, ToolCallRejection
from agent.prompts.loader import build_layered_messages
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState, transition_mode

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

MADRID_TZ = ZoneInfo("Europe/Madrid")
_HISTORY_LIMIT = 8

# Affirmative phrases that trigger pending_confirmation=True
_AFFIRMATIVE_PHRASES: frozenset[str] = frozenset(
    {
        "si",
        "sí",
        "dale",
        "ok",
        "perfecto",
        "va",
        "adelante",
        "bueno",
        "confirmo",
        "confirmar",
        "confirmá",
        "confirmalo",
        "de acuerdo",
        "genial",
        "claro",
        "por supuesto",
        "venga",
        "listo",
        "hecho",
        "eso",
        "correcto",
        "exacto",
        "tal cual",
        "quiero cancelar",
        "cancelar",
        "anular",
        "reagendar",
        "reprogramar",
    }
)

# Negation phrases that cancel a pending_confirmation
_NEGATION_PHRASES: frozenset[str] = frozenset(
    {
        "no",
        "no quiero",
        "mejor no",
        "cancelar",
        "anular",
        "para atras",
        "para atrás",
        "olvida",
        "olvidalo",
        "olvidá",
        "no confirmo",
    }
)

# Keywords for detecting action from intent string
_CANCEL_KEYWORDS: frozenset[str] = frozenset({"cancel", "cancelar", "anular", "baja", "eliminar"})
_RESCHEDULE_KEYWORDS: frozenset[str] = frozenset(
    {
        "reschedule",
        "reagendar",
        "reprogramar",
        "cambiar",
        "mover",
        "cambio",
        "otro dia",
        "otro horario",
    }
)
_QUERY_KEYWORDS: frozenset[str] = frozenset(
    {
        "query",
        "ver",
        "consultar",
        "listar",
        "mis citas",
        "mis reservas",
        "tengo cita",
        "info",
        "cuando",
        "cuándo",
    }
)


def _normalize_text(text: str) -> str:
    """Normalize text for comparison: lowercase, remove accents."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in normalized if not unicodedata.combining(c))


# ============================================================================
# AppointmentManagementMode
# ============================================================================


class AppointmentManagementMode(BaseModeNode):
    """LLM-driven appointment management mode — single agentic loop.

    Handles: listing appointments, cancelling, and rescheduling.
    Uses AppointmentContext as the data bag (same pattern as BookingContext).

    Safety gates:
    - _pre_tool_call() blocks cancel_appointment/reschedule_appointment
      until pending_confirmation=True is set by pre-resolver.
    - 48h window violations trigger ESCALATION mode.
    - Successful actions trigger GENERAL mode.
    """

    @property
    def mode_name(self) -> str:
        return "APPOINTMENT_MANAGEMENT"

    def get_tools(self) -> list[StructuredTool]:
        """Return all appointment management tools, injected with customer_phone.

        Tools:
        - list_customer_appointments (T2)
        - cancel_appointment (T3)
        - reschedule_appointment (T4)
        - check_availability (availability_tools)
        - find_next_available (availability_tools)
        """
        from agent.tools.appointment_management_tools import create_appointment_tools
        from agent.tools.availability_tools import check_availability, find_next_available

        state: ConversationState = getattr(self, "_current_state", {})
        customer_phone: str = state.get("customer_phone") or ""

        appointment_tools = create_appointment_tools(customer_phone)
        return [*appointment_tools, check_availability, find_next_available]

    # ──────────────────────────────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────────────────────────────

    async def handle(self, state: ConversationState, intent: Any) -> dict:
        """Process one turn of the appointment management conversation.

        Flow:
        1. Hydrate AppointmentContext from mode_context
        2. Pre-resolvers (deterministic, before LLM call)
        3. Build unified prompt with dynamic context
        4. Run single agentic loop with all tools
        5. Extract tool results into context
        6. Build and return state update (with mode transitions if needed)
        """
        # Store state for tool injection (get_tools uses _current_state)
        self._current_state = state

        mode_context = dict(state.get("mode_context") or {})
        ctx = AppointmentContext.from_mode_context(mode_context)

        # 1. Pre-resolvers (deterministic)
        user_message = self._get_last_user_message(state)
        self._resolve_action_from_intent(ctx, intent, user_message)
        self._resolve_appointment_selection(ctx, user_message)
        self._resolve_confirmation_state(ctx, user_message)

        # 2. Store ctx for _pre_tool_call and _post_tool_result access
        self._ctx = ctx

        # 3. Build messages
        messages = await self._build_messages(state, ctx)

        # 4. Run agentic loop
        result = await self._run_agentic_loop(messages, tools=self.get_tools())

        # 5. Extract tool results into ctx
        self._apply_tool_results(result.tool_results, ctx)

        # 6. Build and return state update
        return self._build_response(state, ctx, result)

    # ──────────────────────────────────────────────────────────────────────
    # Pre-Resolvers
    # ──────────────────────────────────────────────────────────────────────

    def _resolve_action_from_intent(
        self,
        ctx: AppointmentContext,
        intent: Any,
        user_message: str,
    ) -> None:
        """Detect action (cancel/reschedule/query) from intent and message.

        Only sets ctx.action if it is not already determined (preserves
        cross-turn continuity).
        """
        if ctx.action:
            return  # Already determined — preserve across turns

        intent_name = self._extract_intent_name(intent)
        msg_lower = _normalize_text(user_message)

        # Check intent string first
        if any(kw in intent_name for kw in _CANCEL_KEYWORDS):
            ctx.action = "cancel"
            logger.info("_resolve_action: cancel from intent=%r", intent_name)
            return

        if any(kw in intent_name for kw in _RESCHEDULE_KEYWORDS):
            ctx.action = "reschedule"
            logger.info("_resolve_action: reschedule from intent=%r", intent_name)
            return

        if any(kw in intent_name for kw in _QUERY_KEYWORDS):
            ctx.action = "query"
            logger.info("_resolve_action: query from intent=%r", intent_name)
            return

        # Fallback: check user message keywords
        if any(kw in msg_lower for kw in _CANCEL_KEYWORDS):
            ctx.action = "cancel"
            logger.info("_resolve_action: cancel from message=%r", user_message[:50])
            return

        if any(kw in msg_lower for kw in _RESCHEDULE_KEYWORDS):
            ctx.action = "reschedule"
            logger.info("_resolve_action: reschedule from message=%r", user_message[:50])
            return

        if any(kw in msg_lower for kw in _QUERY_KEYWORDS):
            ctx.action = "query"
            logger.info("_resolve_action: query from message=%r", user_message[:50])
            return

        # No action detected — LLM will ask the user
        logger.debug("_resolve_action: no action detected, LLM will ask")

    def _resolve_appointment_selection(
        self,
        ctx: AppointmentContext,
        user_message: str,
    ) -> None:
        """If appointments_list is loaded and user replied with a number, select it.

        Supports 1-based index: "1" → appointments_list[0].
        Only runs when selected_appointment_id is not yet set.
        """
        if ctx.selected_appointment_id:
            return  # Already selected

        if not ctx.appointments_list:
            return  # Nothing to select from

        msg_stripped = user_message.strip() if user_message else ""

        # Match a leading digit (1–20)
        match = re.match(r"^(\d{1,2})(?:\D|$)", msg_stripped)
        if not match:
            return

        index_1based = int(match.group(1))
        index_0based = index_1based - 1

        if 0 <= index_0based < len(ctx.appointments_list):
            selected = ctx.appointments_list[index_0based]
            ctx.selected_appointment_id = selected.get("id", "")
            ctx.selected_appointment_snapshot = dict(selected)
            logger.info(
                "_resolve_appointment_selection: selected index=%d id=%s",
                index_1based,
                ctx.selected_appointment_id,
            )
        else:
            logger.warning(
                "_resolve_appointment_selection: index=%d out of range (list len=%d)",
                index_1based,
                len(ctx.appointments_list),
            )

    def _resolve_confirmation_state(
        self,
        ctx: AppointmentContext,
        user_message: str,
    ) -> None:
        """Detect user affirmation or negation to update pending_confirmation.

        Rules:
        - If pending_confirmation=True and user negates → reset pending_confirmation
        - If pending_confirmation=False and user affirms → set pending_confirmation=True
          (only when a selected_appointment_id exists, so we know what to confirm)

        Note: when pending_confirmation=True and user says "sí", we keep it True —
        the tool will fire in _pre_tool_call when the LLM calls cancel/reschedule.
        """
        if not user_message:
            return

        msg_lower = _normalize_text(user_message)

        # If pending_confirmation is True and user negates → reset
        if ctx.pending_confirmation:
            if any(neg in msg_lower for neg in _NEGATION_PHRASES):
                # Only reset on explicit negation UNLESS the negation IS the action word
                # e.g. "cancelar" is both in negation AND is the action — don't reset for that
                pure_negations = {
                    "no",
                    "no quiero",
                    "mejor no",
                    "para atras",
                    "para atrás",
                    "olvida",
                    "olvidalo",
                    "olvidá",
                    "no confirmo",
                }
                if any(neg in msg_lower for neg in pure_negations):
                    ctx.pending_confirmation = False
                    ctx.pending_confirmation_type = ""
                    logger.info("_resolve_confirmation: user negated — pending_confirmation reset")
                    return

        # If pending_confirmation is False and we have a selected appointment and user affirms
        if (
            not ctx.pending_confirmation
            and ctx.selected_appointment_id
            and ctx.action in ("cancel", "reschedule")
        ):
            # For reschedule: require a pending_new_slot too
            if ctx.action == "reschedule" and not ctx.pending_new_slot:
                return  # Can't confirm reschedule without knowing the new slot

            if any(affirm in msg_lower for affirm in _AFFIRMATIVE_PHRASES):
                ctx.pending_confirmation = True
                ctx.pending_confirmation_type = ctx.action
                logger.info(
                    "_resolve_confirmation: user affirmed → pending_confirmation=True, type=%s",
                    ctx.action,
                )

    # ──────────────────────────────────────────────────────────────────────
    # Pre-tool-call safety gates
    # ──────────────────────────────────────────────────────────────────────

    async def _pre_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> dict[str, Any] | ToolCallRejection:
        """Gate dangerous tools — block destructive operations without confirmation.

        Gates:
        - cancel_appointment: requires pending_confirmation=True AND type="cancel"
        - reschedule_appointment: requires pending_confirmation=True AND type="reschedule"
          AND pending_new_slot is set

        Returns:
            Modified tool_args (or unchanged), or ToolCallRejection to skip execution.
        """
        ctx: AppointmentContext | None = getattr(self, "_ctx", None)

        if tool_name == "cancel_appointment":
            if ctx is None:
                return ToolCallRejection(
                    name="cancel_appointment",
                    error_code="NO_CONTEXT",
                    error_message="No hay contexto de cita disponible.",
                )
            if not ctx.pending_confirmation or ctx.pending_confirmation_type != "cancel":
                logger.warning(
                    "_pre_tool_call: cancel_appointment blocked — pending_confirmation=%s, type=%r",
                    ctx.pending_confirmation,
                    ctx.pending_confirmation_type,
                )
                return ToolCallRejection(
                    name="cancel_appointment",
                    error_code="CONFIRMATION_REQUIRED",
                    error_message=(
                        "Debes confirmar la cancelación antes de ejecutarla. "
                        "Mostrá el resumen de la cita y pedí confirmación explícita al cliente."
                    ),
                )

            # Inject appointment_id from context (never trust LLM's value alone)
            if ctx.selected_appointment_id:
                tool_args["appointment_id"] = ctx.selected_appointment_id
                logger.info(
                    "_pre_tool_call: injected appointment_id=%s into cancel_appointment",
                    ctx.selected_appointment_id,
                )

        elif tool_name == "reschedule_appointment":
            if ctx is None:
                return ToolCallRejection(
                    name="reschedule_appointment",
                    error_code="NO_CONTEXT",
                    error_message="No hay contexto de cita disponible.",
                )
            if not ctx.pending_confirmation or ctx.pending_confirmation_type != "reschedule":
                logger.warning(
                    "_pre_tool_call: reschedule_appointment blocked — "
                    "pending_confirmation=%s, type=%r",
                    ctx.pending_confirmation,
                    ctx.pending_confirmation_type,
                )
                return ToolCallRejection(
                    name="reschedule_appointment",
                    error_code="CONFIRMATION_REQUIRED",
                    error_message=(
                        "Debes confirmar el nuevo horario antes de reagendar. "
                        "Mostrá el nuevo horario y pedí confirmación explícita al cliente."
                    ),
                )
            if not ctx.pending_new_slot:
                logger.warning(
                    "_pre_tool_call: reschedule_appointment blocked — pending_new_slot is empty"
                )
                return ToolCallRejection(
                    name="reschedule_appointment",
                    error_code="NO_NEW_SLOT",
                    error_message=(
                        "No hay un nuevo horario seleccionado. "
                        "Llamá check_availability o find_next_available primero, "
                        "y esperá que el cliente elija un horario."
                    ),
                )

            # Inject appointment_id from context
            if ctx.selected_appointment_id:
                tool_args["appointment_id"] = ctx.selected_appointment_id
                logger.info(
                    "_pre_tool_call: injected appointment_id=%s into reschedule_appointment",
                    ctx.selected_appointment_id,
                )
            # Inject new_start_time from pending_new_slot if not already set
            if not tool_args.get("new_start_time") and ctx.pending_new_slot:
                new_dt = ctx.pending_new_slot.get("full_datetime") or ctx.pending_new_slot.get(
                    "start_time"
                )
                if new_dt:
                    tool_args["new_start_time"] = new_dt
                    logger.info(
                        "_pre_tool_call: injected new_start_time=%s from pending_new_slot",
                        new_dt,
                    )

        return tool_args

    # ──────────────────────────────────────────────────────────────────────
    # Post-tool-result hook
    # ──────────────────────────────────────────────────────────────────────

    async def _post_tool_result(
        self,
        tool_name: str,
        tool_args: dict,
        result: Any,
    ) -> Any:
        """Extract tool results into ctx immediately (mid-loop) so the LLM
        sees fresh context on its next invocation.
        """
        ctx: AppointmentContext | None = getattr(self, "_ctx", None)
        if ctx is None:
            return result

        # Parse result if it's a JSON string
        parsed: dict | None = None
        if isinstance(result, dict):
            parsed = result
        elif isinstance(result, str):
            try:
                candidate = json.loads(result)
                if isinstance(candidate, dict):
                    parsed = candidate
            except (json.JSONDecodeError, TypeError):
                pass

        if not parsed:
            return result

        if tool_name == "list_customer_appointments":
            appointments = parsed.get("appointments", [])
            if appointments:
                ctx.appointments_list = appointments
                logger.info(
                    "_post_tool_result: list_customer_appointments — loaded %d appointments",
                    len(appointments),
                )

        elif tool_name in ("check_availability", "find_next_available"):
            # Extract offered slots for reschedule flow
            slots: list[dict] = []

            # check_availability format
            if "available_slots" in parsed:
                slots = parsed.get("available_slots", [])

            # find_next_available format (v4.2)
            elif "available_stylists" in parsed:
                for stylist_entry in parsed.get("available_stylists", []):
                    slots.extend(stylist_entry.get("slots", []))
                # Also include soonest_any if present
                soonest = parsed.get("soonest_any")
                if soonest:
                    slots.insert(0, soonest)

            if slots:
                ctx.offered_slots = slots
                logger.info(
                    "_post_tool_result: %s — loaded %d offered slots",
                    tool_name,
                    len(slots),
                )

        return result

    # ──────────────────────────────────────────────────────────────────────
    # Tool result application (post-loop)
    # ──────────────────────────────────────────────────────────────────────

    def _apply_tool_results(
        self,
        tool_results: dict[str, Any],
        ctx: AppointmentContext,
    ) -> None:
        """Apply all tool results accumulated from the agentic loop into ctx.

        Handles:
        - cancel_appointment success/within_window
        - reschedule_appointment success/within_window
        """
        for tool_name, results_list in tool_results.items():
            for result in results_list:
                parsed: dict | None = None
                if isinstance(result, dict):
                    parsed = result
                elif isinstance(result, str):
                    try:
                        parsed = json.loads(result)
                    except (json.JSONDecodeError, TypeError):
                        pass

                if not parsed:
                    continue

                if tool_name == "cancel_appointment":
                    if parsed.get("success"):
                        ctx.action_completed = True
                        logger.info(
                            "_apply_tool_results: cancel_appointment success — action_completed=True"
                        )
                    elif parsed.get("within_window"):
                        ctx._escalate_within_window = True
                        ctx._escalation_tool = "cancel_appointment"
                        hours = parsed.get("hours_until")
                        ctx._escalation_hours = hours
                        logger.info(
                            "_apply_tool_results: cancel_appointment within_window "
                            "(hours_until=%s) — escalation required",
                            hours,
                        )

                elif tool_name == "reschedule_appointment":
                    if parsed.get("success"):
                        ctx.action_completed = True
                        logger.info(
                            "_apply_tool_results: reschedule_appointment success — "
                            "action_completed=True"
                        )
                    elif parsed.get("within_window"):
                        ctx._escalate_within_window = True
                        ctx._escalation_tool = "reschedule_appointment"
                        hours = parsed.get("hours_until")
                        ctx._escalation_hours = hours
                        logger.info(
                            "_apply_tool_results: reschedule_appointment within_window "
                            "(hours_until=%s) — escalation required",
                            hours,
                        )

    # ──────────────────────────────────────────────────────────────────────
    # Prompt Building
    # ──────────────────────────────────────────────────────────────────────

    async def _build_messages(self, state: ConversationState, ctx: AppointmentContext) -> list:
        """Build the complete message list for the agentic loop.

        Uses build_layered_messages() with a dynamic_context_override that
        contains the appointment management context (collected/missing data).
        """
        dynamic_context = self._build_dynamic_context(state, ctx)

        messages, dynamic_context_index = await build_layered_messages(
            state=state,
            mode_context=dict(state.get("mode_context") or {}),
            mode_name="APPOINTMENT_MANAGEMENT",
            dynamic_context_override=dynamic_context,
            include_history=True,
            history_limit=_HISTORY_LIMIT,
        )

        # Store for potential mid-loop refresh
        self._dynamic_context_index = dynamic_context_index
        self._dynamic_context_state = state

        return messages

    @staticmethod
    def _build_dynamic_context(state: ConversationState, ctx: AppointmentContext) -> str:
        """Build the dynamic context SystemMessage injected last in the prompt.

        Pattern mirrors BookingMode._build_dynamic_context():
        <collected_data> / <missing_data> / <appointment_context> / <instrucciones_situación>
        """
        now = datetime.now(MADRID_TZ)
        parts: list[str] = []

        # Temporal context
        parts.append(f"Fecha y hora actual: {now.strftime('%A %d de %B de %Y, %H:%M')} (Madrid)")

        # Phone
        phone = state.get("customer_phone")
        if phone:
            parts.append(f"Teléfono del cliente: {phone}")

        # Conversation summary
        summary = state.get("conversation_summary")
        if summary:
            parts.append(f"\nContexto previo:\n{summary}")

        # Collected data (AppointmentContext renders this)
        parts.append(f"\n<collected_data>\n{ctx.collected_summary()}\n</collected_data>")

        # Missing data
        parts.append(f"\n<missing_data>\n{ctx.missing_summary()}\n</missing_data>")

        # Appointment context — flat view of key state fields for LLM
        appts_str = f"{len(ctx.appointments_list)} cita(s) cargada(s)"
        appt_ids = (
            ", ".join(
                f"[{a.get('index', i + 1)}] {a.get('date_display', '')} {a.get('time_display', '')}"
                for i, a in enumerate(ctx.appointments_list[:5])
            )
            if ctx.appointments_list
            else "ninguna"
        )
        parts.append(
            f"\n<appointment_context>"
            f"\n  acción: {ctx.action or 'desconocida'}"
            f"\n  citas cargadas: {appts_str} ({appt_ids})"
            f"\n  cita seleccionada: {ctx.selected_appointment_id or 'ninguna'}"
            f"\n  confirmación pendiente: {ctx.pending_confirmation} ({ctx.pending_confirmation_type or '-'})"
            f"\n  slots ofrecidos: {len(ctx.offered_slots) if ctx.offered_slots is not None else 0}"
            f"\n</appointment_context>"
        )

        # Situational instructions — tell the LLM exactly what to do next
        parts.append(f"\n<instrucciones_situación>")
        instructions = _build_situational_instructions(ctx)
        parts.append(instructions)
        parts.append("</instrucciones_situación>")

        return "\n".join(parts)

    # ──────────────────────────────────────────────────────────────────────
    # Response Building
    # ──────────────────────────────────────────────────────────────────────

    def _build_response(
        self,
        state: ConversationState,
        ctx: AppointmentContext,
        result: Any,
    ) -> dict:
        """Build final state update dict.

        Handles:
        - 48h window escalation → transition to ESCALATION
        - Success → transition to GENERAL
        - Normal turn → persist ctx to mode_context
        - First-turn AI disclosure
        """
        response_text = result.response_text or ""

        # First-turn intro (EU AI Act compliance)
        response_text, disclosure_sent = self._maybe_prepend_intro(response_text, state)

        # Check for within_window escalation (48h block)
        escalate_window = getattr(ctx, "_escalate_within_window", False)
        if escalate_window:
            snapshot = ctx.selected_appointment_snapshot
            date_display = snapshot.get("date_display", "próxima")
            time_display = snapshot.get("time_display", "")
            action_word = (
                "cancelar"
                if getattr(ctx, "_escalation_tool", "") == "cancel_appointment"
                else "reagendar"
            )
            escalation_response = (
                f"Tu cita del {date_display}"
                + (f" a las {time_display}" if time_display else "")
                + f" está dentro de las 48 horas. "
                f"Para {action_word} una cita tan próxima, te comunico con el equipo. "
                f"Te ayudarán enseguida. 🙏"
            )
            escalation_response, disclosure_sent = self._maybe_prepend_intro(
                escalation_response, state
            )

            stylist_name = snapshot.get("stylist_name", "")
            customer_name = state.get("customer_name", "")
            updates: dict = {
                **transition_mode(
                    state,
                    "ESCALATION",
                    context_update={
                        "escalation_reason": (
                            f"Cliente solicitó {action_word} de cita dentro de ventana 48h. "
                            f"Cita: {date_display} {time_display} con {stylist_name}. "
                            f"Acción solicitada: {action_word}. "
                            f"Cliente: {customer_name}."
                        ),
                        "escalation_action": action_word,
                        "appointment_date": date_display,
                        "appointment_time": time_display,
                        "stylist_name": stylist_name,
                        "customer_name": customer_name,
                        "appointment_id": ctx.selected_appointment_id,
                        "requested_action": getattr(ctx, "action", action_word),
                    },
                ),
                **add_message(state, "assistant", escalation_response),
                "last_node": "appointment_management",
                "user_message": None,
            }
            if disclosure_sent:
                updates["ai_disclosure_sent"] = True
            logger.info(
                "_build_response: 48h window → ESCALATION (action=%s, date=%s)",
                action_word,
                date_display,
            )
            return updates

        # Check for successful action completion → transition to GENERAL
        if ctx.action_completed:
            logger.info("_build_response: action_completed=True → transitioning to GENERAL")
            updates = {
                **transition_mode(state, "GENERAL"),
                **add_message(state, "assistant", response_text),
                "last_node": "appointment_management",
                "user_message": None,
            }
            if disclosure_sent:
                updates["ai_disclosure_sent"] = True
            return updates

        # Normal turn — persist ctx
        updates = {
            **add_message(state, "assistant", response_text),
            "mode_context": ctx.to_mode_context(),
            "last_node": "appointment_management",
            "user_message": None,
        }
        if disclosure_sent:
            updates["ai_disclosure_sent"] = True

        return updates

    # ──────────────────────────────────────────────────────────────────────
    # Utility helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_intent_name(intent: Any) -> str:
        """Extract intent name string from various intent object shapes."""
        if intent is None:
            return ""
        if hasattr(intent, "intent"):
            return str(intent.intent)
        if isinstance(intent, dict):
            return str(intent.get("intent", ""))
        if isinstance(intent, str):
            return intent
        return ""

    @staticmethod
    def _get_last_user_message(state: ConversationState) -> str:
        """Extract the last user message content from state messages."""
        for msg in reversed(state.get("messages", [])):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return ""


# ============================================================================
# Module-level helper — situational instructions for LLM
# ============================================================================


def _build_situational_instructions(ctx: AppointmentContext) -> str:
    """Build situation-aware instructions for the LLM based on ctx state.

    The LLM sees exactly what to do next — no guessing required.
    """
    lines: list[str] = []

    # Case 1: Action not determined yet
    if not ctx.action:
        lines.append(
            "El cliente no ha indicado qué quiere hacer. "
            "Preguntá si quiere VER sus citas, CANCELAR una cita, o REAGENDAR una cita. "
            "Una vez determinada la acción, llamá list_customer_appointments."
        )
        return "\n".join(lines)

    # Case 2: No appointments loaded
    if not ctx.appointments_list and not ctx.action_completed:
        lines.append(
            f"Acción detectada: {ctx.action}. "
            "Llamá list_customer_appointments para cargar las citas del cliente."
        )
        return "\n".join(lines)

    # Case 3: Appointments loaded but none selected
    if ctx.appointments_list and not ctx.selected_appointment_id and not ctx.action_completed:
        if len(ctx.appointments_list) == 1:
            # Only one appointment — auto-select or ask for confirmation
            lines.append(f"Solo hay 1 cita. Mostrala y preguntá si es la que quiere {ctx.action}.")
        else:
            lines.append(
                f"Hay {len(ctx.appointments_list)} citas. "
                "Mostrá la lista numerada y pedí al cliente que elija con un número (1, 2, 3...)."
            )
        return "\n".join(lines)

    # Case 4: Appointment selected, action=query → done, can transition
    if ctx.action == "query" and ctx.selected_appointment_id:
        lines.append(
            "El cliente solo quería VER sus citas. "
            "Mostrá el detalle de la cita seleccionada o el listado completo. "
            "Luego ofrecé más ayuda."
        )
        return "\n".join(lines)

    # Case 5: Action=cancel, appointment selected
    if ctx.action == "cancel" and ctx.selected_appointment_id:
        if ctx.pending_confirmation and ctx.pending_confirmation_type == "cancel":
            lines.append(
                "✅ CONFIRMACIÓN RECIBIDA para cancelación. "
                "Llamá cancel_appointment ahora mismo con el appointment_id del contexto."
            )
        else:
            snapshot = ctx.selected_appointment_snapshot
            date_str = snapshot.get("date_display", "")
            time_str = snapshot.get("time_display", "")
            stylist_str = snapshot.get("stylist_name", "")
            cita_desc = f"del {date_str}" + (f" a las {time_str}" if time_str else "")
            if stylist_str:
                cita_desc += f" con {stylist_str}"
            lines.append(
                f"Mostrá el resumen de la cita {cita_desc} y preguntá: "
                f"'¿Confirmás la cancelación?' Esperá respuesta afirmativa antes de actuar."
            )
        return "\n".join(lines)

    # Case 6: Action=reschedule, appointment selected
    if ctx.action == "reschedule" and ctx.selected_appointment_id:
        if not ctx.offered_slots:
            lines.append(
                "Llamá check_availability o find_next_available para buscar horarios disponibles "
                "y mostrárselos al cliente."
            )
        elif not ctx.pending_new_slot:
            lines.append(
                f"Hay {len(ctx.offered_slots)} horario(s) disponible(s). "
                "Mostrá la lista numerada y pedí al cliente que elija uno."
            )
        elif ctx.pending_confirmation and ctx.pending_confirmation_type == "reschedule":
            lines.append(
                "✅ CONFIRMACIÓN RECIBIDA para reagendado. "
                "Llamá reschedule_appointment ahora mismo con el appointment_id y new_start_time del contexto."
            )
        else:
            slot_time = ctx.pending_new_slot.get("time", "")
            slot_date = ctx.pending_new_slot.get("date", "")
            lines.append(
                f"El cliente eligió el horario: {slot_date} a las {slot_time}. "
                "Mostrá el resumen del nuevo horario y preguntá: "
                "'¿Confirmás el reagendado?' Esperá respuesta afirmativa."
            )
        return "\n".join(lines)

    # Default: shouldn't reach here, but guide LLM to ask
    lines.append("Continuá el flujo según el estado actual. Preguntá al cliente qué necesita.")
    return "\n".join(lines)

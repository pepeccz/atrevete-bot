"""
Booking Mode — Simplified LLM-Driven Booking Architecture.

~380 lines. Python retains ONLY what the LLM cannot do:
  - UUID injection (slot_index → stylist_id/start_time)
  - mode_context update from tool results

Tool surface: check_availability, book (2 tools).
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
from agent.services.customer_memory_service import write_customer_memories
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


# ============================================================================
# Disambiguation table — deterministic mapping from service keywords to questions
# ============================================================================

_DISAMBIGUATION_TABLE: list[dict[str, Any]] = [
    # Audience disambiguation (corte has audience variants)
    {
        "keywords": ["corte", "cortarme", "cortarme el pelo", "pelo"],
        "axis": "audience",
        "question": "Para el corte: ¿es para señora, caballero, niño/a o bebé?",
        "skip_if_audience_hint": True,
    },
    # Condition disambiguation (service families with condition variants)
    {
        "keywords": ["oleo", "óleo"],
        "axis": "condition",
        "question": "Para el tratamiento de óleo: ¿es un mantenimiento o tu pelo está muy seco/dañado?",
    },
    {
        "keywords": ["peinado", "peinarme", "secado con forma"],
        "axis": "condition",
        "question": "Para el peinado: ¿tu pelo es corto, largo o muy largo?",
    },
    {
        "keywords": ["moldeado"],
        "axis": "condition",
        "question": "Para el moldeado: ¿tu pelo es largo o muy denso?",
    },
    {
        "keywords": ["mechas"],
        "axis": "condition",
        "question": "Para las mechas: ¿completas o solo en algunas zonas?",
    },
    {
        "keywords": ["recogido"],
        "axis": "condition",
        "question": "Para el recogido: ¿es para boda, evento especial o algo más casual?",
    },
    {
        "keywords": ["cultura de color", "color", "tinte", "teñirme"],
        "axis": "condition",
        "question": "Para el color: ¿tu pelo es de densidad normal o muy denso/largo?",
    },
    {
        "keywords": ["barro"],
        "axis": "condition",
        "question": "Para el barro: ¿clásico o con tonos dorados (Gold)? ¿Pelo normal o denso/dañado?",
    },
    {
        "keywords": ["infoactivo"],
        "axis": "condition",
        "question": "Para el tratamiento: ¿sentís el pelo debilitado o el cuero cabelludo sensible?",
    },
    {
        "keywords": ["maquillaje", "maquillarme"],
        "axis": "condition",
        "question": "Para el maquillaje: ¿es para el día a día, un evento o una boda?",
    },
    {
        "keywords": ["masaje"],
        "axis": "condition",
        "question": "Para el masaje: ¿preferís 30 minutos o una hora completa?",
    },
    {
        "keywords": ["sculptor", "anticelul"],
        "axis": "condition",
        "question": "Para la bioterapia sculptor: ¿querés añadir radiofrecuencia?",
    },
    {
        "keywords": ["uñas de manos", "manicura", "pintar manos", "uñas manos"],
        "axis": "condition",
        "question": "Para las uñas de manos: ¿pintar normal, permanente, tratamiento o permanente con tratamiento?",
    },
    {
        "keywords": ["uñas de pies", "pedicura", "pintar pies", "uñas pies"],
        "axis": "condition",
        "question": "Para las uñas de pies: ¿pintar normal, permanente, tratamiento o permanente con tratamiento?",
    },
    {
        "keywords": ["bioterapia facial", "facial"],
        "axis": "condition",
        "question": "Para la bioterapia facial: ¿querés añadir radiofrecuencia?",
    },
]


def _normalize_for_match(text: str) -> str:
    """Normalize text for keyword matching: lowercase, strip accents."""
    import unicodedata

    raw = text.strip().lower()
    normalized = unicodedata.normalize("NFKD", raw)
    return "".join(c for c in normalized if not unicodedata.combining(c))


# ============================================================================
# Deterministic signal keywords — used by _resolve_conversational_signals
# ============================================================================

_ADD_MORE_DECLINE_KEYWORDS: frozenset[str] = frozenset({
    "no", "nada", "nada mas", "solo eso", "ya esta", "eso es todo",
    "no gracias", "solo", "no mas", "ya",
})

_NO_PREFERENCE_KEYWORDS: frozenset[str] = frozenset({
    "me da igual", "cualquiera", "la primera", "sin preferencia",
    "da lo mismo", "no me importa", "la que sea", "el que sea",
    "da igual", "no tengo preferencia", "la primera disponible",
    "la que este", "el que este",
})

_NOTES_DECLINE_KEYWORDS: frozenset[str] = frozenset({
    "no", "nada", "ninguna", "sin notas", "paso", "no tengo",
    "nada especial", "no hace falta", "no gracias",
})


def _detect_disambiguation_needs(
    message: str, audience_hint: str | None = None
) -> list[str]:
    """Detect which disambiguation questions are needed for services in a message.

    Returns a list of natural-language question strings. Deterministic — no LLM involved.
    """
    normalized = _normalize_for_match(message)
    questions: list[str] = []
    matched_axes: set[str] = set()

    for entry in _DISAMBIGUATION_TABLE:
        # Skip if this axis+family combo already matched
        axis_key = f"{entry['axis']}:{entry['keywords'][0]}"
        if axis_key in matched_axes:
            continue

        # Check if any keyword appears in the message
        for kw in entry["keywords"]:
            kw_normalized = _normalize_for_match(kw)
            if kw_normalized in normalized:
                # Skip audience question if audience_hint is already set
                if entry.get("skip_if_audience_hint") and audience_hint:
                    break
                questions.append(entry["question"])
                matched_axes.add(axis_key)
                break

    return questions




# ============================================================================
# BookingModeNode
# ============================================================================


class BookingModeNode(BaseModeNode):
    """Simplified LLM-driven booking mode — 3 tools, flat dict mode_context.

    Python retains only what the LLM cannot do:
    - UUID injection (slot_index → stylist_id/start_time)
    - Confirmation gate (book() rejected unless step == confirmation)
    - mode_context updates from tool results
    """

    @property
    def mode_name(self) -> str:
        return "BOOKING"

    def get_tools(self) -> list:
        """Return the 2 booking tools for the agentic loop."""
        from agent.tools.availability_tools import check_availability
        from agent.tools.booking_tools import book

        return [check_availability, book]

    # ──────────────────────────────────────────────────────────────────────
    # Booking completeness check — GATE for book(), not a flow sequencer
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _booking_complete(ctx: dict) -> tuple[bool, list[str]]:
        """Check if all required booking fields are present.

        This is a GATE, not a sequencer — it checks whether book() can proceed,
        without dictating the ORDER in which data should be collected.

        Returns:
            (is_complete, list_of_missing_field_names_in_spanish)
        """
        missing: list[str] = []
        if not ctx.get("last_services"):
            missing.append("servicio")
        if not (ctx.get("last_stylist") or ctx.get("no_preference_stylist")):
            missing.append("estilista")
        if not ctx.get("selected_slot"):
            missing.append("fecha/hora")
        if not ctx.get("customer_name"):
            missing.append("nombre")
        # Notes are optional — the LLM handles asking via prompt (Paso 5).
        # No Python gate needed; book() accepts notes=None.
        return (len(missing) == 0, missing)

    @staticmethod
    def _build_flow_hint(ctx: dict) -> str:
        """Build a prescriptive flow hint for the current booking phase.

        Phase-aware: detects where the flow is from booking_context fields
        and outputs a specific instruction with explicit tool constraints.
        """
        has_services = bool(ctx.get("last_services"))
        has_stylist = bool(ctx.get("last_stylist") or ctx.get("no_preference_stylist"))
        has_slots = bool(ctx.get("offered_slots"))
        has_selected = bool(ctx.get("selected_slot"))
        has_name = bool(ctx.get("customer_name"))
        has_notes = bool(ctx.get("notes") or ctx.get("notes_asked"))

        # Phase 1: services not resolved yet
        if not has_services:
            return (
                "<flow_hint>PASO ACTUAL: Identificar servicios del catálogo. "
                "NO llames herramientas hasta tener todos los servicios resueltos.</flow_hint>"
            )

        # Phase 1B: services resolved, check if "¿algo más?" needed
        # Skip if user gave date or stylist hints (complete-intent shortcut)
        if not ctx.get("add_more_asked"):
            if not ctx.get("preferred_date_hint") and not ctx.get("preferred_stylist_name"):
                return (
                    "<flow_hint>PASO ACTUAL: Preguntá al cliente \"¿Querés añadir algo más a la cita?\". "
                    "NO llames herramientas. Esperá respuesta.</flow_hint>"
                )

        # Phase 2: stylist not resolved
        if not has_stylist:
            return (
                "<flow_hint>PASO ACTUAL: Mostrá la lista numerada de estilistas de "
                "<available_stylists> con la última opción \"la primera con disponibilidad\". "
                "NO llames check_availability hasta tener respuesta del cliente.</flow_hint>"
            )

        # Phase 3: date — need to ask what day
        if not has_slots:
            return (
                "<flow_hint>PASO ACTUAL: Preguntá \"¿Qué día te viene bien?\". "
                "Llamá check_availability SOLO cuando el cliente diga un día concreto.</flow_hint>"
            )

        # Phase 3b: slots offered, waiting for selection
        if not has_selected:
            return (
                "<flow_hint>PASO ACTUAL: El cliente elige horario de la lista. "
                "NO llames herramientas. Esperá selección.</flow_hint>"
            )

        # Phase 4: name
        if not has_name:
            return (
                "<flow_hint>PASO ACTUAL: Preguntá nombre y apellidos para la reserva. "
                "NO llames herramientas.</flow_hint>"
            )

        # Phase 5: notes
        if not has_notes:
            return (
                "<flow_hint>PASO ACTUAL: Preguntá si tiene alguna nota para la estilista. "
                "NO llames herramientas.</flow_hint>"
            )

        # Phase 6: confirmation
        return (
            "<flow_hint>PASO ACTUAL: Mostrá resumen de la cita y pedí confirmación. "
            "Llamá book() SOLO cuando el cliente confirme.</flow_hint>"
        )

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
        6. Build response (LLM-generated text only — no code override)

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

        # Reset stale booking_context from a previously completed booking
        if booking_context.get("_booking_completed"):
            logger.info(
                "BookingModeNode: clearing completed booking_context | conversation=%s",
                state.get("conversation_id", "unknown"),
            )
            booking_context = {}

        # 1. Resolve digit selection: map bare digit user reply → selected_slot
        self._resolve_digit_selection(state, booking_context)

        # 1a. Ensure opening_booking_request is set for disambiguation.
        # The router only sets it on first-interaction→BOOKING transitions.
        # For returning customers or re-entries, populate it from the user message
        # so _detect_disambiguation_needs() can fire.
        if not booking_context.get("opening_booking_request") and not booking_context.get("last_services"):
            user_msg = get_last_user_message(state).strip()
            if user_msg:
                booking_context["opening_booking_request"] = user_msg

        # 1b. Pre-load stylist names by category for dynamic context
        self._cached_stylists_by_category = await self._load_stylists_by_category()

        # 1c. Resolve service category if services are known but category is not yet cached
        if booking_context.get("last_services") and not booking_context.get("last_service_category"):
            await self._resolve_service_category(booking_context)

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

        # 3b. Deterministic state sync — resolve conversational signals.
        # Runs BEFORE building messages so flow_hint and collected_data reflect
        # what the user confirmed in their latest message.
        self._resolve_conversational_signals(state, booking_context)

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

        # 6. Build response (LLM-generated text via _sanitize_response)
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

        # Transition to GENERAL after successful booking
        # Note: booking_context persists independently — no need to restore after transition_mode
        if booking_context.get("_booking_completed"):
            updates["appointment_created"] = True
            updates.update(transition_mode(state, "GENERAL"))
            # booking_context persists via its own field (replace_booking_context reducer)
            # — do NOT re-inject into mode_context after transition_mode
            updates["booking_context"] = booking_context  # ensure booking_context survives

        return updates

    # ──────────────────────────────────────────────────────────────────────
    # _pre_tool_call — 3 gates
    # ──────────────────────────────────────────────────────────────────────

    async def _pre_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> dict[str, Any] | ToolCallRejection:
        """Intercept tool calls before execution.

        3 gates:
        (a) check_availability: stylist guard
        (b) book(): slot_index→UUID injection + confirmation gate + services injection
        (c) Everything else: pass through unchanged
        """
        mode_context: dict = getattr(self, "_booking_context", getattr(self, "_mode_context", {}))

        # ── check_availability: service + stylist guards ─────────────────
        if tool_name == "check_availability":
            # Gate 1: reject if services not yet identified
            if not mode_context.get("last_services"):
                return ToolCallRejection(
                    name="check_availability",
                    error_code="SERVICES_NOT_RESOLVED",
                    error_message=(
                        "No puedes llamar a check_availability todavía. "
                        "Primero identificá los servicios del catálogo y resolvé "
                        "cualquier desambiguación pendiente."
                    ),
                )
            # Gate 2: accept stylist_name from tool_args — LLM resolved it from conversation.
            # This prevents STYLIST_NOT_RESOLVED deadlock when the LLM provides the
            # stylist directly in args before last_stylist is set in mode_context.
            stylist_from_args = tool_args.get("stylist_name")
            if stylist_from_args and not mode_context.get("last_stylist"):
                mode_context["last_stylist"] = stylist_from_args
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

            # Step A.1b: fallback — inject from selected_slot if slot_index was absent
            if not tool_args.get("stylist_id") or not tool_args.get("start_time"):
                selected = mode_context.get("selected_slot")
                if selected:
                    tool_args.setdefault("stylist_id", selected.get("stylist_id"))
                    tool_args.setdefault(
                        "start_time", selected.get("start_time") or selected.get("full_datetime")
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

            # Step A.3: capture notes from tool args (LLM passes them after Paso 5)
            notes_arg = tool_args.get("notes")
            if notes_arg is not None:
                mode_context["notes"] = notes_arg if notes_arg.lower() not in ("no", "ninguna", "sin notas") else None
                mode_context["notes_asked"] = True

            # Step B: Confirmation gate — reject book() if required fields are missing.
            # Runs AFTER Steps A/A.1b/A.2/A.3 so selected_slot, customer_name,
            # and notes are already persisted to mode_context even when rejected.
            is_complete, missing_fields = self._booking_complete(mode_context)
            if not is_complete:
                missing_hint = ", ".join(missing_fields)
                return ToolCallRejection(
                    name="book",
                    error_code="CONFIRMATION_REQUIRED",
                    error_message=(
                        f"No puedes llamar a book() todavía. "
                        f"Faltan: {missing_hint}. "
                        f"Recoge los datos que faltan, mostrá el resumen y esperá confirmación explícita."
                    ),
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
            if svc_names:
                mode_context["last_services"] = svc_names
                # Auto-skip "algo más?" if opening message had complete intent
                if not mode_context.get("add_more_asked"):
                    if mode_context.get("preferred_date_hint") or mode_context.get("preferred_stylist_name"):
                        mode_context["add_more_asked"] = True
                        logger.info("_post_tool_result: auto-set add_more_asked (complete-intent shortcut)")
            # Capture total duration from result
            total_dur = result_dict.get("total_duration_minutes")
            if total_dur:
                mode_context["last_total_duration_minutes"] = total_dur
            # Capture stylist name from args
            stylist_name = tool_args.get("stylist_name")
            if stylist_name:
                mode_context["last_stylist"] = stylist_name
            # No stylist specified + slots returned → implicit "no preference"
            if not stylist_name and slots:
                mode_context["no_preference_stylist"] = True
                if not mode_context.get("last_stylist"):
                    mode_context["last_stylist"] = "Sin preferencia"

        elif tool_name == "book":
            status = result_dict.get("status")
            if status == "ok" or result_dict.get("appointment_id"):
                mode_context["_booking_completed"] = True
                logger.info("_post_tool_result[book]: booking completed successfully")

                # Write cross-conversation memories — set _booking_completed BEFORE this
                # block so that write failures never affect the flag.
                customer_phone = getattr(self, "_current_state", {}).get("customer_phone")
                if customer_phone:
                    try:
                        selected_slot = mode_context.get("selected_slot") or {}
                        booking_data = {
                            "service_names": mode_context.get("last_services") or [],
                            "stylist_name": mode_context.get("last_stylist"),
                            "stylist_id": selected_slot.get("stylist_id"),
                            "no_preference_stylist": mode_context.get(
                                "no_preference_stylist", False
                            ),
                            "start_time": selected_slot.get("start_time"),
                            "notes": mode_context.get("notes"),
                        }
                        existing_prefs = getattr(self, "_current_state", {}).get(
                            "customer_memories"
                        )
                        await write_customer_memories(customer_phone, booking_data, existing_prefs)
                        logger.info(
                            "_post_tool_result[book]: customer memories written for %s",
                            customer_phone,
                        )
                    except Exception as mem_exc:
                        logger.warning(
                            "_post_tool_result[book]: customer memory write failed: %s", mem_exc
                        )
                else:
                    logger.debug(
                        "_post_tool_result[book]: no customer_phone, skipping memory write"
                    )

        return result

    # ──────────────────────────────────────────────────────────────────────
    # Response building
    # ──────────────────────────────────────────────────────────────────────

    def _build_response(self, result: AgenticLoopResult, mode_context: dict) -> str:
        """Build the final response text.

        Returns the LLM-generated text as-is (via _sanitize_response).
        The LLM generates the post-booking confirmation per booking.md instructions,
        including the Google Calendar link — no code override needed.
        """
        response_text = result.response_text or ""
        return self._sanitize_response(response_text)

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
        parts.append("<ui_constraint>Nunca menciones duraciones, tiempos de servicio ni datos marcados como [INTERNO] al cliente. Son datos internos.</ui_constraint>")
        parts.append(
            f"<min_valid_date>{min_date_label}</min_valid_date>\n"
            f"<min_valid_date_iso>{min_date.isoformat()}</min_valid_date_iso>"
        )

        # Flow hint — neutral factual list of pending data (not prescriptive)
        parts.append(self._build_flow_hint(mode_context))

        # Available stylists — shown whenever services are known and stylist not yet chosen
        if mode_context.get("last_services") and not mode_context.get("last_stylist"):
            stylist_names = self._get_stylists_for_services(mode_context)
            if stylist_names:
                # Build numbered list with "Sin preferencia" as last option
                display_list = stylist_names + ["La primera con disponibilidad 👌"]
                numbered = "\n".join(f"{i + 1}. {name}" for i, name in enumerate(display_list))
                parts.append(
                    f"<available_stylists>\n{numbered}\n</available_stylists>"
                )
                # Store for digit-based resolution in _resolve_stylist_signal
                mode_context["_offered_stylists"] = stylist_names + ["Sin preferencia"]

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

        # Opening booking request — informational context (decoupled from disambiguation)
        opening_request = mode_context.get("opening_booking_request")
        if opening_request and not mode_context.get("last_services"):
            parts.append(
                f"<opening_booking_request>{opening_request}</opening_booking_request>"
            )

        # Deterministic disambiguation — show-once, runs on current user message
        if not mode_context.get("last_services"):
            if not mode_context.get("_disambiguation_questions_shown"):
                user_msg = get_last_user_message(state).strip()
                audience_hint = mode_context.get("service_audience_hint")
                questions = _detect_disambiguation_needs(user_msg, audience_hint)
                if questions:
                    q_lines = "\n".join(f"- {q}" for q in questions)
                    parts.append(
                        f"<required_questions>\nPresenta TODAS estas preguntas al cliente "
                        f"en un solo mensaje con lenguaje natural y cercano:\n{q_lines}\n"
                        f"</required_questions>"
                    )
                    mode_context["_disambiguation_questions_shown"] = True
            else:
                parts.append(
                    "<disambiguation_context>Preguntas de desambiguación ya realizadas. "
                    "Revisá las respuestas del cliente en el historial y resolvé los "
                    "servicios exactos del catálogo antes de llamar a check_availability."
                    "</disambiguation_context>"
                )

        collected = self._build_collected_summary(mode_context)
        if collected:
            parts.append(f"<collected_data>\n{collected}\n</collected_data>")

        offered_slots = mode_context.get("offered_slots") or []
        if offered_slots:
            slot_lines = "\n".join(
                f"{i + 1}. {s.get('day_label', '?')} a las {s.get('time', '?')}"
                f" con {s.get('stylist_name', '?')}"
                for i, s in enumerate(offered_slots)
            )
            parts.append(f"<offered_slots>\n{slot_lines}\n</offered_slots>")

        parts.append(
            "<natural_language_rule>NUNCA uses nombres técnicos del catálogo "
            '("Óleo Pigmento", "Corte - Señora", "Peinado Extra", etc.) al '
            "hablar con el cliente. Usa siempre lenguaje natural y cercano. "
            "Los nombres del catálogo son EXCLUSIVAMENTE para las herramientas."
            "</natural_language_rule>"
        )
        parts.append("</booking_context>")

        # Cross-conversation customer memories (injected when present)
        customer_memories = state.get("customer_memories")
        if customer_memories and isinstance(customer_memories, dict):
            from agent.prompts.loader import _build_customer_memory_context

            parts.append(_build_customer_memory_context(customer_memories))

        return "\n".join(parts)

    def _build_collected_summary(self, mode_context: dict) -> str:
        """Build collected_data summary from flat mode_context dict."""
        lines: list[str] = []

        last_services = mode_context.get("last_services") or []
        if last_services:
            if len(last_services) == 1:
                lines.append(f"✅ Servicio: {last_services[0]}")
            else:
                lines.append(f"✅ Servicios: {', '.join(last_services)}")

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

    # ──────────────────────────────────────────────────────────────────────
    # Digit slot selection — deterministic fast-path
    # ──────────────────────────────────────────────────────────────────────

    def _resolve_digit_selection(self, state: ConversationState, mode_context: dict) -> None:
        """Resolve bare digit slot selection — deterministic fast-path only.

        When the user sends a single digit (e.g., "2") and offered_slots exist,
        maps it to the corresponding slot. All other natural language parsing
        (times, ordinals, affirmatives, declines) is handled by the LLM.

        Called at the top of handle(), BEFORE the agentic loop.
        """
        user_message = get_last_user_message(state).strip()
        if not user_message:
            return

        offered_slots: list[dict] = mode_context.get("offered_slots") or []
        if not offered_slots or mode_context.get("selected_slot"):
            return

        try:
            digit = int(user_message.strip())
            if 1 <= digit <= len(offered_slots):
                slot_resolved = offered_slots[digit - 1]
                mode_context["selected_slot"] = slot_resolved
                if not mode_context.get("last_stylist") and slot_resolved.get("stylist_name"):
                    mode_context["last_stylist"] = slot_resolved["stylist_name"]
                logger.info(
                    "_resolve_digit_selection: slot resolved by digit %d → %r",
                    digit,
                    slot_resolved,
                )
        except (ValueError, TypeError):
            pass

    # ──────────────────────────────────────────────────────────────────────
    # Deterministic conversational signal resolution
    # ──────────────────────────────────────────────────────────────────────

    def _resolve_conversational_signals(
        self, state: ConversationState, booking_context: dict[str, Any]
    ) -> None:
        """Resolve conversational signals deterministically before the agentic loop.

        Uses the same phase-detection logic as _build_flow_hint() to determine
        what question the bot asked in the PREVIOUS turn, then pattern-matches
        the user's response. Only fires for conversational phases (1B, 2, 5).

        Follows the same pattern as _resolve_digit_selection(): reads user message,
        checks context, writes to booking_context in-place. Zero LLM calls.
        """
        user_message = get_last_user_message(state).strip()
        if not user_message:
            return

        normalized = _normalize_for_match(user_message)

        # Compute current phase from booking_context (same logic as _build_flow_hint)
        has_services = bool(booking_context.get("last_services"))
        has_stylist = bool(booking_context.get("last_stylist") or booking_context.get("no_preference_stylist"))
        has_slots = bool(booking_context.get("offered_slots"))
        has_selected = bool(booking_context.get("selected_slot"))
        has_name = bool(booking_context.get("customer_name"))
        has_notes = bool(booking_context.get("notes") or booking_context.get("notes_asked"))

        # ── Phase 1B: "¿Algo más?" ──
        if has_services and not booking_context.get("add_more_asked"):
            if not booking_context.get("preferred_date_hint") and not booking_context.get("preferred_stylist_name"):
                # Multi-signal: check stylist names FIRST ("no, con Pilar")
                stylist_resolved = self._resolve_stylist_signal(normalized, booking_context)
                if stylist_resolved:
                    booking_context["add_more_asked"] = True
                    logger.info(
                        "signal_resolved: Phase 1B+2 multi-signal | add_more_asked=True, last_stylist=%s",
                        booking_context.get("last_stylist"),
                    )
                    return

                if normalized in _ADD_MORE_DECLINE_KEYWORDS:
                    booking_context["add_more_asked"] = True
                    logger.info("signal_resolved: Phase 1B | add_more_asked=True | msg=%r", normalized)
                return

        # ── Phase 2: Stylist preference ──
        if has_services and booking_context.get("add_more_asked") and not has_stylist:
            resolved = self._resolve_stylist_signal(normalized, booking_context)
            if resolved:
                logger.info("signal_resolved: Phase 2 | last_stylist=%s | msg=%r", booking_context.get("last_stylist"), normalized)
            return

        # ── Phase 5: Notes ──
        if has_services and has_stylist and has_slots and has_selected and has_name and not has_notes:
            if normalized in _NOTES_DECLINE_KEYWORDS:
                booking_context["notes_asked"] = True
                booking_context["notes"] = None
                logger.info("signal_resolved: Phase 5 decline | msg=%r", normalized)
            else:
                booking_context["notes_asked"] = True
                booking_context["notes"] = user_message.strip()
                logger.info("signal_resolved: Phase 5 provide | notes=%r", user_message.strip())
            return

    def _resolve_stylist_signal(
        self, normalized_msg: str, booking_context: dict[str, Any]
    ) -> bool:
        """Try to resolve a stylist selection from the user's message.

        Tries in order: digit from offered list, name match, no-preference keyword.
        Returns True if resolved, False otherwise.
        """
        if booking_context.get("last_stylist"):
            return False

        # 1. Digit match from offered stylist list
        offered_stylists: list[str] = booking_context.get("_offered_stylists") or []
        if offered_stylists:
            try:
                digit = int(normalized_msg.strip())
                if 1 <= digit <= len(offered_stylists):
                    chosen = offered_stylists[digit - 1]
                    if chosen == "Sin preferencia":
                        booking_context["last_stylist"] = "Sin preferencia"
                        booking_context["no_preference_stylist"] = True
                    else:
                        booking_context["last_stylist"] = chosen
                    return True
            except (ValueError, TypeError):
                pass

        # 2. Name match from cached stylists
        stylist_names = self._get_stylists_for_services(booking_context)
        for name in stylist_names:
            if _normalize_for_match(name) in normalized_msg:
                booking_context["last_stylist"] = name
                return True

        # 3. No-preference keywords
        if normalized_msg in _NO_PREFERENCE_KEYWORDS:
            booking_context["last_stylist"] = "Sin preferencia"
            booking_context["no_preference_stylist"] = True
            return True

        return False

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


    @staticmethod
    async def _load_stylists_by_category() -> dict[str, list[str]]:
        """Load active stylist names grouped by service category.

        Returns a dict mapping category value (e.g. "HAIRDRESSING") to a sorted
        list of stylist names that serve that category. Stylists with category
        BOTH appear in both lists.

        Falls back to an empty dict on any error — never raises.
        """
        try:
            from sqlalchemy import select as sa_select

            from database.connection import get_async_session
            from database.models import Stylist, ServiceCategory

            async with get_async_session() as session:
                result = await session.execute(
                    sa_select(Stylist.name, Stylist.category)
                    .where(Stylist.is_active == True)
                    .order_by(Stylist.name)
                )
                rows = result.all()

            grouped: dict[str, list[str]] = {
                ServiceCategory.HAIRDRESSING.value: [],
                ServiceCategory.AESTHETICS.value: [],
            }
            for name, cat in rows:
                cat_val = cat.value if hasattr(cat, "value") else cat
                if cat_val == ServiceCategory.BOTH.value:
                    grouped[ServiceCategory.HAIRDRESSING.value].append(name)
                    grouped[ServiceCategory.AESTHETICS.value].append(name)
                elif cat_val in grouped:
                    grouped[cat_val].append(name)
            return grouped
        except Exception as exc:
            logger.warning("_load_stylists_by_category: failed: %s", exc)
            return {}

    @staticmethod
    async def _resolve_service_category(booking_context: dict) -> None:
        """Look up and cache the service category from the first service name.

        Sets booking_context["last_service_category"] to the category value string
        (e.g. "HAIRDRESSING"). No-op if last_services is empty or already set.
        Falls back silently on any DB error.
        """
        service_names = booking_context.get("last_services") or []
        if not service_names:
            return
        try:
            from sqlalchemy import select as sa_select

            from database.connection import get_async_session
            from database.models import Service

            async with get_async_session() as session:
                result = await session.execute(
                    sa_select(Service.category).where(
                        Service.name == service_names[0], Service.is_active == True
                    )
                )
                row = result.first()
            if row:
                cat_val = row[0].value if hasattr(row[0], "value") else row[0]
                booking_context["last_service_category"] = cat_val
        except Exception as exc:
            logger.warning("_resolve_service_category: failed for %r: %s", service_names[0], exc)

    def _get_stylists_for_services(self, mode_context: dict) -> list[str]:
        """Return category-compatible stylist names for the selected services.

        Uses self._cached_stylists_by_category (pre-loaded in handle()).
        Falls back to all active stylists if category is unknown.
        """
        cached: dict[str, list[str]] = getattr(self, "_cached_stylists_by_category", {})
        if not cached:
            return []

        service_category = mode_context.get("last_service_category")
        if service_category and service_category in cached:
            return cached[service_category]

        # Fallback: deduplicated union of all categories, sorted
        all_names: set[str] = set()
        for names in cached.values():
            all_names.update(names)
        return sorted(all_names)


# Backward-compat alias — conversation_flow.py imports BookingMode by name
BookingMode = BookingModeNode

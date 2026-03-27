"""
Booking Mode — LLM-Driven Booking Architecture.

Replaces the rigid BookingSubstep FSM (3,500 LOC) with a single agentic loop
where the LLM drives conversation flow based on collected data, not code-enforced
step ordering.

Core principle: "AI Data Given" — the LLM sees what data has been collected and
what's missing. It decides what to ask/call next. Python only does:
1. Pre-resolvers (deterministic): inject customer from state, extract audience hints
2. Post-processing (apply_all_tool_results): extract canonical fields from tool JSON
3. Hard validation gate: book() tool's BookSchema refuses incomplete bookings
"""

import json
import logging
import re
import unicodedata
from datetime import datetime
from typing import Any

from agent.utils.date_parser import format_date_es

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.modes.base import AgenticLoopResult, BaseModeNode, ToolCallRejection
from agent.modes.booking_context import BookingContext
from agent.modes.tool_extractors import (
    apply_all_tool_results,
    extract_service_audience_hint,
    resolve_pending_clarification,
)
from agent.prompts.loader import build_layered_messages, get_system_prompt, load_markdown
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState, transition_mode

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

# Cancel/Escalate detection phrases (Spanish, accent-normalized)
# NOTE: broad conversational negations ("no me interesa", "mejor no") have been
# intentionally removed. They are valid replies to clarification questions and
# should NOT cancel an active booking. They are still handled by _SOFT_CANCEL_PHRASES
# which are only active when there is no booking context.
_CANCEL_PHRASES: frozenset[str] = frozenset(
    {
        "cancelar",
        "anular",
        "no quiero reservar",
        "dejalo",
        "dejalo por ahora",
        "olvidalo",
        "dejemoslo",
        "cancela",
        "lo dejo",
        "lo dejo por ahora",
        "mejor lo dejo",
        "he cambiado de opinion",
        "cambie de opinion",
        "ya no quiero",
        "lo cancelo",
        "no quiero hacer la reserva",
        "no quiero la cita",
    }
)

# Soft cancel phrases: only trigger cancellation when there is NO active booking
# context (i.e., selected_services is empty AND pending_clarifications is empty).
# These are broad negations that can be valid mid-clarification responses.
_SOFT_CANCEL_PHRASES: frozenset[str] = frozenset(
    {
        "no me interesa",
        "mejor no",
        "paso",
        "no quiero",
    }
)

_ADDON_DECLINE_PHRASES: frozenset[str] = frozenset(
    {
        "no gracias",
        "solo eso",
        "nada mas",
        "con eso esta bien",
        "no quiero nada mas",
        "solo lo que pedi",
        "no necesito nada mas",
        "asi esta bien",
        "no hace falta",
        "esta bien asi",
    }
)

_ESCALATE_PHRASES: frozenset[str] = frozenset(
    {
        "humano",
        "persona real",
        "hablar con alguien",
        "agente",
        "quiero hablar con",
        "operador",
    }
)

# Negation tokens that neutralize cancel phrases
# e.g. "no quiero cancelar" is NOT a cancel intent
_CANCEL_NEGATION_TOKENS: frozenset[str] = frozenset(
    {
        "no cancelar",
        "no quiero cancelar",
        "no anular",
        "no la canceles",
        "no canceles",
        "sigue",
        "seguimos",
        "continuemos",
        "continua",
    }
)

# History window for message context
_HISTORY_LIMIT = 8

# Confirmation summary detection — patterns that indicate the LLM showed
# a confirmation summary to the user (Spanish booking context)
_CONFIRMATION_SUMMARY_MARKERS: tuple[str, ...] = (
    "resumen de tu cita",
    "resumen de la cita",
    "confirmo la cita",
    "confirmo tu cita",
    "confirmamos la cita",
    "confirmamos tu cita",
    "confirmamos?",
    "¿confirmo?",
    "¿confirmo la cita?",
    "¿confirmamos?",
    "¿te confirmo",
    "¿lo confirmo",
    "¿quieres que confirme",
    "¿queres que confirme",
    "datos de tu cita",
    "datos de la cita",
)

# Confirmation question patterns — the LLM asking for confirmation in question form.
# These supplement _CONFIRMATION_SUMMARY_MARKERS for detection in _build_response().
_CONFIRMATION_QUESTION_PATTERNS: tuple[str, ...] = (
    "confirmo",
    "confirmamos",
    "te parece bien",
    "te parece correcto",
    "esta todo bien",
    "esta todo correcto",
    "procedemos",
    "reservo",
    "queres que reserve",
    "quieres que reserve",
)

# User affirmative phrases that confirm a booking after summary is shown
_USER_CONFIRMATION_PHRASES: tuple[str, ...] = (
    "si",
    "sí",
    "dale",
    "ok",
    "perfecto",
    "va",
    "adelante",
    "bueno",
    "confirmo",
    "confirma",
    "confirmalo",
    "confirmá",
    "confirmar",
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
)

# ============================================================================
# Tool registry — all booking tools, available every turn
# ============================================================================


def _get_all_booking_tools() -> list:
    """Lazy-load all booking tools to avoid circular imports.

    Returns a list of 7 LangChain tool functions for the agentic loop.
    """
    from agent.tools.availability_tools import check_availability, find_next_available
    from agent.tools.booking_tools import book
    from agent.tools.customer_tools import manage_customer
    from agent.tools.info_tools import list_stylists, query_info
    from agent.tools.search_services import search_services

    return [
        search_services,
        query_info,
        list_stylists,
        check_availability,
        find_next_available,
        manage_customer,
        book,
    ]


# ============================================================================
# BookingMode
# ============================================================================


class BookingMode(BaseModeNode):
    """LLM-driven booking mode — single agentic loop, all tools available.

    Replaces the rigid BookingMode FSM with a flow where:
    - The LLM sees collected + missing data in the prompt
    - The LLM decides what to ask or which tool to call
    - Python only pre-resolves deterministic context and post-processes tool results
    - book() tool's Pydantic schema is the ONLY hard gate for booking preconditions
    """

    @property
    def mode_name(self) -> str:
        return "BOOKING"

    def get_tools(self) -> list:
        """Return booking tools, excluding failed tools via circuit breaker.

        GAP-05: The circuit breaker reads self._ctx which is set in handle() BEFORE
        get_tools() is called (line: self._ctx = ctx → self.get_tools()). This ordering
        is correct. However, to be resilient if get_tools() is ever called before _ctx is
        initialized (e.g. during testing or if handle() is refactored), we use getattr
        with a None default and skip the circuit breaker when ctx is unavailable.
        This prevents AttributeError and ensures all tools are returned in the safe
        fallback case (better to allow book() than to crash the agent).
        """
        tools = _get_all_booking_tools()
        ctx: BookingContext | None = getattr(self, "_ctx", None)
        if ctx is not None:
            book_failures = getattr(ctx, "book_failure_count", 0)
            manage_failures = getattr(ctx, "manage_customer_failure_count", 0)
            if book_failures >= 3:
                logger.warning(
                    "get_tools: book excluded — book_failure_count=%d",
                    book_failures,
                )
                tools = [t for t in tools if t.name != "book"]
            if manage_failures >= 2:
                logger.warning(
                    "get_tools: manage_customer excluded — failure_count=%d",
                    manage_failures,
                )
                tools = [t for t in tools if t.name != "manage_customer"]
        return tools

    # ──────────────────────────────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────────────────────────────

    async def handle(self, state: ConversationState, intent: Any) -> dict:
        """Process one turn of the booking conversation.

        Flow:
        1. Hydrate BookingContext from mode_context
        2. Pre-resolve: inject customer info, audience hint from state
        3. Check cancel/escalate intents (fast path — no LLM call)
        4. Build unified prompt with dynamic data sections
        5. Run single agentic loop with ALL 7 tools
        6. Extract tool results into context
        7. Build and return state update
        """
        mode_context = dict(state.get("mode_context") or {})

        # 0. Escalation guard: if awaiting_human, forward to ESCALATION immediately
        if mode_context.get("awaiting_human"):
            logger.info("BookingMode: awaiting_human=True, forwarding to ESCALATION")
            response = "Te paso con una persona del equipo. Un momento. 🙏"
            return {
                **transition_mode(state, "ESCALATION"),
                **add_message(state, "assistant", response),
                "last_node": "booking",
                "user_message": None,
            }

        ctx = BookingContext.from_mode_context(mode_context)

        # 1. Pre-resolve: populate context deterministically
        self._resolve_customer_from_state(state, ctx)
        self._resolve_audience_hint(state, ctx)

        # 1c. Pre-resolve: attempt to resolve pending service clarification
        # Pass the user message so hair_density/hair_length axes can be matched
        # via hint maps (the audience axis uses service_audience_hint instead).
        user_message_for_resolver = self._get_last_user_message(state)
        resolved = resolve_pending_clarification(ctx, user_message=user_message_for_resolver)
        if resolved:
            logger.info("BookingMode: auto-resolved pending service clarification")

        # 1d. Pre-resolve: detect confirmation exchange (summary shown + user confirmed)
        if not ctx.confirmation_shown:
            _detect_confirmation_exchange(state, ctx)

        # 1e. Pre-resolve: detect notes exchange (bot asked + user replied)
        if ctx and not ctx.notes_asked:
            messages = state.get("messages", [])
            if ctx.notes_ask_attempts >= 2:
                ctx.notes_asked = True
                logger.info(
                    "handle: notes_asked auto-set True (attempts=%d >= 2)",
                    ctx.notes_ask_attempts,
                )
            elif _previous_assistant_asked_for_notes(messages):
                ctx.notes_asked = True
                logger.info("handle: notes_asked=True (bot asked, user replied)")

        # 1f. Pre-resolve: deterministically persist slot/stylist from user message.
        # This covers the tool_skip case where the LLM does not call book() on the
        # slot-selection turn — the resolver inspects offered_slots and persists
        # ctx.selected_slot / ctx.stylist_id / ctx.stylist_name so the next-turn
        # dynamic context renders "✅ Estilista: Pilar" instead of "❌ pendiente".
        user_message_for_slot = self._get_last_user_message(state)
        if user_message_for_slot:
            _resolve_user_slot_selection(user_message_for_slot, ctx)

        # 2. Fast-path: cancel / escalate (before LLM call)
        user_message = self._get_last_user_message(state)
        special = self._check_special_intents(state, user_message, intent, ctx)
        if special is not None:
            return special

        # 3. Pre-resolve: prefetch stylists if needed
        await self._maybe_prefetch_stylists(ctx)

        # 4. Build unified prompt
        messages = await self._build_messages(state, ctx)

        # 5. Agentic loop (max 3 tool rounds, inherited from BaseModeNode)
        # Store ctx as transient instance attribute so _pre_tool_call can access it
        self._ctx = ctx
        result = await self._run_agentic_loop(messages, tools=self.get_tools())

        # 6. Detect tool skips (R4/R6 list_stylists, F-7 search_services)
        self._detect_tool_skips(result, ctx)

        # 7. Detect stylist hallucinations (R2)
        self._detect_stylist_hallucination(result.response_text or "", ctx)

        # R6 priority fix: when force_stylist_correction is True, the correction
        # prompt already includes the full stylist list — suppress the list reminder
        # to avoid duplicate/conflicting instructions to the LLM.
        if ctx.force_stylist_correction and ctx.force_list_stylists_reminder:
            logger.debug(
                "handle: suppressing force_list_stylists_reminder because "
                "force_stylist_correction takes priority"
            )
            ctx.force_list_stylists_reminder = False

        # 8. Extract tool results → update context
        apply_all_tool_results(result.tool_results, ctx)

        # 6b. GAP-04 fix: attempt to resolve stylist from user message when the
        # LLM called list_stylists this turn and the user expressed a preference.
        # Runs only when stylist_id is still unset after the agentic loop.
        if not ctx.stylist_id and ctx.prefetched_stylists and user_message:
            _try_resolve_stylist_from_message(user_message, ctx)

        # 6c. Check if user declined recommendations
        _detect_recommendation_decline(user_message, ctx)

        # 6d. P1/P2/P3 fix: extract customer name from user message if still missing.
        # When the LLM asked for the name and the user replied, the LLM may
        # acknowledge the name without calling manage_customer. We extract it
        # from the conversation context to avoid the manage_customer loop.
        if not ctx.customer_name and user_message:
            _extract_name_from_conversation(state, user_message, ctx)

        # 6e. T-06: extract notes from conversation when bot previously asked for them.
        if ctx.notes is None and user_message:
            _extract_notes_from_conversation(state, user_message, ctx)

        # 7. Build response with state updates
        return self._build_response(state, ctx, result)

    # ──────────────────────────────────────────────────────────────────────
    # Pre-Resolvers (deterministic, before LLM)
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_customer_from_state(state: ConversationState, ctx: BookingContext) -> None:
        """Inject customer name and ID from state if not already in context.

        Handles returning customers whose data was collected in GREETING mode.
        Priority: customer_first_name > customer_name from state.
        """
        if not ctx.customer_name:
            state_name = state.get("customer_first_name") or state.get("customer_name")
            if state_name:
                ctx.customer_name = str(state_name)

        if not ctx.customer_id:
            state_id = state.get("customer_id")
            if state_id:
                ctx.customer_id = str(state_id)

    def _resolve_audience_hint(self, state: ConversationState, ctx: BookingContext) -> None:
        """Extract service_audience_hint from mode_context handoff or user message.

        The greeting/router may have already detected an audience hint (e.g. "corte
        de mujer" → adult_female). Preserve that across turns.

        P0 fix (audience_hint mismatch): the current user message can OVERRIDE a
        previously set hint. If the user explicitly says "dama" or "caballero" in the
        current message, that takes priority over whatever was stored in ctx from a
        prior turn. This prevents booking the wrong service when the audience changes
        (e.g. user starts with "caballero" context but then asks for "dama").
        """
        # P0: always check the current user message first — explicit mention overrides stored hint
        user_msg = self._get_last_user_message(state)
        if user_msg:
            extracted = extract_service_audience_hint(user_msg)
            if extracted and extracted != ctx.service_audience_hint:
                logger.info(
                    "_resolve_audience_hint: current message overrides hint %r → %r",
                    ctx.service_audience_hint,
                    extracted,
                )
                ctx.service_audience_hint = extracted
                return

        if ctx.service_audience_hint:
            logger.debug("_resolve_audience_hint: already set to %s", ctx.service_audience_hint)
            return  # Already set from a previous turn — no override from message

        mc = state.get("mode_context") or {}
        hint = mc.get("service_audience_hint")
        if hint:
            ctx.service_audience_hint = hint
            logger.info("_resolve_audience_hint: restored from mode_context: %s", hint)
            return

        # Try extracting from implicit_service_hint (greeting handoff)
        implicit = mc.get("implicit_service_hint")
        if implicit:
            extracted = extract_service_audience_hint(implicit)
            if extracted:
                ctx.service_audience_hint = extracted
                return

        # Fallback: try user message (already tried above — this branch won't trigger
        # unless the first extraction returned None; left for clarity)
        if user_msg:
            extracted = extract_service_audience_hint(user_msg)
            if extracted:
                ctx.service_audience_hint = extracted
                logger.info(
                    "_resolve_audience_hint: extracted '%s' from user message",
                    extracted,
                )

    # ──────────────────────────────────────────────────────────────────────
    # Pre-tool-call hook (slot_index → stylist_id + start_time resolution)
    # ──────────────────────────────────────────────────────────────────────

    async def _pre_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> dict[str, Any] | ToolCallRejection:
        """Inject real customer_id and resolve slot_index before book() executes.

        Always intercepts book() calls to:
        1. Guard preconditions — return ToolCallRejection if not met (no sentinel
           strings injected into fields).
        2. Inject the REAL customer_id from context — never trust the LLM's value.
        3. Resolve slot_index to stylist_id + start_time from offered_slots.

        Backwards compatible: if slot_index is absent but stylist_id is already
        a real UUID, the args pass through unchanged.
        """
        if tool_name == "search_services":
            ctx_ss: BookingContext | None = getattr(self, "_ctx", None)
            if ctx_ss and ctx_ss.service_audience_hint and not tool_args.get("audience"):
                tool_args["audience"] = ctx_ss.service_audience_hint
                logger.info(
                    "_pre_tool_call: injected audience=%s into search_services",
                    ctx_ss.service_audience_hint,
                )
            return tool_args

        # Validate manage_customer calls: bypass name-only calls, reject stale customer_ids
        if tool_name == "manage_customer":
            action = tool_args.get("action")
            phone = tool_args.get("phone")
            data = tool_args.get("data") or {}

            logger.info(
                "_pre_tool_call: manage_customer called with action=%s, phone=%s, data=%s",
                action,
                phone,
                data,
            )

            # P1/P2/P3 fix: intercept name-only manage_customer calls.
            # When the LLM calls manage_customer just to "save" a name (create or update
            # with only first_name/last_name), bypass the actual tool call and store the
            # name directly in ctx.customer_name. This avoids the fragile manage_customer
            # loop where the tool fails or returns unexpected data.
            ctx_mc: BookingContext | None = getattr(self, "_ctx", None)
            if ctx_mc and action in ("create", "update"):
                first_name = data.get("first_name") or tool_args.get("first_name")
                last_name = data.get("last_name") or tool_args.get("last_name")
                # Detect name-only calls: the data dict contains ONLY name fields
                # (first_name, last_name) and optionally customer_id for updates.
                name_only_keys = {"first_name", "last_name", "customer_id"}
                data_keys = set(data.keys()) if data else set()
                is_name_only = bool(first_name) and data_keys <= name_only_keys

                # CRITICAL: Do NOT intercept manage_customer(create) when customer_id
                # is not yet set. This means the LLM correctly followed the flow:
                #   manage_customer(get) → exists: false → manage_customer(create)
                # Intercepting this would leave customer_id=None and break book().
                # Only intercept name-only calls when customer_id is ALREADY known
                # (i.e., the customer exists and the LLM only wants to update the name).
                if is_name_only and action == "create" and not ctx_mc.customer_id:
                    # Let the actual create call through — we need the UUID back
                    is_name_only = False

                if is_name_only:
                    # Build full name from parts
                    full_name = first_name.strip()
                    if last_name and last_name.strip():
                        full_name = f"{full_name} {last_name.strip()}"
                    ctx_mc.customer_name = full_name
                    logger.info(
                        "_pre_tool_call: bypassed manage_customer (name-only) — "
                        "stored customer_name=%r directly in context",
                        full_name,
                    )
                    return ToolCallRejection(
                        name="manage_customer",
                        error_code="NAME_STORED_DIRECTLY",
                        error_message=f"Nombre guardado: {full_name}. "
                        "No necesitás llamar a manage_customer para el nombre. "
                        "Continuá con la reserva.",
                    )

            # Guard: reject update() with customer_id if we have a ctx and it doesn't match
            if action == "update" and data.get("customer_id") and ctx_mc:
                provided_cid = str(data["customer_id"]).lower()
                ctx_cid = str(ctx_mc.customer_id).lower() if ctx_mc.customer_id else ""

                # If provided customer_id doesn't match context, reject and tell LLM to use create
                if ctx_cid and provided_cid != ctx_cid:
                    logger.warning(
                        "_pre_tool_call: rejecting manage_customer(update) — stale customer_id. "
                        "Provided=%s, Context=%s. Tell LLM to call create instead.",
                        provided_cid,
                        ctx_cid,
                    )
                    return ToolCallRejection(
                        name="manage_customer",
                        error_code="STALE_CUSTOMER_ID",
                        error_message="Ese customer_id no es válido para este cliente. "
                        "Llama manage_customer(action='create'...) para crear o recuperar el cliente correcto.",
                    )

            return tool_args

        if tool_name != "book":
            return tool_args

        ctx: BookingContext | None = getattr(self, "_ctx", None)

        # ── Guard: reject book() when no slots have been offered ────────
        if ctx and not ctx.offered_slots:
            logger.warning("_pre_tool_call: book() rejected — offered_slots is empty")
            return ToolCallRejection(
                name="book",
                error_code="NO_OFFERED_SLOTS",
                error_message="Consulta disponibilidad primero",
            )

        # ── Guard: reject book() when availability needs refresh ────────
        if ctx and ctx.needs_availability_refresh:
            logger.warning("_pre_tool_call: book() rejected — needs_availability_refresh is True")
            return ToolCallRejection(
                name="book",
                error_code="NEEDS_AVAILABILITY_REFRESH",
                error_message="El horario anterior estaba ocupado, "
                "consulta disponibilidad de nuevo",
            )

        # ── Guard: reject book() when services list is empty ────────────
        if ctx and not ctx.selected_services:
            logger.warning("_pre_tool_call: book() rejected — selected_services is empty")
            return ToolCallRejection(
                name="book",
                error_code="NO_SELECTED_SERVICES",
                error_message="Confirma los servicios primero",
            )

        # ── Hard gate: reject book() if customer has no real name ──────────
        if ctx:
            cname = ctx.customer_name
            if not cname or cname.strip().lower() in ("cliente", ""):
                logger.warning(
                    "_pre_tool_call: book() rejected — customer_name is %r, "
                    "must collect real name first",
                    cname,
                )
                return ToolCallRejection(
                    name="book",
                    error_code="NO_CUSTOMER_NAME",
                    error_message="Pregunta el nombre del cliente primero",
                )

            # ── Name splitting: split on LAST space so compound first names are preserved
            # Examples: "Ana Torres" → first="Ana", last="Torres"
            #           "María de los Ángeles Vega" → first="María de los Ángeles", last="Vega"
            #           "Pedro" → first="Pedro", last=""
            name = cname.strip()
            if " " in name:
                parts = name.rsplit(" ", 1)
                first_name = parts[0]
                last_name = parts[1]
            else:
                first_name = name
                last_name = ""
            tool_args["first_name"] = first_name
            if last_name:
                tool_args["last_name"] = last_name
            elif "last_name" in tool_args:
                tool_args["last_name"] = ""
            logger.info(
                "_pre_tool_call: split customer_name=%r → first_name=%r, last_name=%r",
                name,
                first_name,
                last_name,
            )

        # ── Hard gate: reject book() if no customer_id ─────────────────────
        if not (ctx and ctx.customer_id):
            logger.warning("_pre_tool_call: book() rejected — no customer_id in context")
            return ToolCallRejection(
                name="book",
                error_code="NO_CUSTOMER_ID",
                error_message="Llama a manage_customer primero para obtener el customer_id",
            )

        # ── Hard gate: reject book() if notes haven't been asked ──────────
        if ctx and not ctx.notes_asked:
            logger.warning("_pre_tool_call: book() rejected — notes_asked is False")
            return ToolCallRejection(
                name="book",
                error_code="NOTES_NOT_ASKED",
                error_message=(
                    "ANTES de llamar a book(), preguntá a la clienta si tiene alguna "
                    "nota, preferencia o indicación especial para su cita. "
                    "Preguntá ahora y NO llames a book() hasta tener la respuesta."
                ),
            )

        # ── Hard gate: reject book() if confirmation summary not shown ─────
        # The LLM MUST show a confirmation summary and the user MUST reply
        # with an affirmative before book() can execute. This prevents the
        # LLM from skipping the mandatory confirmation step.
        if ctx and not ctx.confirmation_shown:
            logger.warning(
                "_pre_tool_call: book() rejected — confirmation_shown is False. "
                "LLM must present summary and wait for user confirmation first."
            )
            return ToolCallRejection(
                name="book",
                error_code="CONFIRMATION_NOT_SHOWN",
                error_message=(
                    "ANTES de llamar a book(), debés mostrar el resumen de confirmación "
                    "con todos los datos (nombre, servicio, estilista, fecha, hora) "
                    "y ESPERAR a que la clienta confirme con 'sí', 'dale', 'ok', etc. "
                    "Mostrá el resumen ahora y NO llames a book() hasta recibir confirmación."
                ),
            )

        # ── Hard gate: always inject selected_services ─────────────────────
        if ctx and ctx.selected_services:
            tool_args["services"] = list(ctx.selected_services)
            logger.info(
                "_pre_tool_call: injected selected_services=%s into book() args",
                ctx.selected_services,
            )

        # ── Hard gate: always inject real customer_id ──────────────────────
        tool_args["customer_id"] = ctx.customer_id

        # ── Inject appointment notes from context (never from LLM) ────────
        if ctx.notes and ctx.notes.strip():
            tool_args["notes"] = ctx.notes.strip()
        else:
            tool_args.setdefault("notes", None)

        # ── slot_index resolution ──────────────────────────────────────────
        offered = ctx.offered_slots if ctx else None
        slot_index = tool_args.get("slot_index")

        if slot_index is not None:
            # PREFERRED path: resolve stylist_id + start_time from the indexed slot.
            # Any stylist_id the LLM passed directly is OVERWRITTEN — slot is authoritative.
            if not offered:
                logger.warning(
                    "_pre_tool_call: slot_index=%s but no offered_slots in context",
                    slot_index,
                )
                return tool_args

            array_index = slot_index - 1  # 1-based → 0-based

            if array_index < 0 or array_index >= len(offered):
                logger.warning(
                    "_pre_tool_call: slot_index=%d out of range (offered_slots has %d items)",
                    slot_index,
                    len(offered),
                )
                return tool_args

            slot = offered[array_index]
            tool_args["stylist_id"] = slot.get("stylist_id", tool_args.get("stylist_id", ""))
            tool_args["start_time"] = slot.get(
                "full_datetime",
                slot.get("start_time", tool_args.get("start_time", "")),
            )
            # Remove slot_index — BookSchema doesn't need it after resolution
            del tool_args["slot_index"]

            stylist_name = slot.get("stylist_name", slot.get("stylist", "???"))
            logger.info(
                "_pre_tool_call: resolved slot_index=%d → stylist=%s, "
                "stylist_id=%s, start_time=%s (offered_slots has %d items)",
                slot_index,
                stylist_name,
                tool_args["stylist_id"],
                tool_args["start_time"],
                len(offered),
            )

            # GAP-01 fix: populate ctx.selected_slot so collected_summary() can render
            # the date/time in "## Datos recogidos" and the booking summary is complete.
            if ctx:
                ctx.selected_slot = {
                    "date": slot.get("date", slot.get("day_name", "")),
                    "time": slot.get("time", ""),
                    "full_datetime": slot.get("full_datetime", ""),
                    "stylist_id": tool_args["stylist_id"],
                    "stylist_name": stylist_name,
                }
                logger.info(
                    "_pre_tool_call: GAP-01 populated selected_slot=%s",
                    ctx.selected_slot,
                )
                ctx.stylist_id = tool_args["stylist_id"]
                ctx.stylist_name = stylist_name

            return tool_args

        # ── No slot_index: validate directly-passed stylist_id ────────────
        # GAP-09/10: if no slot_index, the LLM is passing stylist_id directly.
        # Validate it is a UUID that actually appears in offered_slots so that
        # stale or hallucinated UUIDs cannot reach BookingTransaction.
        current_stylist_id = tool_args.get("stylist_id", "")

        # Gate: sentinel still present means the LLM forgot to pass slot_index
        if current_stylist_id == "__RESOLVE_FROM_SLOT__":
            logger.warning(
                "_pre_tool_call: book() rejected — stylist_id is sentinel "
                "__RESOLVE_FROM_SLOT__ and no slot_index was provided"
            )
            return ToolCallRejection(
                name="book",
                error_code="MISSING_SLOT_INDEX",
                error_message=(
                    "Debés pasar slot_index con el número del horario elegido (1, 2, 3…). "
                    "NO pases stylist_id directamente. "
                    "Revisá '## Horarios ofrecidos' y llamá book(slot_index=N)."
                ),
            )

        # Gate: if offered_slots exist, try to auto-recover by matching
        # stylist_id + start_time against the offered slots. If a unique
        # exact match is found, resolve identically to Path A. If the
        # start_time is unparseable or no slot matches, hard-reject.
        if offered and current_stylist_id and current_stylist_id != "__RESOLVE_FROM_SLOT__":
            # Try to parse the provided start_time for comparison
            try:
                try_dt = datetime.fromisoformat(tool_args.get("start_time", ""))
            except (ValueError, TypeError):
                logger.warning(
                    "_pre_tool_call: book() rejected — start_time '%s' is not parseable",
                    tool_args.get("start_time"),
                )
                return ToolCallRejection(
                    name="book",
                    error_code="SLOT_NOT_IN_OFFERED",
                    error_message=(
                        "El horario indicado no es válido. "
                        "Usá slot_index con el número del horario (1, 2, 3…) "
                        "en lugar de pasar stylist_id y start_time directamente."
                    ),
                )

            # Search offered_slots for exact match on stylist_id + start_time
            matched_slot = None
            matched_index = -1
            for i, s in enumerate(offered):
                if s.get("stylist_id") != current_stylist_id:
                    continue
                try:
                    slot_dt = datetime.fromisoformat(s.get("full_datetime", ""))
                except (ValueError, TypeError):
                    continue
                if slot_dt == try_dt:
                    matched_slot = s
                    matched_index = i
                    break

            if matched_slot is not None:
                logger.warning(
                    "_pre_tool_call: book() called without slot_index but stylist_id+start_time "
                    "matched offered slot %d — auto-recovering. stylist_id=%s, start_time=%s",
                    matched_index + 1,
                    matched_slot.get("stylist_id"),
                    tool_args["start_time"],
                )
                # Resolve exactly like Path A
                tool_args["stylist_id"] = matched_slot.get("stylist_id", current_stylist_id)
                tool_args["start_time"] = matched_slot.get("full_datetime", tool_args["start_time"])
                tool_args.pop("slot_index", None)
                if ctx:
                    stylist_name = matched_slot.get(
                        "stylist_name", matched_slot.get("stylist", "???")
                    )
                    ctx.selected_slot = {
                        "date": matched_slot.get("date", matched_slot.get("day_name", "")),
                        "time": matched_slot.get("time", ""),
                        "full_datetime": matched_slot.get("full_datetime", ""),
                        "stylist_id": tool_args["stylist_id"],
                        "stylist_name": stylist_name,
                    }
                return tool_args
            else:
                logger.warning(
                    "_pre_tool_call: book() rejected — stylist_id+start_time (%s, %s) "
                    "do not match any offered slot",
                    current_stylist_id,
                    tool_args.get("start_time"),
                )
                return ToolCallRejection(
                    name="book",
                    error_code="SLOT_NOT_IN_OFFERED",
                    error_message=(
                        "El horario indicado no coincide con ninguno de los horarios ofrecidos. "
                        "Usá slot_index con el número del horario (1, 2, 3…) "
                        "en lugar de pasar stylist_id y start_time directamente."
                    ),
                )

        return tool_args

    async def _post_tool_result(
        self,
        tool_name: str,
        tool_args: dict,
        result: Any,
    ) -> Any:
        """Apply tool results immediately to ctx, mid-loop.

        Extracts results for key tools (manage_customer, search_services, check_availability)
        before the LLM sees the ToolMessage. This ensures that ctx is updated so the NEXT
        LLM invocation (if any) will see fresh "Datos recogidos" with the latest values.

        Critical for multi-tool flows in the same agentic loop iteration where the LLM
        might call search_services then book() — the book() preconditions check ctx
        values that would be stale if extraction only happened post-loop.
        """
        if self._ctx is None:
            return result

        # Parse result once (may be a JSON string or already a dict)
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

        # Import extractors (late import to avoid circular deps)
        from agent.modes.tool_extractors import (
            extract_customer_fields,
            extract_service_fields,
            extract_slot_fields,
        )

        # Apply extractors by tool name
        if tool_name == "manage_customer":
            logger.debug("_post_tool_result: manage_customer parsed result: %s", parsed)
            extract_customer_fields(parsed, self._ctx)
            logger.info(
                "_post_tool_result: manage_customer — extracted name=%s, customer_id=%s, full_result=%s",
                parsed.get("first_name", ""),
                parsed.get("id", ""),
                parsed,
            )

        elif tool_name == "search_services":
            extract_service_fields(parsed, self._ctx)
            logger.info(
                "_post_tool_result: search_services — extracted service=%s, selected_services=%s",
                self._ctx.service_name,
                self._ctx.selected_services,
            )
            # Cambio 3: disparar prefetch mid-loop cuando search_services acaba de resolver
            # el servicio en el mismo turno en que el LLM necesita mostrar estilistas.
            # Esto cubre el caso donde _maybe_prefetch_stylists corrió antes del loop
            # cuando service_id era todavía None.
            if (
                self._ctx.service_id
                and not self._ctx.stylist_id
                and not self._ctx.prefetched_stylists
            ):
                try:
                    await self._maybe_prefetch_stylists(self._ctx)
                    logger.info(
                        "_post_tool_result: post-search_services prefetch → %d estilistas cargados",
                        len(self._ctx.prefetched_stylists),
                    )
                except Exception as exc:
                    logger.warning(
                        "_post_tool_result: post-search_services prefetch falló (non-fatal): %s",
                        exc,
                    )

        elif tool_name == "check_availability":
            extract_slot_fields(parsed, self._ctx)
            logger.info(
                "_post_tool_result: check_availability — extracted offered_slots (count=%d)",
                len(self._ctx.offered_slots),
            )

        elif tool_name == "list_stylists":
            # GAP-04 fix: extract stylist list mid-loop so the dynamic context
            # can show the prefetched stylists section before the LLM responds.
            # Also attempt to resolve stylist_id if the user already expressed a
            # preference (e.g., "quiero con Ana") in their current message.
            from agent.modes.tool_extractors import extract_stylist_fields

            extract_stylist_fields(parsed, self._ctx)
            # Attempt to auto-resolve stylist from user message if not yet set
            if not self._ctx.stylist_id and self._ctx.prefetched_stylists:
                user_msg = getattr(self, "_dynamic_context_state", None)
                if user_msg is not None:
                    last_user = self._get_last_user_message(user_msg)
                    _try_resolve_stylist_from_message(last_user, self._ctx)
            logger.info(
                "_post_tool_result: list_stylists — %d stylists loaded, stylist_id=%s",
                len(self._ctx.prefetched_stylists),
                self._ctx.stylist_id,
            )

        return result

    def _detect_tool_skips(self, result: AgenticLoopResult, ctx: BookingContext) -> None:
        """Detect when LLM skipped required tools (R4/R6).

        Checks two conditions:
        - R4/R6: service_id set but list_stylists not called (skip reminder injection)
        - F-7: service_id NOT set and search_services not called (skip reminder injection)

        Sets appropriate flags in ctx for dynamic context injection next turn.

        Args:
            result: AgenticLoopResult from agentic loop
            ctx: BookingContext to update with reminder flags
        """
        # R4/R6: stylist list not fetched even though service is resolved
        # Condition: service_id set, stylist_id NOT set, prefetched_stylists is empty,
        # but list_stylists was not called this turn
        if (
            ctx.service_id
            and not ctx.stylist_id
            and not ctx.prefetched_stylists
            and not result.tool_results.get("list_stylists")
        ):
            logger.warning(
                "BookingMode: R4/R6 tool-skip detected — service resolved "
                "but list_stylists not called. service_id=%s, stylist_id=%s",
                ctx.service_id,
                ctx.stylist_id,
            )
            ctx.force_list_stylists_reminder = True
        else:
            ctx.force_list_stylists_reminder = False

        # F-7: service not resolved and search_services not called
        # Condition: service_id None, selected_services empty, no pending clarifications,
        # and search_services was not called
        if (
            ctx.service_id is None
            and not ctx.selected_services
            and not ctx.pending_clarifications
            and not result.tool_results.get("search_services")
        ):
            logger.warning(
                "BookingMode: F-7 tool-skip detected — service unresolved after turn "
                "but search_services was not called. service_id=None, selected_services=[]"
            )
            ctx.force_search_services_reminder = True
        else:
            ctx.force_search_services_reminder = False

    def _detect_stylist_hallucination(self, response_text: str, ctx: BookingContext) -> None:
        """Detect when LLM invents stylist names not in the database (R2).

        Extracts capitalized proper nouns from response, filters against known stylists,
        and warns if hallucinated names are detected. Sets force_stylist_correction=True
        to inject a correction prompt next turn.

        Args:
            response_text: LLM response text to scan
            ctx: BookingContext with prefetched_stylists list
        """
        if not ctx.prefetched_stylists or not response_text:
            ctx.force_stylist_correction = False
            return

        # Build normalized stylist names set (lowercase, accent-normalized)
        def _nfd_lower(text: str) -> str:
            """Normalize text to NFD form (decomposed accents) and lowercase."""
            normalized = unicodedata.normalize("NFD", text.lower())
            return "".join(c for c in normalized if not unicodedata.combining(c))

        known_stylists = {
            _nfd_lower(s.get("name", "")) for s in ctx.prefetched_stylists if s.get("name")
        }

        # Common Spanish words to skip (blocklist for false positives).
        # These are capitalized words that appear frequently in Spanish responses
        # but are NOT stylist names. All in lowercase for comparison with _nfd_lower().
        common_words = {
            # Function words / articles
            "la",
            "del",
            "los",
            "el",
            "es",
            "un",
            "una",
            "unos",
            "unas",
            "te",
            "nos",
            "sos",
            "por",
            "con",
            "para",
            "que",
            "del",
            "hay",
            # Greetings / affirmations / common responses
            "hola",
            "perfecto",
            "genial",
            "claro",
            "bueno",
            "vale",
            "entendido",
            "estupendo",
            "gracias",
            "listo",
            "dale",
            "venga",
            "bien",
            "correcto",
            # Pronouns / subject words
            "tenemos",
            "puedo",
            "tienes",
            "quieres",
            "estas",
            "puede",
            "podemos",
            # Salon-specific common nouns (not proper names)
            "estilista",
            "profesional",
            "especialista",
            "peluqueria",
            "estetica",
            "salon",
            "corte",
            "tinte",
            "reserva",
            "cita",
            "disponibilidad",
            "horario",
            "servicio",
            "servicios",
            # Days of week (Mon-Sun)
            "lunes",
            "martes",
            "miercoles",
            "jueves",
            "viernes",
            "sabado",
            "domingo",
            # Months
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
            # Bot identity / salon name tokens
            "maite",
            "atrevete",
            "alcobendas",
        }

        # Extract capitalized words (likely proper nouns)
        words = re.findall(r"\b[A-Z][a-záéíóúñ]*\b", response_text)

        hallucinated = []
        for word in words:
            normalized_word = _nfd_lower(word)
            # Check if word is NOT in known stylists and NOT in blocklist
            if normalized_word not in known_stylists and normalized_word not in common_words:
                hallucinated.append(word)

        if hallucinated:
            log_extra: dict[str, Any] = {
                "event": "stylist_hallucination_detected",
                "hallucinated_names": hallucinated,
                "valid_names": [s["name"] for s in ctx.prefetched_stylists],
            }
            conversation_id = getattr(ctx, "conversation_id", None)
            if conversation_id is not None:
                log_extra["conversation_id"] = conversation_id
            logger.warning("Stylist hallucination detected", extra=log_extra)
            ctx.force_stylist_correction = True
        else:
            ctx.force_stylist_correction = False

    def _refresh_dynamic_context(self, working_messages: list) -> None:
        """Rebuild the dynamic context SystemMessage with fresh ctx data.

        After tools like manage_customer update ctx (e.g. setting customer_name),
        the stale SystemMessage still shows '❌ Nombre: pendiente'. This hook
        replaces it so the LLM sees '✅ Nombre: María' on its next invocation.
        """
        ctx = getattr(self, "_ctx", None)
        idx = getattr(self, "_dynamic_context_index", None)
        state = getattr(self, "_dynamic_context_state", None)
        if ctx is None or idx is None or state is None:
            return
        if idx >= len(working_messages):
            return

        fresh_context = self._build_dynamic_context(state, ctx)
        working_messages[idx] = SystemMessage(content=fresh_context)
        logger.debug("_refresh_dynamic_context: rebuilt SystemMessage at index %d", idx)

    async def _maybe_prefetch_stylists(self, ctx: BookingContext) -> None:
        """Prefetch stylist options when service is resolved but no stylist yet.

        This saves one LLM round-trip by providing stylist options in the prompt.
        The LLM can still call list_stylists if the prefetch fails or is stale.
        """
        if not ctx.service_id:
            return
        if ctx.stylist_id:
            return  # Stylist already selected
        if ctx.prefetched_stylists:
            return  # Already prefetched from a previous turn

        try:
            from agent.tools.info_tools import list_stylists

            result = await list_stylists.ainvoke({"category": ctx.service_category or ""})
            parsed = json.loads(result) if isinstance(result, str) else result
            if isinstance(parsed, dict):
                stylists = parsed.get("stylists", [])
                if stylists:
                    ctx.prefetched_stylists = stylists
                    # Find soonest slot across all stylists
                    for s in stylists:
                        summary = s.get("next_slot_summary")
                        if summary:
                            ctx.soonest_any_slot = summary
                            break
        except Exception as exc:
            logger.warning("_maybe_prefetch_stylists failed (non-fatal): %s", exc)

    # ──────────────────────────────────────────────────────────────────────
    # Special Intent Detection (fast path — no LLM call)
    # ──────────────────────────────────────────────────────────────────────

    def _check_special_intents(
        self,
        state: ConversationState,
        user_message: str,
        intent: Any,
        ctx: "BookingContext | None" = None,
    ) -> dict | None:
        """Check for cancel/escalate before running the agentic loop.

        Returns a state update dict if a special intent is detected,
        or None to continue normal processing.

        Cancel negation detection: "no quiero cancelar" → NOT a cancel.

        Cancel scoping (REQ-MSF-4): _SOFT_CANCEL_PHRASES are only treated as
        cancellations when there is NO active booking context (selected_services
        is empty AND pending_clarifications is empty). This prevents broad
        negations like "no me interesa" from cancelling an in-progress booking
        when the user is simply answering a clarification question.
        """
        intent_name = self._extract_intent_name(intent)
        msg_lower = _normalize_text(user_message)

        # Determine if we have an active booking context
        has_active_context = bool(
            ctx is not None and (ctx.selected_services or ctx.pending_clarifications)
        )

        # ── Cancel intent ───────────────────────────────────────────────
        # Always check explicit cancel phrases
        is_cancel = intent_name == "cancel" or any(p in msg_lower for p in _CANCEL_PHRASES)

        # Only check soft phrases when there is NO active booking context
        if not is_cancel and not has_active_context:
            is_cancel = any(p in msg_lower for p in _SOFT_CANCEL_PHRASES)

        if is_cancel:
            # Check for negation: "no quiero cancelar" is NOT a cancel
            is_negated = any(neg in msg_lower for neg in _CANCEL_NEGATION_TOKENS)
            if not is_negated:
                logger.info(
                    "BookingMode: cancel intent detected, transitioning to GENERAL "
                    "(has_active_context=%s)",
                    has_active_context,
                )
                response = "Entendido, cancelamos la reserva. ¿Puedo ayudarte en algo más? 😊"
                return {
                    **transition_mode(state, "GENERAL"),
                    **add_message(state, "assistant", response),
                    "last_node": "booking",
                    "user_message": None,
                }

        # ── Escalate intent ─────────────────────────────────────────────
        is_escalate = intent_name == "escalate" or any(p in msg_lower for p in _ESCALATE_PHRASES)

        if is_escalate:
            logger.info("BookingMode: escalate intent detected, transitioning to ESCALATION")
            response = "Te paso con una persona del equipo. Un momento. 🙏"
            return {
                **transition_mode(state, "ESCALATION"),
                **add_message(state, "assistant", response),
                "last_node": "booking",
                "user_message": None,
            }

        return None

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

    # ──────────────────────────────────────────────────────────────────────
    # Prompt Building
    # ──────────────────────────────────────────────────────────────────────

    async def _build_messages(self, state: ConversationState, ctx: BookingContext) -> list:
        """Build the complete message list for the agentic loop via layered assembly.

        Delegates to build_layered_messages() with dynamic_context_override.

        Structure:
        1. SystemMessage: Cached shared prompt (identity + rules)
        2. SystemMessage: Booking mode prompt (booking.md)
        3. SystemMessage: Dynamic context (collected/missing data, stylists, slots)
        4. Conversation history (last N messages)
        """
        # Build dynamic context using booking-specific logic
        dynamic_context = self._build_dynamic_context(state, ctx)

        # Delegate to loader — pass dynamic_context_override to use custom build
        messages, dynamic_context_index = await build_layered_messages(
            state=state,
            mode_context=dict(state.get("mode_context") or {}),
            mode_name="BOOKING",
            dynamic_context_override=dynamic_context,
            include_history=True,
            history_limit=_HISTORY_LIMIT,
        )

        # Store index for potential mid-loop refresh
        self._dynamic_context_index = dynamic_context_index
        self._dynamic_context_state = state

        return messages

    @staticmethod
    def _build_dynamic_context(state: ConversationState, ctx: BookingContext) -> str:
        """Build the dynamic context section injected as SystemMessage.

        Contains: temporal context, phone, collected data, missing data,
        disambiguation state, offered slots, available stylists.
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo("Europe/Madrid"))
        parts: list[str] = []

        # Temporal context (locale-independent Spanish format)
        parts.append(f"Fecha y hora actual: {format_date_es(now)}")

        # Phone (for manage_customer calls)
        phone = state.get("customer_phone")
        if phone:
            parts.append(f"Teléfono de la clienta: {phone}")

        # Conversation summary (if available from summarizer)
        summary = state.get("conversation_summary")
        if summary:
            parts.append(f"\nContexto previo:\n{summary}")

        # Collected data
        parts.append(f"\n<collected_data>\n{ctx.collected_summary()}\n</collected_data>")

        # Missing data
        parts.append(f"\n<missing_data>\n{ctx.missing_summary()}\n</missing_data>")

        # Disambiguation (pending clarification or candidate services)
        disambiguation = _build_disambiguation_section(ctx)
        if disambiguation:
            parts.append(f"\n<clarification>\n{disambiguation}\n</clarification>")

        # Combo recommendations
        recommendations = _build_recommendations_section(ctx)
        if recommendations:
            parts.append(f"\n<recommendations>\n{recommendations}\n</recommendations>")

        # Service details (transparency)
        details_section = _build_service_details_section(ctx)
        if details_section:
            parts.append(f"\n<service_details>\n{details_section}\n</service_details>")

        # Prefetched stylists
        stylists_section = _build_stylists_section(ctx)
        if stylists_section:
            parts.append(f"\n<available_stylists>\n{stylists_section}\n</available_stylists>")

        # Offered slots
        slots_section = _build_offered_slots_section(ctx)
        if slots_section:
            parts.append(f"\n<offered_slots>\n{slots_section}\n</offered_slots>")

        # Date substitution / parse error metadata block
        if ctx.substitution_made:
            parts.append(
                f"\n<date_substitution>\n"
                f"⚠️ Fecha solicitada: {ctx.date_requested} — no disponible "
                f"({ctx.substitution_reason})\n"
                f"✅ Primera disponibilidad desde: {ctx.date_substituted}\n"
                f"</date_substitution>"
            )
        elif ctx.date_parse_error:
            parts.append(
                "\n<date_substitution>\n"
                "⚠️ No pude interpretar la fecha pedida. Pedí al usuario que especifique "
                "la fecha con formato YYYY-MM-DD o una frase clara en español.\n"
                "</date_substitution>"
            )

        # F-7: Tool-skip reminder — injected when LLM skipped search_services last turn
        if ctx.force_search_services_reminder:
            parts.append(
                "\n⚠️ Recordatorio: el servicio sigue sin resolver. "
                "DEBES llamar search_services antes de continuar. "
                "No hagas preguntas al usuario sin haber llamado la tool primero."
            )

        # R4/R6: Tool-skip reminder — injected when LLM skipped list_stylists after service resolved
        if ctx.force_list_stylists_reminder:
            parts.append(
                "\n⚠️ Recordatorio: el servicio está resuelto pero aún falta elegir estilista. "
                "DEBES llamar list_stylists para mostrar los profesionales disponibles. "
                "No preguntes la preferencia sin haber llamado list_stylists primero."
            )

        # R2: Stylist hallucination correction — injected when LLM invented stylist names
        if ctx.force_stylist_correction:
            parts.append(
                "\n⚠️ CORRECCIÓN: algunos de los nombres mencionados no coinciden con nuestras estilistas. "
                "DEBES usar SOLO los nombres que aparecen en la lista de estilistas disponibles. "
                "Nunca inventes o asumas nombres que no están en la lista."
            )

        # Book failure circuit breaker
        if ctx.book_failure_count >= 2:
            parts.append(
                "\n⚠️ La reserva ha fallado 2 veces. "
                "NO intentes reservar de nuevo. "
                "Ofrecé derivar al equipo humano."
            )

        # manage_customer failure circuit breaker
        if ctx.manage_customer_failure_count >= 2:
            parts.append(
                "\n⚠️ No se pudo guardar el nombre (falló 2 veces). "
                "NO llames a manage_customer de nuevo. "
                "Continuá la reserva sin guardar el nombre — "
                "pedile a la clienta que lo confirme al llegar al salón."
            )

        # Confirmation gate status
        if ctx.confirmation_shown:
            parts.append(
                "\n✅ CONFIRMACIÓN RECIBIDA: la clienta confirmó el resumen. "
                "Podés llamar a `book()` ahora."
            )

        return "\n".join(parts)

    # ──────────────────────────────────────────────────────────────────────
    # Response Building
    # ──────────────────────────────────────────────────────────────────────

    def _build_response(
        self,
        state: ConversationState,
        ctx: BookingContext,
        result: AgenticLoopResult,
    ) -> dict:
        """Build the final state update dict.

        Handles:
        - Name redaction from LLM response (privacy guard)
        - First-turn AI disclosure prepending (EU AI Act)
        - Mode transition to GENERAL after successful booking
        - Context serialization to mode_context
        """
        response_text = result.response_text or ""

        # F-8: Code-rendered booking confirmation — replace LLM text for success path.
        # This eliminates LLM hallucination on the critical confirmation message.
        if ctx._booking_completed:
            selected_slot = ctx.selected_slot or ctx.last_booked_slot or {}
            date_str = selected_slot.get("date", "")
            time_str = selected_slot.get("time", "")
            stylist = ctx.stylist_name or ""
            services_display = (
                ", ".join(ctx.selected_services)
                if ctx.selected_services
                else (ctx.service_name or "")
            )
            # Build price line only if available in service details
            price_parts = [
                d.get("price") for d in (ctx.selected_services_details or []) if d.get("price")
            ]
            price_line = f"\n💰 {price_parts[0]}" if price_parts else ""
            # Build confirmation lines, skipping blank fields
            lines = ["¡Perfecto! ✅ Cita confirmada:"]
            if date_str and time_str:
                lines.append(f"📅 {date_str} a las {time_str}")
            elif date_str:
                lines.append(f"📅 {date_str}")
            if stylist:
                lines.append(f"💇 {stylist}")
            if services_display:
                lines.append(f"✂️ {services_display}")
            if price_line:
                lines.append(f"💰 {price_parts[0]}")
            lines.append("")
            lines.append(
                "📩 Recibirás un mensaje de confirmación 48h antes de tu cita. "
                "Respondé SÍ para confirmar o NO para cancelar."
            )
            lines.append("Te esperamos en Alcobendas 🌸")
            response_text = "\n".join(lines)
            logger.info(
                "_build_response: F-8 code-rendered confirmation built "
                "(date=%s, time=%s, stylist=%s, services=%s)",
                date_str,
                time_str,
                stylist,
                services_display,
            )

        # Name redaction (privacy guard — LLM must not expose customer names)
        response_text = self._redact_names(state, response_text)

        # If redaction emptied the response, use a fallback
        if not response_text.strip():
            response_text = "De acuerdo, continuemos con tu reserva. 🙏"

        # First-turn intro (EU AI Act compliance)
        response_text, disclosure_sent = self._maybe_prepend_intro(response_text, state)

        # F-2: detect confirmation summary in OUR outgoing response and set deterministic flag
        if not ctx.confirmation_summary_sent and _is_booking_data_complete(ctx):
            normalized_resp = _normalize_text(response_text)
            if any(marker in normalized_resp for marker in _CONFIRMATION_SUMMARY_MARKERS):
                ctx.confirmation_summary_sent = True
                logger.info(
                    "_build_response: confirmation_summary_sent=True (summary detected in response)"
                )

        # F-2 additive: also detect confirmation question pattern when booking data is complete.
        # Catches cases where the LLM asks "¿Reservo?" instead of rendering a formal summary block.
        if not ctx.confirmation_summary_sent and _is_booking_data_complete(ctx):
            normalized_resp_q = _normalize_text(response_text)
            if any(pattern in normalized_resp_q for pattern in _CONFIRMATION_QUESTION_PATTERNS):
                ctx.confirmation_summary_sent = True
                logger.info(
                    "_build_response: confirmation_summary_sent=True "
                    "(confirmation question pattern detected in response)"
                )

        # Detect notes-asking markers in outgoing response → increment attempts counter
        if ctx and not ctx.notes_asked:
            _NOTES_ASK_MARKERS = (
                "nota",
                "preferencia",
                "indicacion",
                "alergia",
                "algo que debamos saber",
                "algo que deba saber",
            )
            normalized_resp_notes = _normalize_text(response_text)
            if any(marker in normalized_resp_notes for marker in _NOTES_ASK_MARKERS):
                ctx.notes_ask_attempts += 1
                logger.info(
                    "_build_response: notes_ask_attempts incremented to %d",
                    ctx.notes_ask_attempts,
                )

        # T-03 fix: set recommendations_shown AFTER the LLM has generated its
        # response — not during _build_dynamic_context() (before LLM sees the
        # context). This ensures the flag is only set when the LLM had the
        # recommendations section in its context this turn.
        if ctx.pending_recommendations and not ctx.recommendations_shown:
            ctx.recommendations_shown = True

        updates: dict[str, Any] = {
            **add_message(state, "assistant", response_text),
            "mode_context": ctx.to_mode_context(),
            "last_node": "booking",
            "user_message": None,
        }

        if disclosure_sent:
            updates["ai_disclosure_sent"] = True

        # P1/P2/P3 fix: propagate customer_name from booking context to state
        # so the router and other nodes see the name without requiring
        # manage_customer to have stored it.
        if ctx.customer_name and not state.get("customer_name"):
            updates["customer_name"] = ctx.customer_name

        # If book() succeeded → mark appointment created and transition out
        if ctx._booking_completed:
            logger.info("BookingMode: booking completed, transitioning to GENERAL")
            updates["appointment_created"] = True
            updates.update(transition_mode(state, "GENERAL"))
            # Re-inject mode_context AFTER transition_mode (which resets it)
            # so the post-booking context is preserved for the response
            updates["mode_context"] = ctx.to_mode_context()

        return updates

    # ──────────────────────────────────────────────────────────────────────
    # Name Redaction (ported from v6 BookingMode._response_updates)
    # ──────────────────────────────────────────────────────────────────────

    def _redact_names(self, state: ConversationState, text: str) -> str:
        """Redact customer name tokens from LLM response text.

        The booking.md prompt instructs the LLM not to mention the customer's
        name, but this is a hard code-level safety net in case it does.
        """
        names_to_redact: list[str] = []

        customer_name = state.get("customer_name")
        pending_name = state.get("pending_whatsapp_name")
        if customer_name:
            names_to_redact.append(str(customer_name))
        if pending_name and pending_name != customer_name:
            names_to_redact.append(str(pending_name))

        for name in names_to_redact:
            if _contains_name_token(text, name):
                self.logger.warning("BookingMode: redacting customer name tokens from response")
                text = _redact_name_tokens(text, name)

        return text


# ============================================================================
# Module-level helper functions (pure, no class dependency)
# ============================================================================


# ── Name patterns for conversational extraction ─────────────────────────────
# Matches "me llamo X", "soy X", "mi nombre es X" and bare single/two-word names
_NAME_INTRO_PATTERN = re.compile(
    r"(?:me\s+llamo|soy|mi\s+nombre\s+es)\s+([A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+"
    r"(?:\s+[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+)?)",
    re.IGNORECASE,
)

# Bare name: 1-2 capitalized words that look like a name (for messages that
# are ONLY a name, e.g. user replied "María" or "Ana Torres" to "¿Tu nombre?")
_BARE_NAME_PATTERN = re.compile(
    r"^([A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+"
    r"(?:\s+[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+)?)\s*[.!]?\s*$"
)

# Words that look like names but are NOT (common false positives in Spanish)
_NAME_STOPWORDS: frozenset[str] = frozenset(
    {
        "hola",
        "buenas",
        "gracias",
        "dale",
        "perfecto",
        "vale",
        "claro",
        "bueno",
        "genial",
        "bien",
        "listo",
    }
)

# Audience/demographic words that sound like names but describe the service target.
# BUG-2 fix: "soy caballero" / "para dama" must NOT be captured as customer_name.
# Normalized (accent-stripped, lowercase) for comparison via _normalize_text().
_AUDIENCE_KEYWORDS: frozenset[str] = frozenset(
    {
        "caballero",
        "dama",
        "senora",
        "senor",
        "mujer",
        "hombre",
        "nino",
        "nina",
        "nene",
        "nena",
        "bebe",
        "adulto",
        "adulta",
        "chico",
        "chica",
        "senorita",
        "srita",
        "cliente",
        "clienta",
    }
)


def _try_resolve_stylist_from_message(user_message: str, ctx: BookingContext) -> None:
    """Attempt to resolve stylist_id/stylist_name from the user's message.

    GAP-04 fix: When the user says "quiero con Ana" or "para Pilar" and
    prefetched_stylists already contains the stylist list, this function
    matches the user's stated preference against the list and sets
    ctx.stylist_id and ctx.stylist_name so the dynamic context shows
    "✅ Estilista: Ana" instead of "❌ Estilista: pendiente".

    Only runs when stylist_id is still None (i.e., not already resolved by
    slot selection). Uses accent-insensitive token matching. If multiple
    names match, the first match wins (rare edge case — stylist names are
    unique in practice).
    """
    if not user_message or not ctx.prefetched_stylists:
        return
    if ctx.stylist_id:
        return  # Already resolved — nothing to do

    normalized_msg = _normalize_text(user_message)
    for stylist in ctx.prefetched_stylists:
        name = stylist.get("name", "")
        stylist_id = stylist.get("id") or stylist.get("stylist_id")
        if not name or not stylist_id:
            continue
        # Match on any word token of the stylist's first name (≥ 3 chars)
        name_tokens = [tok for tok in re.split(r"\W+", _normalize_text(name)) if len(tok) >= 3]
        if any(tok in normalized_msg for tok in name_tokens):
            ctx.stylist_id = str(stylist_id)
            ctx.stylist_name = name
            logger.info(
                "_try_resolve_stylist_from_message: resolved stylist_id=%s name=%r "
                "from user message token match",
                ctx.stylist_id,
                name,
            )
            return


_AFFIRMATIVES: frozenset[str] = frozenset(
    {
        "sí",
        "si",
        "dale",
        "ok",
        "confirma",
        "perfecto",
        "bueno",
        "adelante",
        "venga",
        "va",
        "claro",
    }
)


def _resolve_user_slot_selection(user_message: str, ctx: BookingContext) -> bool:
    """Deterministically resolve a slot from user_message against ctx.offered_slots.

    Persists ctx.selected_slot, ctx.stylist_id, ctx.stylist_name if a match is found.
    Returns True if a slot was resolved, False otherwise.

    Matching rules (strict only — no fuzzy):
    0. Affirmative-only message (no time/number) + exactly 1 offered slot → resolve that slot.
    1. Bare slot-index number: e.g. "3" or "el 3" → slot at index 3 (1-based) in offered_slots.
    2. Exact HH:MM time: e.g. "11:20" or "a las 11:20" → slot where slot["time"] == "11:20".

    Guard conditions (returns False immediately if):
    - ctx.offered_slots is empty or None
    - ctx.stylist_id is already set (already resolved — don't overwrite)
    - user message is a bare affirmative AND there are multiple offered slots (ambiguous)
    """
    # Guard: no slots offered yet
    if not ctx.offered_slots:
        return False

    # Guard: slot already resolved — don't overwrite
    if ctx.stylist_id:
        return False

    offered = ctx.offered_slots
    n = len(offered)

    # Guard: affirmative-only message (no time/number tokens)
    stripped_lower = user_message.strip().lower()
    has_time_token = bool(re.search(r"\d{1,2}:\d{2}", user_message))
    has_digit_token = bool(re.search(r"\b\d+\b", user_message))
    if stripped_lower in _AFFIRMATIVES and not has_time_token and not has_digit_token:
        if n == 1:
            slot = offered[0]
            ctx.selected_slot = {
                "date": slot.get("date", slot.get("day_name", "")),
                "time": slot.get("time", ""),
                "full_datetime": slot.get("full_datetime", ""),
                "stylist_id": slot.get("stylist_id", ""),
                "stylist_name": slot.get("stylist_name", slot.get("stylist", "")),
            }
            ctx.stylist_id = slot.get("stylist_id", "")
            ctx.stylist_name = slot.get("stylist_name", slot.get("stylist", ""))
            logger.info(
                "_resolve_user_slot_selection: resolved by affirmative (single slot) → "
                "stylist_id=%s, stylist_name=%r, time=%s",
                ctx.stylist_id,
                ctx.stylist_name,
                slot.get("time", ""),
            )
            return True
        else:
            # Multiple slots + bare affirmative → ambiguous, cannot resolve
            return False

    # --- Try 1: bare slot-index number (1-based) ---
    # Normalize: strip accents/punctuation, check if it's a bare integer 1..N
    normalized = _normalize_text(user_message)
    # Remove common filler words ("el", "la", "numero", "opcion") and check residual
    tokens = re.split(r"[\s,;.!?]+", normalized)
    # Filter tokens that are purely digits
    digit_tokens = [t for t in tokens if t.isdigit()]
    for dt in digit_tokens:
        idx = int(dt)
        if 1 <= idx <= n:
            slot = offered[idx - 1]
            ctx.selected_slot = {
                "date": slot.get("date", slot.get("day_name", "")),
                "time": slot.get("time", ""),
                "full_datetime": slot.get("full_datetime", ""),
                "stylist_id": slot.get("stylist_id", ""),
                "stylist_name": slot.get("stylist_name", slot.get("stylist", "")),
            }
            ctx.stylist_id = slot.get("stylist_id", "")
            ctx.stylist_name = slot.get("stylist_name", slot.get("stylist", ""))
            logger.info(
                "_resolve_user_slot_selection: resolved by slot index %d → "
                "stylist_id=%s, stylist_name=%r, time=%s",
                idx,
                ctx.stylist_id,
                ctx.stylist_name,
                slot.get("time", ""),
            )
            return True

    # --- Try 2: exact HH:MM time string in user message ---
    time_matches = re.findall(r"\b(\d{1,2}:\d{2})\b", user_message)
    for time_str in time_matches:
        for slot in offered:
            if slot.get("time") == time_str:
                ctx.selected_slot = {
                    "date": slot.get("date", slot.get("day_name", "")),
                    "time": slot.get("time", ""),
                    "full_datetime": slot.get("full_datetime", ""),
                    "stylist_id": slot.get("stylist_id", ""),
                    "stylist_name": slot.get("stylist_name", slot.get("stylist", "")),
                }
                ctx.stylist_id = slot.get("stylist_id", "")
                ctx.stylist_name = slot.get("stylist_name", slot.get("stylist", ""))
                logger.info(
                    "_resolve_user_slot_selection: resolved by time %r → "
                    "stylist_id=%s, stylist_name=%r",
                    time_str,
                    ctx.stylist_id,
                    ctx.stylist_name,
                )
                return True

    # --- Try 3: informal bare-hour references (e.g. "a las 14", "14 hs", "11") ---
    # Collect candidate hour integers from informal patterns (no minutes component).
    # We only reach here if no HH:MM match fired, so these patterns are unambiguous.
    candidate_hours: list[int] = []

    # "a las 14" or "a la 14" (with optional :MM already handled above)
    for m in re.finditer(r"\ba\s+las?\s+(\d{1,2})(?::\d{2})?\b", user_message):
        candidate_hours.append(int(m.group(1)))

    # "14 hs" or "14 h"
    for m in re.finditer(r"\b(\d{1,2})\s+hs?\b", user_message, re.IGNORECASE):
        candidate_hours.append(int(m.group(1)))

    # bare integer (e.g. "11") — only when it cannot be a valid slot index
    # (i.e. the number is > number of offered slots, so it can't be an index pick)
    if not candidate_hours:
        for dt in digit_tokens:
            hour_candidate = int(dt)
            if hour_candidate > n:
                # Too large to be a 1-based index → treat as bare hour
                candidate_hours.append(hour_candidate)

    for hour in candidate_hours:
        time_str = f"{hour:02d}:00"
        for slot in offered:
            if slot.get("time") == time_str:
                ctx.selected_slot = {
                    "date": slot.get("date", slot.get("day_name", "")),
                    "time": slot.get("time", ""),
                    "full_datetime": slot.get("full_datetime", ""),
                    "stylist_id": slot.get("stylist_id", ""),
                    "stylist_name": slot.get("stylist_name", slot.get("stylist", "")),
                }
                ctx.stylist_id = slot.get("stylist_id", "")
                ctx.stylist_name = slot.get("stylist_name", slot.get("stylist", ""))
                logger.info(
                    "_resolve_user_slot_selection: resolved by informal hour %02d:00 → "
                    "stylist_id=%s, stylist_name=%r",
                    hour,
                    ctx.stylist_id,
                    ctx.stylist_name,
                )
                return True

    return False


def _extract_name_from_conversation(
    state: ConversationState, user_message: str, ctx: BookingContext
) -> None:
    """Extract customer name from user message when it looks like a name reply.

    Called when ctx.customer_name is None after the agentic loop. This catches
    the common case where the LLM asked for the name and the user replied with
    just their name (e.g. "María", "Me llamo Ana Torres").

    GAP-07 fix: Extraction is now attempted in two tiers:
    1. ALWAYS attempt structured patterns ("me llamo X", "soy X", "mi nombre es X").
       These are high-precision and safe to run on any message — the intro phrase
       makes false positives nearly impossible.
    2. Bare-name pattern ("María") only runs when a RECENT assistant message asked
       for the name. This prevents false positives from capitalized words like
       "Perfecto" or service names being mistaken for customer names.

    This ensures that a user who volunteers their name proactively (e.g. "Soy Ana
    García, quiero un corte") gets captured without needing the bot to ask first.
    """
    if not user_message or not user_message.strip():
        return

    # Tier 1: structured intro patterns — always safe, high precision
    # "me llamo X", "soy X", "mi nombre es X" → explicit name declaration
    match = _NAME_INTRO_PATTERN.search(user_message)
    if match:
        name = match.group(1).strip()
        name_normalized = _normalize_text(name)
        # BUG-2 fix: reject audience/demographic words (e.g. "soy caballero")
        if name.lower() not in _NAME_STOPWORDS and name_normalized not in _AUDIENCE_KEYWORDS:
            ctx.customer_name = name
            logger.info(
                "_extract_name_from_conversation: extracted name=%r from intro pattern "
                "(no name-request required — GAP-07)",
                name,
            )
            return

    # Tier 2: bare-name pattern — only when bot previously asked for name
    # (prevents "Perfecto" or service names from being captured as customer names)
    messages = state.get("messages", [])
    if not _previous_assistant_asked_for_name(messages):
        return

    match = _BARE_NAME_PATTERN.match(user_message.strip())
    if match:
        name = match.group(1).strip()
        if name.lower() not in _NAME_STOPWORDS:
            ctx.customer_name = name
            logger.info(
                "_extract_name_from_conversation: extracted name=%r from bare name pattern",
                name,
            )
            return


def _previous_assistant_asked_for_name(messages: list[dict]) -> bool:
    """Check if the most recent assistant message asked for the customer's name.

    Looks for name-asking patterns like "nombre", "¿cómo te llamas?", etc.
    in the last assistant message.
    """
    # Find the last assistant message
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = (msg.get("content") or "").lower()
            name_ask_patterns = (
                "nombre",
                "como te llamas",
                "cómo te llamás",
                "a nombre de",
                "tu nombre",
                "su nombre",
                "decime tu nombre",
                "dime tu nombre",
                "quien seria",
                "quién sería",
            )
            return any(pattern in content for pattern in name_ask_patterns)
    return False


def _previous_assistant_asked_for_notes(messages: list[dict]) -> bool:
    """Check if the most recent assistant message asked for notes/preferences.

    Scans reversed messages for the last assistant turn and checks for
    notes-asking phrases like 'nota', 'preferencia', 'alergia', etc.
    """
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = _normalize_text(msg.get("content") or "")
            notes_ask_patterns = (
                "nota",
                "preferencia",
                "algo que debamos saber",
                "algo que deba saber",
                "alergia",
                "indicacion",
                "comentario",
                "especial",
            )
            return any(pattern in content for pattern in notes_ask_patterns)
    return False


def _extract_notes_from_conversation(
    state: ConversationState, user_message: str, ctx: BookingContext
) -> None:
    """Extract notes from user message when the bot just asked for notes/preferences.

    Only runs when:
    1. The last assistant message asked for notes (_previous_assistant_asked_for_notes).
    2. ctx.notes is None (not yet collected).

    Decline phrases (e.g. "no", "nada") are ignored — ctx.notes stays None
    so the LLM can decide whether to re-ask or proceed.
    """
    if not user_message or ctx.notes is not None:
        return

    messages = state.get("messages", [])
    if not _previous_assistant_asked_for_notes(messages):
        return

    # If the user's reply is a refusal, skip — don't capture "no" as a note
    msg_normalized = _normalize_text(user_message)
    decline_phrases = {
        "no",
        "nada",
        "no gracias",
        "sin notas",
        "ninguna",
        "ninguno",
        "todo bien",
        "nada mas",
        "nada más",
        "ninguna nota",
        "sin preferencias",
    }
    if msg_normalized.strip() in decline_phrases:
        return

    # Capture the full message as notes
    ctx.notes = user_message.strip()
    logger.info(
        "_extract_notes_from_conversation: captured notes=%r",
        ctx.notes,
    )


def _is_booking_data_complete(ctx: BookingContext) -> bool:
    """Check if all required booking fields are populated.

    This is used as a guard for _detect_confirmation_exchange to prevent
    premature confirmation_shown when the user says "sí" to a non-booking
    question (e.g., "¿Para dama?" → "Sí").

    Required fields:
    - service_id or selected_services (service chosen)
    - stylist_id (stylist chosen)
    - offered_slots (availability checked = date/time in progress)
    - customer_name or customer_id (customer identified)
    """
    has_service = bool(ctx.service_id or ctx.selected_services)
    has_stylist = bool(ctx.stylist_id)
    has_slots = bool(ctx.offered_slots)
    has_customer = bool(ctx.customer_name or ctx.customer_id)
    return has_service and has_stylist and has_slots and has_customer


def _detect_confirmation_exchange(state: ConversationState, ctx: BookingContext) -> None:
    """Detect if the previous turn was a confirmation summary + user affirmative.

    Scans the last few messages looking for:
    1. An assistant message containing confirmation summary markers
    2. A subsequent user message with an affirmative response

    If both are found in sequence AND all booking data is complete, sets
    ctx.confirmation_shown = True so the book() gate in _pre_tool_call will
    allow the booking to proceed.

    The data-completeness guard prevents premature confirmation when the user
    says "sí" to a non-booking question (e.g., clarification about service
    audience or hair type).
    """
    # Guard: don't set confirmation_shown unless all booking data is collected.
    # This prevents "sí" to "¿Para dama?" from opening the book() gate.
    if not _is_booking_data_complete(ctx):
        return

    # F-2: Step 1 — check deterministic flag instead of scanning assistant messages.
    # The flag is set by _build_response() when the code detects summary markers in
    # OUR outgoing response — more reliable than scanning conversation history.
    if not ctx.confirmation_summary_sent:
        return  # No summary sent by code yet — can't confirm

    messages = state.get("messages", [])
    if len(messages) < 1:
        return

    # F-2: Step 2 — find the most recent user message in the last 6 messages
    recent = messages[-6:]
    last_user: dict | None = None
    for msg in reversed(recent):
        if msg.get("role") == "user":
            last_user = msg
            break

    if last_user is None:
        return  # No user message found

    # F-2: Step 3 — check if the last user message is an affirmative confirmation
    user_text = _normalize_text(last_user.get("content", ""))
    user_tokens = set(re.split(r"[\s,;.!?]+", user_text))
    has_confirmation = any(
        phrase in user_tokens or user_text.startswith(phrase)
        for phrase in _USER_CONFIRMATION_PHRASES
    )

    if has_confirmation:
        ctx.confirmation_shown = True
        logger.info(
            "_detect_confirmation_exchange: F-2 confirmation detected — "
            "confirmation_summary_sent=True, user confirmed with %r",
            last_user.get("content", "")[:50],
        )
        return


def _normalize_text(text: str | None) -> str:
    """Unicode NFKD normalization, lowercase, strip accents."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text.lower().strip())
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _nfd_lower(text: str) -> str:
    """NFD normalization, lowercase, strip combining marks."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn"
    )


def _contains_name_token(response_text: str, customer_name: str) -> bool:
    """Check if any meaningful token (>=3 chars) from customer_name appears in response.

    Uses NFD normalization for accent-insensitive matching.
    Tokens shorter than 3 chars (prepositions, articles) are skipped.
    """
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


def _redact_name_tokens(text: str, name: str) -> str:
    """Redact individual name tokens (>= 3 chars) from text.

    Uses case-insensitive + accent-insensitive matching.
    Preserves original text around the redacted tokens.
    """
    tokens = re.split(r"\W+", name)
    for token in tokens:
        if len(token) < 3:
            continue
        # Case-insensitive pass
        pattern = rf"\b{re.escape(token)}\b"
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
        # Accent-insensitive pass
        stripped_token = _nfd_lower(token)
        if stripped_token != token.lower():
            text_nfd = _nfd_lower(text)
            pattern_nfd = rf"\b{re.escape(stripped_token)}\b"
            if re.search(pattern_nfd, text_nfd):
                text = re.sub(pattern_nfd, "", text_nfd, flags=re.IGNORECASE)

    # Clean up artifacts
    text = re.sub(r"  +", " ", text).strip()
    text = re.sub(r"^[,;.\s]+", "", text).strip()
    # Clean orphaned punctuation left after name removal (e.g. ", !" → "!")
    text = re.sub(r",\s*([!?.])", r"\1", text)
    text = re.sub(r"\s+([!?.,;:])", r"\1", text)
    text = re.sub(r"  +", " ", text).strip()
    return text


# ── Dynamic context section builders ────────────────────────────────────────


def _build_disambiguation_section(ctx: BookingContext) -> str:
    """Build prompt section for pending disambiguation/clarification.

    Pure renderer — no auto-resolve logic. The resolve_pending_clarification()
    pre-resolver handles audience matching BEFORE this function is called.
    Renders the first entry in pending_clarifications (FIFO queue).
    """
    lines: list[str] = []

    pending = ctx.pending_clarifications[0] if ctx.pending_clarifications else None
    if pending:
        axis = pending.get("axis", "")
        hint = pending.get("question_hint", "")
        options = pending.get("options", [])

        lines.append(f"CLARIFICACIÓN PENDIENTE ({axis}):")
        lines.append(f"  Pregunta: {hint}")
        for i, opt in enumerate(options, 1):
            label_display = opt.get("label", opt.get("value", ""))
            desc = opt.get("description", "")
            lines.append(f"  {i}. {label_display}" + (f" — {desc}" if desc else ""))

    if ctx.candidate_services and not ctx.service_name:
        names = [s.get("name", "") for s in ctx.candidate_services[:5] if isinstance(s, dict)]
        if names:
            lines.append(f"Servicios candidatos: {', '.join(names)}")

    return "\n".join(lines)


def _build_recommendations_section(ctx: BookingContext) -> str:
    """Build prompt section for combo service recommendations.

    Renders once per booking flow. Returns empty string if:
    - No pending recommendations
    - User declined recommendations
    - Recommendations were already shown
    """
    if not ctx.pending_recommendations or ctx.recommendations_declined:
        return ""
    if ctx.recommendations_shown:
        return ""  # Already shown once — don't repeat

    lines = ["SERVICIOS RECOMENDADOS (complementos opcionales):"]
    for rec in ctx.pending_recommendations:
        lines.append(f"  - {rec}")
    lines.append(
        "Sugiere estos servicios de forma natural. "
        "Si la clienta dice que no, respeta su decisión y continúa."
    )
    return "\n".join(lines)


def _build_service_details_section(ctx: BookingContext) -> str:
    """Build prompt section describing what each selected service includes."""
    if not ctx.selected_services_details:
        return ""
    lines: list[str] = []
    for detail in ctx.selected_services_details:
        name = detail.get("name", "")
        dur = detail.get("duration")
        desc = detail.get("description", "")
        if not desc:
            continue
        dur_str = f" ({dur}min)" if dur else ""
        lines.append(f"- **{name}**{dur_str}: {desc}")
    return "\n".join(lines)


def _detect_recommendation_decline(message: str, ctx: BookingContext) -> bool:
    """Check if user declined add-on recommendations.

    Only checks when recommendations have been shown and not yet declined.
    Returns True if decline detected and ctx.recommendations_declined was set.
    """
    if not ctx.pending_recommendations:
        return False
    if ctx.recommendations_declined:
        return False
    if not ctx.recommendations_shown:
        return False  # Haven't shown yet — can't decline what wasn't offered

    msg_normalized = _normalize_text(message)
    if any(phrase in msg_normalized for phrase in _ADDON_DECLINE_PHRASES):
        ctx.recommendations_declined = True
        return True
    return False


def _build_stylists_section(ctx: BookingContext) -> str:
    """Build prompt section for available stylists.

    Muestra solo los nombres de los estilistas disponibles. No intenta mostrar
    disponibilidad (next_slot_summary) porque list_stylists no devuelve ese campo
    — hacerlo causaba que apareciera "Sin disponibilidad" para cada estilista.
    """
    if not ctx.prefetched_stylists:
        return ""

    lines: list[str] = []
    for s in ctx.prefetched_stylists:
        name = s.get("name", "???")
        lines.append(f"- {name}")

    lines.append("- La estilista con disponibilidad más temprana")

    if ctx.recurrent_stylist_hint:
        lines.append(f"Estilista habitual de la clienta: {ctx.recurrent_stylist_hint}")

    return "\n".join(lines)


def _build_offered_slots_section(ctx: BookingContext) -> str:
    """Build prompt section for currently offered time slots.

    Sorts slots by (full_datetime, stylist_name) for deterministic ordering,
    then stores the sorted list back to ctx so _pre_tool_call resolves against
    the same order the user sees.

    Includes stylist_id (UUID) and full_datetime (ISO 8601) so the LLM can
    pass them verbatim to book(). Without these, the LLM may hallucinate
    values or pass names instead of UUIDs.
    """
    if not ctx.offered_slots:
        return ""

    # Sort by (full_datetime, stylist_name) for deterministic ordering
    sorted_slots = sorted(
        ctx.offered_slots,
        key=lambda s: (
            s.get("full_datetime", ""),
            s.get("stylist_name", s.get("stylist", "")),
        ),
    )
    # Store sorted list back so _pre_tool_call resolves against same order
    ctx.offered_slots = sorted_slots

    lines: list[str] = []
    lines.append(
        "IMPORTANTE: Mostrá TODOS estos horarios al cliente con los MISMOS números"
        " y en el MISMO orden. NUNCA omitas, reordenes ni filtrés horarios."
    )
    for i, slot in enumerate(sorted_slots, 1):
        day = slot.get("day_name", slot.get("date", ""))
        time_str = slot.get("time", "")
        stylist = slot.get("stylist_name", slot.get("stylist", ""))
        stylist_id = slot.get("stylist_id", "")
        full_dt = slot.get("full_datetime", "")
        display = f"{i}. {day} a las {time_str}" + (f" con {stylist}" if stylist else "")
        if stylist_id:
            display += f" | stylist_id: {stylist_id}"
        if full_dt:
            display += f" | full_datetime: {full_dt}"
        lines.append(display)

    lines.append(
        "\n⚠️ Cuando llames a book(), usá slot_index con el número del hueco (1, 2, 3...)."
        " NO copies stylist_id ni full_datetime manualmente."
    )
    return "\n".join(lines)

"""
Booking Mode v7 — LLM-Driven Booking Architecture.

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
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.modes.base import AgenticLoopResult, BaseModeNode, ToolCallRejection
from agent.modes.booking_context_v7 import BookingContextV7
from agent.modes.tool_extractors import (
    apply_all_tool_results,
    extract_service_audience_hint,
    resolve_pending_clarification,
)
from agent.prompts.loader import get_system_prompt, load_markdown
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
_CANCEL_PHRASES: frozenset[str] = frozenset({
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
})

# Soft cancel phrases: only trigger cancellation when there is NO active booking
# context (i.e., selected_services is empty AND pending_clarifications is empty).
# These are broad negations that can be valid mid-clarification responses.
_SOFT_CANCEL_PHRASES: frozenset[str] = frozenset({
    "no me interesa",
    "mejor no",
    "paso",
    "no quiero",
})

_ADDON_DECLINE_PHRASES: frozenset[str] = frozenset({
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
})

_ESCALATE_PHRASES: frozenset[str] = frozenset({
    "humano",
    "persona real",
    "hablar con alguien",
    "agente",
    "quiero hablar con",
    "operador",
})

# Negation tokens that neutralize cancel phrases
# e.g. "no quiero cancelar" is NOT a cancel intent
_CANCEL_NEGATION_TOKENS: frozenset[str] = frozenset({
    "no cancelar",
    "no quiero cancelar",
    "no anular",
    "no la canceles",
    "no canceles",
    "sigue",
    "seguimos",
    "continuemos",
    "continua",
})

# History window for message context
_HISTORY_LIMIT = 8

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
# BookingModeV7
# ============================================================================


class BookingModeV7(BaseModeNode):
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
        """Return booking tools, excluding book() after 3+ failures (circuit breaker)."""
        tools = _get_all_booking_tools()
        ctx: BookingContextV7 | None = getattr(self, "_ctx", None)
        if ctx and ctx.book_failure_count >= 3:
            logger.warning(
                "get_tools: book excluded — book_failure_count=%d",
                ctx.book_failure_count,
            )
            tools = [t for t in tools if t.name != "book"]
        return tools

    # ──────────────────────────────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────────────────────────────

    async def handle(self, state: ConversationState, intent: Any) -> dict:
        """Process one turn of the booking conversation.

        Flow:
        1. Hydrate BookingContextV7 from mode_context
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
            logger.info("BookingModeV7: awaiting_human=True, forwarding to ESCALATION")
            response = "Te paso con una persona del equipo. Un momento. 🙏"
            return {
                **transition_mode(state, "ESCALATION"),
                **add_message(state, "assistant", response),
                "last_node": "booking",
                "user_message": None,
            }

        ctx = BookingContextV7.from_mode_context(mode_context)

        # 1. Pre-resolve: populate context deterministically
        self._resolve_customer_from_state(state, ctx)
        self._resolve_audience_hint(state, ctx)

        # 1c. Pre-resolve: attempt to resolve pending service clarification
        # Pass the user message so hair_density/hair_length axes can be matched
        # via hint maps (the audience axis uses service_audience_hint instead).
        user_message_for_resolver = self._get_last_user_message(state)
        resolved = resolve_pending_clarification(ctx, user_message=user_message_for_resolver)
        if resolved:
            logger.info("BookingModeV7: auto-resolved pending service clarification")

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

        # 6. Extract tool results → update context
        apply_all_tool_results(result.tool_results, ctx)

        # 6b. Check if user declined recommendations
        _detect_recommendation_decline(user_message, ctx)

        # 7. Build response with state updates
        return self._build_response(state, ctx, result)

    # ──────────────────────────────────────────────────────────────────────
    # Pre-Resolvers (deterministic, before LLM)
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_customer_from_state(
        state: ConversationState, ctx: BookingContextV7
    ) -> None:
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

    def _resolve_audience_hint(self, state: ConversationState, ctx: BookingContextV7) -> None:
        """Extract service_audience_hint from mode_context handoff or user message.

        The greeting/router may have already detected an audience hint (e.g. "corte
        de mujer" → adult_female). Preserve that across turns.
        """
        if ctx.service_audience_hint:
            logger.debug("_resolve_audience_hint: already set to %s", ctx.service_audience_hint)
            return  # Already set from a previous turn

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

        # Try extracting from current user message (e.g. "para dama", "soy mujer")
        user_msg = self._get_last_user_message(state)
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
            ctx_ss: BookingContextV7 | None = getattr(self, "_ctx", None)
            if ctx_ss and ctx_ss.service_audience_hint and not tool_args.get("audience"):
                tool_args["audience"] = ctx_ss.service_audience_hint
                logger.info(
                    "_pre_tool_call: injected audience=%s into search_services",
                    ctx_ss.service_audience_hint,
                )
            return tool_args

        # Log manage_customer calls to debug name collection issues
        if tool_name == "manage_customer":
            logger.info("_pre_tool_call: manage_customer called with action=%s, phone=%s, data=%s",
                       tool_args.get("action"), tool_args.get("phone"), tool_args.get("data"))
            return tool_args

        if tool_name != "book":
            return tool_args

        ctx: BookingContextV7 | None = getattr(self, "_ctx", None)

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
            logger.warning(
                "_pre_tool_call: book() rejected — needs_availability_refresh is True"
            )
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
            logger.warning(
                "_pre_tool_call: book() rejected — no customer_id in context"
            )
            return ToolCallRejection(
                name="book",
                error_code="NO_CUSTOMER_ID",
                error_message="Llama a manage_customer primero para obtener "
                "el customer_id",
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

        # ── slot_index resolution ──────────────────────────────────────────
        if tool_args.get("slot_index") is None:
            return tool_args

        offered = ctx.offered_slots if ctx else None

        if not offered:
            logger.warning(
                "_pre_tool_call: slot_index=%s but no offered_slots in context",
                tool_args["slot_index"],
            )
            return tool_args

        slot_index = tool_args["slot_index"]
        array_index = slot_index - 1  # 1-based → 0-based

        if array_index < 0 or array_index >= len(offered):
            logger.warning(
                "_pre_tool_call: slot_index=%d out of range (offered_slots has %d items)",
                slot_index,
                len(offered),
            )
            return tool_args

        slot = offered[array_index]
        tool_args["stylist_id"] = slot.get(
            "stylist_id", tool_args.get("stylist_id", "")
        )
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

        elif tool_name == "check_availability":
            extract_slot_fields(parsed, self._ctx)
            logger.info(
                "_post_tool_result: check_availability — extracted offered_slots (count=%d)",
                len(self._ctx.offered_slots),
            )

        return result

    async def _maybe_prefetch_stylists(self, ctx: BookingContextV7) -> None:
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

            result = await list_stylists.ainvoke(
                {"category": ctx.service_category or ""}
            )
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
        ctx: "BookingContextV7 | None" = None,
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
            ctx is not None
            and (ctx.selected_services or ctx.pending_clarifications)
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
                    "BookingModeV7: cancel intent detected, transitioning to GENERAL "
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
        is_escalate = intent_name == "escalate" or any(
            p in msg_lower for p in _ESCALATE_PHRASES
        )

        if is_escalate:
            logger.info("BookingModeV7: escalate intent detected, transitioning to ESCALATION")
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

    async def _build_messages(
        self, state: ConversationState, ctx: BookingContextV7
    ) -> list:
        """Build the complete message list for the agentic loop.

        Structure:
        1. SystemMessage: Cached shared prompt (identity + rules + glossary)
        2. SystemMessage: Unified booking prompt (booking_v7.md — static instructions)
        3. SystemMessage: Dynamic context (collected/missing data, temporal, stylists)
        4. Conversation history (last N messages as HumanMessage/AIMessage)
        """
        messages: list = []

        # 1. Shared system prompt (cached, ~2,200 tokens)
        system_prompt = await get_system_prompt()
        messages.append(SystemMessage(content=system_prompt))

        # 2. Booking mode prompt (static instructions + tool guidance)
        booking_prompt = load_markdown("booking_v7.md", "modes")
        if booking_prompt:
            messages.append(SystemMessage(content=booking_prompt))

        # 3. Dynamic context (changes every turn)
        dynamic_context = self._build_dynamic_context(state, ctx)
        messages.append(SystemMessage(content=dynamic_context))

        # 4. Conversation history (last N messages for context window)
        for msg in state.get("messages", [])[-_HISTORY_LIMIT:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))

        return messages

    @staticmethod
    def _build_dynamic_context(state: ConversationState, ctx: BookingContextV7) -> str:
        """Build the dynamic context section injected as SystemMessage.

        Contains: temporal context, phone, collected data, missing data,
        disambiguation state, offered slots, available stylists.
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo("Europe/Madrid"))
        parts: list[str] = []

        # Temporal context
        parts.append(f"Fecha y hora actual: {now.strftime('%A %d de %B de %Y, %H:%M')}")

        # Phone (for manage_customer calls)
        phone = state.get("customer_phone")
        if phone:
            parts.append(f"Teléfono de la clienta: {phone}")

        # Conversation summary (if available from summarizer)
        summary = state.get("conversation_summary")
        if summary:
            parts.append(f"\nContexto previo:\n{summary}")

        # Collected data
        parts.append(f"\n## Datos recogidos\n{ctx.collected_summary()}")

        # Missing data
        parts.append(f"\n## Datos que faltan\n{ctx.missing_summary()}")

        # Disambiguation (pending clarification or candidate services)
        disambiguation = _build_disambiguation_section(ctx)
        if disambiguation:
            parts.append(f"\n## Clarificación\n{disambiguation}")

        # Combo recommendations
        recommendations = _build_recommendations_section(ctx)
        if recommendations:
            parts.append(f"\n## Recomendaciones\n{recommendations}")
            ctx.recommendations_shown = True  # Mark as shown

        # Service details (transparency)
        details_section = _build_service_details_section(ctx)
        if details_section:
            parts.append(f"\n## Detalle de servicios\n{details_section}")

        # Prefetched stylists
        stylists_section = _build_stylists_section(ctx)
        if stylists_section:
            parts.append(f"\n## Estilistas disponibles\n{stylists_section}")

        # Offered slots
        slots_section = _build_offered_slots_section(ctx)
        if slots_section:
            parts.append(f"\n## Horarios ofrecidos\n{slots_section}")

        # Book failure circuit breaker
        if ctx.book_failure_count >= 2:
            parts.append(
                "\n⚠️ La reserva ha fallado 2 veces. "
                "NO intentes reservar de nuevo. "
                "Ofrecé derivar al equipo humano."
            )

        return "\n".join(parts)

    # ──────────────────────────────────────────────────────────────────────
    # Response Building
    # ──────────────────────────────────────────────────────────────────────

    def _build_response(
        self,
        state: ConversationState,
        ctx: BookingContextV7,
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

        # Name redaction (privacy guard — LLM must not expose customer names)
        response_text = self._redact_names(state, response_text)

        # If redaction emptied the response, use a fallback
        if not response_text.strip():
            response_text = "De acuerdo, continuemos con tu reserva. 🙏"

        # First-turn intro (EU AI Act compliance)
        response_text, disclosure_sent = self._maybe_prepend_intro(response_text, state)

        updates: dict[str, Any] = {
            **add_message(state, "assistant", response_text),
            "mode_context": ctx.to_mode_context(),
            "last_node": "booking",
            "user_message": None,
        }

        if disclosure_sent:
            updates["ai_disclosure_sent"] = True

        # If book() succeeded → mark appointment created and transition out
        if ctx._booking_completed:
            logger.info("BookingModeV7: booking completed, transitioning to GENERAL")
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

        The booking_v7.md prompt instructs the LLM not to mention the customer's
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
                self.logger.warning(
                    "BookingModeV7: redacting customer name tokens from response"
                )
                text = _redact_name_tokens(text, name)

        return text


# ============================================================================
# Module-level helper functions (pure, no class dependency)
# ============================================================================


def _normalize_text(text: str | None) -> str:
    """Unicode NFKD normalization, lowercase, strip accents."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text.lower().strip())
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _nfd_lower(text: str) -> str:
    """NFD normalization, lowercase, strip combining marks."""
    return "".join(
        c
        for c in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(c) != "Mn"
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


def _build_disambiguation_section(ctx: BookingContextV7) -> str:
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


def _build_recommendations_section(ctx: BookingContextV7) -> str:
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


def _build_service_details_section(ctx: BookingContextV7) -> str:
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


def _detect_recommendation_decline(message: str, ctx: BookingContextV7) -> bool:
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


def _build_stylists_section(ctx: BookingContextV7) -> str:
    """Build prompt section for available stylists."""
    if not ctx.prefetched_stylists:
        return ""

    lines: list[str] = []
    for s in ctx.prefetched_stylists:
        name = s.get("name", "???")
        slot_info = s.get("next_slot_summary", "Sin disponibilidad")
        lines.append(f"- {name}: {slot_info}")

    if ctx.soonest_any_slot:
        lines.append(f"Cualquier profesional disponible: {ctx.soonest_any_slot}")

    if ctx.recurrent_stylist_hint:
        lines.append(f"Estilista habitual de la clienta: {ctx.recurrent_stylist_hint}")

    return "\n".join(lines)


def _build_offered_slots_section(ctx: BookingContextV7) -> str:
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

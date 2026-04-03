"""
Booking Mode — Simplified LLM-Driven Booking Architecture.

~800 lines. All compensatory code (pre-resolvers, text scanners, force-reminder flags)
has been removed. Python retains ONLY what the LLM cannot do:
  - UUID injection (slot_index → stylist_id/start_time)
  - Race-condition holds (_maybe_create_hold)
  - Code-rendered confirmations (F-8 path)
  - Typed tool-result extraction (via tool_extractors)

The prompt guides the LLM through the booking flow; Python enforces data-integrity gates.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from agent.modes.base import AgenticLoopResult, BaseModeNode, ToolCallRejection
from agent.modes.booking_context import BookingContext, format_service_list
from agent.modes.tool_extractors import apply_all_tool_results
from agent.prompts.loader import build_layered_messages
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState, transition_mode

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

_HISTORY_LIMIT = 8


# ============================================================================
# Module-level helpers (kept for _maybe_create_hold)
# ============================================================================


def _get_all_booking_tools() -> list:
    """Lazy-load all booking tools to avoid circular imports.

    Returns a list of 9 LangChain tool functions for the agentic loop.
    Includes create_hold and confirm_from_hold for the HOLD-based booking flow.
    """
    from agent.tools.availability_tools import check_availability, find_next_available
    from agent.tools.booking_tools import book
    from agent.tools.customer_tools import manage_customer
    from agent.tools.hold_tools import confirm_from_hold, create_hold
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
        create_hold,
        confirm_from_hold,
    ]


async def _maybe_create_hold(ctx: BookingContext) -> None:
    """Programmatically create a HOLD when a slot has been selected but not yet held.

    Called as a pre-resolver in BookingMode.handle() after slot resolution (step 1f).
    This closes the race condition window between showing availability to the user
    and them confirming the booking.

    Conditions for creating a hold:
    - ctx.selected_slot is set (slot was just selected by user)
    - ctx.hold_id is None (no active hold yet)
    - ctx.confirmation_shown is False (hold should be created BEFORE confirmation, not after)
    - ctx.customer_id is available (required for the appointment row)
    - ctx.stylist_id is available (required for the appointment row)
    - ctx.service_duration_minutes or ctx.selected_services_details has duration info

    If create_hold fails (SLOT_UNAVAILABLE), ctx.hold_id remains None and the next
    LLM turn will show the slot as taken. The GIST constraint still provides L1 safety.
    """
    if not ctx.selected_slot:
        return
    if ctx.hold_id:
        return  # Already held
    if ctx.confirmation_shown:
        return  # Confirmation already received — don't overwrite with new hold
    if not ctx.customer_id or not ctx.stylist_id:
        return  # Missing required IDs — skip hold creation
    if ctx._booking_completed:
        return  # Booking already done

    # Determine duration from context
    duration = ctx.service_duration_minutes
    if not duration and ctx.selected_services_details:
        # selected_services_details stores "duration" (not "duration_minutes") — check both
        duration = (
            sum(
                d.get("duration_minutes") or d.get("duration") or 0
                for d in ctx.selected_services_details
            )
            or None
        )
    if not duration:
        logger.debug("_maybe_create_hold: no duration available, skipping hold creation")
        return

    start_time_str = ctx.selected_slot.get("full_datetime") or ctx.selected_slot.get("start_time")
    if not start_time_str:
        logger.debug("_maybe_create_hold: no full_datetime in selected_slot, skipping")
        return

    # Determine service IDs — use selected_services_details IDs or fall back to service_id
    service_ids: list[str] = []
    if ctx.selected_services_details:
        service_ids = [str(d.get("id")) for d in ctx.selected_services_details if d.get("id")]
    if not service_ids and ctx.service_id:
        service_ids = [ctx.service_id]
    if not service_ids:
        logger.debug("_maybe_create_hold: no service_ids available, skipping hold creation")
        return

    from agent.tools.hold_tools import create_hold  # lazy import to avoid circular

    idempotency_key = f"{ctx.customer_id}:{ctx.stylist_id}:{start_time_str}"
    try:
        result = await create_hold.ainvoke(
            {
                "stylist_id": ctx.stylist_id,
                "service_ids": service_ids,
                "start_time": start_time_str,
                "customer_id": ctx.customer_id,
                "duration_minutes": duration,
                "idempotency_key": idempotency_key,
                "first_name": ctx.customer_name or "Cliente",
            }
        )
        if isinstance(result, str):
            import json

            result = json.loads(result)
        if result.get("status") == "ok":
            ctx.hold_id = result["hold_id"]
            logger.info(
                "_maybe_create_hold: HOLD created — hold_id=%s expires_at=%s",
                ctx.hold_id,
                result.get("expires_at"),
            )
        else:
            logger.warning(
                "_maybe_create_hold: HOLD creation failed — error=%s message=%s",
                result.get("error"),
                result.get("message"),
            )
            # If slot is taken, signal that availability needs refresh
            if result.get("error") == "SLOT_UNAVAILABLE":
                ctx.needs_availability_refresh = True
    except Exception as e:
        logger.error("_maybe_create_hold: unexpected error: %s", e, exc_info=True)
        # Non-fatal: the GIST constraint (L1) still provides protection


# ============================================================================
# BookingMode
# ============================================================================


class BookingMode(BaseModeNode):
    """Simplified LLM-driven booking mode — single agentic loop, all tools available.

    Python retains only what the LLM cannot do:
    - UUID injection (slot_index → stylist_id/start_time)
    - Race-condition holds (_maybe_create_hold)
    - Code-rendered confirmations (F-8 path)
    - Typed tool-result extraction (apply_all_tool_results)
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
            if manage_failures >= 3:
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

        8-step flow:
        1. Load BookingContext from mode_context
        2. Cross-mode customer handoff
        3. Race-condition hold creation
        4. Compute tool_choice (forced only on blank-slate turns)
        5. Build messages with dynamic context
        6. Run agentic loop
        7. Apply typed tool results
        8. Build response (F-8 override for completed bookings)
        """
        # Fast-path: awaiting human escalation
        mode_context = dict(state.get("mode_context") or {})
        if mode_context.get("awaiting_human"):
            return {
                **transition_mode(state, "ESCALATION"),
                **add_message(state, "assistant", "Te paso con una persona del equipo. 🙏"),
                "last_node": "booking",
                "user_message": None,
            }

        # 1. Load context
        ctx = BookingContext.from_mode_context(mode_context)

        # 1b. Confirmation gate: if user just confirmed, unlock book()
        #     The LLM already showed the summary (confirmation_summary_sent=True) and
        #     the intent router classified this turn as "confirm". Flip the flag so
        #     _pre_tool_call lets book() / confirm_from_hold() through.
        intent_str = str(intent) if intent else ""
        if not ctx.confirmation_shown and ctx.confirmation_summary_sent and "confirm" in intent_str:
            ctx.confirmation_shown = True

        # 2. Cross-mode customer handoff
        self._resolve_customer_from_state(state, ctx)

        # 3. Race-condition hold creation
        await _maybe_create_hold(ctx)

        # 4. tool_choice only when completely blank-slate
        #    (no service, no candidates, no slots, no clarifications)
        tool_choice: str | None = None
        if (
            not ctx.service_id
            and not ctx.selected_services
            and not ctx.candidate_services
            and not ctx.pending_clarifications
            and not ctx.offered_slots
            and not ctx.confirmation_shown
        ):
            tool_choice = "required"
            logger.info("BookingMode: tool_choice='required' (blank slate)")

        # Store for _pre_tool_call access
        self._ctx = ctx
        self._current_state = state

        # 5. Build messages with dynamic context
        messages = await self._build_messages(state, ctx)

        # 6. Run agentic loop — LLM calls tools freely
        result = await self._run_agentic_loop(
            messages, tools=self.get_tools(), tool_choice=tool_choice
        )

        # 7. Apply typed tool results
        self._apply_tool_results(result, ctx)

        # 8. Build response (F-8 override for confirmed bookings)
        response_text = self._build_response(result, ctx)

        updates: dict[str, Any] = {
            **add_message(state, "assistant", response_text),
            "mode_context": ctx.to_mode_context(),
            "last_node": "booking",
            "user_message": None,
        }

        # Propagate customer name to top-level state if discovered
        if ctx.customer_name and not state.get("customer_name"):
            updates["customer_name"] = ctx.customer_name

        # F-8: transition to GENERAL after successful booking
        if ctx._booking_completed:
            updates["appointment_created"] = True
            updates.update(transition_mode(state, "GENERAL"))
            # Restore mode_context after transition_mode reset
            updates["mode_context"] = ctx.to_mode_context()

        return updates

    # ──────────────────────────────────────────────────────────────────────
    # _pre_tool_call — 3 gate categories only
    # ──────────────────────────────────────────────────────────────────────

    async def _pre_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> dict[str, Any] | ToolCallRejection:
        """Intercept tool calls before execution.

        3 categories:
        (a) book() / confirm_from_hold(): confirmation gate + customer_id gate
            + slot_index→UUID injection + services/notes injection
        (b) Availability tools (check_availability, find_next_available):
            clear stale slot state
        (c) Everything else: pass through unchanged
        """
        ctx: BookingContext | None = getattr(self, "_ctx", None)

        # ── Availability tools: clear stale slot state ─────────────────────────
        if tool_name in ("check_availability", "find_next_available"):
            if ctx:
                ctx.offered_slots = []
                ctx.selected_slot = None
            return tool_args

        # ── book() / confirm_from_hold(): UUID injection + gates ──────────────
        if tool_name in ("book", "confirm_from_hold"):
            if not ctx:
                return tool_args

            # Gate 1: confirmation required
            if not ctx.confirmation_shown:
                # Auto-generate confirmation summary if all data available
                if ctx.service_id and ctx.stylist_id and ctx.selected_slot and ctx.customer_name:
                    summary = self._build_confirmation_summary(ctx)
                    ctx.confirmation_summary_sent = True
                    return ToolCallRejection(
                        name=tool_name,
                        error_code="CONFIRMATION_NOT_SHOWN",
                        error_message=(
                            "Mostrá este resumen al usuario y esperá su confirmación:\n\n"
                            f"{summary}\n\nNO llames book() hasta recibir confirmación."
                        ),
                    )
                elif ctx.confirmation_summary_sent:
                    return ToolCallRejection(
                        name=tool_name,
                        error_code="CONFIRMATION_NOT_SHOWN",
                        error_message="Esperá la confirmación del usuario antes de llamar book().",
                    )
                else:
                    return ToolCallRejection(
                        name=tool_name,
                        error_code="CONFIRMATION_NOT_SHOWN",
                        error_message=(
                            "Mostrá el resumen de confirmación y esperá la respuesta del usuario."
                        ),
                    )

            # Gate 2: customer_id injection
            if ctx.customer_id:
                tool_args["customer_id"] = ctx.customer_id
            elif not tool_args.get("customer_id"):
                return ToolCallRejection(
                    name=tool_name,
                    error_code="NO_CUSTOMER_ID",
                    error_message=(
                        "Llamá manage_customer(action='get') primero para obtener el customer_id."
                    ),
                )

            # Gate 3: slot_index → UUID resolution
            slot_index = tool_args.get("slot_index")
            if slot_index is not None and ctx.offered_slots:
                try:
                    idx = int(slot_index)
                    if 1 <= idx <= len(ctx.offered_slots):
                        slot = ctx.offered_slots[idx - 1]
                        tool_args["stylist_id"] = slot.get("stylist_id")
                        tool_args["start_time"] = slot.get("start_time")
                        ctx.selected_slot = slot
                    else:
                        return ToolCallRejection(
                            name=tool_name,
                            error_code="INVALID_SLOT_INDEX",
                            error_message=(
                                f"slot_index {idx} fuera de rango "
                                f"(1-{len(ctx.offered_slots)}). Mostrá la lista de nuevo."
                            ),
                        )
                except (ValueError, TypeError):
                    return ToolCallRejection(
                        name=tool_name,
                        error_code="INVALID_SLOT_INDEX",
                        error_message="slot_index debe ser un número entero.",
                    )

            # Inject services and notes
            if ctx.selected_services:
                tool_args["services"] = list(ctx.selected_services)
            elif ctx.service_id:
                tool_args.setdefault("services", [ctx.service_id])
            if ctx.notes:
                tool_args.setdefault("notes", ctx.notes)

            return tool_args

        # ── All other tools: pass through ──────────────────────────────────────
        return tool_args

    # ──────────────────────────────────────────────────────────────────────
    # Tool results bridge
    # ──────────────────────────────────────────────────────────────────────

    def _apply_tool_results(self, result: AgenticLoopResult, ctx: BookingContext) -> None:
        """Thin bridge to apply_all_tool_results from tool_extractors."""
        tool_results = result.tool_results if result.tool_results else []
        apply_all_tool_results(tool_results, ctx)

    # ──────────────────────────────────────────────────────────────────────
    # Response building — F-8 only
    # ──────────────────────────────────────────────────────────────────────

    def _build_response(self, result: AgenticLoopResult, ctx: BookingContext) -> str:
        """Build the final response text.

        F-8: code-render a structured confirmation block after successful booking.
        Everything else: return LLM text as-is (via _sanitize_response).
        """
        response_text = result.response_text or ""

        # F-8: code-rendered confirmation after successful booking
        if getattr(ctx, "_booking_completed", False) and ctx.selected_slot:
            return self._render_booking_confirmation(ctx)

        return self._sanitize_response(response_text)

    def _build_confirmation_summary(self, ctx: BookingContext) -> str:
        """Build a short confirmation summary for the user to review before booking."""
        slot = ctx.selected_slot or {}
        day = slot.get("day_label", "?")
        time_ = slot.get("time", "?")
        stylist = ctx.stylist_name or "?"
        service = ctx.service_name or (ctx.selected_services[0] if ctx.selected_services else "?")
        return f"Te agendo el *{day} a las {time_}* con *{stylist}* para *{service}*. ¿Lo confirmo?"

    def _render_booking_confirmation(self, ctx: BookingContext) -> str:
        """Code-render the post-booking confirmation block (F-8 path)."""
        slot = ctx.selected_slot or {}
        day = slot.get("day_label", "?")
        time_ = slot.get("time", "?")
        stylist = ctx.stylist_name or "?"
        services = (
            ", ".join(ctx.selected_services) if ctx.selected_services else (ctx.service_name or "?")
        )
        return (
            f"✅ ¡Reserva confirmada!\n\n"
            f"📅 {day} a las {time_}\n"
            f"💇 {stylist}\n"
            f"✨ {services}\n\n"
            f"Te esperamos 🌸"
        )

    # ──────────────────────────────────────────────────────────────────────
    # Message construction
    # ──────────────────────────────────────────────────────────────────────

    async def _build_messages(self, state: ConversationState, ctx: BookingContext) -> list:
        """Build the complete message list for the agentic loop via layered assembly.

        Structure:
        1. SystemMessage: Cached shared prompt (identity + critical_rules)
        2. SystemMessage: Booking mode overlay (booking.md)
        3. Conversation history (last _HISTORY_LIMIT messages)
        4. SystemMessage: Dynamic context (collected/missing data, stylists, slots) — LAST
        """
        dynamic_context = self._build_dynamic_context(ctx, state)

        messages, dynamic_context_index = await build_layered_messages(
            state=state,
            mode_context=dict(state.get("mode_context") or {}),
            mode_name="BOOKING",
            dynamic_context_override=dynamic_context,
            include_history=True,
            history_limit=_HISTORY_LIMIT,
        )

        # Store index for potential mid-loop refresh (inherited hook)
        self._dynamic_context_index = dynamic_context_index
        self._dynamic_context_state = state

        return messages

    def _build_dynamic_context(self, ctx: BookingContext, state: ConversationState) -> str:
        """Build the dynamic context XML section injected as the last SystemMessage.

        Contains: temporal context, phone, conversation summary, collected data,
        missing data, available stylists, offered slots, pending clarifications,
        candidate services, hold context.
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

        # Booking context XML block
        parts.append("<booking_context>")

        collected = ctx.collected_summary()
        if collected:
            parts.append(f"<collected_data>\n{collected}\n</collected_data>")

        missing = ctx.missing_summary()
        if missing:
            parts.append(f"<missing_data>\n{missing}\n</missing_data>")

        if ctx.prefetched_stylists:
            stylist_lines = "\n".join(
                f"{i + 1}. {s['name']} (id: {s['id']})"
                for i, s in enumerate(ctx.prefetched_stylists)
            )
            parts.append(f"<available_stylists>\n{stylist_lines}\n</available_stylists>")

        if ctx.offered_slots:
            slot_lines = "\n".join(
                f"{i + 1}. {s.get('day_label', '?')} a las {s.get('time', '?')}"
                f" con {s.get('stylist_name', '?')}"
                for i, s in enumerate(ctx.offered_slots)
            )
            parts.append(f"<offered_slots>\n{slot_lines}\n</offered_slots>")

        if ctx.pending_clarifications:
            for clar in ctx.pending_clarifications:
                axis = clar.get("axis", "opción")
                options = clar.get("options", [])
                svc = clar.get("service_name", "servicio")
                opts_text = "\n".join(f"- {o}" for o in options)
                parts.append(
                    f"<clarification service='{svc}' axis='{axis}'>\n{opts_text}\n</clarification>"
                )

        if ctx.candidate_services:
            cands = "\n".join(
                f"{i + 1}. {c.get('name', '?')}" for i, c in enumerate(ctx.candidate_services)
            )
            parts.append(f"<candidate_services>\n{cands}\n</candidate_services>")

        if ctx.hold_id:
            parts.append(
                f"<hold_context>\n✅ Hold activo: {ctx.hold_id}\n"
                "Usá confirm_from_hold() en lugar de book().\n</hold_context>"
            )

        if ctx.confirmation_shown:
            parts.append("✅ CONFIRMACIÓN RECIBIDA — podés llamar book() ahora.")

        parts.append("</booking_context>")

        return "\n".join(parts)

    # ──────────────────────────────────────────────────────────────────────
    # Context helpers
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

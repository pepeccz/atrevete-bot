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


def _resolve_slot_from_message(user_message: str, ctx: BookingContext) -> bool:
    """Deterministic slot resolver — safety net for UUID injection.

    Called after the agentic loop when the LLM didn't persist a slot selection.
    Matches the user message against ctx.offered_slots using:
      1. Bare digit (1-N index)
      2. Time string ("a las HH:MM", "HH:MM", "las H")

    On match: sets ctx.selected_slot, ctx.stylist_id, ctx.stylist_name.
    Returns True if a slot was resolved, False otherwise.
    """
    import re

    if not ctx.offered_slots or ctx.selected_slot is not None:
        logger.debug(
            "_resolve_slot_from_message: skipped (offered_slots=%s, selected_slot=%s)",
            "empty/None" if not ctx.offered_slots else len(ctx.offered_slots),
            "set" if ctx.selected_slot is not None else "None",
        )
        return False

    text = user_message.strip()
    if not text:
        return False

    num_slots = len(ctx.offered_slots)
    slot_times = [s.get("time", "?") for s in ctx.offered_slots]
    logger.debug(
        "_resolve_slot_from_message: trying to match '%s' against %d slots (times=%s)",
        text[:60],
        num_slots,
        slot_times,
    )

    # Strategy 1: bare digit (1-N)
    bare_digit = re.fullmatch(r"\d+", text)
    if bare_digit:
        idx = int(bare_digit.group())
        if 1 <= idx <= num_slots:
            return _persist_slot(ctx, idx - 1)
        logger.debug("_resolve_slot_from_message: bare digit %d out of range (1-%d)", idx, num_slots)
        return False

    # Strategy 2: time string — extract HH:MM from message
    time_match = re.search(r"(\d{1,2}):(\d{2})", text)
    if time_match:
        target_time = f"{int(time_match.group(1))}:{time_match.group(2)}"
        for i, slot in enumerate(ctx.offered_slots):
            slot_time = slot.get("time", "")
            # Normalize: "10:00" → "10:00", compare both with and without leading zero
            slot_hour_min = slot_time.lstrip("0") if slot_time.startswith("0") else slot_time
            if target_time == slot_time or target_time == slot_hour_min:
                return _persist_slot(ctx, i)
        logger.debug(
            "_resolve_slot_from_message: time '%s' matched regex but no slot match (slots=%s)",
            target_time,
            slot_times,
        )
        return False

    # Strategy 3: "las N" / "a las N" (hour without minutes)
    hour_match = re.search(r"(?:a\s+)?las\s+(\d{1,2})", text, re.IGNORECASE)
    if hour_match:
        target_hour = int(hour_match.group(1))
        for i, slot in enumerate(ctx.offered_slots):
            slot_time = slot.get("time", "")
            try:
                slot_hour = int(slot_time.split(":")[0])
                if slot_hour == target_hour:
                    return _persist_slot(ctx, i)
            except (ValueError, IndexError):
                continue
        logger.debug(
            "_resolve_slot_from_message: hour %d no match (slots=%s)", target_hour, slot_times
        )

    logger.debug("_resolve_slot_from_message: no strategy matched for '%s'", text[:60])
    return False


def _persist_slot(ctx: BookingContext, index: int) -> bool:
    """Persist a matched slot into BookingContext."""
    slot = ctx.offered_slots[index]
    ctx.selected_slot = slot
    if slot.get("stylist_id"):
        ctx.stylist_id = slot["stylist_id"]
    if slot.get("stylist_name"):
        ctx.stylist_name = slot["stylist_name"]
    logger.info(
        "_resolve_slot_from_message: resolved slot index=%d time=%s stylist=%s",
        index + 1,
        slot.get("time"),
        slot.get("stylist_name"),
    )
    return True


def _resolve_stylist_from_message(user_message: str, ctx: BookingContext) -> bool:
    """Deterministic stylist resolver — safety net for tool_skip on stylist selection.

    Matches the user message against ctx.prefetched_stylists using:
      1. Bare digit (1-N index)
      2. Exact name match (case-insensitive)

    On match: sets ctx.stylist_id, ctx.stylist_name.
    Returns True if a stylist was resolved, False otherwise.
    """
    import re

    if not ctx.prefetched_stylists or ctx.stylist_id:
        return False

    text = user_message.strip()
    if not text:
        return False

    num_stylists = len(ctx.prefetched_stylists)

    # Strategy 1: bare digit (1-N)
    bare_digit = re.fullmatch(r"\d+", text)
    if bare_digit:
        idx = int(bare_digit.group())
        if 1 <= idx <= num_stylists:
            stylist = ctx.prefetched_stylists[idx - 1]
            ctx.stylist_id = stylist["id"]
            ctx.stylist_name = stylist["name"]
            logger.info(
                "_resolve_stylist_from_message: resolved stylist index=%d name=%s",
                idx,
                stylist["name"],
            )
            return True
        return False

    # Strategy 2: name match (case-insensitive)
    text_lower = text.lower()
    for stylist in ctx.prefetched_stylists:
        if stylist["name"].lower() in text_lower:
            ctx.stylist_id = stylist["id"]
            ctx.stylist_name = stylist["name"]
            logger.info(
                "_resolve_stylist_from_message: resolved stylist by name=%s",
                stylist["name"],
            )
            return True

    return False


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
        """Return all booking tools for the agentic loop."""
        return _get_all_booking_tools()

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
        if (
            not ctx.confirmation_shown
            and ctx.confirmation_summary_sent
            and "confirm" in intent_str
            and ctx.service_id
            and ctx.stylist_id
            and ctx.selected_slot
        ):
            ctx.confirmation_shown = True

        # 2. Cross-mode customer handoff
        self._resolve_customer_from_state(state, ctx)

        # 3. Race-condition hold creation
        await _maybe_create_hold(ctx)

        # 4. tool_choice: force tool use ONLY on blank-slate turns.
        #    All other states trust the LLM + <missing_data> context to pick the right tool.
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

        # 7b. Post-loop resolvers — safety net for tool_skip
        #     When the LLM didn't call a tool that persists user selections,
        #     match the user message deterministically.
        user_msg = state.get("user_message") or ""

        # Stylist resolver: bare digit or name match against prefetched_stylists
        if ctx.prefetched_stylists and not ctx.stylist_id:
            _resolve_stylist_from_message(user_msg, ctx)

        # Slot resolver: bare digit or time match against offered_slots
        if ctx.offered_slots and ctx.selected_slot is None:
            if _resolve_slot_from_message(user_msg, ctx):
                # Try to create hold now that slot is resolved
                await _maybe_create_hold(ctx)

        # 8. Build response (F-8 override for confirmed bookings)
        response_text = self._build_response(result, ctx)
        response_text, disclosure_sent = self._maybe_prepend_intro(response_text, state)

        updates: dict[str, Any] = {
            **add_message(state, "assistant", response_text),
            "mode_context": ctx.to_mode_context(),
            "last_node": "booking",
            "user_message": None,
        }
        if disclosure_sent:
            updates["ai_disclosure_sent"] = True

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

        # Gate: list_stylists requires service to be resolved first
        if tool_name == "list_stylists":
            if ctx and not ctx.service_category:
                return ToolCallRejection(
                    name="list_stylists",
                    error_code="SERVICE_NOT_RESOLVED",
                    error_message="Primero resolvé el servicio con search_services() antes de mostrar estilistas.",
                )

        # ── search_services: auto-inject resolved axes, guard stylist-as-service ──
        if tool_name == "search_services":
            # Auto-inject resolved axes so disambiguation doesn't re-ask
            if ctx and ctx.resolved_axes:
                axis_param_map = {
                    "audience": "audience",
                    "hair_length": "hair_length",
                    "hair_density": "hair_density",
                }
                for axis, value in ctx.resolved_axes.items():
                    param = axis_param_map.get(axis)
                    if param and not tool_args.get(param):
                        tool_args[param] = value
                        logger.debug(
                            "_pre_tool_call: auto-injected %s=%s from resolved_axes",
                            param,
                            value,
                        )

            if ctx and ctx.prefetched_stylists and not ctx.stylist_id:
                query = (tool_args.get("query") or "").strip().lower()
                for stylist in ctx.prefetched_stylists:
                    stylist_name = stylist.get("name", "").strip().lower()
                    if query and stylist_name and query == stylist_name:
                        return ToolCallRejection(
                            name="search_services",
                            error_code="STYLIST_NOT_SERVICE",
                            error_message=(
                                f"'{stylist['name']}' es una estilista, no un servicio. "
                                f"Usá find_next_available(stylist_id=\"{stylist['id']}\") o "
                                f"check_availability(stylist_id=\"{stylist['id']}\") "
                                "para buscar disponibilidad."
                            ),
                        )

        # ── Availability tools: stylist gate then clear stale slot state ──────────
        if tool_name in ("check_availability", "find_next_available"):
            if ctx:
                if not ctx.prefetched_stylists:
                    # Capture date hint before rejecting — don't lose user's date
                    date_arg = tool_args.get("start_date") or tool_args.get("date")
                    if date_arg and not ctx.preferred_date_hint:
                        ctx.preferred_date_hint = str(date_arg)
                        logger.info(
                            "Captured preferred_date_hint='%s' from rejected %s",
                            date_arg,
                            tool_name,
                        )
                    return ToolCallRejection(
                        name=tool_name,
                        error_code="NO_STYLISTS_SHOWN",
                        error_message="Llamá list_stylists() primero y esperá la elección del cliente antes de buscar disponibilidad.",
                    )
                ctx.offered_slots = []
                ctx.selected_slot = None
            return tool_args

        # ── book() / confirm_from_hold(): slot resolution → confirmation → injection
        if tool_name in ("book", "confirm_from_hold"):
            if not ctx:
                return tool_args

            # Step A: slot_index → UUID resolution (ALWAYS runs first)
            # Persists selected_slot even when later gates reject the call.
            # This breaks the circular dependency where selected_slot could
            # never be set because the confirmation gate rejected first.
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

            # Step B: confirmation gate
            if not ctx.confirmation_shown:
                # Auto-generate confirmation summary if all data available
                if (
                    ctx.service_id
                    and ctx.stylist_id
                    and ctx.selected_slot
                    and ctx.customer_name
                    and ctx.notes
                ):
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
                    missing = ctx.missing_summary()
                    return ToolCallRejection(
                        name=tool_name,
                        error_code="CONFIRMATION_NOT_SHOWN",
                        error_message=(
                            "Todavía falta info:\n"
                            f"{missing}\n\n"
                            "Recogé los datos que faltan antes de confirmar."
                        ),
                    )

            # Step C: customer_id injection
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

            # Step D: Inject services and notes
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
        tool_results = result.tool_results
        # Guard: apply_all_tool_results expects a dict; a falsy value or a list
        # (e.g. empty [] from AgenticLoopResult default) must become an empty dict.
        if not isinstance(tool_results, dict):
            tool_results = {}
        apply_all_tool_results(tool_results, ctx)

    # ──────────────────────────────────────────────────────────────────────
    # Response building — F-8 only
    # ──────────────────────────────────────────────────────────────────────

    def _build_response(self, result: AgenticLoopResult, ctx: BookingContext) -> str:
        """Build the final response text.

        F-8: code-render a structured confirmation block after successful booking.
        Auto-detect confirmation summary: when all booking data is complete and the
        LLM responds, mark confirmation_summary_sent so the next turn's gate works.
        Everything else: return LLM text as-is (via _sanitize_response).
        """
        response_text = result.response_text or ""

        # F-8: code-rendered confirmation after successful booking
        if getattr(ctx, "_booking_completed", False) and ctx.selected_slot:
            return self._render_booking_confirmation(ctx)

        # Auto-detect confirmation summary: when all required data is present
        # and the LLM generated a response, the response IS the summary.
        # This covers both LLM-generated and _pre_tool_call-generated summaries.
        if (
            not ctx.confirmation_summary_sent
            and not ctx._booking_completed
            and ctx.service_id
            and ctx.stylist_id
            and ctx.selected_slot
            and ctx.customer_name
            and ctx.notes
            and response_text.strip()
        ):
            ctx.confirmation_summary_sent = True
            logger.info("_build_response: auto-set confirmation_summary_sent (all data complete)")

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
                question = clar.get("question_hint", "")
                original_query = clar.get("original_query", "")
                options = clar.get("options", [])
                opts_text = "\n".join(
                    f"- {o.get('label', o) if isinstance(o, dict) else o}"
                    for o in options
                )
                parts.append(
                    f"<clarification axis='{axis}' question='{question}'"
                    f" original_query='{original_query}'>"
                    f"\n{opts_text}\n</clarification>"
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
    # Mid-loop dynamic context refresh
    # ──────────────────────────────────────────────────────────────────────

    def _refresh_dynamic_context(self, working_messages: list) -> None:
        """Rebuild the dynamic context SystemMessage so the LLM sees fresh state.

        Called by the agentic loop after each tool round. Replaces the
        SystemMessage at _dynamic_context_index with an updated version
        reflecting any ctx changes from tool results (e.g., service resolved,
        customer name collected, slot selected).
        """
        from langchain_core.messages import SystemMessage

        idx = getattr(self, "_dynamic_context_index", None)
        ctx = getattr(self, "_ctx", None)
        state = getattr(self, "_dynamic_context_state", None)
        if idx is None or ctx is None or state is None:
            return
        if idx >= len(working_messages):
            return

        refreshed = self._build_dynamic_context(ctx, state)
        working_messages[idx] = SystemMessage(content=refreshed)

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

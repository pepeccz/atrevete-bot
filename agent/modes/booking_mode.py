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


def _last_message_is_human(state) -> bool:
    """Predicate for ``ToolChoiceMiddleware``: True when last message is HumanMessage."""
    from langchain_core.messages import HumanMessage

    messages = state.get("messages") or []
    return bool(messages) and isinstance(messages[-1], HumanMessage)


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

    def get_tools(self, booking_context: dict | None = None) -> list:
        """Return tools filtered by booking state (msi-a pattern).

        Instead of offering all tools and rejecting calls via gates,
        only offer tools that are relevant to the current state.
        The LLM naturally follows the flow when it only sees applicable tools.
        """
        from agent.tools.booking_data_tools import update_booking
        from agent.tools.availability_tools import check_availability
        from agent.tools.booking_tools import book

        ctx = booking_context or {}
        tools = [update_booking]  # always available

        has_services = bool(ctx.get("last_services"))
        has_stylist = bool(ctx.get("last_stylist") or ctx.get("no_preference_stylist"))
        has_slot = bool(ctx.get("selected_slot"))

        # check_availability: only when services + stylist are set, no slot yet
        if has_services and has_stylist and not has_slot:
            tools.append(check_availability)

        # book: only when all required data is collected
        is_complete, _ = self._booking_complete(ctx)
        if is_complete:
            tools.append(book)

        return tools

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
        # Notes are optional — the prompt instructs the LLM to ask (Paso 5).
        # No Python gate needed; book() accepts notes=None.
        return (len(missing) == 0, missing)

    @staticmethod
    def _build_flow_hint(ctx: dict) -> str:
        """Build a descriptive state hint — data, not commands.

        Reports WHAT is collected and WHAT is pending. The LLM reads
        booking.md for flow order and reasons from the state.
        Only _confirmation_shown is set here (deterministic Python gate).
        """
        # ── Collect state facts ─────────────────────────────────────────
        collected: list[str] = []
        pending: list[str] = []

        if ctx.get("last_services"):
            collected.append(f"servicio ({', '.join(ctx['last_services'])})")
        else:
            pending.append("servicio")

        if ctx.get("last_services") and not ctx.get("add_more_asked"):
            pending.append("preguntar ¿algo más?")

        if ctx.get("last_stylist") or ctx.get("no_preference_stylist"):
            stylist = ctx.get("last_stylist", "sin preferencia")
            collected.append(f"estilista ({stylist})")
        else:
            pending.append("estilista")

        if ctx.get("selected_slot"):
            slot = ctx["selected_slot"]
            collected.append(f"horario ({slot.get('date', '?')} a las {slot.get('time', '?')})")
        elif ctx.get("offered_slots"):
            n = len(ctx["offered_slots"])
            pending.append(f"selección de horario ({n} opciones ofrecidas)")
        else:
            pending.append("fecha/hora")

        if ctx.get("customer_name"):
            collected.append(f"nombre ({ctx['customer_name']})")
        else:
            pending.append("nombre")

        if ctx.get("notes_asked"):
            notes = ctx.get("notes")
            collected.append(f"notas ({notes or 'sin notas'})")
        else:
            pending.append("notas")

        # ── Confirmation gate (deterministic, Python-only) ──────────────
        if not pending and not ctx.get("_confirmation_shown"):
            ctx["_confirmation_shown"] = True

        # ── Build hint ──────────────────────────────────────────────────
        parts: list[str] = []

        if collected:
            parts.append(f"Recogido: {', '.join(collected)}.")

        if pending:
            parts.append(f"Pendiente: {', '.join(pending)}.")
        elif ctx.get("_confirmation_shown"):
            parts.append("Todos los datos recogidos — resumen mostrado, esperando confirmación.")
        else:
            parts.append("Todos los datos recogidos.")

        return f"<flow_hint>{' '.join(parts)}</flow_hint>"

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
        # so the LLM has context about what the client originally asked for.
        if not booking_context.get("opening_booking_request") and not booking_context.get("last_services"):
            user_msg = get_last_user_message(state).strip()
            if user_msg:
                booking_context["opening_booking_request"] = user_msg

        # 1b. Pre-load stylist names by category for dynamic context
        self._cached_stylists_by_category = await self._load_stylists_by_category()

        # 1b2. Pre-load service names for customer memory ambiguity check
        self._cached_service_names = await self._load_service_names()

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

        # Store for _pre_tool_call / _post_tool_result / _refresh_dynamic_context access.
        # _booking_context is the canonical store; _mode_context is kept as an alias
        # so that both attributes resolve to the same dict (defensive programming).
        self._booking_context = booking_context
        self._mode_context = booking_context  # alias: both point to booking_context
        self._current_state = state

        # 4. Build messages with dynamic context
        messages = await self._build_messages(state, booking_context)

        # 5. Run the agent loop via ``create_agent`` + composed middleware.
        result = await self._invoke_create_agent(
            messages=messages,
            tools=self.get_tools(booking_context),
            tool_choice=tool_choice,
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

        Tool filtering by state (get_tools) handles WHICH tools the LLM sees.
        _pre_tool_call only handles:
        - update_booking: inject _current_context
        - check_availability: inject service/stylist from context
        - book(): slot_index→UUID injection + completeness gate + services injection
        """
        mode_context: dict = getattr(self, "_booking_context", getattr(self, "_mode_context", {}))

        # ── update_booking: context injection only ──────────────────────
        if tool_name == "update_booking":
            tool_args["_current_context"] = dict(mode_context)
            return tool_args

        # ── check_availability: inject from context ─────────────────────
        if tool_name == "check_availability":
            if not tool_args.get("service_names") and mode_context.get("last_services"):
                tool_args["service_names"] = mode_context["last_services"]
            if not tool_args.get("stylist_name") and mode_context.get("last_stylist"):
                if mode_context["last_stylist"] != "Sin preferencia":
                    tool_args["stylist_name"] = mode_context["last_stylist"]
            if not tool_args.get("total_duration_minutes") and mode_context.get(
                "last_total_duration_minutes"
            ):
                tool_args["total_duration_minutes"] = mode_context[
                    "last_total_duration_minutes"
                ]
            if not tool_args.get("service_category") and mode_context.get(
                "last_service_category"
            ):
                tool_args["service_category"] = mode_context["last_service_category"]
            return tool_args

        # ── book(): slot resolution → completeness gate → injection ─────
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
            # Step A.2: customer_name — prefer mode_context (from update_booking),
            # fall back to tool args (defense-in-depth).
            _NAME_BLOCKLIST = frozenset({
                "cliente", "usuario", "desconocido", "n/a", "nombre",
                "sin nombre", "no proporcionado", "unknown", "user", "customer",
            })
            if not mode_context.get("customer_name"):
                first = (tool_args.get("customer_first_name") or "").strip()
                if first:
                    if first.lower() in _NAME_BLOCKLIST:
                        logger.warning(
                            "_pre_tool_call: rejected placeholder customer_name=%r from book() args",
                            first,
                        )
                    else:
                        last = (tool_args.get("customer_last_name") or "").strip()
                        full_name = f"{first} {last}" if last else first
                        mode_context["customer_name"] = full_name
                        logger.info(
                            "_pre_tool_call: extracted customer_name=%s from book() args",
                            full_name,
                        )

            # Inject customer_first_name/last_name into book() args from mode_context
            if not tool_args.get("customer_first_name") and mode_context.get("customer_first_name"):
                tool_args["customer_first_name"] = mode_context["customer_first_name"]
                tool_args["customer_last_name"] = mode_context.get("customer_last_name")

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
                        f"RECHAZADO. Faltan: {missing_hint}. "
                        f"SIGUIENTE ACCIÓN: pregunta al cliente por los datos "
                        f"faltantes uno a uno."
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

        if tool_name == "update_booking":
            patch = result_dict.get("_booking_context_patch", {})
            if patch:
                for key, val in patch.items():
                    if val is None:
                        mode_context.pop(key, None)
                    else:
                        mode_context[key] = val
                logger.info(
                    "_post_tool_result[update_booking]: applied patch keys=%s",
                    list(patch.keys()),
                )

                # Cascade clear: if the update invalidates previously confirmed data
                # (services changed, slot cleared), reset _confirmation_shown so a new
                # summary is shown before the next book() attempt.
                _INVALIDATING_KEYS = ("last_services", "offered_slots", "selected_slot")
                if mode_context.get("_confirmation_shown") and any(
                    k in patch for k in _INVALIDATING_KEYS
                ):
                    mode_context["_confirmation_shown"] = False
                    logger.info(
                        "_post_tool_result[update_booking]: cascade cleared _confirmation_shown "
                        "because invalidating keys changed: %s",
                        [k for k in _INVALIDATING_KEYS if k in patch],
                    )

            return result

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
    # create_agent integration (M6)
    # ──────────────────────────────────────────────────────────────────────

    async def _invoke_create_agent(
        self,
        messages: list,
        tools: list,
        tool_choice: str | None,
    ) -> AgenticLoopResult:
        """Run ``create_agent`` with the composed booking middleware stack.

        Replaces the legacy ``_run_agentic_loop`` call. Preserves the
        ``AgenticLoopResult`` return contract so ``_build_response`` and the
        existing response-building logic keep working unchanged.
        """
        from langchain.agents import create_agent
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        from agent.middleware.dedup import DedupToolCallMiddleware
        from agent.middleware.node_bridge import NodeBridgeMiddleware
        from agent.middleware.final_text_recovery import FinalTextRecoveryMiddleware
        from agent.middleware.token_tracking import TokenTrackingMiddleware
        from agent.middleware.tool_choice import ToolChoiceMiddleware

        # Split the legacy layered message list into ``system_prompt`` + transcript.
        system_parts: list[str] = []
        transcript: list = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if content:
                    system_parts.append(content)
            else:
                transcript.append(msg)
        system_prompt = "\n\n".join(system_parts)

        fallback_text = (
            "Perdona, tuve un problema procesando tu mensaje. ¿Puedes repetirlo?"
        )

        middleware: list = [
            NodeBridgeMiddleware(self),
            DedupToolCallMiddleware(),
            FinalTextRecoveryMiddleware(fallback_text=fallback_text),
            TokenTrackingMiddleware(mode_name="BOOKING"),
        ]
        if tool_choice:
            middleware.insert(
                0,
                ToolChoiceMiddleware(
                    when=lambda state: _last_message_is_human(state),
                    choice=tool_choice,
                ),
            )

        agent = create_agent(
            model=self.llm,
            tools=tools,
            system_prompt=system_prompt,
            middleware=middleware,
        )

        try:
            result_dict = await agent.ainvoke({"messages": transcript})
        except Exception as exc:
            logger.error("BookingModeNode: create_agent invocation failed: %s", exc)
            return AgenticLoopResult(response_text=fallback_text, error=str(exc))

        response_text = ""
        final_messages = result_dict.get("messages") or []
        for msg in reversed(final_messages):
            if isinstance(msg, AIMessage):
                content = msg.content
                if isinstance(content, str):
                    response_text = content.strip()
                elif isinstance(content, list):
                    parts: list[str] = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            parts.append(block)
                    response_text = "\n".join(parts).strip()
                if response_text:
                    break
        if not response_text:
            response_text = fallback_text

        return AgenticLoopResult(response_text=response_text)

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
        parts.append(
            f"<min_valid_date>{min_date_label}</min_valid_date>\n"
            f"<min_valid_date_iso>{min_date.isoformat()}</min_valid_date_iso>"
        )

        # Flow hint — neutral factual list of pending data (not prescriptive)
        parts.append(self._build_flow_hint(mode_context))

        # Available stylists — shown when services are known, stylist not chosen, and
        # "algo más?" has already been asked (add_more_asked gate)
        if (
            mode_context.get("last_services")
            and not mode_context.get("last_stylist")
            and mode_context.get("add_more_asked")
        ):
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

        # Suggested name from DB/state — requires explicit confirmation from the client
        suggested_name = mode_context.get("_suggested_customer_name")
        if suggested_name and not mode_context.get("customer_name"):
            parts.append(
                f"<suggested_name>\n"
                f"El cliente podría ser: {suggested_name}. "
                f"PREGUNTÁ si la reserva va a ese nombre antes de asumirlo.\n"
                f"</suggested_name>"
            )

        # <collected_data> removed — <flow_hint> already shows collected/pending state

        offered_slots = mode_context.get("offered_slots") or []
        if offered_slots:
            slot_lines = "\n".join(
                f"{i + 1}. {s.get('day_label', '?')} a las {s.get('time', '?')}"
                f" con {s.get('stylist_name', '?')}"
                for i, s in enumerate(offered_slots)
            )
            parts.append(f"<offered_slots>\n{slot_lines}\n</offered_slots>")

        parts.append("</booking_context>")

        # Cross-conversation customer memories (injected when present)
        customer_memories = state.get("customer_memories")
        if customer_memories and isinstance(customer_memories, dict):
            from agent.prompts.loader import _build_customer_memory_context

            # Pass service names from cached stylists catalog for ambiguity check
            all_svc_names = getattr(self, "_cached_service_names", None)
            parts.append(_build_customer_memory_context(customer_memories, all_svc_names))

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
    # Mid-loop dynamic context refresh
    # ──────────────────────────────────────────────────────────────────────

    def _refresh_tools(self) -> list | None:
        """Refresh tool list based on updated booking state after each tool round."""
        ctx = getattr(self, "_booking_context", None)
        if ctx is not None:
            return self.get_tools(ctx)
        return None

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
        """Inject customer suggestion and ID from state if not already in mode_context.

        Handles returning customers whose data was collected in GREETING mode or DB lookup.
        The name is stored as _suggested_customer_name — NOT as customer_name — because
        the customer must explicitly confirm or provide their name in the current conversation.
        customer_name is ONLY set via update_booking() when the user explicitly provides it.

        Priority: customer_first_name > customer_name from state.
        """
        # Only suggest if neither confirmed name nor suggestion already set
        if not mode_context.get("customer_name") and not mode_context.get("_suggested_customer_name"):
            state_name = state.get("customer_first_name") or state.get("customer_name")
            if state_name:
                mode_context["_suggested_customer_name"] = str(state_name)

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
    async def _load_service_names() -> list[str]:
        """Load all active service names for ambiguity checks. Never raises."""
        try:
            from sqlalchemy import select as sa_select

            from database.connection import get_async_session
            from database.models import Service

            async with get_async_session() as session:
                result = await session.execute(
                    sa_select(Service.name).where(Service.is_active == True).order_by(Service.name)
                )
                return [row[0] for row in result.all()]
        except Exception as exc:
            logger.warning("_load_service_names: failed: %s", exc)
            return []

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

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
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from agent.config import get_booking_config, ToolChoicePolicy
from agent.modes.base import AgenticLoopResult, BaseModeNode, ToolCallRejection
from agent.prompts.loader import build_layered_messages
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState, transition_mode

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

_HISTORY_LIMIT = 8


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
    # Main entry point
    # ──────────────────────────────────────────────────────────────────────

    async def handle(self, state: ConversationState, intent: Any) -> dict:
        """Process one turn of the booking conversation.

        Flow:
        1. Load flat mode_context dict
        2. Cross-mode customer handoff
        3. Compute tool_choice (forced only on blank-slate turns)
        4. Build messages with dynamic context
        5. Run agentic loop
        6. Build response (F-8 override for completed bookings)
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

        # 1. Confirmation gate: if user just confirmed, unlock book()
        intent_str = str(intent) if intent else ""
        if (
            not mode_context.get("confirmation_shown")
            and mode_context.get("confirmation_summary_sent")
            and "confirm" in intent_str
            and mode_context.get("last_service")
            and mode_context.get("last_stylist")
            and mode_context.get("offered_slots")
        ):
            mode_context["confirmation_shown"] = True

        # 2. Cross-mode customer handoff
        self._resolve_customer_from_state(state, mode_context)

        # 3. tool_choice: config-driven policy (default: never force)
        config = await get_booking_config()
        tool_choice: str | None = None
        if config.tool_choice_policy == ToolChoicePolicy.ALWAYS_FORCE:
            tool_choice = "required"
            logger.info("BookingModeNode: tool_choice='required' (always_force policy)")
        elif config.tool_choice_policy == ToolChoicePolicy.FORCE_AFTER_SERVICE:
            if mode_context.get("last_service") and not mode_context.get("offered_slots"):
                tool_choice = "required"
                logger.info("BookingModeNode: tool_choice='required' (service known, no slots yet)")
        # else: NEVER_FORCE — tool_choice stays None (LLM decides freely)

        # Store for _pre_tool_call / _post_tool_result / _refresh_dynamic_context access
        self._mode_context = mode_context
        self._current_state = state

        # 4. Build messages with dynamic context
        messages = await self._build_messages(state, mode_context)

        # 5. Run agentic loop — LLM calls tools freely
        result = await self._run_agentic_loop(
            messages, tools=self.get_tools(), tool_choice=tool_choice
        )

        # 6. Build response (F-8 override for confirmed bookings)
        response_text = self._build_response(result, mode_context)
        response_text, disclosure_sent = self._maybe_prepend_intro(response_text, state)

        updates: dict[str, Any] = {
            **add_message(state, "assistant", response_text),
            "mode_context": mode_context,
            "last_node": "booking",
            "user_message": None,
        }
        if disclosure_sent:
            updates["ai_disclosure_sent"] = True

        # Propagate customer name to top-level state if discovered
        customer_name = mode_context.get("customer_name")
        if customer_name and not state.get("customer_name"):
            updates["customer_name"] = customer_name

        # F-8: transition to GENERAL after successful booking
        if mode_context.get("_booking_completed"):
            updates["appointment_created"] = True
            updates.update(transition_mode(state, "GENERAL"))
            # Restore mode_context after transition_mode reset
            updates["mode_context"] = mode_context

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
        (a) book(): confirmation gate + slot_index→UUID injection + services injection
        (b) check_availability: clear stale offered_slots from mode_context
        (c) Everything else: pass through unchanged
        """
        mode_context: dict = getattr(self, "_mode_context", {})

        # ── check_availability: clear stale slot state ─────────────────────────
        if tool_name == "check_availability":
            mode_context["offered_slots"] = []
            mode_context.pop("selected_slot", None)
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
                        tool_args["start_time"] = slot.get("start_time") or slot.get("full_datetime")
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

            # Step B: confirmation gate
            if not mode_context.get("confirmation_shown"):
                selected_slot = mode_context.get("selected_slot")
                last_service = mode_context.get("last_service")
                last_stylist = mode_context.get("last_stylist")
                customer_name = mode_context.get("customer_name")

                if (
                    last_service
                    and last_stylist
                    and selected_slot
                    and customer_name
                    and not mode_context.get("confirmation_summary_sent")
                ):
                    summary = self._build_confirmation_summary(mode_context)
                    mode_context["confirmation_summary_sent"] = True
                    return ToolCallRejection(
                        name="book",
                        error_code="CONFIRMATION_NOT_SHOWN",
                        error_message=(
                            "Mostrá este resumen al usuario y esperá su confirmación:\n\n"
                            f"{summary}\n\nNO llames book() hasta recibir confirmación."
                        ),
                    )
                elif mode_context.get("confirmation_summary_sent"):
                    return ToolCallRejection(
                        name="book",
                        error_code="CONFIRMATION_NOT_SHOWN",
                        error_message="Esperá la confirmación del usuario antes de llamar book().",
                    )
                else:
                    missing = self._build_missing_summary(mode_context)
                    return ToolCallRejection(
                        name="book",
                        error_code="CONFIRMATION_NOT_SHOWN",
                        error_message=(
                            "Todavía falta info:\n"
                            f"{missing}\n\n"
                            "Recogé los datos que faltan antes de confirmar."
                        ),
                    )

            # Step C: inject services from mode_context if LLM didn't provide them
            if not tool_args.get("services") and mode_context.get("last_service"):
                tool_args["services"] = [mode_context["last_service"]]

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
        """Update mode_context from tool results before next LLM turn."""
        mode_context: dict = getattr(self, "_mode_context", {})

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
                mode_context["offered_slots"] = slots
                logger.info(
                    "_post_tool_result[check_availability]: stored %d offered_slots",
                    len(slots),
                )
            # Capture service name from args
            service_name = tool_args.get("service_name")
            if service_name and not mode_context.get("last_service"):
                mode_context["last_service"] = service_name
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

        # Auto-detect confirmation summary: when all required data is present
        # and the LLM generated a response, the response IS the summary.
        if (
            not mode_context.get("confirmation_summary_sent")
            and not mode_context.get("_booking_completed")
            and mode_context.get("last_service")
            and mode_context.get("last_stylist")
            and mode_context.get("selected_slot")
            and mode_context.get("customer_name")
            and response_text.strip()
        ):
            mode_context["confirmation_summary_sent"] = True
            logger.info("_build_response: auto-set confirmation_summary_sent (all data complete)")

        return self._sanitize_response(response_text)

    def _build_confirmation_summary(self, mode_context: dict) -> str:
        """Build a short confirmation summary for the user to review before booking."""
        slot = mode_context.get("selected_slot") or {}
        day = slot.get("day_label", "?")
        time_ = slot.get("time", "?")
        stylist = mode_context.get("last_stylist") or "?"
        service = mode_context.get("last_service") or "?"
        return f"Te agendo el *{day} a las {time_}* con *{stylist}* para *{service}*. ¿Lo confirmo?"

    def _render_booking_confirmation(self, mode_context: dict) -> str:
        """Code-render the post-booking confirmation block (F-8 path)."""
        slot = mode_context.get("selected_slot") or {}
        day = slot.get("day_label", "?")
        time_ = slot.get("time", "?")
        stylist = mode_context.get("last_stylist") or "?"
        service = mode_context.get("last_service") or "?"
        return (
            f"✅ ¡Reserva confirmada!\n\n"
            f"📅 {day} a las {time_}\n"
            f"💇 {stylist}\n"
            f"✨ {service}\n\n"
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
            "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
        ]
        min_date = (now + timedelta(days=MINIMUM_DAYS)).date()
        min_day_name = _DAY_NAMES[min_date.weekday()]
        min_date_label = f"{min_day_name} {min_date.day} de {_MONTH_NAMES[min_date.month - 1]}"

        # Booking context XML block
        parts.append("<booking_context>")
        parts.append(
            f"<min_valid_date>{min_date_label} ({min_date.isoformat()})</min_valid_date>"
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

        if mode_context.get("confirmation_shown"):
            parts.append("✅ CONFIRMACIÓN RECIBIDA — puedes llamar book() ahora.")

        parts.append("</booking_context>")

        return "\n".join(parts)

    def _build_collected_summary(self, mode_context: dict) -> str:
        """Build collected_data summary from flat mode_context dict."""
        lines: list[str] = []

        last_service = mode_context.get("last_service")
        if last_service:
            lines.append(f"✅ Servicio: {last_service}")

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

        last_service = mode_context.get("last_service")
        if not last_service:
            missing.append("❌ Servicio: pendiente")

        if last_service and not mode_context.get("last_stylist"):
            missing.append("❌ Estilista: pendiente")

        selected_slot = mode_context.get("selected_slot")
        offered_slots = mode_context.get("offered_slots") or []
        if selected_slot is None:
            if offered_slots:
                missing.append("⏳ Horario: elige uno de los ofrecidos")
            else:
                missing.append("❌ Fecha/hora: pendiente")

        service_known = bool(last_service)
        if (
            not mode_context.get("customer_name")
            and service_known
            and mode_context.get("last_stylist")
            and selected_slot is not None
        ):
            missing.append("❌ Nombre: pendiente")

        return "\n".join(missing)

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


# Backward-compat alias — conversation_flow.py imports BookingMode by name
BookingMode = BookingModeNode

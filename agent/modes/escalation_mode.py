"""
Escalation Mode — v6.0 Mode-Based Architecture.

Handles human handoff when:
- Customer explicitly requests a human agent
- Error count exceeds threshold (auto-escalation)
- AI cannot handle the request

v6.1: Replaced one-shot handoff with a deterministic 3-step intake FSM that
collects issue summary and contact preference before calling the escalation tool.

FSM steps (stored in mode_context["escalation_step"]):
  ACKNOWLEDGE → DESCRIBE → CONTACT → DONE

Sets escalation_triggered=True in state once the tool is called.
Once triggered, stays in ESCALATION for remaining messages.
"""

import logging

from agent.modes.base import BaseModeNode
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)

# ── FSM step constants ──────────────────────────────────────────────────────────
_STEP_ACKNOWLEDGE = "ACKNOWLEDGE"
_STEP_DESCRIBE = "DESCRIBE"
_STEP_CONTACT = "CONTACT"
_STEP_DONE = "DONE"

# ── Urgency signals — UP-1 ──────────────────────────────────────────────────────
_URGENCY_SIGNALS: frozenset[str] = frozenset(
    {
        "urgente",
        "emergencia",
        "ahora mismo",
        "lo antes posible",
        "inmediato",
        "inmediatamente",
        "necesito hablar ya",
        "urgente necesito",
    }
)

# ── Response templates ──────────────────────────────────────────────────────────
_ALREADY_ESCALATED = (
    "Ya he contactado con nuestro equipo. Te atenderán en breve. 🙏 "
    "¿Hay algo más en lo que pueda ayudarte mientras esperas?"
)
_ESCALATION_SUCCESS = (
    "Entendido. He avisado a nuestro equipo y te atenderán personalmente en breve. 🙏"
)
_ESCALATION_FALLBACK = "He notificado a nuestro equipo. Te contactarán en breve. 🙏"

# T3.1: Step 1 — acknowledgement prompt
_ACKNOWLEDGE_REPLY = (
    "Lamento lo que estás pasando. Quiero que esto se resuelva bien. "
    "Cuéntame brevemente qué pasó para derivarlo al equipo con toda la información."
)

# T3.2: Step 2 — contact preference prompt
_CONTACT_PROMPT = "¿Prefieres que te contacten por WhatsApp o por llamada?"

# T3.3: DONE / waiting message
_DONE_WAITING = (
    "Ya avisé al equipo. Te van a contactar en breve. 🙏 "
    "¿Hay algo más que pueda hacer por ti mientras esperas?"
)


def _normalize_contact_preference(text: str) -> str:
    """
    Normalise the user's contact preference text into a canonical value.

    "whatsapp" / "wsp" / "por whats" → "WhatsApp"
    "llamada" / "telefono" / "teléfono" / "llamen" → "llamada"
    anything else → original text (passed through unchanged)
    """
    lower = text.lower()
    if any(k in lower for k in ("whatsapp", "wsp", "whats")):
        return "WhatsApp"
    if any(k in lower for k in ("llamada", "telefono", "teléfono", "llamen", "llamar", "llama")):
        return "llamada"
    return text.strip()


def _is_urgent(text: str) -> bool:
    """Detect high-confidence urgency signals in user text.

    Returns True when any signal in _URGENCY_SIGNALS is a substring of the
    lowercased, stripped message.  Multi-word signals require an exact substring
    match so "ya" alone does NOT trigger this (it is not in the signal set).
    """
    lower = text.lower().strip()
    return any(signal in lower for signal in _URGENCY_SIGNALS)


class EscalationMode(BaseModeNode):
    """
    Mode node for human handoff using a 3-step intake FSM.

    FSM flow:
      1. ACKNOWLEDGE — empathy + ask for issue description
      2. DESCRIBE    — record issue_summary, ask for contact preference
      3. CONTACT     — normalise preference, call escalate_to_human, confirm, DONE
      4. DONE        — return waiting message for all subsequent turns

    State keys used (all in mode_context):
      escalation_step: str          — current FSM step
      issue_summary: str            — user-provided issue description (may be "")
      contact_preference: str       — "WhatsApp" | "llamada" | raw user text
    """

    # NOTE: This mode is a deterministic FSM — it does NOT use the LLM or load prompts.
    # For the intended escalation flow documentation, see agent/prompts/modes/escalation.md.

    @property
    def mode_name(self) -> str:
        return "ESCALATION"

    async def handle(self, state: ConversationState, intent: object) -> dict:
        """
        Handle escalation using the 3-step intake FSM.

        Args:
            state: Current conversation state
            intent: IntentResult from router (not used directly)

        Returns:
            Partial state update dict
        """
        from agent.services.escalation_service import perform_escalation

        conversation_id = state.get("conversation_id", "unknown")
        ctx = dict(state.get("mode_context") or {})

        # T9 — Fast path for technical auto-escalation (error_count >= 3)
        is_technical = (
            state.get("error_count", 0) >= 3 or state.get("escalation_reason") == "technical_error"
        )
        if is_technical and not ctx.get("escalation_step"):
            self.logger.info(
                "EscalationMode: fast-path technical escalation | conversation=%s | error_count=%s",
                conversation_id,
                state.get("error_count", 0),
            )
            result = await perform_escalation(
                conversation_id=str(state.get("conversation_id", "")),
                customer_phone=state.get("customer_phone") or "",
                reason="technical_error",
                source="auto_error",
                is_technical_error=True,
            )
            ctx["escalation_step"] = _STEP_DONE
            final_response, disclosure_sent = self._maybe_prepend_intro(
                result.user_message or _ESCALATION_FALLBACK, state
            )
            updates = {
                **add_message(state, "assistant", final_response),
                "escalation_triggered": True,
                "mode_context": ctx,
                "last_node": "escalation",
                "user_message": None,
            }
            if disclosure_sent:
                updates["ai_disclosure_sent"] = True
            return updates

        # ── Recover last user message ──────────────────────────────────────────
        # Must be done early — needed by urgency fast-path (UP-1) and FSM steps.
        messages = state.get("messages", [])
        user_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_text = msg.get("content", "").strip()
                break

        # UP-1 — Fast path for urgency signals on fresh ESCALATION entry.
        # Guards: no step set yet (fresh entry) AND escalation not already triggered (done).
        if (
            not ctx.get("escalation_step")
            and not state.get("escalation_triggered")
            and _is_urgent(user_text)
        ):
            self.logger.info(
                "EscalationMode: urgency fast-path | conversation=%s | text=%r",
                conversation_id,
                user_text[:60],
            )
            ctx["escalation_step"] = _STEP_CONTACT
            ctx["issue_summary"] = user_text
            final_response, disclosure_sent = self._maybe_prepend_intro(
                _CONTACT_PROMPT,
                state,
            )
            updates = {
                **add_message(state, "assistant", final_response),
                "mode_context": ctx,
                "last_node": "escalation",
                "user_message": None,
            }
            if disclosure_sent:
                updates["ai_disclosure_sent"] = True
            return updates

        # ── Guard: fresh ESCALATION entry — reset FSM step to ACKNOWLEDGE ──────
        # If we just transitioned INTO ESCALATION from another mode, stale
        # mode_context may contain escalation_step=CONTACT from a prior
        # conversation. Force a clean FSM start so we never skip ACKNOWLEDGE.
        escalation_already_done = state.get("escalation_triggered", False)
        previous_mode = state.get("current_mode", "")

        if not escalation_already_done and previous_mode != "ESCALATION":
            step = _STEP_ACKNOWLEDGE
        else:
            step = ctx.get("escalation_step") or _STEP_ACKNOWLEDGE

        # ── Guard: already triggered → waiting message ─────────────────────────
        if state.get("escalation_triggered") or step == _STEP_DONE:
            self.logger.info(
                "EscalationMode: already escalated/DONE | conversation=%s | step=%s",
                conversation_id,
                step,
            )
            final_response, disclosure_sent = self._maybe_prepend_intro(
                _ALREADY_ESCALATED,
                state,
            )
            updates = {
                **add_message(state, "assistant", final_response),
                "last_node": "escalation",
                "user_message": None,
            }
            if disclosure_sent:
                updates["ai_disclosure_sent"] = True
            return updates

        # ── T3.1: ACKNOWLEDGE step ─────────────────────────────────────────────
        if step == _STEP_ACKNOWLEDGE:
            self.logger.info("EscalationMode: ACKNOWLEDGE step | conversation=%s", conversation_id)
            ctx["escalation_step"] = _STEP_DESCRIBE
            final_response, disclosure_sent = self._maybe_prepend_intro(
                _ACKNOWLEDGE_REPLY,
                state,
            )
            updates = {
                **add_message(state, "assistant", final_response),
                "mode_context": ctx,
                "last_node": "escalation",
                "user_message": None,
            }
            if disclosure_sent:
                updates["ai_disclosure_sent"] = True
            return updates

        # ── T3.2: DESCRIBE step ────────────────────────────────────────────────
        if step == _STEP_DESCRIBE:
            self.logger.info(
                "EscalationMode: DESCRIBE step | conversation=%s | user_text=%r",
                conversation_id,
                user_text[:60],
            )
            # Coerce shortcut phrase to empty summary
            if "solo quiero hablar" in user_text.lower() or len(user_text) < 10:
                issue_summary = ""
            else:
                issue_summary = user_text

            ctx["issue_summary"] = issue_summary
            ctx["escalation_step"] = _STEP_CONTACT

            final_response, disclosure_sent = self._maybe_prepend_intro(
                _CONTACT_PROMPT,
                state,
            )
            updates = {
                **add_message(state, "assistant", final_response),
                "mode_context": ctx,
                "last_node": "escalation",
                "user_message": None,
            }
            if disclosure_sent:
                updates["ai_disclosure_sent"] = True
            return updates

        # ── T3.3: CONTACT step ─────────────────────────────────────────────────
        if step == _STEP_CONTACT:
            self.logger.info(
                "EscalationMode: CONTACT step | conversation=%s | user_text=%r",
                conversation_id,
                user_text[:60],
            )
            contact_preference = _normalize_contact_preference(user_text)
            issue_summary = ctx.get("issue_summary", "")
            customer_phone = state.get("customer_phone", "")

            response_text = _ESCALATION_FALLBACK

            try:
                esc_result = await perform_escalation(
                    conversation_id=str(state.get("conversation_id", "")),
                    customer_phone=customer_phone,
                    reason="manual_request",
                    source="manual",
                    is_technical_error=False,
                    issue_summary=issue_summary,
                    contact_preference=contact_preference,
                    conversation_context=state.get("messages", [])[-5:],
                    customer_id=str(state.get("customer_id", ""))
                    if state.get("customer_id")
                    else None,
                )
                response_text = _ESCALATION_SUCCESS
                self.logger.info(
                    "EscalationMode: escalation completed | conversation=%s | "
                    "issue=%r | contact=%s | steps_completed=%s",
                    conversation_id,
                    issue_summary[:60],
                    contact_preference,
                    esc_result.steps_completed,
                )

            except Exception as exc:
                self.logger.error(
                    "EscalationMode: perform_escalation failed | conversation=%s | error=%s",
                    conversation_id,
                    exc,
                )

            ctx["contact_preference"] = contact_preference
            ctx["escalation_step"] = _STEP_DONE

            final_response, disclosure_sent = self._maybe_prepend_intro(response_text, state)
            updates = {
                **add_message(state, "assistant", final_response),
                "escalation_triggered": True,
                "mode_context": ctx,
                "last_node": "escalation",
                "user_message": None,
            }
            if disclosure_sent:
                updates["ai_disclosure_sent"] = True
            return updates

        # ── Fallback: unknown step → treat as DONE ─────────────────────────────
        self.logger.warning(
            "EscalationMode: unknown step=%r | conversation=%s — returning waiting message",
            step,
            conversation_id,
        )
        final_response, disclosure_sent = self._maybe_prepend_intro(_DONE_WAITING, state)
        updates = {
            **add_message(state, "assistant", final_response),
            "last_node": "escalation",
            "user_message": None,
        }
        if disclosure_sent:
            updates["ai_disclosure_sent"] = True
        return updates

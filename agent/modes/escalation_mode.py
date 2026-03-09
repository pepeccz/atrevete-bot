"""
EscalationMode — Human handoff for complex cases (v6.0).

This mode handles the handoff to human agents when:
- Customer explicitly requests a human ("quiero hablar con una persona")
- Auto-escalation due to repeated errors (error_count >= threshold)
- Booking failures that can't be recovered automatically
- Medical consultations or allergy concerns
- Any situation the AI cannot resolve

Once in ESCALATION mode the bot:
1. Calls the escalate_to_human tool (fire-and-forget) to disable the bot
   in Chatwoot and notify the staff.
2. Sends a warm handoff message to the customer.
3. Stays in ESCALATION mode — does NOT auto-transition back to any other mode.
   Human staff will take over the conversation.

The escalation_triggered flag in state is set to True so other components
(graphs, middleware) know the bot should not respond further.

Tools available:
- escalate_to_human: Triggers the Chatwoot bot-disable + staff notification

Architecture note:
    EscalationMode calls the escalate_to_human tool DIRECTLY (not via the LLM
    agent loop). This avoids any LLM hallucinations about why we're escalating.
    The escalation reason is inferred from mode_context or conversation context.
"""

from __future__ import annotations

import logging

from agent.modes.base import BaseModeNode
from agent.routing.intent_router import IntentResult
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState
from agent.tools.escalation_tools import escalate_to_human, ESCALATION_MESSAGES

logger = logging.getLogger(__name__)


# Default escalation reason when none can be inferred
_DEFAULT_ESCALATION_REASON = "manual_request"

# Customer-facing message when already escalated (bot should be silent, but just in case)
_ALREADY_ESCALATED_MESSAGE = (
    "Ya he notificado al equipo. Estarán contigo en breve. "
    "Por favor, espera un momento. 💕"
)


class EscalationMode(BaseModeNode):
    """
    Mode node for the ESCALATION phase — human handoff.

    Calls escalate_to_human tool directly, sets escalation state flags,
    and sends a warm handoff message. Stays in ESCALATION mode permanently
    (no auto-transition).
    """

    @property
    def mode_name(self) -> str:
        return "ESCALATION"

    async def handle(
        self,
        state: ConversationState,
        intent: IntentResult,
    ) -> dict:
        """
        Process a turn in ESCALATION mode.

        On first entry (escalation_triggered=False):
        - Call escalate_to_human tool
        - Set escalation_triggered=True, escalation_reason
        - Send handoff message to customer

        On subsequent turns (escalation_triggered=True):
        - Bot is already escalated, human staff is handling it
        - Return a polite "please wait" message (or be silent)
        - Stay in ESCALATION mode

        Args:
            state: Current ConversationState (read-only).
            intent: Classified intent from IntentRouter.

        Returns:
            Partial state update dict for LangGraph reducers.
        """
        conversation_id = state.get("conversation_id", "unknown")
        customer_phone = state.get("customer_phone")
        escalation_triggered = state.get("escalation_triggered", False)

        logger.info(
            "EscalationMode.handle | conversation_id=%s | already_triggered=%s | intent=%s",
            conversation_id,
            escalation_triggered,
            intent.intent,
        )

        # ── If already escalated, stay silent / brief message ─────────────────
        # Human staff is already handling this. We don't want to confuse the
        # customer with bot messages after escalation.
        if escalation_triggered:
            logger.info(
                "EscalationMode: already escalated, staying silent | "
                "conversation_id=%s",
                conversation_id,
            )
            # Return empty update — no new message, stay in ESCALATION
            # This prevents the bot from interfering with the human handoff.
            return {
                "current_mode": "ESCALATION",
            }

        # ── First entry: trigger escalation ───────────────────────────────────
        # Determine reason from mode_context or intent
        mode_context = state.get("mode_context") or {}
        reason = (
            mode_context.get("escalation_reason")
            or _infer_reason_from_intent(intent)
        )

        logger.info(
            "EscalationMode: triggering escalation | "
            "conversation_id=%s | reason=%s",
            conversation_id,
            reason,
        )

        # Call escalate_to_human tool directly
        # This handles: Chatwoot bot-disable + admin notification (fire-and-forget)
        try:
            tool_result = await escalate_to_human.ainvoke({
                "reason": reason,
                "_conversation_id": conversation_id,
                "_customer_phone": customer_phone or "",
                "_conversation_context": state.get("messages", [])[-5:],
            })

            customer_message = tool_result.get(
                "message",
                ESCALATION_MESSAGES.get(reason, "Te conecto con el equipo ahora mismo.")
            )

            logger.info(
                "EscalationMode: escalation triggered successfully | "
                "conversation_id=%s | reason=%s | escalated=%s",
                conversation_id,
                reason,
                tool_result.get("escalated"),
            )

        except Exception as exc:
            logger.error(
                "EscalationMode: escalate_to_human failed | "
                "conversation_id=%s | error=%s",
                conversation_id,
                exc,
                exc_info=True,
            )
            # Tool failed, but we still set escalation state and send message
            # Staff won't be notified automatically, but at least we tell the customer
            customer_message = (
                "Te conecto con el equipo ahora mismo. "
                "Estarán contigo en breve. 💕"
            )

        # Build state update
        msg_update = add_message(state, "assistant", customer_message)

        return {
            **msg_update,
            "escalation_triggered": True,
            "escalation_reason": reason,
            "current_mode": "ESCALATION",
        }


def _infer_reason_from_intent(intent: IntentResult) -> str:
    """
    Infer an escalation reason from the classified intent.

    Maps IntentResult intents to escalation reason strings that the
    escalate_to_human tool understands.

    Args:
        intent: Classified intent from IntentRouter.

    Returns:
        Escalation reason string compatible with escalate_to_human tool.
    """
    intent_to_reason: dict[str, str] = {
        "escalate": "manual_request",
        "ambiguous": "ambiguity",
        "cancel": "manual_request",
    }

    return intent_to_reason.get(intent.intent, _DEFAULT_ESCALATION_REASON)

"""
Escalation Mode — v6.0 Mode-Based Architecture.

Handles human handoff when:
- Customer explicitly requests a human agent
- Error count exceeds threshold (auto-escalation)
- AI cannot handle the request

Sets escalation_triggered=True in state and calls the escalate_to_human tool.
Once triggered, stays in ESCALATION for remaining messages.
"""

import logging

from agent.modes.base import BaseModeNode
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)

_ALREADY_ESCALATED = (
    "Ya he contactado con nuestro equipo. Te atenderán en breve. 🙏 "
    "¿Hay algo más en lo que pueda ayudarte mientras esperás?"
)
_ESCALATION_SUCCESS = (
    "Entendido, {name}. He avisado a nuestro equipo y te atenderán "
    "personalmente en breve. 🙏"
)
_ESCALATION_FALLBACK = (
    "He notificado a nuestro equipo. Te contactarán en breve. 🙏"
)


class EscalationMode(BaseModeNode):
    """
    Mode node for human handoff.

    Calls escalate_to_human tool and sets escalation_triggered=True in state.
    Subsequent messages in the same conversation will see escalation_triggered=True
    and the router will route them here again, returning a simple "waiting" message.
    """

    @property
    def mode_name(self) -> str:
        return "ESCALATION"

    async def handle(self, state: ConversationState, intent: object) -> dict:
        """
        Handle escalation to human agent.

        Args:
            state: Current conversation state
            intent: IntentResult from router (not used — escalation is unconditional)

        Returns:
            Partial state update dict with escalation_triggered=True
        """
        conversation_id = state.get("conversation_id", "unknown")

        # If already escalated, just confirm and wait
        if state.get("escalation_triggered"):
            self.logger.info(
                "EscalationMode: already escalated | conversation=%s", conversation_id
            )
            return {
                **add_message(state, "assistant", _ALREADY_ESCALATED),
                "last_node": "escalation",
                "user_message": None,
            }

        # Attempt to call escalate_to_human tool
        customer_name = state.get("customer_name") or "Cliente"
        customer_phone = state.get("customer_phone", "")

        response_text = _ESCALATION_FALLBACK

        try:
            from agent.tools.escalation_tools import escalate_to_human

            await escalate_to_human.ainvoke({
                "reason": "customer_request",
                "customer_name": customer_name,
                "customer_phone": customer_phone,
                "conversation_id": conversation_id,
            })
            response_text = _ESCALATION_SUCCESS.format(name=customer_name)
            self.logger.info(
                "EscalationMode: escalation successful | conversation=%s | customer=%s",
                conversation_id,
                customer_name,
            )

        except Exception as exc:
            self.logger.error(
                "EscalationMode: escalate_to_human failed | conversation=%s | error=%s",
                conversation_id,
                exc,
            )
            # Still mark as escalated to avoid infinite retries
            response_text = _ESCALATION_FALLBACK

        return {
            **add_message(state, "assistant", response_text),
            "escalation_triggered": True,
            "last_node": "escalation",
            "user_message": None,
        }

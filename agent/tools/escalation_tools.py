"""escalate tool — trigger human escalation for the conversation.

When the customer wants to speak with a human agent or the bot cannot handle
the request, call this tool to hand off the conversation.
"""

from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.services.escalation_service import EscalationResult, perform_escalation

logger = logging.getLogger(__name__)

# Map tool-level reason strings to escalation_service source values.
# Keys match REASON_TO_NOTIFICATION_TYPE in escalation_service.py.
_REASON_TO_SOURCE: dict[str, str] = {
    "medical_consultation": "medical_consultation",
    "manual_request": "manual_request",
    "ambiguity": "ambiguity",
    "technical_error": "technical_error",
    "policy_rejection": "manual_request",
}
_DEFAULT_SOURCE = "auto_escalation"

# N2 — machine-readable failure payload. The marker prevents the LLM from
# claiming a handoff that was never recorded (V6 C2 phantom escalation).
# Spanish instructions are directed at the LLM, like tool error vocabulary.
_ESCALATION_FAILED_PAYLOAD = (
    "status=ESCALATION_FAILED — la escalación NO quedó registrada y ningún humano "
    "fue avisado. NO digas al cliente que ya le has pasado con el equipo. "
    "Discúlpate brevemente, dile que avisaremos al equipo por otro medio y sigue "
    "atendiendo la conversación. NO le pidas que llame al salón."
)


@tool
async def escalate(
    reason: str,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """Escalate the conversation to a human agent.

    conversation_id and customer_phone are injected from session state;
    they are not tool arguments.

    Args:
        reason: Brief reason for escalation (e.g., 'medical_consultation', 'manual_request').

    Call this tool when the customer explicitly asks to speak with a person,
    or when the bot cannot handle the request adequately.

    ONLY if this tool returns a success message: stop responding to booking
    requests for this conversation — a human will take over.
    If it returns ESCALATION_FAILED: the handoff did NOT happen. Never claim
    a human was notified. Apologize, tell the customer the team will be
    notified by other means, and keep assisting. Do NOT tell the customer
    to call the salon.
    """
    _state = state or {}
    conversation_id = _state.get("conversation_id")
    customer_phone = _state.get("customer_phone") or ""

    if not conversation_id:
        logger.error(
            "escalate.state.missing_conversation_id",
            extra={"tool_name": "escalate"},
        )
        return "Estado de conversación incompleto. No puedo transferir la conversación."

    source = _REASON_TO_SOURCE.get(reason, _DEFAULT_SOURCE)

    try:
        result: EscalationResult = await perform_escalation(
            conversation_id=conversation_id,
            customer_phone=customer_phone,
            reason=reason,
            source=source,
        )
        if result.success:
            return result.user_message or "Te transfiero con el equipo. Un momento por favor."
        failed = ", ".join(result.steps_failed) if result.steps_failed else "unknown step"
        logger.error(
            "escalate: escalation failed at step(s) %s",
            failed,
            extra={"tool_name": "escalate", "conversation_id": conversation_id},
        )
        return _ESCALATION_FAILED_PAYLOAD
    except Exception as exc:
        logger.error(
            "escalate tool error: %s",
            exc,
            exc_info=True,
            extra={"tool_name": "escalate", "conversation_id": conversation_id},
        )
        return _ESCALATION_FAILED_PAYLOAD

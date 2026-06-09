"""escalate tool — trigger human escalation for the conversation.

When the customer wants to speak with a human agent or the bot cannot handle
the request, call this tool to hand off the conversation.
"""

from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.services.escalation_service import perform_escalation

logger = logging.getLogger(__name__)


@tool
async def escalate(
    reason: str,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """Escalate the conversation to a human agent.

    conversation_id and customer_phone are injected from session state;
    they are not tool arguments.

    Args:
        reason: Brief reason for escalation (e.g., 'customer request', 'complex inquiry').

    Call this tool when the customer explicitly asks to speak with a person,
    or when the bot cannot handle the request adequately.
    After calling this tool, stop responding to booking requests for this conversation.
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

    if not customer_phone:
        logger.error(
            "escalate.state.missing_customer_phone",
            extra={"tool_name": "escalate"},
        )
        return "Estado de conversación incompleto. No puedo transferir la conversación."

    try:
        result = await perform_escalation(
            conversation_id=conversation_id,
            customer_phone=customer_phone,
            reason=reason,
        )
        if result.get("success"):
            return (
                "He transferido tu conversación a un agente humano. "
                "En breve alguien del equipo de Atrévete se pondrá en contacto contigo. 💕"
            )
        return (
            "Estoy intentando transferirte a un agente. "
            "Por favor, espera un momento o llámanos directamente."
        )
    except Exception as exc:
        logger.error("escalate tool error: %s", exc, exc_info=True)
        return (
            "No pude realizar la transferencia en este momento. "
            "Por favor, llámanos directamente o inténtalo de nuevo."
        )

"""escalate tool — trigger human escalation for the conversation.

When the customer wants to speak with a human agent or the bot cannot handle
the request, call this tool to hand off the conversation.
"""

from __future__ import annotations

import logging

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent.services.escalation_service import perform_escalation

logger = logging.getLogger(__name__)


class EscalateSchema(BaseModel):
    """Input schema for escalate tool."""

    reason: str = Field(
        description="Brief reason for escalation (e.g., 'customer request', 'complex inquiry')."
    )
    conversation_id: str = Field(description="Conversation ID to escalate.")
    customer_phone: str = Field(description="Customer phone number (E.164 format).")


@tool(args_schema=EscalateSchema)
async def escalate(
    reason: str,
    conversation_id: str,
    customer_phone: str,
) -> str:
    """Escalate the conversation to a human agent.

    Call this tool when the customer explicitly asks to speak with a person,
    or when the bot cannot handle the request adequately.
    After calling this tool, stop responding to booking requests for this conversation.
    """
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

"""
Human escalation tools for conversational agent.

Handles escalation to human support when AI cannot handle the conversation.
This tool integrates with the escalation service to:
1. Disable bot in Chatwoot (atencion_automatica = false)
2. Create notification in admin panel
3. (Future) Trigger webhooks to external services

The tool receives context injection from NonBookingHandler which provides
conversation_id, customer_phone, and recent messages for full context.
"""

import asyncio
import logging
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EscalateToHumanSchema(BaseModel):
    """Schema for escalate_to_human tool parameters."""

    reason: str = Field(
        description="Reason for escalation (medical_consultation, ambiguity, manual_request, technical_error)"
    )


# Customer-facing messages for each escalation reason
ESCALATION_MESSAGES: dict[str, str] = {
    "medical_consultation": "Por temas de salud, es mejor que hables directamente con el equipo. Te conecto ahora mismo.",
    "ambiguity": "Quiero asegurarme de ayudarte bien. Te conecto con el equipo para que te asistan mejor.",
    "delay_notice": "Entendido. Notificare al equipo de inmediato para ajustar tu cita si es posible.",
    "manual_request": "Claro! Te conecto con el equipo ahora mismo.",
    "technical_error": "Disculpa, he tenido un problema al procesar tu mensaje. He notificado al equipo y te atenderan lo antes posible.",
    "auto_escalation": "Disculpa, estoy teniendo dificultades tecnicas. Te paso con un companero humano que te ayudara enseguida.",
}


@tool(args_schema=EscalateToHumanSchema)
async def escalate_to_human(
    reason: str,
    # These parameters are injected by NonBookingHandler, not passed by LLM
    _conversation_id: str | None = None,
    _customer_phone: str | None = None,
    _conversation_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Escalate conversation to human support.

    Triggers escalation workflow which:
    1. Disables bot in Chatwoot (atencion_automatica = false)
    2. Creates notification in admin panel
    3. (Future) Sends webhooks to Slack/Teams

    Args:
        reason: Escalation reason for logging and routing
        _conversation_id: Injected by handler (Chatwoot conversation ID)
        _customer_phone: Injected by handler
        _conversation_context: Injected by handler (recent messages)

    Returns:
        Dict with:
        - escalated: Boolean (always True)
        - reason: The escalation reason
        - message: Message to show customer

    Example:
        >>> result = await escalate_to_human("medical_consultation")
        >>> result["escalated"]
        True
    """
    logger.warning(
        f"Escalating conversation to human | reason={reason} | "
        f"conversation_id={_conversation_id} | customer_phone={_customer_phone}"
    )

    # Trigger full escalation workflow if context is available
    if _conversation_id and _customer_phone:
        # Import here to avoid circular imports
        from agent.services.escalation_service import trigger_escalation

        # Fire-and-forget: create task but don't await (non-blocking)
        asyncio.create_task(
            trigger_escalation(
                reason=reason,
                conversation_id=_conversation_id,
                customer_phone=_customer_phone,
                conversation_context=_conversation_context,
            )
        )
        logger.info(
            f"Escalation triggered (fire-and-forget) | conversation_id={_conversation_id}"
        )
    else:
        logger.warning(
            f"Escalation triggered without context | "
            f"conversation_id={_conversation_id} | customer_phone={_customer_phone} | "
            "Bot will NOT be disabled in Chatwoot (missing conversation_id)"
        )

    customer_message = ESCALATION_MESSAGES.get(
        reason, "Te conecto con el equipo ahora mismo."
    )

    return {
        "escalated": True,
        "reason": reason,
        "message": customer_message,
    }

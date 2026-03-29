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
    # These parameters are injected by the mode node, not passed by LLM
    _conversation_id: str | None = None,
    _customer_phone: str | None = None,
    _conversation_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Escalate conversation to human support.

    Delegates to perform_escalation() which handles:
    1. Disabling bot in Chatwoot (atencion_automatica = false)
    2. Adding conversation labels
    3. Adding a private note with context
    4. Assigning to team (if configured)
    5. Recording in database

    Args:
        reason: Escalation reason for logging and routing
        _conversation_id: Injected by mode node (Chatwoot conversation ID)
        _customer_phone: Injected by mode node
        _conversation_context: Injected by mode node (recent messages)

    Returns:
        Dict with escalation result fields.

    Example:
        >>> result = await escalate_to_human("medical_consultation")
        >>> result["escalated"]
        True
    """
    from agent.services.escalation_service import perform_escalation

    if not _conversation_id or not _customer_phone:
        logger.warning(
            "[escalate_to_human] Missing conversation_id or customer_phone — escalation incomplete"
        )
        return {"escalated": True, "error": "missing_context"}

    result = await perform_escalation(
        conversation_id=_conversation_id,
        customer_phone=_customer_phone,
        reason=reason,
        source="fallback",
        conversation_context=_conversation_context,
    )
    return {
        "escalated": result.success,
        "duplicate_prevented": result.duplicate_prevented,
        "steps_completed": result.steps_completed,
    }

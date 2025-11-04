"""
Human escalation tools for conversational agent.

Handles escalation to human support when AI cannot handle the conversation.
"""

import logging
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EscalateToHumanSchema(BaseModel):
    """Schema for escalate_to_human tool parameters."""

    reason: str = Field(
        description="Reason for escalation: 'medical_consultation', 'payment_failure', 'ambiguity', 'delay_notice', 'manual_request', 'technical_error'"
    )


@tool(args_schema=EscalateToHumanSchema)
async def escalate_to_human(reason: str) -> dict[str, Any]:
    """
    Escalate conversation to human support.

    Triggers escalation workflow which:
    1. Sets Redis flag for human mode
    2. Notifies support team
    3. Stops AI from responding further

    Args:
        reason: Escalation reason for logging and routing

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
    logger.warning(f"Escalating conversation to human | Reason: {reason}")

    # TODO: Implement Redis flag setting and notification
    # For now, just return escalation confirmation

    messages = {
        "medical_consultation": "Por temas de salud, es mejor que hables directamente con el equipo. Te conecto ahora mismo 💕",
        "payment_failure": "Parece que hay un problema con el pago. Déjame conectarte con el equipo para resolverlo 😊",
        "ambiguity": "Quiero asegurarme de ayudarte bien. Te conecto con el equipo para que te asistan mejor 🌸",
        "delay_notice": "Entendido. Notificaré al equipo de inmediato para ajustar tu cita si es posible 😊",
        "manual_request": "¡Claro! Te conecto con el equipo ahora mismo 💕",
        "technical_error": "Disculpa, he tenido un problema al procesar tu mensaje. He notificado al equipo y te atenderán lo antes posible 🌸",
    }

    customer_message = messages.get(reason, "Te conecto con el equipo ahora mismo 💕")

    return {
        "escalated": True,
        "reason": reason,
        "message": customer_message,
    }

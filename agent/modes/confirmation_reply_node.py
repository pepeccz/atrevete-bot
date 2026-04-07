"""Confirmation reply node for appointment confirmation template responses."""

import logging
from typing import Any
from uuid import UUID

from agent.fsm.models import IntentType
from agent.services.confirmation_service import handle_confirmation_response
from agent.state.helpers import add_message, get_last_user_message
from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)


def _extract_response_text(result: Any, intent: str) -> tuple[str, dict[str, Any]]:
    confirm_fallback = "¡Perfecto! Tu cita ha sido confirmada. ¡Te esperamos!"
    decline_fallback = "Entendido, hemos anotado tu respuesta. Si necesitás algo más, avisame."
    default_fallback = confirm_fallback if intent == "confirm" else decline_fallback

    if isinstance(result, str):
        return result, {}

    if isinstance(result, dict):
        for key in ("message", "response", "text", "response_text", "error_message"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value, dict(result.get("state_updates") or {})
        return default_fallback, dict(result.get("state_updates") or {})

    state_updates = dict(getattr(result, "state_updates", None) or {})
    for attr in ("message", "response", "text", "response_text", "error_message"):
        value = getattr(result, attr, None)
        if isinstance(value, str) and value.strip():
            return value, state_updates

    return default_fallback, state_updates


async def confirmation_reply_node(state: ConversationState) -> dict[str, Any]:
    mode_context = state.get("mode_context", {}) or {}
    appointment_id = state.get("pending_confirmation_appointment_id") or mode_context.get(
        "pending_confirmation_appointment_id"
    )
    intent = str(mode_context.get("last_intent") or "cancel")
    customer_id = state.get("customer_id")
    conversation_id = state.get("conversation_id", "unknown")

    logger.info(
        "confirmation_reply_node | conversation_id=%s | intent=%s | appointment_id=%s",
        conversation_id,
        intent,
        appointment_id,
    )

    intent_type = IntentType.DECLINE_APPOINTMENT
    if intent == "confirm":
        intent_type = IntentType.CONFIRM_APPOINTMENT

    try:
        if customer_id:
            UUID(str(customer_id))
        if appointment_id:
            UUID(str(appointment_id))

        result = await handle_confirmation_response(
            customer_phone=state.get("customer_phone", ""),
            intent_type=intent_type,
            message_text=get_last_user_message(state),
        )
        response_text, state_updates = _extract_response_text(result, intent)
    except Exception as exc:
        logger.exception(
            "confirmation_reply_node error | conversation_id=%s | error=%s",
            conversation_id,
            exc,
        )
        response_text = "Hubo un problema procesando tu respuesta. Por favor, intentá de nuevo o escribí 'ayuda'."
        state_updates = {}

    return {
        **add_message(state, "assistant", response_text),
        **state_updates,
        "pending_confirmation_appointment_id": None,
        "last_node": "confirmation_reply",
        "user_message": None,
    }

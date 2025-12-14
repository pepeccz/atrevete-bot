"""
Escalation Service - Handles human escalation workflow.

This service is responsible for:
1. Disabling bot in Chatwoot (atencion_automatica = false)
2. Creating notifications in admin panel
3. Preparing webhook payloads for future integrations (Slack, Teams, etc.)

The escalation system ensures conversations that the AI cannot handle are
properly transferred to human agents with full context preserved.
"""

import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select

from database.connection import get_async_session
from database.models import Customer, Notification, NotificationType
from shared.chatwoot_client import ChatwootClient

logger = logging.getLogger(__name__)

# Map escalation reasons to notification types
REASON_TO_NOTIFICATION_TYPE: dict[str, NotificationType] = {
    "medical_consultation": NotificationType.ESCALATION_MEDICAL,
    "ambiguity": NotificationType.ESCALATION_AMBIGUITY,
    "manual_request": NotificationType.ESCALATION_MANUAL,
    "technical_error": NotificationType.ESCALATION_TECHNICAL,
    "auto_escalation": NotificationType.ESCALATION_AUTO,
    # Default fallback for unknown reasons
    "default": NotificationType.ESCALATION_MANUAL,
}

# Human-readable titles for each escalation type
ESCALATION_TITLES: dict[NotificationType, str] = {
    NotificationType.ESCALATION_MEDICAL: "Escalacion: Consulta medica",
    NotificationType.ESCALATION_AMBIGUITY: "Escalacion: Solicitud ambigua",
    NotificationType.ESCALATION_MANUAL: "Escalacion: Solicitud de usuario",
    NotificationType.ESCALATION_TECHNICAL: "Escalacion: Error tecnico",
    NotificationType.ESCALATION_AUTO: "Escalacion automatica: Errores consecutivos",
}

# Human-readable reason descriptions
REASON_DESCRIPTIONS: dict[str, str] = {
    "medical_consultation": "Consulta relacionada con salud (alergias, embarazo, medicamentos)",
    "ambiguity": "Solicitud ambigua tras multiples intentos de clarificacion",
    "manual_request": "Cliente solicito hablar con persona humana",
    "technical_error": "Error tecnico en el procesamiento",
    "auto_escalation": "Multiples errores consecutivos detectados",
}


async def disable_bot_in_chatwoot(conversation_id: str) -> bool:
    """
    Disable bot for a Chatwoot conversation.

    Sets atencion_automatica = false so the webhook will ignore future messages
    until a human agent manually re-enables it.

    Args:
        conversation_id: Chatwoot conversation ID (numeric string)

    Returns:
        True if successful, False if failed (logged, not raised)
    """
    try:
        client = ChatwootClient()
        await client.update_conversation_attributes(
            conversation_id=int(conversation_id),
            attributes={"atencion_automatica": False},
        )
        logger.info(
            f"Bot disabled for conversation | conversation_id={conversation_id}"
        )
        return True
    except Exception as e:
        logger.error(
            f"Failed to disable bot in Chatwoot | conversation_id={conversation_id} | "
            f"error={str(e)}",
            exc_info=True,
        )
        return False


async def create_escalation_notification(
    reason: str,
    customer_phone: str,
    conversation_id: str,
    conversation_context: list[dict[str, Any]] | None = None,
) -> UUID | None:
    """
    Create escalation notification in admin panel database.

    Args:
        reason: Escalation reason (maps to NotificationType)
        customer_phone: Customer phone number
        conversation_id: Chatwoot conversation ID
        conversation_context: Last 3-5 messages for context (optional)

    Returns:
        Notification UUID if created, None if failed
    """
    notification_type = REASON_TO_NOTIFICATION_TYPE.get(
        reason, REASON_TO_NOTIFICATION_TYPE["default"]
    )

    title = ESCALATION_TITLES.get(notification_type, "Escalacion")
    reason_description = REASON_DESCRIPTIONS.get(reason, reason)

    try:
        async with get_async_session() as session:
            # Get customer name for message
            customer_name = "Cliente"
            if customer_phone:
                stmt = select(Customer).where(Customer.phone == customer_phone)
                result = await session.execute(stmt)
                customer = result.scalar_one_or_none()
                if customer:
                    customer_name = f"{customer.first_name} {customer.last_name or ''}".strip()

            # Build message with context
            context_preview = ""
            if conversation_context:
                # Get last 3 messages for context
                recent = conversation_context[-3:]
                context_lines = []
                for msg in recent:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    # Truncate long messages
                    if len(content) > 100:
                        content = content[:100] + "..."
                    context_lines.append(f"- {role}: {content}")
                context_preview = "\n\nContexto reciente:\n" + "\n".join(context_lines)

            message = (
                f"{customer_name} ({customer_phone}) necesita atencion humana.\n"
                f"Motivo: {reason_description}\n"
                f"Conversacion ID: {conversation_id}"
                f"{context_preview}"
            )

            notification = Notification(
                type=notification_type,
                title=title,
                message=message,
                entity_type="conversation",
                entity_id=None,  # No entity_id for escalations (could link to customer in future)
            )

            session.add(notification)
            await session.commit()
            await session.refresh(notification)

            logger.info(
                f"Escalation notification created | id={notification.id} | "
                f"type={notification_type.value} | customer_phone={customer_phone}"
            )

            return notification.id

    except Exception as e:
        logger.error(
            f"Failed to create escalation notification | reason={reason} | "
            f"error={str(e)}",
            exc_info=True,
        )
        return None


async def trigger_escalation(
    reason: str,
    conversation_id: str,
    customer_phone: str,
    conversation_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Execute full escalation workflow.

    This is the main entry point for escalation. It:
    1. Disables bot in Chatwoot (prevents bot from responding)
    2. Creates notification in database (appears in admin panel)
    3. (Future) Triggers webhooks to external services (Slack, Teams, etc.)

    All operations are fire-and-forget with timeouts to not block the response.

    Args:
        reason: Escalation reason (e.g., "manual_request", "technical_error")
        conversation_id: Chatwoot conversation ID
        customer_phone: Customer phone number
        conversation_context: Recent messages for context

    Returns:
        Dict with escalation result:
        {
            "chatwoot_disabled": bool,
            "notification_id": UUID | None,
            "webhooks_triggered": list[str]  # Future: ["slack", "teams"]
        }
    """
    logger.warning(
        f"Triggering escalation | reason={reason} | "
        f"conversation_id={conversation_id} | customer_phone={customer_phone}"
    )

    result: dict[str, Any] = {
        "chatwoot_disabled": False,
        "notification_id": None,
        "webhooks_triggered": [],
    }

    # 1. Disable bot in Chatwoot (with timeout)
    try:
        chatwoot_result = await asyncio.wait_for(
            disable_bot_in_chatwoot(conversation_id),
            timeout=5.0,
        )
        result["chatwoot_disabled"] = chatwoot_result
    except asyncio.TimeoutError:
        logger.warning(
            f"Chatwoot disable timed out | conversation_id={conversation_id}"
        )
    except Exception as e:
        logger.error(
            f"Chatwoot disable failed | conversation_id={conversation_id} | error={e}"
        )

    # 2. Create notification (with timeout)
    try:
        notification_id = await asyncio.wait_for(
            create_escalation_notification(
                reason=reason,
                customer_phone=customer_phone,
                conversation_id=conversation_id,
                conversation_context=conversation_context,
            ),
            timeout=5.0,
        )
        result["notification_id"] = notification_id
    except asyncio.TimeoutError:
        logger.warning(
            f"Notification creation timed out | conversation_id={conversation_id}"
        )
    except Exception as e:
        logger.error(
            f"Notification creation failed | conversation_id={conversation_id} | error={e}"
        )

    # 3. (Future) Trigger webhooks - placeholder for extensibility
    # When webhook_service is fully implemented:
    # try:
    #     from agent.services.webhook_service import trigger_all_webhooks
    #     webhook_payload = {
    #         "type": "escalation",
    #         "reason": reason,
    #         "conversation_id": conversation_id,
    #         "customer_phone": customer_phone,
    #         "timestamp": datetime.now(UTC).isoformat(),
    #     }
    #     webhook_results = await trigger_all_webhooks(webhook_payload)
    #     result["webhooks_triggered"] = [name for name, success in webhook_results.items() if success]
    # except Exception as e:
    #     logger.error(f"Webhook trigger failed | error={e}")

    logger.info(
        f"Escalation completed | conversation_id={conversation_id} | "
        f"chatwoot_disabled={result['chatwoot_disabled']} | "
        f"notification_created={result['notification_id'] is not None}"
    )

    return result

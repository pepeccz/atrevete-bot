"""Chatwoot webhook route handler."""

import hmac
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from api.models.chatwoot_webhook import (
    ChatwootMessageEvent,
    ChatwootWebhookPayload,
)
from shared.config import get_settings
from shared.redis_client import publish_to_channel

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chatwoot/{token}")
async def receive_chatwoot_webhook(
    request: Request,
    token: str,
) -> JSONResponse:
    """
    Receive and process Chatwoot webhook events.

    Authentication: Token in URL path must match CHATWOOT_WEBHOOK_TOKEN.
    Configure in Chatwoot: https://your-domain.com/webhook/chatwoot/{your_secret_token}

    Only processes 'message_created' events with 'incoming' message type.
    Valid messages are enqueued to Redis 'incoming_messages' channel.

    Args:
        request: FastAPI request object
        token: Secret token from URL path

    Returns:
        JSONResponse with 200 OK status

    Raises:
        HTTPException 401: Invalid or missing token
    """
    settings = get_settings()

    # Validate token using timing-safe comparison
    if not hmac.compare_digest(token, settings.CHATWOOT_WEBHOOK_TOKEN):
        logger.warning(
            f"Invalid Chatwoot webhook token attempted from IP: {request.client.host}"
        )
        raise HTTPException(status_code=401, detail="Invalid token")

    # Read and parse webhook payload
    body = await request.body()
    payload = ChatwootWebhookPayload.model_validate_json(body)

    # Filter: Only process conversations with messages
    if not payload.messages:
        logger.debug(f"Ignoring conversation {payload.id} with no messages")
        return JSONResponse(status_code=200, content={"status": "ignored"})

    # Get the last (most recent) message from the array
    last_message = payload.messages[-1]

    # Filter: Only process incoming messages (message_type == 0)
    if last_message.message_type != 0:
        logger.debug(
            f"Ignoring non-incoming message: message_type={last_message.message_type}"
        )
        return JSONResponse(status_code=200, content={"status": "ignored"})

    # Ensure phone number exists
    if not last_message.sender.phone_number:
        logger.warning(f"Message {last_message.id} has no phone number, ignoring")
        return JSONResponse(status_code=200, content={"status": "ignored"})

    # Create message event for Redis
    message_event = ChatwootMessageEvent(
        conversation_id=str(payload.id),
        customer_phone=last_message.sender.phone_number,  # Will be normalized to E.164
        message_text=last_message.content or "",
        customer_name=last_message.sender.name,
    )

    # Publish to Redis channel
    await publish_to_channel(
        "incoming_messages",
        message_event.model_dump(),
    )

    logger.info(
        f"Chatwoot message enqueued: conversation_id={message_event.conversation_id}, "
        f"phone={message_event.customer_phone}"
    )

    return JSONResponse(status_code=200, content={"status": "received"})

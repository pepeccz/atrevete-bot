"""Stripe webhook route handler."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from api.middleware.signature_validation import validate_stripe_signature
from api.models.stripe_webhook import StripePaymentEvent
from shared.redis_client import publish_to_channel

logger = logging.getLogger(__name__)

router = APIRouter()

# Stripe event types we process
PROCESSED_EVENT_TYPES = {"checkout.session.completed", "charge.refunded"}


@router.post("/stripe")
async def receive_stripe_webhook(
    request: Request,
    event: dict[str, Any] = Depends(validate_stripe_signature),
) -> JSONResponse:
    """
    Receive and process Stripe webhook events.

    Only processes 'checkout.session.completed' and 'charge.refunded' events.
    Valid payment events are enqueued to Redis 'payment_events' channel.

    Args:
        request: FastAPI request object
        event: Validated Stripe event dict (from signature validation)

    Returns:
        JSONResponse with 200 OK status

    Raises:
        HTTPException: 400 if appointment_id is missing from metadata
    """
    event_type = event.get("type")

    # Filter: Only process specific event types
    if event_type not in PROCESSED_EVENT_TYPES:
        logger.debug(f"Ignoring Stripe event type: {event_type}")
        return JSONResponse(status_code=200, content={"status": "ignored"})

    # Extract event data
    event_data = event.get("data", {}).get("object", {})
    metadata = event_data.get("metadata", {})

    # Validate appointment_id exists in metadata
    appointment_id = metadata.get("appointment_id")
    if not appointment_id:
        logger.error(
            f"Missing appointment_id in Stripe event {event.get('id')}: type={event_type}"
        )
        raise HTTPException(
            status_code=400, detail="Missing appointment_id in metadata"
        )

    # Extract payment ID
    stripe_payment_id = event_data.get("id")
    if not stripe_payment_id:
        logger.error(f"Missing payment ID in Stripe event {event.get('id')}")
        raise HTTPException(status_code=400, detail="Missing payment ID")

    # Create payment event for Redis
    payment_event = StripePaymentEvent(
        appointment_id=appointment_id,
        stripe_payment_id=stripe_payment_id,
        event_type=event_type,
    )

    # Publish to Redis channel
    await publish_to_channel(
        "payment_events",
        payment_event.model_dump(),
    )

    logger.info(
        f"Stripe event enqueued: type={event_type}, "
        f"appointment_id={appointment_id}, "
        f"payment_id={stripe_payment_id}"
    )

    return JSONResponse(status_code=200, content={"status": "received"})

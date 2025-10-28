"""Middleware for webhook signature validation."""

import logging
from typing import Any, cast

import stripe
from fastapi import HTTPException, Request
from stripe import SignatureVerificationError

from shared.config import get_settings

logger = logging.getLogger(__name__)


async def validate_stripe_signature(request: Request) -> dict[str, Any]:
    """
    Validate Stripe webhook signature and parse event.

    Args:
        request: FastAPI request object

    Returns:
        Parsed Stripe event object

    Raises:
        HTTPException: 401 if signature verification fails
    """
    settings = get_settings()
    body = await request.body()

    # Extract signature from header
    signature_header: str | None = request.headers.get("Stripe-Signature")

    if not signature_header:
        logger.warning("Stripe webhook received without signature header")
        raise HTTPException(status_code=401, detail="Invalid Stripe signature")

    try:
        # Verify signature and construct event
        event = stripe.Webhook.construct_event(
            payload=body,
            sig_header=signature_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
        logger.debug(f"Stripe signature validated: event_type={event['type']}")
        return cast(dict[str, Any], event)

    except SignatureVerificationError as e:
        logger.warning(f"Stripe signature verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid Stripe signature") from e

    except Exception as e:
        logger.error(f"Unexpected error validating Stripe signature: {e}")
        raise HTTPException(status_code=401, detail="Invalid Stripe signature") from e

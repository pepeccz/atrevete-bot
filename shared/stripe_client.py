"""
Stripe API client for payment processing.

This module provides reusable functions for interacting with Stripe's Payment Links API.
"""

import stripe
from typing import Any
from decimal import Decimal
import logging

from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize Stripe with API key (use secret key for server-side operations)
stripe.api_key = settings.STRIPE_SECRET_KEY


async def create_payment_link_for_appointment(
    appointment_id: str,
    customer_id: str,
    conversation_id: str,
    amount_euros: Decimal,
    description: str,
    customer_email: str | None = None,
    customer_name: str | None = None,
) -> dict[str, Any]:
    """
    Create a Stripe Payment Link for an appointment booking.

    Uses ad-hoc product creation with price_data to avoid creating permanent products
    for every booking combination.

    Args:
        appointment_id: UUID of the provisional appointment
        customer_id: UUID of the customer
        conversation_id: Chatwoot conversation ID for tracking
        amount_euros: Amount to charge in euros (Decimal)
        description: Description of the services (e.g., "Mechas, Corte - Atrévete")
        customer_email: Optional customer email for pre-filling
        customer_name: Optional customer name for pre-filling

    Returns:
        dict with:
            - url: str - The payment link URL to share with customer
            - id: str - The payment link ID (for deactivation)
            - expires_at: int - Unix timestamp when link expires

    Raises:
        stripe.error.StripeError: If Stripe API call fails
    """
    try:
        # Convert euros to cents (Stripe uses smallest currency unit)
        amount_cents = int(amount_euros * 100)

        logger.info(
            f"Creating Stripe Payment Link for appointment {appointment_id}, "
            f"amount: {amount_euros}€ ({amount_cents} cents)"
        )

        # Build metadata for tracking
        metadata = {
            "appointment_id": str(appointment_id),
            "customer_id": str(customer_id),
            "conversation_id": str(conversation_id),
            "source": "atrevete_whatsapp_bot",
        }

        # Build line items with ad-hoc price
        line_items = [
            {
                "price_data": {
                    "currency": "eur",
                    "unit_amount": amount_cents,
                    "product_data": {
                        "name": "Anticipo Cita - Atrévete Peluquería",
                        "description": description,
                    },
                },
                "quantity": 1,
            }
        ]

        # Build payment link parameters
        payment_link_params: dict[str, Any] = {
            "line_items": line_items,
            "metadata": metadata,
            "after_completion": {
                "type": "hosted_confirmation",
                "hosted_confirmation": {
                    "custom_message": (
                        "¡Pago confirmado! Tu cita ha sido reservada. "
                        "Recibirás la confirmación por WhatsApp en breve."
                    )
                },
            },
            # Prevent multiple submissions
            "allow_promotion_codes": False,
            # Collect billing address for card payments
            "billing_address_collection": "auto",
        }

        # Add customer email if provided (pre-fill checkout)
        if customer_email:
            payment_link_params["customer_creation"] = "if_required"
            # Note: Payment Links don't support pre-filling email directly
            # The email is filled when customer enters checkout

        # Create the payment link
        payment_link = stripe.PaymentLink.create(**payment_link_params)

        logger.info(
            f"Payment Link created successfully: {payment_link.id}, "
            f"URL: {payment_link.url}"
        )

        return {
            "url": payment_link.url,
            "id": payment_link.id,
            "expires_at": None,  # Payment Links don't expire by default
            "metadata": metadata,
        }

    except stripe.error.StripeError as e:
        logger.error(
            f"Stripe API error creating payment link for appointment {appointment_id}: "
            f"{str(e)}"
        )
        raise


async def deactivate_payment_link(payment_link_id: str) -> bool:
    """
    Deactivate a Stripe Payment Link.

    Used when a provisional appointment expires without payment.

    Args:
        payment_link_id: The Stripe Payment Link ID

    Returns:
        bool: True if deactivated successfully, False otherwise

    Raises:
        stripe.error.StripeError: If Stripe API call fails
    """
    try:
        logger.info(f"Deactivating Stripe Payment Link: {payment_link_id}")

        stripe.PaymentLink.modify(
            payment_link_id,
            active=False,
        )

        logger.info(f"Payment Link deactivated successfully: {payment_link_id}")
        return True

    except stripe.error.InvalidRequestError as e:
        # Link might already be inactive or not exist
        logger.warning(
            f"Could not deactivate payment link {payment_link_id}: {str(e)}"
        )
        return False

    except stripe.error.StripeError as e:
        logger.error(
            f"Stripe API error deactivating payment link {payment_link_id}: {str(e)}"
        )
        raise


async def get_payment_link_status(payment_link_id: str) -> dict[str, Any]:
    """
    Retrieve the status of a Stripe Payment Link.

    Args:
        payment_link_id: The Stripe Payment Link ID

    Returns:
        dict with:
            - active: bool - Whether the link is still active
            - url: str - The payment link URL
            - metadata: dict - The metadata associated with the link

    Raises:
        stripe.error.StripeError: If Stripe API call fails
    """
    try:
        payment_link = stripe.PaymentLink.retrieve(payment_link_id)

        return {
            "active": payment_link.active,
            "url": payment_link.url,
            "metadata": payment_link.metadata,
        }

    except stripe.error.StripeError as e:
        logger.error(
            f"Stripe API error retrieving payment link {payment_link_id}: {str(e)}"
        )
        raise

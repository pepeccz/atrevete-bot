"""Stripe payment integration service for SEPA Direct Debit."""

import asyncio
import logging
from uuid import uuid4

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import SystemSetting
from shared.config import get_settings

logger = logging.getLogger(__name__)


class StripeService:
    """
    Stripe API wrapper for SEPA Direct Debit payments.

    All Stripe SDK calls are synchronous — wrapped with run_in_executor
    to avoid blocking the event loop.
    """

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.STRIPE_SECRET_KEY
        stripe.api_key = self.api_key

    def is_configured(self) -> bool:
        """True if Stripe API key is set."""
        return bool(self.api_key)

    async def create_setup_session(
        self, session: AsyncSession, success_url: str, cancel_url: str
    ) -> dict:
        """
        Create Stripe Checkout Session in setup mode for SEPA mandate.

        Returns: {"checkout_url": str, "session_id": str}
        """
        # Get or create Stripe customer
        customer_id = await self._get_setting(session, "stripe_customer_id")

        loop = asyncio.get_event_loop()

        if not customer_id:
            customer = await loop.run_in_executor(
                None,
                lambda: stripe.Customer.create(
                    name="Atrévete Peluquería",
                    metadata={"source": "atrevete-bot"},
                ),
            )
            customer_id = customer.id
            await self._set_setting(
                session, "stripe_customer_id", customer_id, "Stripe Customer ID"
            )

        checkout_session = await loop.run_in_executor(
            None,
            lambda: stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["sepa_debit"],
                mode="setup",
                success_url=success_url,
                cancel_url=cancel_url,
            ),
        )

        return {
            "checkout_url": checkout_session.url,
            "session_id": checkout_session.id,
        }

    async def handle_setup_completed(self, session: AsyncSession, event_data: dict) -> None:
        """
        Handle checkout.session.completed event.
        Stores payment method and customer info in system_settings.
        """
        setup_intent_id = event_data.get("setup_intent")
        customer_id = event_data.get("customer")

        if not setup_intent_id:
            logger.warning("No setup_intent in checkout.session.completed event")
            return

        loop = asyncio.get_event_loop()

        # Retrieve setup intent to get payment method
        setup_intent = await loop.run_in_executor(
            None,
            lambda: stripe.SetupIntent.retrieve(setup_intent_id),
        )

        payment_method_id = setup_intent.payment_method

        # Get payment method details (IBAN last4)
        pm = await loop.run_in_executor(
            None,
            lambda: stripe.PaymentMethod.retrieve(payment_method_id),
        )
        last4 = pm.sepa_debit.last4 if pm.sepa_debit else "****"

        # Store in system_settings
        await self._set_setting(
            session, "stripe_customer_id", customer_id, "Stripe Customer ID"
        )
        await self._set_setting(
            session, "stripe_payment_method_id", payment_method_id, "Stripe Payment Method ID"
        )
        await self._set_setting(
            session, "stripe_payment_method_last4", last4, "IBAN últimos 4 dígitos"
        )

        await session.commit()
        logger.info(f"SEPA mandate configured: customer={customer_id}, PM=...{last4}")

    async def create_sepa_charge(
        self,
        amount_cents: int,
        customer_id: str,
        payment_method_id: str,
        invoice_number: str,
    ) -> stripe.PaymentIntent:
        """
        Create and confirm a SEPA PaymentIntent.

        Idempotency key: invoice_{invoice_number} (prevents double-charge).
        """
        loop = asyncio.get_event_loop()

        return await loop.run_in_executor(
            None,
            lambda: stripe.PaymentIntent.create(
                amount=amount_cents,
                currency="eur",
                customer=customer_id,
                payment_method=payment_method_id,
                payment_method_types=["sepa_debit"],
                confirm=True,
                mandate_data={"customer_acceptance": {"type": "online"}},
                idempotency_key=f"invoice_{invoice_number}",
                metadata={"invoice_number": invoice_number},
            ),
        )

    async def cancel_payment_intent(self, payment_intent_id: str) -> bool:
        """Cancel a PaymentIntent if it's in a cancellable state. Returns True if cancelled."""
        loop = asyncio.get_event_loop()
        try:
            pi = await loop.run_in_executor(
                None,
                lambda: stripe.PaymentIntent.retrieve(payment_intent_id),
            )
            if pi.status in ("requires_payment_method", "requires_confirmation", "processing"):
                await loop.run_in_executor(
                    None,
                    lambda: stripe.PaymentIntent.cancel(payment_intent_id),
                )
                logger.info(f"Cancelled PaymentIntent {payment_intent_id}")
                return True
            else:
                logger.info(
                    f"PaymentIntent {payment_intent_id} in terminal state: {pi.status}, "
                    f"cannot cancel"
                )
                return False
        except stripe.error.StripeError as e:
            logger.warning(f"Failed to cancel PaymentIntent {payment_intent_id}: {e}")
            return False

    def verify_webhook(self, payload: bytes, sig_header: str) -> stripe.Event:
        """
        Verify Stripe webhook signature.

        Raises stripe.error.SignatureVerificationError if invalid.
        """
        settings = get_settings()
        return stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )

    async def get_sepa_status(self, session: AsyncSession) -> dict:
        """
        Get current SEPA configuration status.

        Returns: {"configured": bool, "customer_id": str|None,
                  "payment_method_last4": str|None, ...}
        """
        customer_id = await self._get_setting(session, "stripe_customer_id")
        pm_id = await self._get_setting(session, "stripe_payment_method_id")
        last4 = await self._get_setting(session, "stripe_payment_method_last4")

        result = {
            "configured": bool(customer_id and pm_id),
            "customer_id": customer_id,
            "payment_method_last4": last4,
            "payment_method_status": None,
            "sepa_mandate_status": None,
        }

        # Query Stripe for live status if configured
        if pm_id and self.is_configured():
            try:
                loop = asyncio.get_event_loop()
                pm = await loop.run_in_executor(
                    None,
                    lambda: stripe.PaymentMethod.retrieve(pm_id),
                )
                result["payment_method_status"] = "active"
                if pm.sepa_debit and hasattr(pm.sepa_debit, "mandate"):
                    # If we can determine mandate status
                    result["sepa_mandate_status"] = "active"
                else:
                    result["sepa_mandate_status"] = "active"  # Default when PM exists
            except stripe.error.StripeError as e:
                logger.warning(f"Failed to query Stripe PM status: {e}")
                result["payment_method_status"] = "unknown"

        return result

    async def _get_setting(self, session: AsyncSession, key: str) -> str | None:
        """Read a billing setting from system_settings."""
        result = await session.execute(
            select(SystemSetting).where(
                SystemSetting.key == key,
                SystemSetting.category == "billing",
            )
        )
        setting = result.scalar_one_or_none()
        if setting and setting.value:
            return setting.value.get("value")
        return None

    async def _set_setting(
        self, session: AsyncSession, key: str, value: str, label: str
    ) -> None:
        """Write a billing setting to system_settings (upsert)."""
        result = await session.execute(
            select(SystemSetting).where(
                SystemSetting.key == key,
                SystemSetting.category == "billing",
            )
        )
        setting = result.scalar_one_or_none()

        if setting:
            setting.value = {"value": value}
        else:
            setting = SystemSetting(
                id=uuid4(),
                category="billing",
                key=key,
                value={"value": value},
                value_type="string",
                default_value={"value": ""},
                label=label,
                requires_restart=False,
                display_order=0,
            )
            session.add(setting)

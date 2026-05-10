"""Stripe payment integration service for SEPA Direct Debit."""

import asyncio
import logging
from enum import Enum
from uuid import uuid4

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import SystemSetting
from shared.config import get_settings

logger = logging.getLogger(__name__)


class SepaMandateStatus(str, Enum):
    """SEPA Direct Debit mandate state — surfaces to admin UI via /api/billing/stripe/status."""

    ACTIVE = "active"                  # Mandate is valid, charges can succeed
    INACTIVE = "inactive"              # Mandate revoked or expired
    REQUIRES_ACTION = "requires_action"  # User intervention needed (maps from Stripe 'pending')
    UNKNOWN = "unknown"                # Stripe call failed or status indeterminate


# Stripe mandate.status → SepaMandateStatus mapping
_STRIPE_MANDATE_STATUS_MAP: dict[str, SepaMandateStatus] = {
    "active": SepaMandateStatus.ACTIVE,
    "inactive": SepaMandateStatus.INACTIVE,
    "pending": SepaMandateStatus.REQUIRES_ACTION,
}


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
        setup_intent_id = event_data.setup_intent
        customer_id = event_data.customer

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

    async def create_invoice(
        self,
        customer_id: str,
        invoice_number: str,
        tax_rate_id: str,
        metadata: dict | None = None,
    ) -> stripe.Invoice:
        """Create a draft Stripe Invoice with SEPA auto-charge."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: stripe.Invoice.create(
                customer=customer_id,
                collection_method="charge_automatically",
                auto_advance=True,
                number=invoice_number,
                default_tax_rates=[tax_rate_id] if tax_rate_id else [],
                payment_settings={"payment_method_types": ["sepa_debit"]},
                metadata=metadata or {},
            ),
        )

    async def add_invoice_line_item(
        self,
        customer_id: str,
        invoice_id: str,
        amount_cents: int,
        description: str,
    ) -> stripe.InvoiceItem:
        """Add a line item to a draft invoice. Amount in cents."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: stripe.InvoiceItem.create(
                customer=customer_id,
                invoice=invoice_id,
                amount=amount_cents,
                currency="eur",
                description=description,
            ),
        )

    async def finalize_invoice(self, invoice_id: str) -> stripe.Invoice:
        """Finalize invoice — triggers auto-charge via SEPA. Returns finalized invoice with pdf URL."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: stripe.Invoice.finalize_invoice(invoice_id),
        )

    async def void_stripe_invoice(self, invoice_id: str) -> stripe.Invoice:
        """Void a Stripe invoice. Only works on open/uncollected invoices."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: stripe.Invoice.void_invoice(invoice_id),
        )

    async def ensure_tax_id(
        self, customer_id: str, tax_type: str, tax_value: str
    ) -> bool:
        """Attach tax ID to customer if not already present. Returns True if created."""
        loop = asyncio.get_event_loop()

        # List existing tax IDs
        existing = await loop.run_in_executor(
            None,
            lambda: stripe.Customer.list_tax_ids(customer_id, limit=10),
        )

        for tid in existing.data:
            if tid.type == tax_type and tid.value == tax_value:
                logger.info(f"Tax ID {tax_type}={tax_value} already on customer {customer_id}")
                return False

        await loop.run_in_executor(
            None,
            lambda: stripe.Customer.create_tax_id(customer_id, type=tax_type, value=tax_value),
        )
        logger.info(f"Attached tax ID {tax_type}={tax_value} to customer {customer_id}")
        return True

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

                # Resolve SEPA mandate status via real Stripe Mandate.retrieve
                mandate_id = getattr(pm.sepa_debit, "mandate", None) if pm.sepa_debit else None
                if mandate_id:
                    try:
                        mandate = await loop.run_in_executor(
                            None,
                            lambda: stripe.Mandate.retrieve(mandate_id),
                        )
                        stripe_status = getattr(mandate, "status", None)
                        mapped = _STRIPE_MANDATE_STATUS_MAP.get(stripe_status, SepaMandateStatus.UNKNOWN)
                        if stripe_status and stripe_status not in _STRIPE_MANDATE_STATUS_MAP:
                            logger.warning(
                                f"Unrecognised Stripe mandate status {stripe_status!r} for "
                                f"mandate {mandate_id} — defaulting to UNKNOWN"
                            )
                        result["sepa_mandate_status"] = mapped.value
                    except stripe.error.StripeError as e:
                        logger.warning(f"Failed to retrieve Stripe mandate {mandate_id}: {e}")
                        result["sepa_mandate_status"] = SepaMandateStatus.UNKNOWN.value
                else:
                    # PM exists but no mandate attached yet
                    result["sepa_mandate_status"] = SepaMandateStatus.UNKNOWN.value

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

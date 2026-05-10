"""Core billing service — invoice generation, voiding, estimates, and overdue checks."""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentStatus,
    TokenUsage,
)
from shared.config import get_settings
from api.services.pdf_service import PdfService
from api.services.stripe_service import StripeService
from shared.email_service import EmailService

logger = logging.getLogger(__name__)

# Spanish month names
MONTH_NAMES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}


class BillingService:
    """Stateless billing service — all state flows through function parameters."""

    def __init__(self):
        self.pdf_service = PdfService()
        self.stripe_service = StripeService()
        self.email_service = EmailService()

    async def generate_invoice(
        self, session: AsyncSession, year: int, month: int
    ) -> Invoice:
        """
        Generate invoice for a given billing period using Stripe Invoicing.

        Steps:
        1. Validate period
        2. Guard against duplicates
        3. Query token usage
        4. Calculate amounts (subtotal + IVA = gross)
        5. Generate sequential invoice number (FOR UPDATE lock)
        6. Create Invoice DB row (draft)
        7. Create Stripe Invoice + line items + finalize (triggers SEPA charge)
        8. Create Payment DB row
        9. Commit and return

        Error handling:
        - Stripe failure → invoice saved in DB without stripe refs
        - Email failure → silent (log only)
        """
        settings = get_settings()
        now = datetime.utcnow()

        # 1. Validate period — reject future months
        if year > now.year or (year == now.year and month > now.month):
            raise HTTPException(
                status_code=422,
                detail=f"No se puede generar factura para un periodo futuro ({year}-{month:02d}).",
            )

        # 2. Guard — no active (non-void) invoice for this period
        existing = await session.execute(
            select(Invoice).where(
                Invoice.year == year,
                Invoice.month == month,
                Invoice.status != InvoiceStatus.VOID,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Ya existe una factura para {year}-{month:02d}. "
                    f"Anúlala primero para regenerar."
                ),
            )

        # 3. Query TokenUsage for this period
        token_result = await session.execute(
            select(TokenUsage).where(
                TokenUsage.year == year,
                TokenUsage.month == month,
            )
        )
        token_usage = token_result.scalar_one_or_none()

        # 4. Calculate amounts
        maintenance = settings.MONTHLY_MAINTENANCE_EUR

        if token_usage:
            input_cost = (
                Decimal(token_usage.input_tokens) / Decimal("1000000") * settings.TOKEN_PRICE_INPUT
            )
            output_cost = (
                Decimal(token_usage.output_tokens)
                / Decimal("1000000")
                * settings.TOKEN_PRICE_OUTPUT
            )
            token_amount = (input_cost + output_cost).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            token_amount = Decimal("0.00")

        # Subtotal (base imponible) = maintenance + tokens
        subtotal = (maintenance + token_amount).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        # IVA 21%
        tax_rate_pct = Decimal("21.00")
        tax_amount = (subtotal * tax_rate_pct / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        # Gross (total con IVA)
        gross = subtotal + tax_amount

        # 5. Generate invoice number (with FOR UPDATE lock)
        invoice_number = await self._next_invoice_number(session, year, month)

        # Due date: 30 days from issue
        issued_at = datetime.utcnow()
        due_date = (issued_at + timedelta(days=30)).date()

        # 6. Create Invoice DB row (draft)
        invoice = Invoice(
            invoice_number=invoice_number,
            year=year,
            month=month,
            maintenance_amount_eur=maintenance,
            token_amount_eur=token_amount,
            total_amount_eur=subtotal,  # net amount (backward compat)
            subtotal_eur=subtotal,
            tax_rate_pct=tax_rate_pct,
            tax_amount_eur=tax_amount,
            gross_amount_eur=gross,
            status=InvoiceStatus.DRAFT,
            due_date=due_date,
            issued_at=issued_at,
            token_usage_id=token_usage.id if token_usage else None,
        )

        notes_parts = []
        if not token_usage:
            notes_parts.append("Sin consumo de tokens en este periodo.")

        session.add(invoice)
        await session.flush()  # Get ID without committing

        # 7. Create Stripe Invoice + line items + finalize
        try:
            sepa_status = await self.stripe_service.get_sepa_status(session)
            if sepa_status["configured"]:
                customer_id = sepa_status["customer_id"]
                tax_rate_id = settings.STRIPE_TAX_RATE_ID
                period_label = f"{MONTH_NAMES.get(month, '')} {year}"

                # Create draft Stripe Invoice
                stripe_inv = await self.stripe_service.create_invoice(
                    customer_id=customer_id,
                    invoice_number=invoice_number,
                    tax_rate_id=tax_rate_id,
                    metadata={
                        "source": "atrevete-bot",
                        "period": f"{year}-{month:02d}",
                        "period_label": period_label,
                    },
                )

                # Add line items
                maintenance_cents = int(maintenance * 100)
                await self.stripe_service.add_invoice_line_item(
                    customer_id=customer_id,
                    invoice_id=stripe_inv.id,
                    amount_cents=maintenance_cents,
                    description=f"Mantenimiento mensual — {period_label}",
                )

                if token_amount > 0:
                    token_cents = int(token_amount * 100)
                    token_desc = f"Consumo IA — {period_label}"
                    if token_usage:
                        token_desc += (
                            f" ({token_usage.input_tokens:,} input"
                            f" + {token_usage.output_tokens:,} output tokens)"
                        )
                    await self.stripe_service.add_invoice_line_item(
                        customer_id=customer_id,
                        invoice_id=stripe_inv.id,
                        amount_cents=token_cents,
                        description=token_desc,
                    )

                # Finalize → triggers auto-charge via SEPA
                finalized = await self.stripe_service.finalize_invoice(stripe_inv.id)

                # Store Stripe refs
                invoice.stripe_invoice_id = finalized.id
                invoice.invoice_pdf_url = finalized.invoice_pdf
                invoice.status = InvoiceStatus.ISSUED

                # Extract the PaymentIntent created by Stripe
                pi_id = finalized.payment_intent
                if pi_id:
                    invoice.stripe_payment_intent_id = pi_id
                    payment = Payment(
                        invoice_id=invoice.id,
                        stripe_payment_intent_id=pi_id,
                        amount_eur=gross,
                        status=PaymentStatus.PROCESSING,
                        payment_method="sepa_debit",
                    )
                    session.add(payment)

                logger.info(
                    f"Stripe invoice created for {invoice_number}: "
                    f"stripe_id={finalized.id}, PI={pi_id}"
                )
            else:
                invoice.status = InvoiceStatus.ISSUED
                logger.info(
                    f"SEPA not configured, skipping Stripe for {invoice_number}"
                )
        except Exception as e:
            logger.error(f"Stripe invoice failed for {invoice_number}: {e}")
            notes_parts.append(f"Error en factura Stripe: {e}")
            invoice.status = InvoiceStatus.ISSUED

        # Set notes if any
        if notes_parts:
            invoice.notes = " | ".join(notes_parts)

        # 8a. Generate local PDF and persist path before commit
        try:
            local_pdf_path = await self.pdf_service.ensure_pdf_exists(invoice)
            invoice.pdf_path = str(local_pdf_path)
        except Exception as e:
            logger.warning(
                f"PDF generation failed for {invoice.invoice_number}: {e}. "
                f"Email will be sent without attachment."
            )
            invoice.pdf_path = None

        # 8. Commit (includes pdf_path set above)
        await session.commit()
        await session.refresh(invoice)

        # 9. Send email notification (fire-and-forget)
        try:
            period_label = f"{MONTH_NAMES.get(month, '')} {year}"
            operator_email = settings.OPERATOR_EMAIL
            if operator_email:
                await self.email_service.send_invoice_email(
                    to=operator_email,
                    invoice_number=invoice_number,
                    period_label=period_label,
                    total_eur=gross,
                    pdf_path=invoice.pdf_path,
                )
        except Exception as e:
            logger.warning(f"Email notification failed for {invoice_number}: {e}")

        logger.info(
            f"Invoice generated: {invoice_number} | "
            f"subtotal={subtotal}€ IVA={tax_amount}€ gross={gross}€"
        )

        return invoice

    async def void_invoice(
        self, session: AsyncSession, invoice_id: UUID, reason: str | None = None
    ) -> Invoice:
        """Void an invoice. Cancel Stripe PaymentIntent if pending."""
        result = await session.execute(select(Invoice).where(Invoice.id == invoice_id))
        invoice = result.scalar_one_or_none()

        if not invoice:
            raise HTTPException(status_code=404, detail="Factura no encontrada.")

        if invoice.status not in (
            InvoiceStatus.DRAFT,
            InvoiceStatus.ISSUED,
            InvoiceStatus.OVERDUE,
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Solo se permite anular facturas con estado 'draft', 'issued' o 'overdue'. "
                    f"Estado actual: '{invoice.status.value}'."
                ),
            )

        # Void on Stripe — new invoices use Stripe Invoice, legacy uses PI cancel
        if invoice.stripe_invoice_id:
            try:
                await self.stripe_service.void_stripe_invoice(invoice.stripe_invoice_id)
            except Exception as e:
                logger.warning(
                    f"Failed to void Stripe invoice for {invoice.invoice_number}: {e}"
                )
        elif invoice.stripe_payment_intent_id:
            try:
                await self.stripe_service.cancel_payment_intent(
                    invoice.stripe_payment_intent_id
                )
            except Exception as e:
                logger.warning(
                    f"Failed to cancel Stripe PI for {invoice.invoice_number}: {e}"
                )

        invoice.status = InvoiceStatus.VOID
        if reason:
            existing_notes = invoice.notes or ""
            invoice.notes = f"{existing_notes} | Anulada: {reason}".strip(" |")

        await session.commit()
        await session.refresh(invoice)

        logger.info(f"Invoice voided: {invoice.invoice_number} (reason: {reason})")
        return invoice

    async def get_current_estimate(self, session: AsyncSession) -> dict:
        """Get current month's running total estimate."""
        settings = get_settings()
        now = datetime.utcnow()
        year, month = now.year, now.month

        # Query current month token usage
        result = await session.execute(
            select(TokenUsage).where(
                TokenUsage.year == year,
                TokenUsage.month == month,
            )
        )
        token_usage = result.scalar_one_or_none()

        maintenance = settings.MONTHLY_MAINTENANCE_EUR

        input_tokens = 0
        output_tokens = 0
        total_requests = 0

        if token_usage:
            input_tokens = token_usage.input_tokens
            output_tokens = token_usage.output_tokens
            total_requests = token_usage.total_requests
            input_cost = (
                Decimal(input_tokens) / Decimal("1000000") * settings.TOKEN_PRICE_INPUT
            )
            output_cost = (
                Decimal(output_tokens) / Decimal("1000000") * settings.TOKEN_PRICE_OUTPUT
            )
            token_amount = (input_cost + output_cost).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            token_amount = Decimal("0.00")

        subtotal = (maintenance + token_amount).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        tax_amount = (subtotal * Decimal("21") / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        gross = subtotal + tax_amount

        # Calculate next invoice date (1st of next month)
        if month == 12:
            next_year, next_month = year + 1, 1
        else:
            next_year, next_month = year, month + 1

        period_label = f"{MONTH_NAMES.get(month, '')} {year}"

        return {
            "year": year,
            "month": month,
            "period_label": period_label,
            "estimate_date": now.isoformat(),
            "next_invoice_date": f"{next_year}-{next_month:02d}-01",
            "maintenance_amount_eur": str(maintenance),
            "token_amount_eur": str(token_amount),
            "total_amount_eur": str(subtotal),
            "subtotal_eur": str(subtotal),
            "tax_amount_eur": str(tax_amount),
            "gross_amount_eur": str(gross),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_requests": total_requests,
        }

    async def check_overdue(self, session: AsyncSession) -> int:
        """
        Transition issued invoices past due_date to overdue.

        Returns count of newly overdue invoices.
        """
        today = date.today()

        result = await session.execute(
            select(Invoice).where(
                Invoice.status == InvoiceStatus.ISSUED,
                Invoice.due_date < today,
            )
        )
        overdue_invoices = result.scalars().all()

        count = 0
        for invoice in overdue_invoices:
            invoice.status = InvoiceStatus.OVERDUE
            count += 1
            logger.info(f"Invoice {invoice.invoice_number} marked as overdue")

        if count > 0:
            await session.commit()

        return count

    async def _next_invoice_number(
        self, session: AsyncSession, year: int, month: int
    ) -> str:
        """Generate next invoice number: ATR-YYYY-MM-SEQ with row-level lock."""
        # Lock existing rows for this period to prevent concurrent sequence gaps
        result = await session.execute(
            select(Invoice.id)
            .where(Invoice.year == year, Invoice.month == month)
            .with_for_update()
        )
        count = len(result.all())
        seq = count + 1
        return f"ATR-{year}-{month:02d}-{seq:03d}"

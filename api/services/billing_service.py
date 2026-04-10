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
        Generate invoice for a given billing period.

        Steps:
        1. Validate period
        2. Guard against duplicates
        3. Query token usage
        4. Calculate amounts
        5. Create Invoice (draft)
        6. Generate PDF
        7. Issue invoice
        8. Charge via Stripe (if configured)
        9. Send email notification
        10. Commit and return

        Error handling by layer:
        - PDF failure → invoice saved, pdf_path=None
        - Stripe failure → invoice saved, no Payment row
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

        total = (maintenance + token_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # 5. Generate invoice number
        invoice_number = await self._next_invoice_number(session, year, month)

        # Due date: 30 days from now (or from issue date)
        issued_at = datetime.utcnow()
        due_date = (issued_at + timedelta(days=30)).date()

        # 6. Create Invoice (status=draft)
        invoice = Invoice(
            invoice_number=invoice_number,
            year=year,
            month=month,
            maintenance_amount_eur=maintenance,
            token_amount_eur=token_amount,
            total_amount_eur=total,
            status=InvoiceStatus.DRAFT,
            due_date=due_date,
            token_usage_id=token_usage.id if token_usage else None,
        )

        notes_parts = []
        if not token_usage:
            notes_parts.append("Sin consumo de tokens en este periodo.")

        session.add(invoice)
        await session.flush()  # Get ID without committing

        # 7. Generate PDF (fire-and-forget on failure)
        try:
            # Set issued_at temporarily for PDF rendering
            invoice.issued_at = issued_at
            pdf_path = await self.pdf_service.generate_invoice_pdf(invoice)
            invoice.pdf_path = pdf_path
        except Exception as e:
            logger.error(f"PDF generation failed for {invoice_number}: {e}")
            notes_parts.append(f"Error generando PDF: {e}")

        # 8. Mark as issued
        invoice.status = InvoiceStatus.ISSUED
        invoice.issued_at = issued_at

        # 9. Charge via Stripe (if SEPA mandate is configured)
        try:
            sepa_status = await self.stripe_service.get_sepa_status(session)
            if sepa_status["configured"]:
                customer_id = sepa_status["customer_id"]
                pm_id = await self.stripe_service._get_setting(
                    session, "stripe_payment_method_id"
                )

                amount_cents = int(total * 100)
                pi = await self.stripe_service.create_sepa_charge(
                    amount_cents=amount_cents,
                    customer_id=customer_id,
                    payment_method_id=pm_id,
                    invoice_number=invoice_number,
                )

                invoice.stripe_payment_intent_id = pi.id

                payment = Payment(
                    invoice_id=invoice.id,
                    stripe_payment_intent_id=pi.id,
                    amount_eur=total,
                    status=PaymentStatus.PROCESSING,
                    payment_method="sepa_debit",
                )
                session.add(payment)
                logger.info(f"SEPA charge initiated for {invoice_number}: PI={pi.id}")
            else:
                logger.info(
                    f"SEPA not configured, skipping automatic charge for {invoice_number}"
                )
        except Exception as e:
            logger.error(f"Stripe charge failed for {invoice_number}: {e}")
            notes_parts.append(f"Error en cobro Stripe: {e}")

        # Set notes if any
        if notes_parts:
            invoice.notes = " | ".join(notes_parts)

        # 10. Commit
        await session.commit()
        await session.refresh(invoice)

        # 11. Send email notification (fire-and-forget)
        try:
            period_label = f"{MONTH_NAMES.get(month, '')} {year}"
            operator_email = settings.OPERATOR_EMAIL
            if operator_email and invoice.pdf_path:
                await self.email_service.send_invoice_email(
                    to=operator_email,
                    invoice_number=invoice_number,
                    period_label=period_label,
                    total_eur=total,
                    pdf_path=invoice.pdf_path,
                )
        except Exception as e:
            logger.warning(f"Email notification failed for {invoice_number}: {e}")

        logger.info(
            f"Invoice generated: {invoice_number} | "
            f"maintenance={maintenance}€ tokens={token_amount}€ total={total}€"
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

        # Cancel Stripe PI if exists
        if invoice.stripe_payment_intent_id:
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

        total = (maintenance + token_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

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
            "total_amount_eur": str(total),
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
        """Generate next invoice number: ATR-YYYY-MM-SEQ."""
        result = await session.execute(
            select(func.count()).select_from(Invoice).where(
                Invoice.year == year,
                Invoice.month == month,
            )
        )
        count = result.scalar() or 0
        seq = count + 1
        return f"ATR-{year}-{month:02d}-{seq:03d}"

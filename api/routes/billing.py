"""
Atrévete Bot — Billing API routes.

Provides endpoints for invoice management, cost estimates, and Stripe/SEPA configuration.
All endpoints except the Stripe webhook are protected by admin authentication.
"""

import asyncio
import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload
from starlette.responses import RedirectResponse, StreamingResponse

from api.dependencies.auth import require_permission
from api.models.billing_schemas import (
    CurrentEstimateResponse,
    GenerateInvoiceRequest,
    InvoiceListResponse,
    InvoiceResponse,
    SetupSessionResponse,
    StatusUpdateRequest,
    StripeStatusResponse,
)
from api.services.billing_service import BillingService
from api.services.pdf_service import PdfService
from api.services.stripe_service import StripeService
from database.connection import get_async_session
from database.models import AdminUser, Invoice, InvoiceStatus, Payment, PaymentStatus
from shared.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])


# =============================================================================
# Endpoints — Invoices
# =============================================================================


@router.get(
    "/invoices",
    response_model=InvoiceListResponse,
    summary="List invoices",
    description="Returns paginated list of invoices, newest first. Admin only.",
)
async def list_invoices(
    current_user: Annotated[AdminUser, Depends(require_permission("system:settings"))],
    page: int = 1,
    page_size: int = 12,
) -> InvoiceListResponse:
    """Get paginated invoice list, ordered by billing period descending."""
    page = max(1, page)
    page_size = min(max(1, page_size), 50)
    offset = (page - 1) * page_size

    async with get_async_session() as session:
        # Total count
        count_result = await session.execute(select(func.count()).select_from(Invoice))
        total = count_result.scalar() or 0

        # Paginated results
        result = await session.execute(
            select(Invoice)
            .options(selectinload(Invoice.payments))
            .order_by(desc(Invoice.year), desc(Invoice.month))
            .offset(offset)
            .limit(page_size)
        )
        invoices = result.scalars().all()

        return InvoiceListResponse(
            invoices=[InvoiceResponse.from_invoice(inv) for inv in invoices],
            total=total,
            page=page,
            page_size=page_size,
        )


@router.get(
    "/invoices/{invoice_id}",
    response_model=InvoiceResponse,
    summary="Get invoice detail",
    description="Returns a single invoice with full payment history. Admin only.",
)
async def get_invoice(
    invoice_id: UUID,
    current_user: Annotated[AdminUser, Depends(require_permission("system:settings"))],
) -> InvoiceResponse:
    """Get a single invoice by ID including associated payments."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Invoice).options(selectinload(Invoice.payments)).where(Invoice.id == invoice_id)
        )
        invoice = result.scalar_one_or_none()

        if not invoice:
            raise HTTPException(status_code=404, detail="Factura no encontrada.")

        return InvoiceResponse.from_invoice(invoice)


@router.get(
    "/invoices/{invoice_id}/pdf",
    summary="Download invoice PDF",
    description="Stream the invoice PDF. Regenerates if file is missing on disk. Admin only.",
)
async def download_invoice_pdf(
    invoice_id: UUID,
    current_user: Annotated[AdminUser, Depends(require_permission("system:settings"))],
):
    """Download the PDF for a given invoice. Redirects to Stripe URL if available."""
    async with get_async_session() as session:
        result = await session.execute(select(Invoice).where(Invoice.id == invoice_id))
        invoice = result.scalar_one_or_none()

        if not invoice:
            raise HTTPException(status_code=404, detail="Factura no encontrada.")

        # Prefer Stripe-hosted PDF URL
        if invoice.invoice_pdf_url:
            return RedirectResponse(invoice.invoice_pdf_url, status_code=302)

        # Fall back to locally stored PDF
        if invoice.pdf_path:
            pdf_service = PdfService()
            try:
                pdf_path = await pdf_service.ensure_pdf_exists(invoice)
            except Exception as e:
                logger.error(f"PDF generation failed for invoice {invoice_id}: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="No se pudo generar el PDF de la factura.",
                )

            # Persist the (possibly regenerated) path so subsequent downloads skip weasyprint
            if str(pdf_path) != (invoice.pdf_path or ""):
                try:
                    invoice.pdf_path = str(pdf_path)
                    await session.commit()
                except Exception as e:
                    logger.error(
                        f"Failed to persist pdf_path for invoice {invoice_id}: {e}. "
                        f"Returning PDF to client anyway."
                    )

            pdf_bytes = await asyncio.get_event_loop().run_in_executor(
                None, Path(pdf_path).read_bytes
            )

            filename = f"{invoice.invoice_number}.pdf"
            return StreamingResponse(
                io.BytesIO(pdf_bytes),
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )

        raise HTTPException(status_code=404, detail="PDF no disponible para esta factura.")


@router.post(
    "/invoices/generate",
    response_model=InvoiceResponse,
    status_code=201,
    summary="Generate invoice",
    description="Manually trigger invoice generation for a given period. Admin only.",
)
async def generate_invoice(
    request_body: GenerateInvoiceRequest,
    current_user: Annotated[AdminUser, Depends(require_permission("system:settings"))],
) -> InvoiceResponse:
    """Generate an invoice for the specified year/month. Returns 409 if already exists."""
    async with get_async_session() as session:
        billing_service = BillingService()
        invoice = await billing_service.generate_invoice(
            session, request_body.year, request_body.month
        )
        # Reload with payments relationship after commit
        result = await session.execute(
            select(Invoice).options(selectinload(Invoice.payments)).where(Invoice.id == invoice.id)
        )
        invoice = result.scalar_one()
        return InvoiceResponse.from_invoice(invoice)


@router.get(
    "/current-estimate",
    response_model=CurrentEstimateResponse,
    summary="Current month estimate",
    description="Returns a running cost estimate for the current billing period. Admin only.",
)
async def get_current_estimate(
    current_user: Annotated[AdminUser, Depends(require_permission("system:settings"))],
) -> CurrentEstimateResponse:
    """Get the current month's cost estimate based on token usage so far."""
    async with get_async_session() as session:
        billing_service = BillingService()
        data = await billing_service.get_current_estimate(session)
        return CurrentEstimateResponse(**data)


@router.patch(
    "/invoices/{invoice_id}/status",
    response_model=InvoiceResponse,
    summary="Void invoice",
    description="Transition an invoice to void status. Only 'void' is accepted. Admin only.",
)
async def update_invoice_status(
    invoice_id: UUID,
    request_body: StatusUpdateRequest,
    current_user: Annotated[AdminUser, Depends(require_permission("system:settings"))],
) -> InvoiceResponse:
    """Void an invoice via Stripe Invoicing API."""
    async with get_async_session() as session:
        billing_service = BillingService()
        invoice = await billing_service.void_invoice(session, invoice_id, request_body.reason)
        result = await session.execute(
            select(Invoice).options(selectinload(Invoice.payments)).where(Invoice.id == invoice.id)
        )
        invoice = result.scalar_one()
        return InvoiceResponse.from_invoice(invoice)


# =============================================================================
# Endpoints — Fiscal Details
# =============================================================================


@router.get(
    "/fiscal-details",
    summary="Get billing fiscal details for both parties",
)
async def get_fiscal_details(
    current_user: Annotated[AdminUser, Depends(require_permission("system:settings"))],
) -> dict:
    """Return fiscal details for invoices — client and provider."""
    settings = get_settings()
    return {
        "client_name": settings.CLIENT_COMPANY_NAME,
        "client_nif": settings.CLIENT_NIF,
        "client_address": settings.CLIENT_FISCAL_ADDRESS,
        "provider_name": settings.COMPANY_LEGAL_NAME,
        "provider_nif": settings.COMPANY_NIF,
        "provider_address": settings.COMPANY_FISCAL_ADDRESS,
        "provider_email": settings.OPERATOR_EMAIL or "info@zanovix.com",
    }


# =============================================================================
# Endpoints — Stripe
# =============================================================================


@router.post(
    "/setup-fiscal",
    summary="One-time fiscal setup for Stripe Invoicing",
    description="Creates IVA TaxRate and attaches client NIF to Stripe Customer. Idempotent.",
)
async def setup_stripe_fiscal(
    _: Annotated[AdminUser, Depends(require_permission("system:settings"))],
) -> dict:
    """
    One-time setup:
    1. Create Stripe TaxRate for IVA 21% (skip if STRIPE_TAX_RATE_ID already set)
    2. Attach client NIF to Stripe Customer (skip if already attached)
    """
    settings = get_settings()
    stripe_service = StripeService()
    result = {"tax_rate_id": None, "tax_rate_created": False, "tax_id_attached": False}

    # Step 1: TaxRate
    if settings.STRIPE_TAX_RATE_ID:
        result["tax_rate_id"] = settings.STRIPE_TAX_RATE_ID
        logger.info(f"TaxRate already configured: {settings.STRIPE_TAX_RATE_ID}")
    else:
        loop = asyncio.get_event_loop()
        tax_rate = await loop.run_in_executor(
            None,
            lambda: stripe.TaxRate.create(
                display_name="IVA",
                percentage=21.0,
                inclusive=False,
                country="ES",
                jurisdiction="ES",
                tax_type="vat",
                description="IVA 21% España",
            ),
        )
        result["tax_rate_id"] = tax_rate.id
        result["tax_rate_created"] = True
        logger.info(f"Created TaxRate: {tax_rate.id}")

    # Step 2: Client NIF on Stripe Customer
    if settings.CLIENT_NIF:
        async with get_async_session() as session:
            customer_id = await stripe_service._get_setting(session, "stripe_customer_id")
            if customer_id:
                created = await stripe_service.ensure_tax_id(
                    customer_id, "es_nif", settings.CLIENT_NIF
                )
                result["tax_id_attached"] = created
            else:
                logger.warning("No stripe_customer_id found — configure SEPA first")
    else:
        logger.warning("CLIENT_NIF not set — skipping tax ID attachment")

    return result


@router.post(
    "/stripe/setup-session",
    response_model=SetupSessionResponse,
    summary="Create SEPA setup session",
    description="Create a Stripe Checkout Session for SEPA Direct Debit mandate setup. Admin only.",
)
async def create_setup_session(
    current_user: Annotated[AdminUser, Depends(require_permission("system:settings"))],
) -> SetupSessionResponse:
    """Create a Stripe Checkout Session for SEPA mandate configuration."""
    settings = get_settings()
    base_url = settings.ADMIN_PANEL_URL.rstrip("/")
    success_url = f"{base_url}/settings/billing?stripe_setup=success"
    cancel_url = f"{base_url}/settings/billing?stripe_setup=cancel"

    async with get_async_session() as session:
        stripe_service = StripeService()
        if not stripe_service.is_configured():
            raise HTTPException(
                status_code=503,
                detail="Stripe no está configurado. Contacta con soporte.",
            )

        try:
            result = await stripe_service.create_setup_session(session, success_url, cancel_url)
        except stripe.error.StripeError as e:
            logger.error(f"Stripe setup session creation failed: {e}")
            raise HTTPException(
                status_code=502,
                detail="Error al crear la sesión de configuración de pago.",
            )

        return SetupSessionResponse(
            checkout_url=result["checkout_url"],
            session_id=result["session_id"],
        )


@router.get(
    "/stripe/status",
    response_model=StripeStatusResponse,
    summary="SEPA configuration status",
    description="Returns the current Stripe/SEPA payment configuration status. Admin only.",
)
async def get_stripe_status(
    current_user: Annotated[AdminUser, Depends(require_permission("system:settings"))],
) -> StripeStatusResponse:
    """Get SEPA Direct Debit configuration status from Stripe."""
    async with get_async_session() as session:
        stripe_service = StripeService()
        data = await stripe_service.get_sepa_status(session)
        return StripeStatusResponse(**data)


@router.post(
    "/stripe/webhook",
    summary="Stripe webhook receiver",
    description=(
        "Receives Stripe webhook events. No admin auth — verified via Stripe signature. "
        "Always returns 200 for processed events."
    ),
)
async def stripe_webhook(request: Request) -> dict:
    """
    Handle Stripe webhook events.

    Processes:
    - checkout.session.completed → store SEPA mandate details
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    stripe_service = StripeService()

    # Verify signature
    try:
        event = stripe_service.verify_webhook(payload, sig_header)
    except stripe.error.SignatureVerificationError:
        logger.warning("Stripe webhook signature verification failed")
        raise HTTPException(status_code=400, detail="Invalid Stripe signature.")
    except Exception as e:
        logger.error(f"Stripe webhook verification error: {e}")
        raise HTTPException(status_code=400, detail="Webhook verification failed.")

    event_type = event.type
    event_data = event.data.object

    logger.info(f"Stripe webhook received: type={event_type} id={event.id}")

    async with get_async_session() as session:
        if event_type == "checkout.session.completed":
            try:
                await stripe_service.handle_setup_completed(session, event_data)
                logger.info("SEPA setup completed via webhook")
            except Exception as e:
                logger.error(f"handle_setup_completed failed: {e}")

        elif event_type == "invoice.finalized":
            stripe_inv_id = event_data.id
            if stripe_inv_id:
                result = await session.execute(
                    select(Invoice).where(Invoice.stripe_invoice_id == stripe_inv_id)
                )
                invoice = result.scalar_one_or_none()
                if invoice:
                    invoice.invoice_pdf_url = getattr(event_data, "invoice_pdf", None)
                    if invoice.status == InvoiceStatus.DRAFT:
                        invoice.status = InvoiceStatus.ISSUED
                        invoice.issued_at = datetime.utcnow()
                    await session.commit()
                    logger.info(f"Invoice {invoice.invoice_number} finalized, PDF URL stored")
                else:
                    logger.debug(f"No local invoice for Stripe invoice {stripe_inv_id}")

        elif event_type == "invoice.paid":
            stripe_inv_id = event_data.id
            if stripe_inv_id:
                result = await session.execute(
                    select(Invoice).where(Invoice.stripe_invoice_id == stripe_inv_id)
                )
                invoice = result.scalar_one_or_none()
                if invoice and invoice.status != InvoiceStatus.PAID:
                    invoice.status = InvoiceStatus.PAID
                    invoice.paid_at = datetime.utcnow()
                    invoice.invoice_pdf_url = getattr(event_data, "invoice_pdf", None)

                    # Update Payment row if exists
                    pi_id = getattr(event_data, "payment_intent", None)
                    if pi_id:
                        pay_result = await session.execute(
                            select(Payment).where(Payment.stripe_payment_intent_id == pi_id)
                        )
                        payment = pay_result.scalar_one_or_none()
                        if payment:
                            payment.status = PaymentStatus.SUCCEEDED

                    await session.commit()
                    logger.info(
                        f"Invoice {invoice.invoice_number} marked PAID via invoice.paid webhook"
                    )
                else:
                    logger.debug(f"No local invoice or already paid for {stripe_inv_id}")

        elif event_type == "invoice.payment_failed":
            stripe_inv_id = event_data.id
            if stripe_inv_id:
                result = await session.execute(
                    select(Invoice).where(Invoice.stripe_invoice_id == stripe_inv_id)
                )
                invoice = result.scalar_one_or_none()
                if invoice:
                    pi_id = getattr(event_data, "payment_intent", None)
                    if pi_id:
                        pay_result = await session.execute(
                            select(Payment).where(Payment.stripe_payment_intent_id == pi_id)
                        )
                        payment = pay_result.scalar_one_or_none()
                        if payment:
                            last_error = getattr(event_data, "last_finalization_error", None)
                            payment.status = PaymentStatus.FAILED
                            payment.failure_reason = (
                                last_error.message if last_error else "Unknown failure"
                            )
                            await session.commit()
                            logger.info(f"Payment for {invoice.invoice_number} marked FAILED")

        else:
            logger.debug(f"Unhandled Stripe event type: {event_type}")

    return {"received": True}

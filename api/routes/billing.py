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
from starlette.responses import StreamingResponse

from api.models.billing_schemas import (
    CurrentEstimateResponse,
    GenerateInvoiceRequest,
    InvoiceListResponse,
    InvoiceResponse,
    SetupSessionResponse,
    StatusUpdateRequest,
    StripeStatusResponse,
)
from api.routes.admin import get_current_user
from api.services.billing_service import BillingService
from api.services.pdf_service import PdfService
from api.services.stripe_service import StripeService
from database.connection import get_async_session
from database.models import Invoice, InvoiceStatus, Payment, PaymentStatus
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
    current_user: Annotated[dict, Depends(get_current_user)],
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
    current_user: Annotated[dict, Depends(get_current_user)],
) -> InvoiceResponse:
    """Get a single invoice by ID including associated payments."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Invoice)
            .options(selectinload(Invoice.payments))
            .where(Invoice.id == invoice_id)
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
    current_user: Annotated[dict, Depends(get_current_user)],
) -> StreamingResponse:
    """Download the PDF for a given invoice. Regenerates if not present on disk."""
    async with get_async_session() as session:
        result = await session.execute(select(Invoice).where(Invoice.id == invoice_id))
        invoice = result.scalar_one_or_none()

        if not invoice:
            raise HTTPException(status_code=404, detail="Factura no encontrada.")

        pdf_service = PdfService()
        try:
            pdf_path = await pdf_service.ensure_pdf_exists(invoice)
        except Exception as e:
            logger.error(f"PDF generation failed for invoice {invoice_id}: {e}")
            raise HTTPException(
                status_code=500,
                detail="No se pudo generar el PDF de la factura.",
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


@router.post(
    "/invoices/generate",
    response_model=InvoiceResponse,
    status_code=201,
    summary="Generate invoice",
    description="Manually trigger invoice generation for a given period. Admin only.",
)
async def generate_invoice(
    request_body: GenerateInvoiceRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
) -> InvoiceResponse:
    """Generate an invoice for the specified year/month. Returns 409 if already exists."""
    async with get_async_session() as session:
        billing_service = BillingService()
        invoice = await billing_service.generate_invoice(
            session, request_body.year, request_body.month
        )
        # Reload with payments relationship after commit
        result = await session.execute(
            select(Invoice)
            .options(selectinload(Invoice.payments))
            .where(Invoice.id == invoice.id)
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
    current_user: Annotated[dict, Depends(get_current_user)],
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
    current_user: Annotated[dict, Depends(get_current_user)],
) -> InvoiceResponse:
    """Void an invoice. Cancels the associated Stripe PaymentIntent if pending."""
    async with get_async_session() as session:
        billing_service = BillingService()
        invoice = await billing_service.void_invoice(session, invoice_id, request_body.reason)
        result = await session.execute(
            select(Invoice)
            .options(selectinload(Invoice.payments))
            .where(Invoice.id == invoice.id)
        )
        invoice = result.scalar_one()
        return InvoiceResponse.from_invoice(invoice)


# =============================================================================
# Endpoints — Stripe
# =============================================================================


@router.post(
    "/stripe/setup-session",
    response_model=SetupSessionResponse,
    summary="Create SEPA setup session",
    description="Create a Stripe Checkout Session for SEPA Direct Debit mandate setup. Admin only.",
)
async def create_setup_session(
    current_user: Annotated[dict, Depends(get_current_user)],
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
    current_user: Annotated[dict, Depends(get_current_user)],
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
    - payment_intent.succeeded → mark payment and invoice as paid
    - payment_intent.payment_failed → mark payment as failed with reason
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

    event_type = event["type"]
    event_data = event["data"]["object"]

    logger.info(f"Stripe webhook received: type={event_type} id={event.get('id')}")

    async with get_async_session() as session:
        if event_type == "checkout.session.completed":
            try:
                await stripe_service.handle_setup_completed(session, event_data)
                logger.info("SEPA setup completed via webhook")
            except Exception as e:
                logger.error(f"handle_setup_completed failed: {e}")

        elif event_type == "payment_intent.succeeded":
            pi_id = event_data.get("id")
            if pi_id:
                try:
                    payment_result = await session.execute(
                        select(Payment).where(Payment.stripe_payment_intent_id == pi_id)
                    )
                    payment = payment_result.scalar_one_or_none()

                    if payment:
                        payment.status = PaymentStatus.SUCCEEDED

                        # Update invoice to PAID
                        invoice_result = await session.execute(
                            select(Invoice).where(Invoice.id == payment.invoice_id)
                        )
                        invoice = invoice_result.scalar_one_or_none()
                        if invoice:
                            invoice.status = InvoiceStatus.PAID
                            invoice.paid_at = datetime.utcnow()
                            logger.info(
                                f"Invoice {invoice.invoice_number} marked PAID via webhook"
                            )

                        await session.commit()
                    else:
                        logger.warning(f"No Payment row found for PI {pi_id}")
                except Exception as e:
                    logger.error(f"payment_intent.succeeded handler failed for {pi_id}: {e}")

        elif event_type == "payment_intent.payment_failed":
            pi_id = event_data.get("id")
            if pi_id:
                try:
                    failure_message = (
                        event_data.get("last_payment_error", {}) or {}
                    ).get("message", "Unknown failure")

                    payment_result = await session.execute(
                        select(Payment).where(Payment.stripe_payment_intent_id == pi_id)
                    )
                    payment = payment_result.scalar_one_or_none()

                    if payment:
                        payment.status = PaymentStatus.FAILED
                        payment.failure_reason = failure_message
                        await session.commit()
                        logger.info(f"Payment {pi_id} marked FAILED: {failure_message}")
                    else:
                        logger.warning(f"No Payment row found for failed PI {pi_id}")
                except Exception as e:
                    logger.error(f"payment_intent.payment_failed handler failed for {pi_id}: {e}")

        else:
            logger.debug(f"Unhandled Stripe event type: {event_type}")

    return {"received": True}

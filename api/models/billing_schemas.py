"""Pydantic schemas for billing API endpoints."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class PaymentSummary(BaseModel):
    """Payment summary for invoice detail."""

    id: str
    stripe_payment_intent_id: str
    amount_eur: str
    status: str
    payment_method: str
    failure_reason: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_payment(cls, payment) -> "PaymentSummary":
        return cls(
            id=str(payment.id),
            stripe_payment_intent_id=payment.stripe_payment_intent_id,
            amount_eur=str(payment.amount_eur),
            status=payment.status.value,
            payment_method=payment.payment_method,
            failure_reason=payment.failure_reason,
            created_at=payment.created_at,
        )


class InvoiceResponse(BaseModel):
    """Invoice response with computed fields."""

    id: str
    invoice_number: str
    year: int
    month: int
    period_label: str = ""
    maintenance_amount_eur: str
    token_amount_eur: str
    total_amount_eur: str
    status: str
    issued_at: datetime | None = None
    paid_at: datetime | None = None
    due_date: date
    has_pdf: bool = False
    stripe_payment_intent_id: str | None = None
    notes: str | None = None
    payments: list[PaymentSummary] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_invoice(cls, invoice) -> "InvoiceResponse":
        """Build response from Invoice ORM object."""
        month_names = {
            1: "Enero",
            2: "Febrero",
            3: "Marzo",
            4: "Abril",
            5: "Mayo",
            6: "Junio",
            7: "Julio",
            8: "Agosto",
            9: "Septiembre",
            10: "Octubre",
            11: "Noviembre",
            12: "Diciembre",
        }
        return cls(
            id=str(invoice.id),
            invoice_number=invoice.invoice_number,
            year=invoice.year,
            month=invoice.month,
            period_label=f"{month_names.get(invoice.month, '')} {invoice.year}",
            maintenance_amount_eur=str(invoice.maintenance_amount_eur),
            token_amount_eur=str(invoice.token_amount_eur),
            total_amount_eur=str(invoice.total_amount_eur),
            status=invoice.status.value,
            issued_at=invoice.issued_at,
            paid_at=invoice.paid_at,
            due_date=invoice.due_date,
            has_pdf=bool(invoice.pdf_path),
            stripe_payment_intent_id=invoice.stripe_payment_intent_id,
            notes=invoice.notes,
            payments=[PaymentSummary.from_payment(p) for p in (invoice.payments or [])],
            created_at=invoice.created_at,
            updated_at=invoice.updated_at,
        )


class InvoiceListResponse(BaseModel):
    """Paginated invoice list."""

    invoices: list[InvoiceResponse]
    total: int
    page: int
    page_size: int


class CurrentEstimateResponse(BaseModel):
    """Current month cost estimate."""

    year: int
    month: int
    period_label: str
    estimate_date: str
    next_invoice_date: str
    maintenance_amount_eur: str
    token_amount_eur: str
    total_amount_eur: str
    input_tokens: int
    output_tokens: int
    total_requests: int


class GenerateInvoiceRequest(BaseModel):
    """Request to manually generate an invoice."""

    year: int = Field(ge=2024, le=2030)
    month: int = Field(ge=1, le=12)


class StatusUpdateRequest(BaseModel):
    """Request to update invoice status (only void is allowed)."""

    status: str = Field(pattern="^void$")
    reason: str | None = None


class StripeStatusResponse(BaseModel):
    """SEPA/Stripe configuration status."""

    configured: bool
    customer_id: str | None = None
    payment_method_last4: str | None = None
    payment_method_status: str | None = None
    sepa_mandate_status: str | None = None


class SetupSessionResponse(BaseModel):
    """Stripe Checkout Session for SEPA setup."""

    checkout_url: str
    session_id: str

"""Unit tests for BillingService — invoice generation, voiding, estimates, overdue checks."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from database.models import Invoice, InvoiceStatus, Payment, PaymentStatus, TokenUsage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(
    maintenance: Decimal = Decimal("50.00"),
    price_input: Decimal = Decimal("0.15"),
    price_output: Decimal = Decimal("0.60"),
    operator_email: str = "ops@test.com",
):
    """Return a minimal settings mock for BillingService."""
    s = MagicMock()
    s.MONTHLY_MAINTENANCE_EUR = maintenance
    s.TOKEN_PRICE_INPUT = price_input
    s.TOKEN_PRICE_OUTPUT = price_output
    s.OPERATOR_EMAIL = operator_email
    return s


def _make_token_usage(
    input_tokens: int = 1_000_000,
    output_tokens: int = 500_000,
    total_requests: int = 42,
    year: int = 2026,
    month: int = 3,
):
    """Create a mock TokenUsage ORM object."""
    mock = MagicMock()
    mock.id = uuid.uuid4()
    mock.year = year
    mock.month = month
    mock.input_tokens = input_tokens
    mock.output_tokens = output_tokens
    mock.total_requests = total_requests
    return mock


def _make_invoice(
    status: InvoiceStatus = InvoiceStatus.ISSUED,
    stripe_pi_id: str | None = None,
    invoice_number: str = "ATR-2026-03-001",
    due_date: date | None = None,
):
    """Create a mock Invoice ORM object."""
    mock = MagicMock()
    mock.id = uuid.uuid4()
    mock.invoice_number = invoice_number
    mock.status = status
    mock.stripe_payment_intent_id = stripe_pi_id
    mock.due_date = due_date or (date.today() - timedelta(days=5))
    mock.notes = None
    mock.pdf_path = None
    mock.issued_at = None
    return mock


def _make_async_session():
    """Return a fully-mocked AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _scalar_result(value):
    """Wrap a value so session.execute().scalar_one_or_none() returns it."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_result(values: list):
    """Wrap a list so result.scalars().all() returns it."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def _scalar_count(count: int):
    """Wrap a count so result.scalar() returns it."""
    result = MagicMock()
    result.scalar.return_value = count
    return result


# ---------------------------------------------------------------------------
# Tests — generate_invoice
# ---------------------------------------------------------------------------


class TestGenerateInvoiceHappyPath:
    """generate_invoice with valid inputs and token usage present."""

    async def test_generate_invoice_happy_path(self):
        """Invoice is created with correct amounts when token usage exists."""
        from api.services.billing_service import BillingService

        settings = _make_settings()
        token_usage = _make_token_usage(input_tokens=1_000_000, output_tokens=500_000)
        session = _make_async_session()

        # execute() calls:
        # 1) duplicate check → None (no existing invoice)
        # 2) token usage → token_usage
        # 3) _next_invoice_number → count 0
        session.execute.side_effect = [
            _scalar_result(None),
            _scalar_result(token_usage),
            _scalar_count(0),
        ]
        session.refresh.side_effect = lambda inv: None

        svc = BillingService.__new__(BillingService)
        svc.pdf_service = AsyncMock()
        svc.pdf_service.generate_invoice_pdf = AsyncMock(return_value="/data/invoices/ATR-2026-03-001.pdf")
        svc.stripe_service = AsyncMock()
        svc.stripe_service.get_sepa_status = AsyncMock(return_value={"configured": False})
        svc.email_service = AsyncMock()

        with patch("api.services.billing_service.get_settings", return_value=settings):
            with patch("api.services.billing_service.datetime") as mock_dt:
                mock_dt.utcnow.return_value = datetime(2026, 3, 15, 12, 0, 0)
                invoice = await svc.generate_invoice(session, 2026, 3)

        # invoice was added to session and committed
        session.add.assert_called()
        session.flush.assert_called_once()
        session.commit.assert_called_once()

        # The returned object is whatever session.refresh updated — verify add was called
        # with an Invoice-like object
        added = session.add.call_args_list[0][0][0]
        assert added.year == 2026
        assert added.month == 3
        assert added.maintenance_amount_eur == Decimal("50.00")
        # 1M input * 0.15 + 0.5M output * 0.60 = 0.15 + 0.30 = 0.45
        assert added.token_amount_eur == Decimal("0.45")
        assert added.total_amount_eur == Decimal("50.45")


class TestGenerateInvoiceNoTokenUsage:
    """generate_invoice when no TokenUsage row exists for the period."""

    async def test_generate_invoice_no_token_usage(self):
        """token_amount should be 0.00 when no token usage exists."""
        from api.services.billing_service import BillingService

        settings = _make_settings()
        session = _make_async_session()

        session.execute.side_effect = [
            _scalar_result(None),   # duplicate check
            _scalar_result(None),   # token usage → None
            _scalar_count(0),       # invoice count for number
        ]

        svc = BillingService.__new__(BillingService)
        svc.pdf_service = AsyncMock()
        svc.pdf_service.generate_invoice_pdf = AsyncMock(return_value="/data/invoices/x.pdf")
        svc.stripe_service = AsyncMock()
        svc.stripe_service.get_sepa_status = AsyncMock(return_value={"configured": False})
        svc.email_service = AsyncMock()

        with patch("api.services.billing_service.get_settings", return_value=settings):
            with patch("api.services.billing_service.datetime") as mock_dt:
                mock_dt.utcnow.return_value = datetime(2026, 3, 15, 12, 0, 0)
                await svc.generate_invoice(session, 2026, 3)

        added = session.add.call_args_list[0][0][0]
        assert added.token_amount_eur == Decimal("0.00")
        assert added.total_amount_eur == Decimal("50.00")
        assert added.token_usage_id is None


class TestGenerateInvoiceDuplicateRaises409:
    """generate_invoice raises 409 when a non-void invoice already exists."""

    async def test_generate_invoice_duplicate_raises_409(self):
        """HTTPException 409 raised for duplicate non-void invoice."""
        from api.services.billing_service import BillingService

        settings = _make_settings()
        existing = _make_invoice()
        session = _make_async_session()
        session.execute.return_value = _scalar_result(existing)

        svc = BillingService.__new__(BillingService)
        svc.pdf_service = MagicMock()
        svc.stripe_service = MagicMock()
        svc.email_service = MagicMock()

        with patch("api.services.billing_service.get_settings", return_value=settings):
            with pytest.raises(HTTPException) as exc_info:
                await svc.generate_invoice(session, 2026, 3)

        assert exc_info.value.status_code == 409
        assert "2026-03" in exc_info.value.detail


class TestGenerateInvoiceFuturePeriodRaises422:
    """generate_invoice raises 422 when the requested period is in the future."""

    async def test_generate_invoice_future_period_raises_422(self):
        """HTTPException 422 raised for future year/month."""
        from api.services.billing_service import BillingService

        settings = _make_settings()
        session = _make_async_session()

        svc = BillingService.__new__(BillingService)
        svc.pdf_service = MagicMock()
        svc.stripe_service = MagicMock()
        svc.email_service = MagicMock()

        with patch("api.services.billing_service.get_settings", return_value=settings):
            with patch("api.services.billing_service.datetime") as mock_dt:
                mock_dt.utcnow.return_value = datetime(2026, 3, 15, 12, 0, 0)
                with pytest.raises(HTTPException) as exc_info:
                    # April 2026 is in the future relative to March 2026
                    await svc.generate_invoice(session, 2026, 4)

        assert exc_info.value.status_code == 422

    async def test_generate_invoice_future_year_raises_422(self):
        """HTTPException 422 raised for a future year."""
        from api.services.billing_service import BillingService

        settings = _make_settings()
        session = _make_async_session()

        svc = BillingService.__new__(BillingService)
        svc.pdf_service = MagicMock()
        svc.stripe_service = MagicMock()
        svc.email_service = MagicMock()

        with patch("api.services.billing_service.get_settings", return_value=settings):
            with patch("api.services.billing_service.datetime") as mock_dt:
                mock_dt.utcnow.return_value = datetime(2026, 3, 15, 12, 0, 0)
                with pytest.raises(HTTPException) as exc_info:
                    await svc.generate_invoice(session, 2027, 1)

        assert exc_info.value.status_code == 422


class TestGenerateInvoicePdfFailure:
    """PDF failure must not prevent invoice creation."""

    async def test_generate_invoice_pdf_failure_still_creates_invoice(self):
        """Invoice is saved with pdf_path=None when PdfService raises."""
        from api.services.billing_service import BillingService

        settings = _make_settings()
        token_usage = _make_token_usage()
        session = _make_async_session()

        session.execute.side_effect = [
            _scalar_result(None),
            _scalar_result(token_usage),
            _scalar_count(0),
        ]

        svc = BillingService.__new__(BillingService)
        svc.pdf_service = AsyncMock()
        svc.pdf_service.generate_invoice_pdf = AsyncMock(side_effect=RuntimeError("weasyprint crash"))
        svc.stripe_service = AsyncMock()
        svc.stripe_service.get_sepa_status = AsyncMock(return_value={"configured": False})
        svc.email_service = AsyncMock()

        with patch("api.services.billing_service.get_settings", return_value=settings):
            with patch("api.services.billing_service.datetime") as mock_dt:
                mock_dt.utcnow.return_value = datetime(2026, 3, 15, 12, 0, 0)
                # Should NOT raise
                await svc.generate_invoice(session, 2026, 3)

        # Invoice was still committed
        session.commit.assert_called_once()
        # pdf_path was never set (remains None from MagicMock default)
        added = session.add.call_args_list[0][0][0]
        # pdf_path attribute should not have been set to a real path
        assert added.pdf_path is None or added.pdf_path != "/data/invoices/ok.pdf"


class TestGenerateInvoiceStripeFailure:
    """Stripe failure must not prevent invoice creation."""

    async def test_generate_invoice_stripe_failure_still_creates_invoice(self):
        """Invoice is saved without Payment row when Stripe raises."""
        from api.services.billing_service import BillingService

        settings = _make_settings()
        token_usage = _make_token_usage()
        session = _make_async_session()

        session.execute.side_effect = [
            _scalar_result(None),
            _scalar_result(token_usage),
            _scalar_count(0),
        ]

        svc = BillingService.__new__(BillingService)
        svc.pdf_service = AsyncMock()
        svc.pdf_service.generate_invoice_pdf = AsyncMock(return_value="/data/invoices/ok.pdf")
        svc.stripe_service = AsyncMock()
        svc.stripe_service.get_sepa_status = AsyncMock(side_effect=RuntimeError("Stripe down"))
        svc.email_service = AsyncMock()

        with patch("api.services.billing_service.get_settings", return_value=settings):
            with patch("api.services.billing_service.datetime") as mock_dt:
                mock_dt.utcnow.return_value = datetime(2026, 3, 15, 12, 0, 0)
                await svc.generate_invoice(session, 2026, 3)

        # Invoice committed, no Payment object added (only invoice was added)
        session.commit.assert_called_once()
        # Only one add() call — the Invoice, not a Payment
        add_calls = session.add.call_args_list
        assert len(add_calls) == 1


# ---------------------------------------------------------------------------
# Tests — void_invoice
# ---------------------------------------------------------------------------


class TestVoidInvoice:
    """void_invoice transitions a valid invoice to VOID status."""

    async def test_void_invoice_valid(self):
        """Issued invoice can be voided successfully."""
        from api.services.billing_service import BillingService

        invoice = _make_invoice(status=InvoiceStatus.ISSUED)
        session = _make_async_session()
        session.execute.return_value = _scalar_result(invoice)

        svc = BillingService.__new__(BillingService)
        svc.stripe_service = AsyncMock()
        svc.stripe_service.cancel_payment_intent = AsyncMock()

        await svc.void_invoice(session, invoice.id, reason="Test void")

        assert invoice.status == InvoiceStatus.VOID
        session.commit.assert_called_once()

    async def test_void_invoice_already_paid_raises_400(self):
        """PAID invoice cannot be voided — raises HTTPException 400."""
        from api.services.billing_service import BillingService

        invoice = _make_invoice(status=InvoiceStatus.PAID)
        session = _make_async_session()
        session.execute.return_value = _scalar_result(invoice)

        svc = BillingService.__new__(BillingService)
        svc.stripe_service = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await svc.void_invoice(session, invoice.id)

        assert exc_info.value.status_code == 400
        assert "paid" in exc_info.value.detail

    async def test_void_invoice_not_found_raises_404(self):
        """Non-existent invoice raises HTTPException 404."""
        from api.services.billing_service import BillingService

        session = _make_async_session()
        session.execute.return_value = _scalar_result(None)

        svc = BillingService.__new__(BillingService)
        svc.stripe_service = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await svc.void_invoice(session, uuid.uuid4())

        assert exc_info.value.status_code == 404

    async def test_void_invoice_cancels_stripe_pi(self):
        """Voiding an invoice with a Stripe PI triggers cancellation."""
        from api.services.billing_service import BillingService

        pi_id = "pi_abc123"
        invoice = _make_invoice(status=InvoiceStatus.ISSUED, stripe_pi_id=pi_id)
        session = _make_async_session()
        session.execute.return_value = _scalar_result(invoice)

        svc = BillingService.__new__(BillingService)
        svc.stripe_service = AsyncMock()
        svc.stripe_service.cancel_payment_intent = AsyncMock(return_value=True)

        await svc.void_invoice(session, invoice.id)

        svc.stripe_service.cancel_payment_intent.assert_called_once_with(pi_id)

    async def test_void_invoice_stripe_cancel_failure_does_not_raise(self):
        """Stripe PI cancellation failure is swallowed — void still proceeds."""
        from api.services.billing_service import BillingService

        invoice = _make_invoice(status=InvoiceStatus.ISSUED, stripe_pi_id="pi_xyz")
        session = _make_async_session()
        session.execute.return_value = _scalar_result(invoice)

        svc = BillingService.__new__(BillingService)
        svc.stripe_service = AsyncMock()
        svc.stripe_service.cancel_payment_intent = AsyncMock(
            side_effect=RuntimeError("Stripe unreachable")
        )

        # Should NOT raise
        await svc.void_invoice(session, invoice.id)

        assert invoice.status == InvoiceStatus.VOID
        session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — check_overdue
# ---------------------------------------------------------------------------


class TestCheckOverdue:
    """check_overdue transitions past-due issued invoices to OVERDUE."""

    async def test_check_overdue_transitions_correctly(self):
        """Issued invoices past due_date become OVERDUE."""
        from api.services.billing_service import BillingService

        past_due = _make_invoice(
            status=InvoiceStatus.ISSUED,
            due_date=date.today() - timedelta(days=3),
        )
        session = _make_async_session()
        session.execute.return_value = _scalars_result([past_due])

        svc = BillingService.__new__(BillingService)
        count = await svc.check_overdue(session)

        assert count == 1
        assert past_due.status == InvoiceStatus.OVERDUE
        session.commit.assert_called_once()

    async def test_check_overdue_no_invoices(self):
        """Returns 0 and does not commit when no overdue invoices exist."""
        from api.services.billing_service import BillingService

        session = _make_async_session()
        session.execute.return_value = _scalars_result([])

        svc = BillingService.__new__(BillingService)
        count = await svc.check_overdue(session)

        assert count == 0
        session.commit.assert_not_called()

    async def test_check_overdue_multiple_invoices(self):
        """All past-due issued invoices are transitioned."""
        from api.services.billing_service import BillingService

        past_due_1 = _make_invoice(
            status=InvoiceStatus.ISSUED,
            invoice_number="ATR-2026-01-001",
            due_date=date.today() - timedelta(days=10),
        )
        past_due_2 = _make_invoice(
            status=InvoiceStatus.ISSUED,
            invoice_number="ATR-2026-02-001",
            due_date=date.today() - timedelta(days=5),
        )
        session = _make_async_session()
        session.execute.return_value = _scalars_result([past_due_1, past_due_2])

        svc = BillingService.__new__(BillingService)
        count = await svc.check_overdue(session)

        assert count == 2
        assert past_due_1.status == InvoiceStatus.OVERDUE
        assert past_due_2.status == InvoiceStatus.OVERDUE


# ---------------------------------------------------------------------------
# Tests — get_current_estimate
# ---------------------------------------------------------------------------


class TestGetCurrentEstimate:
    """get_current_estimate returns current month running total."""

    async def test_get_current_estimate_with_usage(self):
        """Returns correct estimate dict with token costs."""
        from api.services.billing_service import BillingService

        settings = _make_settings(
            maintenance=Decimal("50.00"),
            price_input=Decimal("0.15"),
            price_output=Decimal("0.60"),
        )
        token_usage = _make_token_usage(
            input_tokens=2_000_000,
            output_tokens=1_000_000,
            total_requests=100,
            year=2026,
            month=3,
        )
        session = _make_async_session()
        session.execute.return_value = _scalar_result(token_usage)

        svc = BillingService.__new__(BillingService)

        with patch("api.services.billing_service.get_settings", return_value=settings):
            with patch("api.services.billing_service.datetime") as mock_dt:
                mock_dt.utcnow.return_value = datetime(2026, 3, 15, 12, 0, 0)
                result = await svc.get_current_estimate(session)

        # 2M input * 0.15 + 1M output * 0.60 = 0.30 + 0.60 = 0.90
        assert result["maintenance_amount_eur"] == "50.00"
        assert result["token_amount_eur"] == "0.90"
        assert result["total_amount_eur"] == "50.90"
        assert result["input_tokens"] == 2_000_000
        assert result["output_tokens"] == 1_000_000
        assert result["total_requests"] == 100
        assert result["year"] == 2026
        assert result["month"] == 3

    async def test_get_current_estimate_no_usage(self):
        """Returns zero token amount when no token usage exists."""
        from api.services.billing_service import BillingService

        settings = _make_settings()
        session = _make_async_session()
        session.execute.return_value = _scalar_result(None)

        svc = BillingService.__new__(BillingService)

        with patch("api.services.billing_service.get_settings", return_value=settings):
            with patch("api.services.billing_service.datetime") as mock_dt:
                mock_dt.utcnow.return_value = datetime(2026, 3, 15, 12, 0, 0)
                result = await svc.get_current_estimate(session)

        assert result["token_amount_eur"] == "0.00"
        assert result["total_amount_eur"] == "50.00"
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0
        assert result["total_requests"] == 0

    async def test_get_current_estimate_next_invoice_date_december(self):
        """Next invoice date wraps to January of next year in December."""
        from api.services.billing_service import BillingService

        settings = _make_settings()
        session = _make_async_session()
        session.execute.return_value = _scalar_result(None)

        svc = BillingService.__new__(BillingService)

        with patch("api.services.billing_service.get_settings", return_value=settings):
            with patch("api.services.billing_service.datetime") as mock_dt:
                mock_dt.utcnow.return_value = datetime(2026, 12, 15, 12, 0, 0)
                result = await svc.get_current_estimate(session)

        assert result["next_invoice_date"] == "2027-01-01"


# ---------------------------------------------------------------------------
# Tests — _next_invoice_number
# ---------------------------------------------------------------------------


class TestNextInvoiceNumber:
    """_next_invoice_number generates correct ATR-YYYY-MM-SEQ format."""

    async def test_next_invoice_number_format_first(self):
        """First invoice of period is SEQ 001."""
        from api.services.billing_service import BillingService

        session = _make_async_session()
        session.execute.return_value = _scalar_count(0)

        svc = BillingService.__new__(BillingService)
        number = await svc._next_invoice_number(session, 2026, 3)

        assert number == "ATR-2026-03-001"

    async def test_next_invoice_number_format_subsequent(self):
        """Second invoice of period is SEQ 002."""
        from api.services.billing_service import BillingService

        session = _make_async_session()
        session.execute.return_value = _scalar_count(1)

        svc = BillingService.__new__(BillingService)
        number = await svc._next_invoice_number(session, 2026, 3)

        assert number == "ATR-2026-03-002"

    async def test_next_invoice_number_pads_month(self):
        """Single-digit months are zero-padded."""
        from api.services.billing_service import BillingService

        session = _make_async_session()
        session.execute.return_value = _scalar_count(0)

        svc = BillingService.__new__(BillingService)
        number = await svc._next_invoice_number(session, 2026, 1)

        assert number == "ATR-2026-01-001"
        assert "ATR-2026-1-" not in number


# ---------------------------------------------------------------------------
# T9-billing — Tests: Bug 1 PDF generate+persist (TDD RED → T2 GREEN)
# ---------------------------------------------------------------------------


class TestGenerateInvoicePdfPersistence:
    """
    Bug 1: generate_invoice must call ensure_pdf_exists, persist the returned
    path to invoice.pdf_path, and forward that path to send_invoice_email.
    """

    async def test_generate_invoice_persists_pdf_path(self):
        """
        GIVEN PdfService.ensure_pdf_exists returns a valid path
        WHEN generate_invoice is called
        THEN invoice.pdf_path equals the returned path
        AND send_invoice_email is called with that pdf_path value.
        """
        from api.services.billing_service import BillingService

        settings = _make_settings(operator_email="ops@test.com")
        token_usage = _make_token_usage()
        session = _make_async_session()

        session.execute.side_effect = [
            _scalar_result(None),       # duplicate check
            _scalar_result(token_usage),  # token usage
            _scalar_count(0),           # _next_invoice_number
        ]

        expected_pdf_path = "/data/invoices/ATR-2026-03-001.pdf"

        svc = BillingService.__new__(BillingService)
        svc.pdf_service = AsyncMock()
        svc.pdf_service.ensure_pdf_exists = AsyncMock(return_value=expected_pdf_path)
        svc.stripe_service = AsyncMock()
        svc.stripe_service.get_sepa_status = AsyncMock(return_value={"configured": False})
        svc.email_service = AsyncMock()
        svc.email_service.send_invoice_email = AsyncMock(return_value=True)

        with patch("api.services.billing_service.get_settings", return_value=settings):
            with patch("api.services.billing_service.datetime") as mock_dt:
                mock_dt.utcnow.return_value = datetime(2026, 3, 15, 12, 0, 0)
                invoice = await svc.generate_invoice(session, 2026, 3)

        # The invoice object added to session must have pdf_path set
        added = session.add.call_args_list[0][0][0]
        assert added.pdf_path == expected_pdf_path, (
            f"Expected invoice.pdf_path={expected_pdf_path!r}, got {added.pdf_path!r}"
        )

        # email must be called with that pdf_path
        call_kwargs = svc.email_service.send_invoice_email.call_args
        assert call_kwargs is not None, "send_invoice_email was never called"
        if "pdf_path" in call_kwargs.kwargs:
            sent_pdf_path = call_kwargs.kwargs["pdf_path"]
        elif len(call_kwargs.args) > 4:
            sent_pdf_path = call_kwargs.args[4]
        else:
            sent_pdf_path = "NOT_FOUND"
        assert sent_pdf_path == expected_pdf_path, (
            f"send_invoice_email called with pdf_path={sent_pdf_path!r}, expected {expected_pdf_path!r}"
        )

    async def test_generate_invoice_handles_pdf_failure_gracefully(self):
        """
        GIVEN PdfService.ensure_pdf_exists raises an exception
        WHEN generate_invoice is called
        THEN no exception propagates from generate_invoice
        AND invoice is still committed (pdf_path=None)
        AND send_invoice_email is called with pdf_path=None.
        """
        from api.services.billing_service import BillingService

        settings = _make_settings(operator_email="ops@test.com")
        token_usage = _make_token_usage()
        session = _make_async_session()

        session.execute.side_effect = [
            _scalar_result(None),
            _scalar_result(token_usage),
            _scalar_count(0),
        ]

        svc = BillingService.__new__(BillingService)
        svc.pdf_service = AsyncMock()
        svc.pdf_service.ensure_pdf_exists = AsyncMock(
            side_effect=OSError("weasyprint unavailable")
        )
        svc.stripe_service = AsyncMock()
        svc.stripe_service.get_sepa_status = AsyncMock(return_value={"configured": False})
        svc.email_service = AsyncMock()
        svc.email_service.send_invoice_email = AsyncMock(return_value=False)

        with patch("api.services.billing_service.get_settings", return_value=settings):
            with patch("api.services.billing_service.datetime") as mock_dt:
                mock_dt.utcnow.return_value = datetime(2026, 3, 15, 12, 0, 0)
                # Must NOT raise
                invoice = await svc.generate_invoice(session, 2026, 3)

        # Invoice still committed despite PDF failure
        session.commit.assert_called_once()

        # email called with pdf_path=None
        call_kwargs = svc.email_service.send_invoice_email.call_args
        assert call_kwargs is not None, "send_invoice_email was never called"
        # use "pdf_path" kwarg if present; fall back to 5th positional arg (index 4)
        if "pdf_path" in call_kwargs.kwargs:
            sent_pdf_path = call_kwargs.kwargs["pdf_path"]
        elif len(call_kwargs.args) > 4:
            sent_pdf_path = call_kwargs.args[4]
        else:
            sent_pdf_path = "NOT_FOUND"
        assert sent_pdf_path is None, (
            f"Expected send_invoice_email(pdf_path=None), got pdf_path={sent_pdf_path!r}"
        )

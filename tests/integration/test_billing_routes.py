"""
Integration tests for billing API routes — api/routes/billing.py.

Covers:
- GET  /api/billing/invoices          — list (paginated, auth-guarded)
- POST /api/billing/invoices/generate — generate invoice (201 / 409)
- GET  /api/billing/current-estimate  — current estimate
- PATCH /api/billing/invoices/{id}/status — void invoice
- POST /api/billing/stripe/webhook    — webhook (signature check)

Follows the same pattern as tests/integration/test_token_usage_api.py:
- FastAPI TestClient
- app.dependency_overrides for get_current_user
- Patching get_async_session at the route module level
- Patching BillingService / StripeService at the route module level
"""

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import stripe
from fastapi.testclient import TestClient

from api.main import app
from api.routes.admin import get_current_user


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _bypass_rate_limiter():
    """Disable Redis-based rate limiting for all tests in this module."""
    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock()
    with patch("api.middleware.rate_limiting.get_redis_client", return_value=mock_redis):
        yield


@pytest.fixture
def client():
    """Provide a TestClient for the FastAPI app."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def mock_auth():
    """Override get_current_user to bypass JWT authentication."""
    fake_user = {
        "sub": "admin",
        "jti": str(uuid4()),
        "exp": 9999999999,
        "type": "admin",
    }
    app.dependency_overrides[get_current_user] = lambda: fake_user
    yield fake_user
    app.dependency_overrides.pop(get_current_user, None)


# =============================================================================
# Mock factory helpers
# =============================================================================


def _make_invoice(
    year: int = 2026,
    month: int = 3,
    status: str = "issued",
):
    """Return a mock Invoice ORM object compatible with InvoiceResponse.from_invoice()."""
    inv = MagicMock()
    inv.id = uuid4()
    inv.invoice_number = f"INV-{year}-{month:02d}"
    inv.year = year
    inv.month = month
    inv.maintenance_amount_eur = Decimal("99.00")
    inv.token_amount_eur = Decimal("12.50")
    inv.total_amount_eur = Decimal("111.50")
    inv.status = MagicMock()
    inv.status.value = status
    inv.issued_at = datetime(year, month, 1, tzinfo=timezone.utc)
    inv.paid_at = None
    inv.due_date = date(year, month, 15)
    inv.pdf_path = None
    inv.stripe_payment_intent_id = None
    inv.notes = None
    inv.payments = []
    inv.created_at = datetime(year, month, 1, tzinfo=timezone.utc)
    inv.updated_at = datetime(year, month, 1, tzinfo=timezone.utc)
    return inv


def _mock_session_cm(session: AsyncMock) -> MagicMock:
    """Wrap a mock session into a context-manager-compatible object."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_db_session(*query_results) -> AsyncMock:
    """
    Build a mock async session that returns *query_results* in order for each execute() call.

    Each entry in query_results can be either:
    - a list  → result.scalars().all() returns the list and result.scalar() returns len
    - a value → result.scalar_one_or_none() returns the value and result.scalar() returns it
    """
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    results = []
    for qr in query_results:
        mock_result = MagicMock()
        if isinstance(qr, list):
            mock_result.scalars.return_value.all.return_value = qr
            mock_result.scalar.return_value = len(qr)
            mock_result.scalar_one_or_none.return_value = qr[0] if qr else None
        else:
            mock_result.scalar.return_value = qr
            mock_result.scalar_one_or_none.return_value = qr
            mock_result.scalars.return_value.all.return_value = [qr] if qr else []
        results.append(mock_result)

    mock_session.execute = AsyncMock(side_effect=results if results else [MagicMock()])
    return mock_session


# =============================================================================
# GET /api/billing/invoices
# =============================================================================


class TestListInvoices:
    """Tests for GET /api/billing/invoices."""

    def test_list_invoices_requires_auth(self, client):
        """GIVEN no auth, WHEN GET /api/billing/invoices, THEN returns 401/403."""
        response = client.get("/api/billing/invoices")
        assert response.status_code in (401, 403)

    def test_list_invoices_returns_paginated(self, client, mock_auth):
        """GIVEN invoices exist, WHEN GET /api/billing/invoices, THEN returns 200 with structure."""
        inv1 = _make_invoice(year=2026, month=3)
        inv2 = _make_invoice(year=2026, month=2)

        # Two execute calls: COUNT then SELECT with limit/offset
        count_result = MagicMock()
        count_result.scalar.return_value = 2

        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [inv1, inv2]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[count_result, rows_result])

        with patch(
            "api.routes.billing.get_async_session",
            return_value=_mock_session_cm(mock_session),
        ):
            response = client.get("/api/billing/invoices")

        assert response.status_code == 200
        data = response.json()
        assert "invoices" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert data["total"] == 2
        assert len(data["invoices"]) == 2

    def test_list_invoices_returns_empty_list(self, client, mock_auth):
        """GIVEN no invoices, WHEN GET /api/billing/invoices, THEN returns 200 with empty list."""
        count_result = MagicMock()
        count_result.scalar.return_value = 0

        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[count_result, rows_result])

        with patch(
            "api.routes.billing.get_async_session",
            return_value=_mock_session_cm(mock_session),
        ):
            response = client.get("/api/billing/invoices")

        assert response.status_code == 200
        data = response.json()
        assert data["invoices"] == []
        assert data["total"] == 0

    def test_list_invoices_invoice_fields(self, client, mock_auth):
        """GIVEN an invoice, WHEN GET /api/billing/invoices, THEN response includes required fields."""
        inv = _make_invoice(year=2026, month=3, status="issued")

        count_result = MagicMock()
        count_result.scalar.return_value = 1

        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [inv]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[count_result, rows_result])

        with patch(
            "api.routes.billing.get_async_session",
            return_value=_mock_session_cm(mock_session),
        ):
            response = client.get("/api/billing/invoices")

        assert response.status_code == 200
        item = response.json()["invoices"][0]
        assert "id" in item
        assert "invoice_number" in item
        assert "year" in item
        assert "month" in item
        assert "status" in item
        assert item["year"] == 2026
        assert item["month"] == 3


# =============================================================================
# POST /api/billing/invoices/generate
# =============================================================================


class TestGenerateInvoice:
    """Tests for POST /api/billing/invoices/generate."""

    def test_generate_invoice_requires_auth(self, client):
        """GIVEN no auth, WHEN POST generate, THEN returns 401/403."""
        response = client.post(
            "/api/billing/invoices/generate", json={"year": 2026, "month": 3}
        )
        assert response.status_code in (401, 403)

    def test_generate_invoice_returns_201(self, client, mock_auth):
        """GIVEN valid request, WHEN POST generate, THEN returns 201 with invoice."""
        inv = _make_invoice(year=2026, month=3)

        # session.execute for the reload after generation
        reload_result = MagicMock()
        reload_result.scalar_one.return_value = inv

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=reload_result)

        with patch(
            "api.routes.billing.get_async_session",
            return_value=_mock_session_cm(mock_session),
        ):
            with patch("api.routes.billing.BillingService") as MockBillingService:
                mock_svc = MagicMock()
                mock_svc.generate_invoice = AsyncMock(return_value=inv)
                MockBillingService.return_value = mock_svc

                response = client.post(
                    "/api/billing/invoices/generate", json={"year": 2026, "month": 3}
                )

        assert response.status_code == 201
        data = response.json()
        assert data["year"] == 2026
        assert data["month"] == 3

    def test_generate_invoice_409_on_duplicate(self, client, mock_auth):
        """GIVEN BillingService raises 409, WHEN POST generate, THEN returns 409."""
        from fastapi import HTTPException

        mock_session = AsyncMock()
        with patch(
            "api.routes.billing.get_async_session",
            return_value=_mock_session_cm(mock_session),
        ):
            with patch("api.routes.billing.BillingService") as MockBillingService:
                mock_svc = MagicMock()
                mock_svc.generate_invoice = AsyncMock(
                    side_effect=HTTPException(
                        status_code=409, detail="Invoice already exists for this period."
                    )
                )
                MockBillingService.return_value = mock_svc

                response = client.post(
                    "/api/billing/invoices/generate", json={"year": 2026, "month": 3}
                )

        assert response.status_code == 409

    def test_generate_invoice_validates_month_range(self, client, mock_auth):
        """GIVEN month=13 (invalid), WHEN POST generate, THEN returns 422."""
        response = client.post(
            "/api/billing/invoices/generate", json={"year": 2026, "month": 13}
        )
        assert response.status_code == 422


# =============================================================================
# GET /api/billing/current-estimate
# =============================================================================


class TestCurrentEstimate:
    """Tests for GET /api/billing/current-estimate."""

    def test_current_estimate_requires_auth(self, client):
        """GIVEN no auth, WHEN GET current-estimate, THEN returns 401/403."""
        response = client.get("/api/billing/current-estimate")
        assert response.status_code in (401, 403)

    def test_current_estimate_returns_200(self, client, mock_auth):
        """GIVEN service returns estimate, WHEN GET current-estimate, THEN returns 200."""
        estimate_data = {
            "year": 2026,
            "month": 3,
            "period_label": "Marzo 2026",
            "estimate_date": "2026-03-15",
            "next_invoice_date": "2026-04-01",
            "maintenance_amount_eur": "99.00",
            "token_amount_eur": "12.50",
            "total_amount_eur": "111.50",
            "input_tokens": 500_000,
            "output_tokens": 200_000,
            "total_requests": 150,
        }

        mock_session = AsyncMock()
        with patch(
            "api.routes.billing.get_async_session",
            return_value=_mock_session_cm(mock_session),
        ):
            with patch("api.routes.billing.BillingService") as MockBillingService:
                mock_svc = MagicMock()
                mock_svc.get_current_estimate = AsyncMock(return_value=estimate_data)
                MockBillingService.return_value = mock_svc

                response = client.get("/api/billing/current-estimate")

        assert response.status_code == 200
        data = response.json()
        assert data["year"] == 2026
        assert data["month"] == 3
        assert "total_amount_eur" in data
        assert "maintenance_amount_eur" in data
        assert "token_amount_eur" in data


# =============================================================================
# PATCH /api/billing/invoices/{id}/status
# =============================================================================


class TestVoidInvoice:
    """Tests for PATCH /api/billing/invoices/{id}/status."""

    def test_void_invoice_requires_auth(self, client):
        """GIVEN no auth, WHEN PATCH status, THEN returns 401/403."""
        response = client.patch(
            f"/api/billing/invoices/{uuid4()}/status",
            json={"status": "void"},
        )
        assert response.status_code in (401, 403)

    def test_void_invoice_returns_200(self, client, mock_auth):
        """GIVEN valid void request, WHEN PATCH status, THEN returns 200 with invoice."""
        inv = _make_invoice(year=2026, month=3, status="void")

        reload_result = MagicMock()
        reload_result.scalar_one.return_value = inv

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=reload_result)

        invoice_id = uuid4()
        with patch(
            "api.routes.billing.get_async_session",
            return_value=_mock_session_cm(mock_session),
        ):
            with patch("api.routes.billing.BillingService") as MockBillingService:
                mock_svc = MagicMock()
                mock_svc.void_invoice = AsyncMock(return_value=inv)
                MockBillingService.return_value = mock_svc

                response = client.patch(
                    f"/api/billing/invoices/{invoice_id}/status",
                    json={"status": "void", "reason": "Test void"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "void"

    def test_void_invoice_rejects_non_void_status(self, client, mock_auth):
        """GIVEN status='paid' (not allowed), WHEN PATCH status, THEN returns 422."""
        response = client.patch(
            f"/api/billing/invoices/{uuid4()}/status",
            json={"status": "paid"},
        )
        assert response.status_code == 422

    def test_void_invoice_404_when_not_found(self, client, mock_auth):
        """GIVEN BillingService raises 404, WHEN PATCH status, THEN returns 404."""
        from fastapi import HTTPException

        mock_session = AsyncMock()
        invoice_id = uuid4()
        with patch(
            "api.routes.billing.get_async_session",
            return_value=_mock_session_cm(mock_session),
        ):
            with patch("api.routes.billing.BillingService") as MockBillingService:
                mock_svc = MagicMock()
                mock_svc.void_invoice = AsyncMock(
                    side_effect=HTTPException(
                        status_code=404, detail="Factura no encontrada."
                    )
                )
                MockBillingService.return_value = mock_svc

                response = client.patch(
                    f"/api/billing/invoices/{invoice_id}/status",
                    json={"status": "void"},
                )

        assert response.status_code == 404


# =============================================================================
# POST /api/billing/stripe/webhook
# =============================================================================


class TestStripeWebhook:
    """Tests for POST /api/billing/stripe/webhook — no admin auth required."""

    def test_stripe_webhook_invalid_signature_returns_400(self, client):
        """GIVEN bad Stripe signature, WHEN POST webhook, THEN returns 400."""
        with patch("api.routes.billing.StripeService") as MockStripeService:
            mock_svc = MagicMock()
            mock_svc.verify_webhook = MagicMock(
                side_effect=stripe.error.SignatureVerificationError(
                    "Invalid signature", "sig_header"
                )
            )
            MockStripeService.return_value = mock_svc

            response = client.post(
                "/api/billing/stripe/webhook",
                content=b'{"type": "test"}',
                headers={"stripe-signature": "bad_sig"},
            )

        assert response.status_code == 400

    def test_stripe_webhook_valid_returns_200(self, client):
        """GIVEN valid Stripe event, WHEN POST webhook, THEN returns 200 with received=True."""
        fake_event = {
            "type": "checkout.session.completed",
            "id": "evt_test_123",
            "data": {"object": {"id": "cs_test_123"}},
        }

        mock_session = AsyncMock()
        with patch("api.routes.billing.StripeService") as MockStripeService:
            mock_svc = MagicMock()
            mock_svc.verify_webhook = MagicMock(return_value=fake_event)
            mock_svc.handle_setup_completed = AsyncMock()
            MockStripeService.return_value = mock_svc

            with patch(
                "api.routes.billing.get_async_session",
                return_value=_mock_session_cm(mock_session),
            ):
                response = client.post(
                    "/api/billing/stripe/webhook",
                    content=json.dumps(fake_event).encode(),
                    headers={"stripe-signature": "valid_sig"},
                )

        assert response.status_code == 200
        assert response.json() == {"received": True}

    def test_stripe_webhook_unhandled_event_returns_200(self, client):
        """GIVEN unhandled event type, WHEN POST webhook, THEN still returns 200."""
        fake_event = {
            "type": "customer.created",
            "id": "evt_test_456",
            "data": {"object": {}},
        }

        mock_session = AsyncMock()
        with patch("api.routes.billing.StripeService") as MockStripeService:
            mock_svc = MagicMock()
            mock_svc.verify_webhook = MagicMock(return_value=fake_event)
            MockStripeService.return_value = mock_svc

            with patch(
                "api.routes.billing.get_async_session",
                return_value=_mock_session_cm(mock_session),
            ):
                response = client.post(
                    "/api/billing/stripe/webhook",
                    content=json.dumps(fake_event).encode(),
                    headers={"stripe-signature": "valid_sig"},
                )

        assert response.status_code == 200
        assert response.json() == {"received": True}

    def test_stripe_webhook_payment_succeeded_marks_paid(self, client):
        """GIVEN payment_intent.succeeded event, WHEN POST webhook, THEN returns 200."""
        pi_id = "pi_test_789"
        fake_event = {
            "type": "payment_intent.succeeded",
            "id": "evt_test_789",
            "data": {"object": {"id": pi_id}},
        }

        # Mock payment and invoice found in DB
        mock_payment = MagicMock()
        mock_payment.invoice_id = uuid4()
        mock_payment.status = MagicMock()

        mock_invoice = MagicMock()
        mock_invoice.invoice_number = "INV-2026-03"
        mock_invoice.status = MagicMock()

        payment_result = MagicMock()
        payment_result.scalar_one_or_none.return_value = mock_payment

        invoice_result = MagicMock()
        invoice_result.scalar_one_or_none.return_value = mock_invoice

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[payment_result, invoice_result])
        mock_session.commit = AsyncMock()

        with patch("api.routes.billing.StripeService") as MockStripeService:
            mock_svc = MagicMock()
            mock_svc.verify_webhook = MagicMock(return_value=fake_event)
            MockStripeService.return_value = mock_svc

            with patch(
                "api.routes.billing.get_async_session",
                return_value=_mock_session_cm(mock_session),
            ):
                response = client.post(
                    "/api/billing/stripe/webhook",
                    content=json.dumps(fake_event).encode(),
                    headers={"stripe-signature": "valid_sig"},
                )

        assert response.status_code == 200

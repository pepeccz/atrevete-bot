"""T-07 smoke test: Stripe stub in conftest must expose all required symbols.

These symbols are needed by api/services/stripe_service.py and billing routes.
The test fails (RED) if conftest does not wire them into sys.modules["stripe"].
"""

from __future__ import annotations

import sys


def test_stripe_invoice_accessible():
    import stripe
    assert hasattr(stripe, "Invoice"), "stripe.Invoice missing from stub"


def test_stripe_invoice_item_accessible():
    import stripe
    assert hasattr(stripe, "InvoiceItem"), "stripe.InvoiceItem missing from stub"


def test_stripe_payment_method_accessible():
    import stripe
    assert hasattr(stripe, "PaymentMethod"), "stripe.PaymentMethod missing from stub"


def test_stripe_subscription_accessible():
    import stripe
    assert hasattr(stripe, "Subscription"), "stripe.Subscription missing from stub"


def test_stripe_customer_accessible():
    import stripe
    assert hasattr(stripe, "Customer"), "stripe.Customer missing from stub"


def test_stripe_charge_accessible():
    import stripe
    assert hasattr(stripe, "Charge"), "stripe.Charge missing from stub"


def test_stripe_refund_accessible():
    import stripe
    assert hasattr(stripe, "Refund"), "stripe.Refund missing from stub"


def test_stripe_event_accessible():
    import stripe
    assert hasattr(stripe, "Event"), "stripe.Event missing from stub"


def test_stripe_webhook_accessible():
    import stripe
    assert hasattr(stripe, "Webhook"), "stripe.Webhook missing from stub"


def test_stripe_error_stripe_error_accessible():
    import stripe
    assert hasattr(stripe, "error"), "stripe.error submodule missing from stub"
    assert hasattr(stripe.error, "StripeError"), "stripe.error.StripeError missing"
    assert issubclass(stripe.error.StripeError, Exception)


def test_stripe_error_invalid_request_error_accessible():
    import stripe
    assert hasattr(stripe.error, "InvalidRequestError"), (
        "stripe.error.InvalidRequestError missing"
    )
    assert issubclass(stripe.error.InvalidRequestError, stripe.error.StripeError)


def test_stripe_invoice_create_callable():
    import stripe
    inv = stripe.Invoice.create(amount=1000)
    assert inv.amount == 1000


def test_stripe_customer_create_callable():
    import stripe
    cust = stripe.Customer.create(email="test@example.com")
    assert cust.id is not None


def test_stripe_payment_method_create_callable():
    import stripe
    pm = stripe.PaymentMethod.create(type="card")
    assert pm.id is not None

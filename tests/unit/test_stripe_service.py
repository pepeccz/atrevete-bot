"""Unit tests for StripeService — SEPA Direct Debit payment integration."""

from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stripe stub — avoids importing the real stripe SDK in unit tests
# ---------------------------------------------------------------------------


def _make_stripe_stub():
    """Return a minimal stripe module stub with the classes we need."""

    stripe_stub = ModuleType("stripe")
    stripe_stub.__name__ = "stripe"

    # Error hierarchy
    class StripeError(Exception):
        pass

    class SignatureVerificationError(StripeError):
        def __init__(self, message="Invalid signature", sig_header=None):
            super().__init__(message)
            self.sig_header = sig_header

    stripe_stub.StripeError = StripeError
    stripe_stub.error = ModuleType("stripe.error")
    stripe_stub.error.StripeError = StripeError
    stripe_stub.error.SignatureVerificationError = SignatureVerificationError

    # PaymentIntent stub
    class _PaymentIntent:
        @staticmethod
        def create(**kwargs):
            pi = SimpleNamespace()
            pi.id = "pi_test_123"
            pi.status = "processing"
            return pi

        @staticmethod
        def retrieve(pi_id):
            pi = SimpleNamespace()
            pi.id = pi_id
            pi.status = "processing"
            return pi

        @staticmethod
        def cancel(pi_id):
            pi = SimpleNamespace()
            pi.id = pi_id
            pi.status = "canceled"
            return pi

    stripe_stub.PaymentIntent = _PaymentIntent

    # Webhook stub
    class _Webhook:
        @staticmethod
        def construct_event(payload, sig_header, secret):
            return SimpleNamespace(type="test.event", data=SimpleNamespace(object={}))

    stripe_stub.Webhook = _Webhook

    # Customer stub
    class _Customer:
        @staticmethod
        def create(**kwargs):
            return SimpleNamespace(id="cus_test_123")

    stripe_stub.Customer = _Customer

    # PaymentMethod stub
    class _PaymentMethod:
        @staticmethod
        def retrieve(pm_id):
            pm = SimpleNamespace()
            pm.sepa_debit = SimpleNamespace(last4="1234")
            return pm

    stripe_stub.PaymentMethod = _PaymentMethod

    # SetupIntent stub
    class _SetupIntent:
        @staticmethod
        def retrieve(si_id):
            return SimpleNamespace(payment_method="pm_test_123")

    stripe_stub.SetupIntent = _SetupIntent

    # checkout.Session stub
    checkout = ModuleType("stripe.checkout")
    checkout.__name__ = "stripe.checkout"

    class _CheckoutSession:
        @staticmethod
        def create(**kwargs):
            return SimpleNamespace(url="https://checkout.stripe.com/test", id="cs_test_123")

    checkout.Session = _CheckoutSession
    stripe_stub.checkout = checkout

    # Invoice stub — needed for type annotations in stripe_service.py class body
    class _Invoice:
        @staticmethod
        def create(**kwargs):
            return SimpleNamespace(id="in_test_123", status="draft")

        @staticmethod
        def retrieve(iid, **kwargs):
            return SimpleNamespace(id=iid, status="draft")

        @staticmethod
        def finalize_invoice(iid, **kwargs):
            return SimpleNamespace(id=iid, status="open")

        @staticmethod
        def void_invoice(iid, **kwargs):
            return SimpleNamespace(id=iid, status="void")

        @staticmethod
        def pay(iid, **kwargs):
            return SimpleNamespace(id=iid, status="paid")

    stripe_stub.Invoice = _Invoice

    # InvoiceItem stub
    class _InvoiceItem:
        @staticmethod
        def create(**kwargs):
            return SimpleNamespace(id="ii_test_123")

    stripe_stub.InvoiceItem = _InvoiceItem

    # Event stub
    class _Event:
        @staticmethod
        def retrieve(eid, **kwargs):
            return SimpleNamespace(id=eid, type="test.event", data=SimpleNamespace(object={}))

    stripe_stub.Event = _Event

    # Mandate stub (needed for SEPA mandate status lookups)
    class _Mandate:
        @staticmethod
        def retrieve(mid, **kwargs):
            return SimpleNamespace(
                id=mid,
                status="active",
                payment_method_details=SimpleNamespace(
                    sepa_debit=SimpleNamespace(url="https://stripe.com/mandate/stub")
                ),
            )

    stripe_stub.Mandate = _Mandate

    # TaxRate stub
    class _TaxRate:
        @staticmethod
        def create(**kwargs):
            return SimpleNamespace(id="txr_test_123")

        @staticmethod
        def retrieve(tid, **kwargs):
            return SimpleNamespace(id=tid)

    stripe_stub.TaxRate = _TaxRate

    return stripe_stub


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(stripe_key: str = "sk_test_abc123", webhook_secret: str = "whsec_test"):
    s = MagicMock()
    s.STRIPE_SECRET_KEY = stripe_key
    s.STRIPE_WEBHOOK_SECRET = webhook_secret
    return s


def _make_async_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_system_setting(key: str, value: str):
    """Create a mock SystemSetting ORM object."""
    mock = MagicMock()
    mock.key = key
    mock.category = "billing"
    mock.value = {"value": value}
    return mock


def _build_stripe_service(settings=None):
    """Build StripeService bypassing __init__ to avoid real stripe.api_key assignment."""
    from api.services.stripe_service import StripeService

    svc = StripeService.__new__(StripeService)
    s = settings or _make_settings()
    svc.api_key = s.STRIPE_SECRET_KEY
    return svc


# ---------------------------------------------------------------------------
# Tests — is_configured
# ---------------------------------------------------------------------------


class TestIsConfigured:
    """is_configured reflects whether STRIPE_SECRET_KEY is set."""

    def test_is_configured_true(self):
        """Returns True when API key is non-empty."""
        from api.services.stripe_service import StripeService

        settings = _make_settings(stripe_key="sk_test_abc123")
        with patch("api.services.stripe_service.get_settings", return_value=settings):
            with patch("api.services.stripe_service.stripe"):
                svc = StripeService()
        assert svc.is_configured() is True

    def test_is_configured_false(self):
        """Returns False when API key is empty string."""
        from api.services.stripe_service import StripeService

        settings = _make_settings(stripe_key="")
        with patch("api.services.stripe_service.get_settings", return_value=settings):
            with patch("api.services.stripe_service.stripe"):
                svc = StripeService()
        assert svc.is_configured() is False


# ---------------------------------------------------------------------------
# Tests — verify_webhook
# ---------------------------------------------------------------------------


class TestVerifyWebhook:
    """verify_webhook validates Stripe webhook signatures."""

    def test_verify_webhook_valid_signature(self):
        """construct_event is called and event is returned on valid signature."""
        stripe_stub = _make_stripe_stub()
        fake_event = SimpleNamespace(type="invoice.payment_succeeded")
        stripe_stub.Webhook.construct_event = MagicMock(return_value=fake_event)

        with patch.dict("sys.modules", {"stripe": stripe_stub, "stripe.error": stripe_stub.error}):
            from importlib import reload

            import api.services.stripe_service as stripe_mod

            reload(stripe_mod)

            settings = _make_settings(webhook_secret="whsec_real_secret")
            with patch("api.services.stripe_service.get_settings", return_value=settings):
                svc = _build_stripe_service(settings)
                result = svc.verify_webhook(
                    payload=b'{"type":"test"}',
                    sig_header="t=123,v1=abc",
                )

        assert result is fake_event
        stripe_stub.Webhook.construct_event.assert_called_once_with(
            b'{"type":"test"}',
            "t=123,v1=abc",
            "whsec_real_secret",
        )

    def test_verify_webhook_invalid_raises(self):
        """SignatureVerificationError propagates when signature is invalid."""
        stripe_stub = _make_stripe_stub()
        stripe_stub.Webhook.construct_event = MagicMock(
            side_effect=stripe_stub.error.SignatureVerificationError("Bad sig")
        )

        with patch.dict("sys.modules", {"stripe": stripe_stub, "stripe.error": stripe_stub.error}):
            from importlib import reload

            import api.services.stripe_service as stripe_mod

            reload(stripe_mod)

            settings = _make_settings()
            with patch("api.services.stripe_service.get_settings", return_value=settings):
                svc = _build_stripe_service(settings)
                with pytest.raises(stripe_stub.error.SignatureVerificationError):
                    svc.verify_webhook(payload=b"bad", sig_header="wrong")


# ---------------------------------------------------------------------------
# Tests — get_sepa_status
# ---------------------------------------------------------------------------


class TestGetSepaStatus:
    """get_sepa_status reads configuration from system_settings."""

    async def test_get_sepa_status_not_configured(self):
        """Returns configured=False when no settings exist in DB."""
        stripe_stub = _make_stripe_stub()
        session = _make_async_session()
        # All _get_setting calls return None
        session.execute.return_value = _scalar_result(None)

        with patch.dict("sys.modules", {"stripe": stripe_stub, "stripe.error": stripe_stub.error}):
            from importlib import reload

            import api.services.stripe_service as stripe_mod

            reload(stripe_mod)
            svc = _build_stripe_service(_make_settings(stripe_key=""))
            result = await svc.get_sepa_status(session)

        assert result["configured"] is False
        assert result["customer_id"] is None
        assert result["payment_method_last4"] is None

    async def test_get_sepa_status_configured(self):
        """Returns configured=True when customer_id and payment_method_id exist."""
        stripe_stub = _make_stripe_stub()

        # Stub PaymentMethod.retrieve so it doesn't hit real Stripe
        stripe_stub.PaymentMethod.retrieve = MagicMock(
            return_value=SimpleNamespace(sepa_debit=SimpleNamespace(last4="1234"))
        )

        session = _make_async_session()

        # _get_setting is called 3 times: customer_id, pm_id, last4
        # We return appropriate SystemSetting mocks
        customer_setting = _make_system_setting("stripe_customer_id", "cus_abc123")
        pm_setting = _make_system_setting("stripe_payment_method_id", "pm_sepa_456")
        last4_setting = _make_system_setting("stripe_payment_method_last4", "1234")

        session.execute.side_effect = [
            _scalar_result(customer_setting),
            _scalar_result(pm_setting),
            _scalar_result(last4_setting),
            # extra call for PaymentMethod live status query
            _scalar_result(pm_setting),
        ]

        with patch.dict("sys.modules", {"stripe": stripe_stub, "stripe.error": stripe_stub.error}):
            from importlib import reload

            import api.services.stripe_service as stripe_mod

            reload(stripe_mod)
            svc = _build_stripe_service(_make_settings(stripe_key="sk_test_real"))
            result = await svc.get_sepa_status(session)

        assert result["configured"] is True
        assert result["customer_id"] == "cus_abc123"


# ---------------------------------------------------------------------------
# Tests — _get_setting / _set_setting
# ---------------------------------------------------------------------------


class TestGetAndSetSetting:
    """_get_setting reads from DB; _set_setting upserts to DB."""

    async def test_get_setting_returns_value(self):
        """_get_setting returns the value string when setting exists."""
        stripe_stub = _make_stripe_stub()
        session = _make_async_session()
        setting = _make_system_setting("stripe_customer_id", "cus_xyz")
        session.execute.return_value = _scalar_result(setting)

        with patch.dict("sys.modules", {"stripe": stripe_stub, "stripe.error": stripe_stub.error}):
            from importlib import reload

            import api.services.stripe_service as stripe_mod

            reload(stripe_mod)
            svc = _build_stripe_service()
            result = await svc._get_setting(session, "stripe_customer_id")

        assert result == "cus_xyz"

    async def test_get_setting_returns_none_when_missing(self):
        """_get_setting returns None when no DB row exists."""
        stripe_stub = _make_stripe_stub()
        session = _make_async_session()
        session.execute.return_value = _scalar_result(None)

        with patch.dict("sys.modules", {"stripe": stripe_stub, "stripe.error": stripe_stub.error}):
            from importlib import reload

            import api.services.stripe_service as stripe_mod

            reload(stripe_mod)
            svc = _build_stripe_service()
            result = await svc._get_setting(session, "stripe_customer_id")

        assert result is None

    async def test_set_setting_creates_new(self):
        """_set_setting adds a new SystemSetting when one doesn't exist."""
        stripe_stub = _make_stripe_stub()
        session = _make_async_session()
        # No existing setting
        session.execute.return_value = _scalar_result(None)

        with patch.dict("sys.modules", {"stripe": stripe_stub, "stripe.error": stripe_stub.error}):
            from importlib import reload

            import api.services.stripe_service as stripe_mod

            reload(stripe_mod)
            svc = _build_stripe_service()
            await svc._set_setting(session, "stripe_customer_id", "cus_new", "Customer ID")

        # A new setting was added
        session.add.assert_called_once()
        added = session.add.call_args[0][0]
        assert added.key == "stripe_customer_id"
        assert added.value == {"value": "cus_new"}

    async def test_set_setting_updates_existing(self):
        """_set_setting updates value when setting already exists."""
        stripe_stub = _make_stripe_stub()
        session = _make_async_session()
        existing = _make_system_setting("stripe_customer_id", "cus_old")
        session.execute.return_value = _scalar_result(existing)

        with patch.dict("sys.modules", {"stripe": stripe_stub, "stripe.error": stripe_stub.error}):
            from importlib import reload

            import api.services.stripe_service as stripe_mod

            reload(stripe_mod)
            svc = _build_stripe_service()
            await svc._set_setting(session, "stripe_customer_id", "cus_new", "Customer ID")

        # No new add — existing was mutated
        session.add.assert_not_called()
        assert existing.value == {"value": "cus_new"}


# ---------------------------------------------------------------------------
# T11 — Tests: Bug 3 get_sepa_status real mandate status (TDD RED → T4 GREEN)
# ---------------------------------------------------------------------------


def _make_stripe_stub_with_mandate():
    """Extended stripe stub that includes Mandate.retrieve support."""
    stub = _make_stripe_stub()

    class _Mandate:
        @staticmethod
        def retrieve(mandate_id):
            return SimpleNamespace(status="active")

    stub.Mandate = _Mandate
    return stub


class TestGetSepaStatusMandateStatus:
    """
    Bug 3: get_sepa_status must query stripe.Mandate.retrieve and return
    the real mandate status via SepaMandateStatus enum mapping.
    """

    async def _run_get_sepa_status_with(self, pm_stub, mandate_retrieve_fn=None, stripe_err=None):
        """
        Helper: wires up session + stripe stub, calls get_sepa_status,
        returns the result dict.
        """
        from importlib import reload

        import api.services.stripe_service as stripe_mod

        stub = _make_stripe_stub_with_mandate()

        customer_setting = _make_system_setting("stripe_customer_id", "cus_abc123")
        pm_setting = _make_system_setting("stripe_payment_method_id", "pm_sepa_456")
        last4_setting = _make_system_setting("stripe_payment_method_last4", "1234")

        session = _make_async_session()
        session.execute.side_effect = [
            _scalar_result(customer_setting),
            _scalar_result(pm_setting),
            _scalar_result(last4_setting),
        ]

        stub.PaymentMethod.retrieve = MagicMock(return_value=pm_stub)

        if stripe_err:
            stub.Mandate.retrieve = MagicMock(side_effect=stripe_err)
        elif mandate_retrieve_fn:
            stub.Mandate.retrieve = mandate_retrieve_fn

        with patch.dict("sys.modules", {"stripe": stub, "stripe.error": stub.error}):
            reload(stripe_mod)
            svc = _build_stripe_service(_make_settings(stripe_key="sk_test_real"))
            return await svc.get_sepa_status(session)

    async def test_get_sepa_status_returns_active_mandate(self):
        """
        GIVEN Stripe PM has a mandate with status='active'
        WHEN get_sepa_status is called
        THEN sepa_mandate_status == 'active'
        """
        mandate_id = "mandate_abc123"
        pm = SimpleNamespace(
            sepa_debit=SimpleNamespace(last4="1234", mandate=mandate_id)
        )
        retrieve_fn = MagicMock(return_value=SimpleNamespace(status="active"))

        result = await self._run_get_sepa_status_with(pm, mandate_retrieve_fn=retrieve_fn)

        assert result["sepa_mandate_status"] == "active", (
            f"Expected 'active', got {result['sepa_mandate_status']!r}"
        )

    async def test_get_sepa_status_returns_inactive_mandate(self):
        """
        GIVEN Stripe PM has a mandate with status='inactive'
        WHEN get_sepa_status is called
        THEN sepa_mandate_status == 'inactive'
        """
        mandate_id = "mandate_inactive_456"
        pm = SimpleNamespace(
            sepa_debit=SimpleNamespace(last4="5678", mandate=mandate_id)
        )
        retrieve_fn = MagicMock(return_value=SimpleNamespace(status="inactive"))

        result = await self._run_get_sepa_status_with(pm, mandate_retrieve_fn=retrieve_fn)

        assert result["sepa_mandate_status"] == "inactive", (
            f"Expected 'inactive', got {result['sepa_mandate_status']!r}"
        )

    async def test_get_sepa_status_returns_requires_action_for_pending(self):
        """
        GIVEN Stripe PM has a mandate with status='pending'
        WHEN get_sepa_status is called
        THEN sepa_mandate_status == 'requires_action'
        (Stripe 'pending' maps to our REQUIRES_ACTION bucket)
        """
        mandate_id = "mandate_pending_789"
        pm = SimpleNamespace(
            sepa_debit=SimpleNamespace(last4="9012", mandate=mandate_id)
        )
        retrieve_fn = MagicMock(return_value=SimpleNamespace(status="pending"))

        result = await self._run_get_sepa_status_with(pm, mandate_retrieve_fn=retrieve_fn)

        assert result["sepa_mandate_status"] == "requires_action", (
            f"Expected 'requires_action', got {result['sepa_mandate_status']!r}"
        )

    async def test_get_sepa_status_returns_unknown_on_stripe_error(self):
        """
        GIVEN Stripe.Mandate.retrieve raises StripeError
        WHEN get_sepa_status is called
        THEN sepa_mandate_status == 'unknown'
        AND no exception propagates
        """
        from importlib import reload

        import api.services.stripe_service as stripe_mod

        stub = _make_stripe_stub_with_mandate()

        mandate_id = "mandate_err_000"
        pm = SimpleNamespace(
            sepa_debit=SimpleNamespace(last4="3456", mandate=mandate_id)
        )
        stub.PaymentMethod.retrieve = MagicMock(return_value=pm)
        stub.Mandate.retrieve = MagicMock(side_effect=stub.error.StripeError("Network error"))

        customer_setting = _make_system_setting("stripe_customer_id", "cus_abc")
        pm_setting = _make_system_setting("stripe_payment_method_id", "pm_sepa")
        last4_setting = _make_system_setting("stripe_payment_method_last4", "3456")

        session = _make_async_session()
        session.execute.side_effect = [
            _scalar_result(customer_setting),
            _scalar_result(pm_setting),
            _scalar_result(last4_setting),
        ]

        with patch.dict("sys.modules", {"stripe": stub, "stripe.error": stub.error}):
            reload(stripe_mod)
            svc = _build_stripe_service(_make_settings(stripe_key="sk_test_real"))
            # Must NOT raise
            result = await svc.get_sepa_status(session)

        assert result["sepa_mandate_status"] == "unknown", (
            f"Expected 'unknown', got {result['sepa_mandate_status']!r}"
        )

    async def test_get_sepa_status_returns_unknown_when_no_mandate_id(self):
        """
        GIVEN Stripe PM has sepa_debit but mandate attribute is None
        WHEN get_sepa_status is called
        THEN sepa_mandate_status == 'unknown'
        (mandate not yet created by Stripe)
        """
        pm = SimpleNamespace(
            sepa_debit=SimpleNamespace(last4="7890", mandate=None)
        )

        result = await self._run_get_sepa_status_with(pm)

        assert result["sepa_mandate_status"] == "unknown", (
            f"Expected 'unknown', got {result['sepa_mandate_status']!r}"
        )

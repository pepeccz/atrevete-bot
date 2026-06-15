"""
Test configuration and fixtures.

This module sets up test environment and provides shared fixtures for all tests.
"""

import asyncio
import os
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest


# Override DATABASE_URL and REDIS_URL for tests to use localhost instead of Docker hostname
# Must be set BEFORE any imports of database.connection or shared.config
# Skip override if running inside Docker (where postgres/redis hostnames resolve)
def _is_running_in_docker() -> bool:
    """Check if we're running inside a Docker container."""
    import socket
    # Try to resolve Docker service hostnames
    docker_hosts = ["postgres", "redis", "atrevete-postgres", "atrevete-redis"]
    for host in docker_hosts:
        try:
            socket.gethostbyname(host)
            return True  # Can resolve Docker hostname, we're in Docker
        except socket.gaierror:
            continue
    return False


# Only override DATABASE_URL/REDIS_URL when:
#   1. The caller has NOT already exported them (CI sets them explicitly)
#   2. AND we are not running inside Docker (where hostnames like 'postgres' resolve)
# This preserves CI-provided values (e.g. postgres:postgres@localhost in GitHub
# Actions) while still giving local pytest runs sensible defaults.
if not _is_running_in_docker():
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db",
    )
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

# Disable rate limiting in all tests by default.
# Individual tests that assert 429 behaviour must re-enable it via monkeypatch
# and mark themselves with the `rate_limit_required` pytest marker.
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")


# ---------------------------------------------------------------------------
# Stub Docker-only packages that are not installed in the local test environment.
#
# These packages are only available inside the Docker container but several
# project modules import them at the top level (not lazily). We stub them here
# so that `import agent.services.*` works in all unit tests without Docker.
#
# Pattern: create a real ModuleType (not MagicMock) so that
#   `from pkg import name`
# works — Python's import machinery does a real getattr() on the module object.
# ---------------------------------------------------------------------------
def _make_stub_module(name: str, **attrs) -> ModuleType:
    mod = ModuleType(name)
    mod.__name__ = name
    mod.__package__ = name.split(".")[0]
    mod.__spec__ = None
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


# google_auth_oauthlib — needed by agent/services/google_oauth_service.py
if "google_auth_oauthlib" not in sys.modules:
    sys.modules["google_auth_oauthlib"] = _make_stub_module("google_auth_oauthlib")
    sys.modules["google_auth_oauthlib.flow"] = _make_stub_module(
        "google_auth_oauthlib.flow", Flow=MagicMock()
    )

# googleapiclient — needed by gcal_push_service, calendar_tools, gcal_sync_worker.
# HttpError must be a proper class (not just `Exception`) so that tests which
# construct it via `HttpError(resp=..., content=...)` still work correctly.
if "googleapiclient" not in sys.modules:
    class _HttpError(Exception):
        """Minimal stub that mimics googleapiclient.errors.HttpError."""
        def __init__(self, resp=None, content=b"", uri=None, **kwargs):
            self.resp = resp
            self.content = content
            self.uri = uri
            super().__init__(str(resp))

    sys.modules["googleapiclient"] = _make_stub_module("googleapiclient")
    sys.modules["googleapiclient.discovery"] = _make_stub_module(
        "googleapiclient.discovery", build=MagicMock()
    )
    sys.modules["googleapiclient.errors"] = _make_stub_module(
        "googleapiclient.errors", HttpError=_HttpError
    )

# jose (python-jose) — needed by api/routes/admin.py for JWT handling
if "jose" not in sys.modules:
    class _JWTError(Exception):
        """Minimal stub that mimics jose.JWTError."""
        pass

    def _jwt_encode(payload, key, algorithm=None):
        return "stub_token"

    def _jwt_decode(token, key, algorithms=None, **kwargs):
        return {"sub": "test"}

    sys.modules["jose"] = _make_stub_module("jose", JWTError=_JWTError)
    sys.modules["jose.jwt"] = _make_stub_module(
        "jose.jwt", encode=_jwt_encode, decode=_jwt_decode
    )

# passlib — needed by api/routes/admin.py for bcrypt password hashing
if "passlib" not in sys.modules:
    class _bcrypt_stub:
        """Minimal stub that mimics passlib.hash.bcrypt."""
        @staticmethod
        def hash(password):
            return "hashed_password_stub"

        @staticmethod
        def verify(password, hash):
            return True

    sys.modules["passlib"] = _make_stub_module("passlib")
    sys.modules["passlib.hash"] = _make_stub_module("passlib.hash", bcrypt=_bcrypt_stub)

# groq — needed by api/routes/chatwoot.py for audio transcription
if "groq" not in sys.modules:
    class _RateLimitError(Exception):
        """Minimal stub that mimics groq.RateLimitError."""
        pass

    class _APIError(Exception):
        """Minimal stub that mimics groq.APIError."""
        pass

    class _AsyncGroq_stub:
        """Minimal stub that mimics groq.AsyncGroq."""
        pass

    sys.modules["groq"] = _make_stub_module(
        "groq", RateLimitError=_RateLimitError, APIError=_APIError, AsyncGroq=_AsyncGroq_stub
    )

# pydub — needed by shared/audio_conversion.py for audio conversion
if "pydub" not in sys.modules:
    class _AudioSegment_stub:
        """Minimal stub that mimics pydub.AudioSegment."""
        @staticmethod
        def from_ogg(path):
            return _AudioSegment_stub()

        def export(self, path, format=None):
            return self

    sys.modules["pydub"] = _make_stub_module("pydub", AudioSegment=_AudioSegment_stub)

# stripe — needed by api/services/stripe_service.py and billing routes.
# ADR-2: explicit class stubs (not blanket MagicMock) so isinstance() and
# exception-catching work correctly.  Follow the googleapiclient.errors pattern.
if "stripe" not in sys.modules:
    from types import SimpleNamespace as _SN

    # ---------------------------------------------------------------------------
    # Error hierarchy
    # ---------------------------------------------------------------------------
    class _StripeError(Exception):
        """Minimal stub that mimics stripe.error.StripeError."""
        pass

    class _StripeInvalidRequestError(_StripeError):
        """Minimal stub that mimics stripe.error.InvalidRequestError."""
        def __init__(self, message="", param=None, **kwargs):
            super().__init__(message)
            self.param = param

    class _StripeSignatureVerificationError(_StripeError):
        """Minimal stub that mimics stripe.error.SignatureVerificationError."""
        def __init__(self, message="Invalid signature", sig_header=None, **kwargs):
            super().__init__(message)
            self.sig_header = sig_header

    # ---------------------------------------------------------------------------
    # Resource stubs — each has create / retrieve / modify / list classmethods.
    # ---------------------------------------------------------------------------
    class _StripeInvoice:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
            if not hasattr(self, "id"):
                self.id = "in_stub"
            if not hasattr(self, "status"):
                self.status = "draft"

        @staticmethod
        def create(**kwargs):
            return _StripeInvoice(**kwargs)

        @staticmethod
        def retrieve(sid, **kwargs):
            obj = _SN()
            obj.id = sid
            obj.status = "draft"
            return obj

        @staticmethod
        def modify(sid, **kwargs):
            obj = _SN()
            obj.id = sid
            for k, v in kwargs.items():
                setattr(obj, k, v)
            return obj

        @staticmethod
        def list(**kwargs):
            return _SN(data=[])

        @staticmethod
        def finalize_invoice(sid, **kwargs):
            obj = _SN()
            obj.id = sid
            obj.status = "open"
            return obj

        @staticmethod
        def pay(sid, **kwargs):
            obj = _SN()
            obj.id = sid
            obj.status = "paid"
            return obj

        @staticmethod
        def send_invoice(sid, **kwargs):
            obj = _SN()
            obj.id = sid
            return obj

        @staticmethod
        def void_invoice(sid, **kwargs):
            obj = _SN()
            obj.id = sid
            obj.status = "void"
            return obj

    class _StripeInvoiceItem:
        @staticmethod
        def create(**kwargs):
            obj = _SN()
            obj.id = "ii_stub"
            for k, v in kwargs.items():
                setattr(obj, k, v)
            return obj

        @staticmethod
        def retrieve(sid, **kwargs):
            return _SN(id=sid)

        @staticmethod
        def modify(sid, **kwargs):
            return _SN(id=sid)

        @staticmethod
        def list(**kwargs):
            return _SN(data=[])

    class _StripePaymentMethod:
        @staticmethod
        def create(**kwargs):
            obj = _SN()
            obj.id = "pm_stub"
            obj.type = kwargs.get("type", "card")
            obj.sepa_debit = _SN(last4="1234")
            return obj

        @staticmethod
        def retrieve(sid, **kwargs):
            obj = _SN()
            obj.id = sid
            obj.sepa_debit = _SN(last4="1234")
            return obj

        @staticmethod
        def modify(sid, **kwargs):
            return _SN(id=sid)

        @staticmethod
        def list(**kwargs):
            return _SN(data=[])

        @staticmethod
        def attach(pm_id, **kwargs):
            return _SN(id=pm_id)

    class _StripeSubscription:
        @staticmethod
        def create(**kwargs):
            return _SN(id="sub_stub", status="active")

        @staticmethod
        def retrieve(sid, **kwargs):
            return _SN(id=sid, status="active")

        @staticmethod
        def modify(sid, **kwargs):
            return _SN(id=sid)

        @staticmethod
        def list(**kwargs):
            return _SN(data=[])

        @staticmethod
        def cancel(sid, **kwargs):
            return _SN(id=sid, status="canceled")

    class _StripeCustomer:
        @staticmethod
        def create(**kwargs):
            return _SN(id="cus_stub")

        @staticmethod
        def retrieve(sid, **kwargs):
            return _SN(id=sid)

        @staticmethod
        def modify(sid, **kwargs):
            return _SN(id=sid)

        @staticmethod
        def list(**kwargs):
            return _SN(data=[])

    class _StripeCharge:
        @staticmethod
        def create(**kwargs):
            return _SN(id="ch_stub", status="succeeded")

        @staticmethod
        def retrieve(sid, **kwargs):
            return _SN(id=sid, status="succeeded")

        @staticmethod
        def modify(sid, **kwargs):
            return _SN(id=sid)

        @staticmethod
        def list(**kwargs):
            return _SN(data=[])

    class _StripeRefund:
        @staticmethod
        def create(**kwargs):
            return _SN(id="re_stub", status="succeeded")

        @staticmethod
        def retrieve(sid, **kwargs):
            return _SN(id=sid)

        @staticmethod
        def modify(sid, **kwargs):
            return _SN(id=sid)

        @staticmethod
        def list(**kwargs):
            return _SN(data=[])

    class _StripeEvent:
        @staticmethod
        def retrieve(sid, **kwargs):
            return _SN(id=sid, type="test.event", data=_SN(object={}))

        @staticmethod
        def list(**kwargs):
            return _SN(data=[])

    class _StripeWebhook:
        @staticmethod
        def construct_event(payload, sig_header, secret, **kwargs):
            return _SN(type="test.event", data=_SN(object={}))

    # SetupIntent — also commonly needed
    class _StripeSetupIntent:
        @staticmethod
        def create(**kwargs):
            return _SN(id="seti_stub", status="requires_action")

        @staticmethod
        def retrieve(sid, **kwargs):
            return _SN(id=sid, payment_method="pm_stub")

        @staticmethod
        def list(**kwargs):
            return _SN(data=[])

    # PaymentIntent — also needed in billing routes
    class _StripePaymentIntent:
        @staticmethod
        def create(**kwargs):
            return _SN(id="pi_stub", status="processing")

        @staticmethod
        def retrieve(sid, **kwargs):
            return _SN(id=sid, status="processing")

        @staticmethod
        def cancel(sid, **kwargs):
            return _SN(id=sid, status="canceled")

        @staticmethod
        def modify(sid, **kwargs):
            return _SN(id=sid)

    # TaxRate — needed by billing routes
    class _StripeTaxRate:
        @staticmethod
        def create(**kwargs):
            return _SN(id="txr_stub")

        @staticmethod
        def retrieve(sid, **kwargs):
            return _SN(id=sid)

        @staticmethod
        def list(**kwargs):
            return _SN(data=[])

    # checkout.Session stub
    _stripe_checkout = _make_stub_module("stripe.checkout")

    class _CheckoutSession:
        @staticmethod
        def create(**kwargs):
            return _SN(url="https://checkout.stripe.com/test", id="cs_stub")

        @staticmethod
        def retrieve(sid, **kwargs):
            return _SN(id=sid, url="https://checkout.stripe.com/test")

    _stripe_checkout.Session = _CheckoutSession

    # error submodule
    _stripe_error = _make_stub_module(
        "stripe.error",
        StripeError=_StripeError,
        InvalidRequestError=_StripeInvalidRequestError,
        SignatureVerificationError=_StripeSignatureVerificationError,
    )

    # Main stripe module
    _stripe_mod = _make_stub_module(
        "stripe",
        # Error aliases at top-level (stripe.StripeError is common)
        StripeError=_StripeError,
        # Resource classes
        Invoice=_StripeInvoice,
        InvoiceItem=_StripeInvoiceItem,
        PaymentMethod=_StripePaymentMethod,
        Subscription=_StripeSubscription,
        Customer=_StripeCustomer,
        Charge=_StripeCharge,
        Refund=_StripeRefund,
        Event=_StripeEvent,
        Webhook=_StripeWebhook,
        SetupIntent=_StripeSetupIntent,
        PaymentIntent=_StripePaymentIntent,
        TaxRate=_StripeTaxRate,
        # Submodules
        error=_stripe_error,
        checkout=_stripe_checkout,
        # api_key placeholder (stripe_service sets this at init)
        api_key=None,
    )

    sys.modules["stripe"] = _stripe_mod
    sys.modules["stripe.error"] = _stripe_error
    sys.modules["stripe.checkout"] = _stripe_checkout


# ---------------------------------------------------------------------------
# Booking-specific test helpers (B.1.4)
# ---------------------------------------------------------------------------

# Tags that must NOT appear in any message sent to the LLM after Phase B.1.
_BANNED_XML_TAGS = (
    "<booking_context>",
    "<flow_hint>",
    "<audience_ambiguity>",
    "<audience_hint>",
    "<opening_booking_request>",
    "<suggested_name>",
    "<offered_slots>",
    "<available_stylists>",
    "<conversation_summary>",
    "<min_valid_date>",
)


def assert_no_legacy_xml_tags(messages: list) -> None:
    """Assert that no banned legacy XML tags exist in any message content.

    Use this in tests that capture the messages passed to the LLM to verify
    _build_dynamic_context() XML output has been fully removed.
    """

    for msg in messages:
        content = getattr(msg, "content", "")
        if not isinstance(content, str):
            continue
        for tag in _BANNED_XML_TAGS:
            assert tag not in content, (
                f"Legacy XML tag {tag!r} found in {type(msg).__name__}: "
                f"{content[:300]!r}"
            )


@pytest.fixture(scope="function")
def event_loop():
    """
    Create a new event loop for each test function.

    This prevents "Future attached to a different loop" errors with SQLAlchemy async.
    Each test gets a fresh event loop that is properly closed after the test.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture(scope="function", autouse=True)
async def cleanup_engine():
    """
    Clean up database engine and Redis connections after each test.

    This ensures connection pools don't interfere between tests and
    prevents "Future attached to different loop" errors.

    NOTE (test-isolation-refactor): This fixture is retained for PR-1 because
    many tests rely on a real asyncpg connection pool. Once PR-2 introduces the
    savepoint-based db_session fixture, tests will be migrated away from the raw
    engine and this fixture can be safely removed at that point.
    """
    yield
    # Dispose engine after each test to release connections
    # Only if we're using a real engine (not mocked)
    from unittest.mock import Mock

    from database.connection import engine
    if hasattr(engine, 'dispose') and not isinstance(engine, Mock):
        try:
            await engine.dispose()
        except RuntimeError as e:
            if "event loop is closed" in str(e).lower():
                pass  # Loop already closed — engine will be GC'd
            else:
                raise

    # Close Redis connections
    try:
        from shared.redis_client import get_redis_client
        redis_client = get_redis_client()
        if redis_client is not None and not isinstance(redis_client, Mock):
            await redis_client.close()
    except Exception:  # noqa: S110
        pass  # Redis client may not be initialized


@pytest.fixture(scope="module", autouse=True)
def dispose_engine_after_module():
    """
    Module-scoped sync fixture: disposes the SQLAlchemy engine pool after ALL tests
    in the current module have completed.

    Addresses cross-module event-loop contamination: when a module uses
    `loop_scope="module"`, its asyncpg connections are bound to that module's loop.
    After the module finishes and its loop closes, those connections become invalid.
    The next module's tests would error with "Future attached to a different loop" when
    trying to acquire a new connection from the pool.

    Uses asyncio.run() (creates a fresh temporary loop) so this sync fixture can safely
    call async engine.dispose() without needing the module's (already-closed) event loop.
    """
    yield  # all tests in this module run here

    import asyncio as _asyncio
    from unittest.mock import Mock

    from database.connection import engine as _engine

    if not hasattr(_engine, "dispose") or isinstance(_engine, Mock):
        return

    async def _dispose() -> None:
        try:
            await _engine.dispose()
        except Exception:  # noqa: BLE001
            pass  # best-effort — pool will be recreated on next use

    try:
        _asyncio.run(_dispose())
    except RuntimeError:
        pass  # event loop already running or other edge case — safe to ignore

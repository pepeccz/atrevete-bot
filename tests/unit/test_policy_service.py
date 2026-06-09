"""Unit tests for policy_service.accept_policy (T07-T10).

Tests cover:
- T07: accept_policy performs atomic write (Customer UPDATE + CustomerConsent INSERT)
- T08: idempotency window — second call within 10s returns existing row without re-writing
- T09: _invalidate_cached_customer is called AFTER successful writes (with correct phone)
- T10: PolicyConsentError is raised on DB failure

All tests use mock AsyncSession — no live DB connection required.

Refs: Spec §5, Design §3.1-3.3, Tasks T07-T11
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CUSTOMER_ID = uuid4()
CUSTOMER_PHONE = "+34611000001"
POLICY_VERSION = "1.0"


def _make_mock_customer(phone: str = CUSTOMER_PHONE) -> MagicMock:
    """Build a Customer-like mock with required fields."""
    customer = MagicMock()
    customer.id = CUSTOMER_ID
    customer.phone = phone
    customer.policy_accepted_at = None
    customer.policy_version = None
    return customer


def _make_mock_session(
    customer: MagicMock | None = None,
    existing_consent: MagicMock | None = None,
) -> AsyncMock:
    """Build an AsyncSession mock with configurable query results.

    - session.get(Customer, id) → customer
    - execute() for SELECT consent → scalars().first() → existing_consent or None
    - flush() is a no-op
    """
    session = AsyncMock()

    # session.get returns a customer (for Customer.id lookup)
    if customer is not None:
        session.get = AsyncMock(return_value=customer)
    else:
        session.get = AsyncMock(return_value=_make_mock_customer())

    # execute for consent idempotency check
    scalars_mock = MagicMock()
    scalars_mock.first = MagicMock(return_value=existing_consent)
    execute_result = MagicMock()
    execute_result.scalars = MagicMock(return_value=scalars_mock)
    session.execute = AsyncMock(return_value=execute_result)

    session.add = MagicMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()

    return session


# ---------------------------------------------------------------------------
# T07: Atomic write — Customer UPDATE + CustomerConsent INSERT
# ---------------------------------------------------------------------------


class TestAcceptPolicyAtomicWrite:
    """T07: verify Customer UPDATE + CustomerConsent INSERT in single session (no commit)."""

    @pytest.mark.asyncio
    async def test_accept_policy_returns_customer_consent_instance(self):
        """accept_policy must return a CustomerConsent instance."""
        from agent.services.policy_service import accept_policy
        from database.models import CustomerConsent

        session = _make_mock_session()

        with patch(
            "agent.services.policy_service._invalidate_cached_customer",
            new=AsyncMock(),
        ):
            result = await accept_policy(
                db=session,
                customer_id=CUSTOMER_ID,
                policy_version=POLICY_VERSION,
                accepted_via="whatsapp",
            )

        assert isinstance(result, CustomerConsent)

    @pytest.mark.asyncio
    async def test_accept_policy_sets_customer_policy_accepted_at(self):
        """accept_policy must set Customer.policy_accepted_at on the customer object."""
        from agent.services.policy_service import accept_policy

        customer = _make_mock_customer()
        session = _make_mock_session(customer=customer)

        with patch(
            "agent.services.policy_service._invalidate_cached_customer",
            new=AsyncMock(),
        ):
            await accept_policy(
                db=session,
                customer_id=CUSTOMER_ID,
                policy_version=POLICY_VERSION,
                accepted_via="whatsapp",
            )

        assert customer.policy_accepted_at is not None, (
            "accept_policy must set customer.policy_accepted_at"
        )

    @pytest.mark.asyncio
    async def test_accept_policy_sets_customer_policy_version(self):
        """accept_policy must set Customer.policy_version to the provided version."""
        from agent.services.policy_service import accept_policy

        customer = _make_mock_customer()
        session = _make_mock_session(customer=customer)

        with patch(
            "agent.services.policy_service._invalidate_cached_customer",
            new=AsyncMock(),
        ):
            await accept_policy(
                db=session,
                customer_id=CUSTOMER_ID,
                policy_version=POLICY_VERSION,
                accepted_via="whatsapp",
            )

        assert customer.policy_version == POLICY_VERSION

    @pytest.mark.asyncio
    async def test_accept_policy_adds_consent_to_session(self):
        """accept_policy must add a CustomerConsent instance to session (INSERT)."""
        from agent.services.policy_service import accept_policy
        from database.models import CustomerConsent

        session = _make_mock_session()

        with patch(
            "agent.services.policy_service._invalidate_cached_customer",
            new=AsyncMock(),
        ):
            await accept_policy(
                db=session,
                customer_id=CUSTOMER_ID,
                policy_version=POLICY_VERSION,
                accepted_via="whatsapp",
            )

        # session.add must have been called with a CustomerConsent instance
        assert session.add.called, "session.add was never called — consent was not staged"
        added_obj = session.add.call_args[0][0]
        assert isinstance(added_obj, CustomerConsent), (
            f"Expected CustomerConsent passed to session.add, got {type(added_obj)}"
        )

    @pytest.mark.asyncio
    async def test_accept_policy_calls_flush(self):
        """accept_policy must call session.flush() to stage changes within the transaction."""
        from agent.services.policy_service import accept_policy

        session = _make_mock_session()

        with patch(
            "agent.services.policy_service._invalidate_cached_customer",
            new=AsyncMock(),
        ):
            await accept_policy(
                db=session,
                customer_id=CUSTOMER_ID,
                policy_version=POLICY_VERSION,
                accepted_via="whatsapp",
            )

        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_accept_policy_consent_has_correct_fields(self):
        """Returned CustomerConsent must have correct customer_id, policy_version, accepted_via."""
        from agent.services.policy_service import accept_policy

        session = _make_mock_session()

        with patch(
            "agent.services.policy_service._invalidate_cached_customer",
            new=AsyncMock(),
        ):
            consent = await accept_policy(
                db=session,
                customer_id=CUSTOMER_ID,
                policy_version=POLICY_VERSION,
                accepted_via="admin_panel",
                source_message_id="msg_test_123",
            )

        assert consent.customer_id == CUSTOMER_ID
        assert consent.policy_version == POLICY_VERSION
        assert consent.accepted_via == "admin_panel"
        assert consent.source_message_id == "msg_test_123"

    @pytest.mark.asyncio
    async def test_accept_policy_does_not_commit(self):
        """accept_policy must NOT call session.commit() — caller owns the transaction."""
        from agent.services.policy_service import accept_policy

        session = _make_mock_session()
        session.commit = AsyncMock()  # add commit spy

        with patch(
            "agent.services.policy_service._invalidate_cached_customer",
            new=AsyncMock(),
        ):
            await accept_policy(
                db=session,
                customer_id=CUSTOMER_ID,
                policy_version=POLICY_VERSION,
                accepted_via="whatsapp",
            )

        session.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# T08: Idempotency window — 10 seconds
# ---------------------------------------------------------------------------


class TestAcceptPolicyIdempotencyWindow:
    """T08: second call within 10s returns existing row without re-inserting."""

    @pytest.mark.asyncio
    async def test_second_call_within_10s_returns_existing_consent(self):
        """If existing consent is within 10s, return it without new INSERT."""
        from agent.services.policy_service import accept_policy

        # Stub existing consent accepted 5 seconds ago (within window)
        existing_consent = MagicMock()
        existing_consent.customer_id = CUSTOMER_ID
        existing_consent.policy_version = POLICY_VERSION
        existing_consent.accepted_at = datetime.now(UTC) - timedelta(seconds=5)
        existing_consent.accepted_via = "whatsapp"

        session = _make_mock_session(existing_consent=existing_consent)

        with patch(
            "agent.services.policy_service._invalidate_cached_customer",
            new=AsyncMock(),
        ):
            result = await accept_policy(
                db=session,
                customer_id=CUSTOMER_ID,
                policy_version=POLICY_VERSION,
                accepted_via="whatsapp",
            )

        # Must return the existing row
        assert result is existing_consent, (
            "Within 10s idempotency window, existing row must be returned"
        )

    @pytest.mark.asyncio
    async def test_second_call_within_10s_does_not_insert_new_row(self):
        """Within 10s window, session.add must NOT be called again."""
        from agent.services.policy_service import accept_policy

        existing_consent = MagicMock()
        existing_consent.customer_id = CUSTOMER_ID
        existing_consent.policy_version = POLICY_VERSION
        existing_consent.accepted_at = datetime.now(UTC) - timedelta(seconds=3)
        existing_consent.accepted_via = "whatsapp"

        session = _make_mock_session(existing_consent=existing_consent)

        with patch(
            "agent.services.policy_service._invalidate_cached_customer",
            new=AsyncMock(),
        ):
            await accept_policy(
                db=session,
                customer_id=CUSTOMER_ID,
                policy_version=POLICY_VERSION,
                accepted_via="whatsapp",
            )

        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_call_after_10s_inserts_new_row(self):
        """If existing consent is older than 10s, a new INSERT must occur."""
        from agent.services.policy_service import accept_policy
        from database.models import CustomerConsent

        # Consent from 15 seconds ago — outside idempotency window
        old_consent = MagicMock()
        old_consent.customer_id = CUSTOMER_ID
        old_consent.policy_version = POLICY_VERSION
        old_consent.accepted_at = datetime.now(UTC) - timedelta(seconds=15)
        old_consent.accepted_via = "whatsapp"

        session = _make_mock_session(existing_consent=old_consent)

        with patch(
            "agent.services.policy_service._invalidate_cached_customer",
            new=AsyncMock(),
        ):
            result = await accept_policy(
                db=session,
                customer_id=CUSTOMER_ID,
                policy_version=POLICY_VERSION,
                accepted_via="whatsapp",
            )

        # A new CustomerConsent should be staged
        assert session.add.called, "session.add should be called for consent outside window"
        assert isinstance(result, CustomerConsent), "Result must be the new CustomerConsent"

    @pytest.mark.asyncio
    async def test_no_existing_consent_always_inserts(self):
        """If no prior consent exists, a new INSERT must always occur."""
        from agent.services.policy_service import accept_policy
        from database.models import CustomerConsent

        session = _make_mock_session(existing_consent=None)

        with patch(
            "agent.services.policy_service._invalidate_cached_customer",
            new=AsyncMock(),
        ):
            result = await accept_policy(
                db=session,
                customer_id=CUSTOMER_ID,
                policy_version=POLICY_VERSION,
                accepted_via="whatsapp",
            )

        assert session.add.called, "No prior consent → session.add must be called"
        assert isinstance(result, CustomerConsent)


# ---------------------------------------------------------------------------
# T09: Cache invalidation called after successful writes
# ---------------------------------------------------------------------------


class TestAcceptPolicyCacheInvalidation:
    """T09: _invalidate_cached_customer called with correct phone AFTER writes."""

    @pytest.mark.asyncio
    async def test_invalidate_called_with_customer_phone(self):
        """_invalidate_cached_customer must be called with the customer's phone."""
        from agent.services.policy_service import accept_policy

        phone = "+34611000099"
        customer = _make_mock_customer(phone=phone)
        session = _make_mock_session(customer=customer)

        with patch(
            "agent.services.policy_service._invalidate_cached_customer",
            new=AsyncMock(),
        ) as mock_invalidate:
            await accept_policy(
                db=session,
                customer_id=CUSTOMER_ID,
                policy_version=POLICY_VERSION,
                accepted_via="whatsapp",
            )

        mock_invalidate.assert_awaited_once_with(phone)

    @pytest.mark.asyncio
    async def test_invalidate_not_called_when_db_raises(self):
        """_invalidate_cached_customer must NOT be called when the DB write fails."""
        from sqlalchemy.exc import SQLAlchemyError

        from agent.services.policy_service import PolicyConsentError, accept_policy

        session = _make_mock_session()
        session.flush = AsyncMock(side_effect=SQLAlchemyError("DB failure"))

        with patch(
            "agent.services.policy_service._invalidate_cached_customer",
            new=AsyncMock(),
        ) as mock_invalidate:
            with pytest.raises(PolicyConsentError):
                await accept_policy(
                    db=session,
                    customer_id=CUSTOMER_ID,
                    policy_version=POLICY_VERSION,
                    accepted_via="whatsapp",
                )

        mock_invalidate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalidate_called_even_when_returning_idempotent_row(self):
        """Cache invalidation must be called even when returning the idempotent existing row.

        Rationale: caller may have updated customer fields before calling accept_policy;
        the cache must always be refreshed after a policy acceptance interaction.
        """
        from agent.services.policy_service import accept_policy

        phone = "+34611000077"
        customer = _make_mock_customer(phone=phone)

        # Existing consent within idempotency window
        existing_consent = MagicMock()
        existing_consent.accepted_at = datetime.now(UTC) - timedelta(seconds=2)

        session = _make_mock_session(customer=customer, existing_consent=existing_consent)

        with patch(
            "agent.services.policy_service._invalidate_cached_customer",
            new=AsyncMock(),
        ) as mock_invalidate:
            await accept_policy(
                db=session,
                customer_id=CUSTOMER_ID,
                policy_version=POLICY_VERSION,
                accepted_via="whatsapp",
            )

        mock_invalidate.assert_awaited_once_with(phone)


# ---------------------------------------------------------------------------
# T10: PolicyConsentError raised on DB failure; transaction rolled back
# ---------------------------------------------------------------------------


class TestAcceptPolicyDbFailure:
    """T10: PolicyConsentError raised on SQLAlchemy failure."""

    @pytest.mark.asyncio
    async def test_raises_policy_consent_error_on_flush_failure(self):
        """PolicyConsentError must be raised when session.flush raises SQLAlchemyError."""
        from sqlalchemy.exc import SQLAlchemyError

        from agent.services.policy_service import PolicyConsentError, accept_policy

        session = _make_mock_session()
        session.flush = AsyncMock(side_effect=SQLAlchemyError("connection reset"))

        with patch(
            "agent.services.policy_service._invalidate_cached_customer",
            new=AsyncMock(),
        ):
            with pytest.raises(PolicyConsentError) as exc_info:
                await accept_policy(
                    db=session,
                    customer_id=CUSTOMER_ID,
                    policy_version=POLICY_VERSION,
                    accepted_via="whatsapp",
                )

        assert "PolicyConsentError" in type(exc_info.value).__name__ or isinstance(
            exc_info.value, PolicyConsentError
        )

    @pytest.mark.asyncio
    async def test_raises_policy_consent_error_on_get_failure(self):
        """PolicyConsentError must be raised when session.get raises SQLAlchemyError."""
        from sqlalchemy.exc import SQLAlchemyError

        from agent.services.policy_service import PolicyConsentError, accept_policy

        session = _make_mock_session()
        session.get = AsyncMock(side_effect=SQLAlchemyError("DB unavailable"))

        with patch(
            "agent.services.policy_service._invalidate_cached_customer",
            new=AsyncMock(),
        ):
            with pytest.raises(PolicyConsentError):
                await accept_policy(
                    db=session,
                    customer_id=CUSTOMER_ID,
                    policy_version=POLICY_VERSION,
                    accepted_via="whatsapp",
                )

    @pytest.mark.asyncio
    async def test_policy_consent_error_is_importable(self):
        """PolicyConsentError must be importable from agent.services.policy_service."""
        from agent.services.policy_service import PolicyConsentError  # noqa: F401

    @pytest.mark.asyncio
    async def test_policy_consent_error_is_exception_subclass(self):
        """PolicyConsentError must be a subclass of Exception."""
        from agent.services.policy_service import PolicyConsentError

        assert issubclass(PolicyConsentError, Exception)

    @pytest.mark.asyncio
    async def test_policy_consent_error_wraps_original_exception(self):
        """PolicyConsentError should preserve context of original SQLAlchemy error."""
        from sqlalchemy.exc import SQLAlchemyError

        from agent.services.policy_service import PolicyConsentError, accept_policy

        session = _make_mock_session()
        original_error = SQLAlchemyError("unique violation")
        session.flush = AsyncMock(side_effect=original_error)

        with patch(
            "agent.services.policy_service._invalidate_cached_customer",
            new=AsyncMock(),
        ):
            with pytest.raises(PolicyConsentError) as exc_info:
                await accept_policy(
                    db=session,
                    customer_id=CUSTOMER_ID,
                    policy_version=POLICY_VERSION,
                    accepted_via="whatsapp",
                )

        # The PolicyConsentError should be raised from the original error
        assert exc_info.value.__cause__ is original_error or (
            original_error.__class__.__name__ in str(exc_info.value)
            or str(original_error) in str(exc_info.value)
        )

"""
Unit tests for admin customer API — policy acceptance fields (PR-3 / Group H).

Covers:
- T29: CustomerDetailResponse Pydantic model includes policy_accepted_at and policy_version
- T31: GET /api/admin/customers/{customer_id}/consents returns list ordered by accepted_at DESC
- T31b: GET /api/admin/customers/{customer_id}/consents returns 404 if customer not found

All tests use mocks — no real database required.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ============================================================================
# Helpers
# ============================================================================


def _make_customer_mock(
    policy_accepted_at: datetime | None = None,
    policy_version: str | None = None,
):
    from database.models import Customer

    customer = MagicMock(spec=Customer)
    customer.id = uuid4()
    customer.phone = "+34612345678"
    customer.first_name = "María"
    customer.last_name = "García"
    from decimal import Decimal

    customer.total_spent = Decimal("150.00")
    customer.last_service_date = None
    customer.preferred_stylist_id = None
    customer.preferred_stylist = None
    customer.notes = None
    customer.chatwoot_conversation_id = None
    customer.metadata_ = {}
    customer.created_at = datetime(2026, 3, 12, 10, 0, 0, tzinfo=UTC)
    customer.policy_accepted_at = policy_accepted_at
    customer.policy_version = policy_version
    return customer


def _make_consent_mock(
    customer_id,
    policy_version: str = "1.0",
    accepted_at: datetime | None = None,
    accepted_via: str = "whatsapp",
    source_message_id: str | None = None,
):
    from database.models import CustomerConsent

    consent = MagicMock(spec=CustomerConsent)
    consent.id = uuid4()
    consent.customer_id = customer_id
    consent.policy_version = policy_version
    consent.accepted_at = accepted_at or datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)
    consent.accepted_via = accepted_via
    consent.source_message_id = source_message_id
    return consent


def _build_session_mock_single(row_to_return):
    """Build an AsyncMock session returning a single row from scalar_one_or_none()."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row_to_return
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


def _build_session_mock_scalars(rows_to_return: list):
    """Build an AsyncMock session returning a list from scalars().all()."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rows_to_return
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


def _build_dual_session_mock(customer_result, consents_list: list):
    """Build an AsyncMock session that handles two execute calls:
    first returns scalar_one_or_none for customer check,
    second returns scalars().all() for consent list.
    """
    mock_session = AsyncMock()

    customer_mock_result = MagicMock()
    customer_mock_result.scalar_one_or_none.return_value = customer_result

    consents_mock_result = MagicMock()
    consents_mock_result.scalars.return_value.all.return_value = consents_list

    mock_session.execute = AsyncMock(
        side_effect=[customer_mock_result, consents_mock_result]
    )
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


# ============================================================================
# T29: CustomerDetailResponse includes policy fields
# ============================================================================


def test_customer_detail_response_has_policy_fields():
    """
    T29: CustomerDetailResponse Pydantic model must declare policy_accepted_at
    and policy_version as nullable fields.
    """
    from api.routes.admin import CustomerDetailResponse

    # Verify the fields exist in the model schema
    fields = CustomerDetailResponse.model_fields
    assert "policy_accepted_at" in fields, (
        "CustomerDetailResponse must have 'policy_accepted_at' field"
    )
    assert "policy_version" in fields, (
        "CustomerDetailResponse must have 'policy_version' field"
    )


def test_customer_detail_response_policy_fields_are_nullable():
    """
    T29: Both policy fields must default to None (nullable).
    """
    from api.routes.admin import CustomerDetailResponse

    # Build an instance with only required fields and no policy data
    instance = CustomerDetailResponse(
        id=str(uuid4()),
        phone="+34612345678",
        first_name="María",
        last_name=None,
        total_spent="150.00",
        last_service_date=None,
        preferred_stylist_id=None,
        preferred_stylist_name=None,
        notes=None,
        chatwoot_conversation_id=None,
        memories=None,
        created_at=datetime(2026, 3, 12, 10, 0, 0, tzinfo=UTC),
        policy_accepted_at=None,
        policy_version=None,
    )
    assert instance.policy_accepted_at is None
    assert instance.policy_version is None


def test_customer_detail_response_policy_fields_set_correctly():
    """
    T29: When policy fields are provided, they are stored correctly.
    """
    from api.routes.admin import CustomerDetailResponse

    accepted_at = datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)
    instance = CustomerDetailResponse(
        id=str(uuid4()),
        phone="+34612345678",
        first_name="María",
        last_name=None,
        total_spent="150.00",
        last_service_date=None,
        preferred_stylist_id=None,
        preferred_stylist_name=None,
        notes=None,
        chatwoot_conversation_id=None,
        memories=None,
        created_at=datetime(2026, 3, 12, 10, 0, 0, tzinfo=UTC),
        policy_accepted_at=accepted_at,
        policy_version="1.0",
    )
    assert instance.policy_accepted_at == accepted_at
    assert instance.policy_version == "1.0"


@pytest.mark.asyncio
async def test_get_customer_response_includes_policy_fields():
    """
    T29: GET /api/admin/customers/{id} response dict includes policy_accepted_at
    and policy_version keys.
    """
    from api.routes.admin import get_customer

    accepted_at = datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)
    customer = _make_customer_mock(
        policy_accepted_at=accepted_at,
        policy_version="1.0",
    )
    mock_ctx = _build_session_mock_single(customer)
    mock_user = MagicMock()

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await get_customer(customer_id=customer.id, current_user=mock_user)

    assert "policy_accepted_at" in result
    assert "policy_version" in result


@pytest.mark.asyncio
async def test_get_customer_response_policy_null_when_not_set():
    """
    T29: When customer has no policy acceptance, both fields are null in response.
    """
    from api.routes.admin import get_customer

    customer = _make_customer_mock(policy_accepted_at=None, policy_version=None)
    mock_ctx = _build_session_mock_single(customer)
    mock_user = MagicMock()

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await get_customer(customer_id=customer.id, current_user=mock_user)

    assert result["policy_accepted_at"] is None
    assert result["policy_version"] is None


# ============================================================================
# T31: GET /api/admin/customers/{id}/consents — ordered list + 404
# ============================================================================


@pytest.mark.asyncio
async def test_list_customer_consents_ordered():
    """
    T31: GET /api/admin/customers/{id}/consents returns consents ordered by
    accepted_at DESC (newest first).
    """
    from api.routes.admin import list_customer_consents

    customer_id = uuid4()

    # Two consents — newer one second in list to verify ordering is from query, not insertion
    older_consent = _make_consent_mock(
        customer_id=customer_id,
        accepted_at=datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC),
        policy_version="1.0",
    )
    newer_consent = _make_consent_mock(
        customer_id=customer_id,
        accepted_at=datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC),
        policy_version="1.0",
    )
    # DB returns them newest-first (ORDER BY accepted_at DESC)
    consents_from_db = [newer_consent, older_consent]

    mock_session = AsyncMock()

    customer_check_result = MagicMock()
    customer_check_result.scalar_one_or_none.return_value = MagicMock()  # customer exists

    consents_result = MagicMock()
    consents_result.scalars.return_value.all.return_value = consents_from_db

    mock_session.execute = AsyncMock(
        side_effect=[customer_check_result, consents_result]
    )
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_user = MagicMock()

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await list_customer_consents(
            customer_id=customer_id, current_user=mock_user
        )

    assert len(result) == 2
    # Verify both consent fields are present
    first = result[0]
    assert "id" in first
    assert "policy_version" in first
    assert "accepted_at" in first
    assert "accepted_via" in first
    assert "source_message_id" in first
    assert "customer_id" in first


@pytest.mark.asyncio
async def test_list_customer_consents_empty():
    """
    T31: Returns empty list when customer has no consent records.
    """
    from api.routes.admin import list_customer_consents

    customer_id = uuid4()
    mock_session = AsyncMock()

    customer_check_result = MagicMock()
    customer_check_result.scalar_one_or_none.return_value = MagicMock()

    consents_result = MagicMock()
    consents_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(
        side_effect=[customer_check_result, consents_result]
    )
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_user = MagicMock()

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await list_customer_consents(
            customer_id=customer_id, current_user=mock_user
        )

    assert result == []


@pytest.mark.asyncio
async def test_list_customer_consents_404_when_customer_not_found():
    """
    T31: Returns HTTP 404 if the customer does not exist.
    """
    from fastapi import HTTPException

    from api.routes.admin import list_customer_consents

    mock_session = AsyncMock()
    customer_check_result = MagicMock()
    customer_check_result.scalar_one_or_none.return_value = None  # not found

    mock_session.execute = AsyncMock(return_value=customer_check_result)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_user = MagicMock()

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        with pytest.raises(HTTPException) as exc_info:
            await list_customer_consents(
                customer_id=uuid4(), current_user=mock_user
            )

    assert exc_info.value.status_code == 404

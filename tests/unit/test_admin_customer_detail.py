"""
Unit tests for enriched GET /api/admin/customers/{customer_id} endpoint.

Tests cover:
- Returned response includes the 3 new fields (preferred_stylist_name, chatwoot_conversation_id, memories)
- preferred_stylist_name is resolved from the joined Stylist row
- preferred_stylist_name is null when no preferred stylist is set
- memories is extracted from customer.metadata_["memories"]
- memories is null when metadata_ has no memories key
- Returns HTTP 404 for non-existent customer

All tests use mocks — no real database required.
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from database.models import Customer, Stylist

# ============================================================================
# Helpers
# ============================================================================


def _make_stylist_mock(name: str = "Ana"):
    stylist = MagicMock(spec=Stylist)
    stylist.id = uuid4()
    stylist.name = name
    return stylist


def _make_customer_mock(
    preferred_stylist: Stylist | None = None,
    metadata_: dict | None = None,
    chatwoot_conversation_id: str | None = None,
):
    customer = MagicMock(spec=Customer)
    customer.id = uuid4()
    customer.phone = "+34612345678"
    customer.first_name = "María"
    customer.last_name = "García"
    customer.total_spent = Decimal("150.00")
    customer.last_service_date = None
    customer.preferred_stylist_id = preferred_stylist.id if preferred_stylist else None
    customer.preferred_stylist = preferred_stylist
    customer.notes = None
    customer.chatwoot_conversation_id = chatwoot_conversation_id
    customer.metadata_ = metadata_ if metadata_ is not None else {}
    now = datetime(2026, 3, 12, 10, 0, 0)
    customer.created_at = now
    return customer


def _build_session_mock(customer_to_return):
    """Build an AsyncMock session that returns a single customer from scalar_one_or_none()."""
    mock_session = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = customer_to_return

    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    return mock_ctx


# ============================================================================
# Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_customer_returns_enriched_fields():
    """
    GIVEN a customer with a preferred stylist, chatwoot_id, and memories
    WHEN GET /api/admin/customers/{id} is called
    THEN the response includes preferred_stylist_name, chatwoot_conversation_id, and memories
    """
    from api.routes.admin import get_customer

    stylist = _make_stylist_mock("Carlos")
    memories_data = {"preferred_stylist_name": "Carlos", "visit_count": 3}
    customer = _make_customer_mock(
        preferred_stylist=stylist,
        metadata_={"memories": memories_data},
        chatwoot_conversation_id="abc-123",
    )
    mock_ctx = _build_session_mock(customer)
    mock_user = {"sub": "admin"}

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await get_customer(customer_id=customer.id, current_user=mock_user)

    assert "preferred_stylist_name" in result
    assert "chatwoot_conversation_id" in result
    assert "memories" in result


@pytest.mark.asyncio
async def test_get_customer_preferred_stylist_name_resolved():
    """
    GIVEN a customer with preferred_stylist_id pointing to stylist "Carlos"
    WHEN GET /api/admin/customers/{id} is called
    THEN preferred_stylist_name equals "Carlos"
    """
    from api.routes.admin import get_customer

    stylist = _make_stylist_mock("Carlos")
    customer = _make_customer_mock(preferred_stylist=stylist, metadata_={})
    mock_ctx = _build_session_mock(customer)
    mock_user = {"sub": "admin"}

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await get_customer(customer_id=customer.id, current_user=mock_user)

    assert result["preferred_stylist_name"] == "Carlos"


@pytest.mark.asyncio
async def test_get_customer_no_preferred_stylist():
    """
    GIVEN a customer with no preferred stylist (preferred_stylist_id is None)
    WHEN GET /api/admin/customers/{id} is called
    THEN preferred_stylist_name is null
    """
    from api.routes.admin import get_customer

    customer = _make_customer_mock(preferred_stylist=None, metadata_={})
    mock_ctx = _build_session_mock(customer)
    mock_user = {"sub": "admin"}

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await get_customer(customer_id=customer.id, current_user=mock_user)

    assert result["preferred_stylist_name"] is None


@pytest.mark.asyncio
async def test_get_customer_memories_from_metadata():
    """
    GIVEN a customer whose metadata_ contains {"memories": {...}}
    WHEN GET /api/admin/customers/{id} is called
    THEN the response memories field equals that dict
    """
    from api.routes.admin import get_customer

    memories_data = {"preferred_stylist_name": "Ana", "visit_count": 5}
    customer = _make_customer_mock(metadata_={"memories": memories_data})
    mock_ctx = _build_session_mock(customer)
    mock_user = {"sub": "admin"}

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await get_customer(customer_id=customer.id, current_user=mock_user)

    assert result["memories"] == memories_data


@pytest.mark.asyncio
async def test_get_customer_no_memories():
    """
    GIVEN a customer whose metadata_ is an empty dict (no memories key)
    WHEN GET /api/admin/customers/{id} is called
    THEN memories is null
    """
    from api.routes.admin import get_customer

    customer = _make_customer_mock(metadata_={})
    mock_ctx = _build_session_mock(customer)
    mock_user = {"sub": "admin"}

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await get_customer(customer_id=customer.id, current_user=mock_user)

    assert result["memories"] is None


@pytest.mark.asyncio
async def test_get_customer_404():
    """
    GIVEN no customer matches the given UUID
    WHEN GET /api/admin/customers/{non-existent-uuid} is called
    THEN HTTP 404 is returned
    """
    from fastapi import HTTPException

    from api.routes.admin import get_customer

    mock_ctx = _build_session_mock(None)  # No customer found
    mock_user = {"sub": "admin"}

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        with pytest.raises(HTTPException) as exc_info:
            await get_customer(customer_id=uuid4(), current_user=mock_user)

    assert exc_info.value.status_code == 404

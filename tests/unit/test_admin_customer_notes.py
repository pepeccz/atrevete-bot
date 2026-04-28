"""Round-trip coverage for the Customer.notes field across admin endpoints."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime
from decimal import Decimal

from database.models import Customer


def _make_customer(notes: str | None = None) -> MagicMock:
    customer = MagicMock(spec=Customer)
    customer.id = uuid4()
    customer.phone = "+34612345678"
    customer.first_name = "Lucía"
    customer.last_name = "Ramos"
    customer.total_spent = Decimal("0.00")
    customer.last_service_date = None
    customer.preferred_stylist_id = None
    customer.preferred_stylist = None
    customer.notes = notes
    customer.chatwoot_conversation_id = None
    customer.metadata_ = {}
    customer.created_at = datetime(2026, 4, 28, 10, 0, 0)
    return customer


def _session_mock(*scalar_returns):
    mock_session = AsyncMock()
    results_queue = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=r)) for r in scalar_returns
    ]

    async def execute(*_args, **_kwargs):
        return results_queue.pop(0) if results_queue else MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        )

    mock_session.execute = execute
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx, mock_session


@pytest.mark.asyncio
async def test_get_customer_returns_notes():
    from api.routes.admin import get_customer

    customer = _make_customer(notes="Alérgica a parabenos. Prefiere productos hipoalergénicos.")
    mock_ctx, _ = _session_mock(customer)  # GET: single SELECT

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await get_customer(customer_id=customer.id, current_user={"sub": "admin"})

    assert result["notes"] == "Alérgica a parabenos. Prefiere productos hipoalergénicos."


@pytest.mark.asyncio
async def test_create_customer_persists_notes():
    from api.routes.admin import CreateCustomerRequest, create_customer

    captured: dict = {}

    def capture_add(obj):
        captured["customer"] = obj
        obj.id = uuid4()
        obj.total_spent = Decimal("0.00")
        obj.last_service_date = None
        obj.created_at = datetime(2026, 4, 28, 10, 0, 0)

    mock_ctx, mock_session = _session_mock(None)  # POST: existing-phone check returns None
    mock_session.add = capture_add

    request = CreateCustomerRequest(
        phone="+34699112233",
        first_name="Marta",
        notes="Cliente VIP. Trato preferente.",
    )

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await create_customer(request=request, current_user={"sub": "admin"})

    assert captured["customer"].notes == "Cliente VIP. Trato preferente."
    assert result["notes"] == "Cliente VIP. Trato preferente."


@pytest.mark.asyncio
async def test_update_customer_persists_notes():
    from api.routes.admin import UpdateCustomerRequest, update_customer

    customer = _make_customer(notes="Nota vieja")
    mock_ctx, _ = _session_mock(customer)  # PUT: SELECT customer (no phone change → no second check)

    request = UpdateCustomerRequest(notes="Nota actualizada con detalles importantes")

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        await update_customer(
            customer_id=customer.id, request=request, current_user={"sub": "admin"}
        )

    assert customer.notes == "Nota actualizada con detalles importantes"

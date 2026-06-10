"""Change N (N1) regression — CustomerResolveMiddleware must resolve real Customer rows.

V6 audit C1: customer_resolve.py read `customer.name` but the Customer model only
has `first_name` / `last_name`. The AttributeError was swallowed by the fail-open
except, so EVERY existing customer was treated as new (production-affecting).

These tests build a REAL Customer ORM instance so attribute drift between the
model and the middleware can never pass silently again.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from database.models import Customer

PHONE = "+34999000033"


def _real_customer(last_name: str | None = "Cordero") -> Customer:
    """Build a real (non-mock) Customer ORM instance."""
    return Customer(
        id=uuid4(),
        phone=PHONE,
        first_name="Raquel",
        last_name=last_name,
        notes="Alergia al amoniaco",
        policy_accepted_at=datetime(2025, 8, 14, tzinfo=UTC),
        policy_version="1.0",
    )


def _session_returning(customer: Customer | None):
    """Async session mock whose first execute returns the customer, second an appointment."""
    session = MagicMock()

    customer_result = MagicMock()
    customer_result.scalars.return_value.first.return_value = customer

    appt_result = MagicMock()
    appt_result.scalars.return_value.first.return_value = object()  # has appointments

    session.execute = AsyncMock(side_effect=[customer_result, appt_result])
    return session


@asynccontextmanager
async def _session_ctx(session):
    yield session


# ---------------------------------------------------------------------------
# _lookup_customer with a REAL Customer instance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_customer_resolves_real_customer_instance():
    """_lookup_customer must return a dict (NOT None) for a real Customer row."""
    from agent.middleware.customer_resolve import _lookup_customer

    customer = _real_customer()
    session = _session_returning(customer)

    with patch(
        "database.connection.get_async_session",
        return_value=_session_ctx(session),
    ):
        result = await _lookup_customer(PHONE)

    assert result is not None, (
        "Real Customer row resolved to None — attribute drift between "
        "Customer model and _lookup_customer (V6 C1 regression)"
    )
    assert result["name"] == "Raquel Cordero"
    assert result["id"] == customer.id
    assert result["is_returning"] is True
    assert result["notes"] == "Alergia al amoniaco"
    assert result["policy_accepted_at"] == customer.policy_accepted_at
    assert result["policy_version"] == "1.0"


@pytest.mark.asyncio
async def test_lookup_customer_handles_null_last_name():
    """last_name is nullable — name must be first_name only, no trailing space."""
    from agent.middleware.customer_resolve import _lookup_customer

    customer = _real_customer(last_name=None)
    session = _session_returning(customer)

    with patch(
        "database.connection.get_async_session",
        return_value=_session_ctx(session),
    ):
        result = await _lookup_customer(PHONE)

    assert result is not None
    assert result["name"] == "Raquel"


@pytest.mark.asyncio
async def test_lookup_customer_failure_logs_error_level(caplog):
    """Fail-open is kept, but the failure must be LOUD: ERROR level with phone."""
    from agent.middleware.customer_resolve import _lookup_customer

    session = MagicMock()
    session.execute = AsyncMock(side_effect=RuntimeError("DB outage"))

    with (
        patch(
            "database.connection.get_async_session",
            return_value=_session_ctx(session),
        ),
        caplog.at_level(logging.ERROR, logger="agent.middleware.customer_resolve"),
    ):
        result = await _lookup_customer(PHONE, conversation_id="conv-123")

    assert result is None, "fail-open behavior must be preserved"
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records, "lookup failure must log at ERROR level, not WARNING"
    joined = " ".join(r.getMessage() for r in error_records)
    assert PHONE in joined
    assert "conv-123" in joined


# ---------------------------------------------------------------------------
# Middleware end-to-end: real Customer → slot + state fields
# ---------------------------------------------------------------------------


def _make_request(state: dict):
    from langchain_core.messages import SystemMessage

    req = MagicMock()
    req.state = state
    req.system_message = SystemMessage(content="base system")

    def override(**kwargs):
        new_req = MagicMock()
        new_req.state = {**state, **kwargs.get("state", {})}
        new_req.system_message = kwargs.get("system_message", req.system_message)
        return new_req

    req.override = MagicMock(side_effect=override)
    return req


@pytest.mark.asyncio
async def test_middleware_resolves_name_memories_and_policy_from_real_customer():
    """Full middleware path: real Customer → <customer> slot with name, memories, policy."""
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    customer = _real_customer()
    session = _session_returning(customer)
    memories = {
        "visit_count": 3,
        "preferred_stylist_name": "Marta",
        "typical_services": ["Corte Dama"],
    }

    middleware = CustomerResolveMiddleware()
    state = {
        "customer_phone": PHONE,
        "customer_id": None,
        "customer_name": None,
        "conversation_id": "conv-xyz",
        "messages": [],
    }
    request = _make_request(state)

    received = []

    async def handler(req):
        received.append(req)
        return MagicMock()

    settings = MagicMock()
    settings.POLICY_VERSION = "1.0"

    with (
        patch(
            "agent.middleware.customer_resolve._get_cached_customer",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "agent.middleware.customer_resolve._set_cached_customer",
            new_callable=AsyncMock,
        ),
        patch(
            "database.connection.get_async_session",
            return_value=_session_ctx(session),
        ),
        patch(
            "agent.middleware.customer_resolve.read_customer_memories",
            new_callable=AsyncMock,
            return_value=memories,
        ),
        patch(
            "agent.middleware.customer_resolve.get_settings",
            return_value=settings,
        ),
    ):
        await middleware.awrap_model_call(request, handler)

    assert len(received) == 1
    final_state = received[0].state
    slot = final_state.get("_slot_customer", "")

    assert "- Nombre: Raquel Cordero" in slot
    assert "Cliente recurrente: Sí" in slot
    assert "Estilista preferido: Marta" in slot
    assert "Política privacidad: aceptada v1.0" in slot
    assert final_state.get("customer_id") == customer.id
    assert final_state.get("customer_name") == "Raquel Cordero"
    assert final_state.get("customer_memories") == memories

"""
Tests for agent/services/booking_service.py — TDD Phase B (T4.4 RED).

Covers:
  - create_appointment() happy path → BookingResult(success=True, appointment_id=UUID)
  - create_appointment() duplicate/UniqueViolation → BookingResult(success=False, error_code="duplicate")
  - create_appointment() GCal failure after DB commit → BookingResult(success=True) — fire-and-forget

DB calls are mocked via patch on
`agent.services.booking_service.get_async_session`.
GCal push is mocked via patch on
`agent.services.booking_service.fire_and_forget_push_appointment`.
No live Postgres required.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_fake_session():
    """Return a minimal fake AsyncSession."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@asynccontextmanager
async def fake_session_ctx(session):
    yield session


def future_start() -> datetime:
    from datetime import timedelta

    return datetime.now(UTC) + timedelta(days=5, hours=10)


# ---------------------------------------------------------------------------
# T4.4 a — create_appointment happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_appointment_success():
    """Happy path: returns BookingResult(success=True, appointment_id=UUID).

    FAILS before agent/services/booking_service.py exists (ModuleNotFoundError or ImportError).
    PASSES after service is implemented.
    """
    from agent.services.booking_service import BookingService

    service_id = uuid4()
    stylist_id = uuid4()
    customer_id = uuid4()
    start_at = future_start()

    # Customer lookup returns None (new customer path)
    customer_result = MagicMock()
    customer_result.scalar_one_or_none = MagicMock(return_value=None)

    # Duration query returns 60 minutes
    duration_result = MagicMock()
    duration_result.fetchall = MagicMock(return_value=[(60,)])

    # Service names for GCal
    svc_names_result = MagicMock()
    svc_names_result.fetchall = MagicMock(return_value=[("Corte de Mujer",)])

    # Stylist name query
    stylist_result = MagicMock()
    stylist_result.scalar_one_or_none = MagicMock(return_value="María")

    session = make_fake_session()
    call_count = [0]

    async def execute_side_effect(stmt):
        call_count[0] += 1
        if call_count[0] == 1:
            return duration_result  # fetch service duration
        if call_count[0] == 2:
            return customer_result  # customer lookup
        if call_count[0] == 3:
            return svc_names_result  # service names for GCal
        return stylist_result  # stylist name for GCal link

    session.execute.side_effect = execute_side_effect

    # Mock customer ORM object created during get_or_create
    mock_customer = MagicMock()
    mock_customer.id = customer_id
    session.flush.side_effect = lambda: setattr(mock_customer, "id", customer_id)

    with (
        patch(
            "agent.services.booking_service.get_async_session",
            return_value=fake_session_ctx(session),
        ),
        patch(
            "agent.services.booking_service.fire_and_forget_push_appointment",
            new_callable=AsyncMock,
        ),
    ):
        result = await BookingService.create_appointment(
            service_ids=[service_id],
            stylist_id=stylist_id,
            start_at=start_at,
            customer_phone="+5491112345678",
            first_name="Ana",
            last_name="García",
            notes=None,
        )

    assert result.success is True
    assert result.appointment_id is not None
    assert result.error_message is None
    assert result.error_code is None


# ---------------------------------------------------------------------------
# T4.4 b — duplicate / UniqueViolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_appointment_duplicate():
    """UniqueViolation → BookingResult(success=False, error_code='duplicate').

    FAILS before service exists.
    PASSES after IntegrityError is caught and mapped to error_code.
    """
    from agent.services.booking_service import BookingService

    session = make_fake_session()

    # Duration returns ok
    duration_result = MagicMock()
    duration_result.fetchall = MagicMock(return_value=[(60,)])
    call_count = [0]

    async def execute_side_effect(stmt):
        call_count[0] += 1
        if call_count[0] == 1:
            return duration_result
        # Customer lookup
        cust_result = MagicMock()
        cust_result.scalar_one_or_none = MagicMock(return_value=None)
        return cust_result

    session.execute.side_effect = execute_side_effect

    # Commit raises IntegrityError (simulating UniqueViolation / exclusion constraint)
    orig = IntegrityError("duplicate key", None, None)
    session.commit.side_effect = orig

    with patch(
        "agent.services.booking_service.get_async_session",
        return_value=fake_session_ctx(session),
    ):
        result = await BookingService.create_appointment(
            service_ids=[uuid4()],
            stylist_id=uuid4(),
            start_at=future_start(),
            customer_phone="+5491112345678",
            first_name="Ana",
            last_name="García",
            notes=None,
        )

    assert result.success is False
    assert result.error_code == "duplicate"
    assert result.error_message is not None


# ---------------------------------------------------------------------------
# T4.4 c — GCal failure after DB commit does NOT roll back
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gcal_failure_does_not_rollback():
    """GCal push failure after DB commit must not affect BookingResult.success.

    The DB commit has already succeeded — DB is source of truth.
    GCal failure is fire-and-forget: log and continue.

    FAILS before service exists.
    PASSES after GCal exceptions are caught inside service.
    """
    from agent.services.booking_service import BookingService

    service_id = uuid4()
    stylist_id = uuid4()
    customer_id = uuid4()

    # Duration ok
    duration_result = MagicMock()
    duration_result.fetchall = MagicMock(return_value=[(45,)])

    # Customer lookup: None (new customer)
    customer_result = MagicMock()
    customer_result.scalar_one_or_none = MagicMock(return_value=None)

    # Service names for GCal title
    svc_names_result = MagicMock()
    svc_names_result.fetchall = MagicMock(return_value=[("Tinte",)])

    # Stylist name
    stylist_result = MagicMock()
    stylist_result.scalar_one_or_none = MagicMock(return_value="Valentina")

    session = make_fake_session()
    call_count = [0]

    async def execute_side_effect(stmt):
        call_count[0] += 1
        if call_count[0] == 1:
            return duration_result
        if call_count[0] == 2:
            return customer_result
        if call_count[0] == 3:
            return svc_names_result
        return stylist_result

    session.execute.side_effect = execute_side_effect

    # GCal push raises
    async def gcal_raises(*args, **kwargs):
        raise RuntimeError("GCal API unavailable")

    with (
        patch(
            "agent.services.booking_service.get_async_session",
            return_value=fake_session_ctx(session),
        ),
        patch(
            "agent.services.booking_service.fire_and_forget_push_appointment",
            side_effect=gcal_raises,
        ),
    ):
        result = await BookingService.create_appointment(
            service_ids=[service_id],
            stylist_id=stylist_id,
            start_at=future_start(),
            customer_phone="+5491199887766",
            first_name="Laura",
            last_name="Pérez",
            notes="sin fragancia",
        )

    # DB commit was called
    session.commit.assert_called_once()
    # Rollback was NOT called
    session.rollback.assert_not_called()
    # Result is success despite GCal failure
    assert result.success is True
    assert result.appointment_id is not None

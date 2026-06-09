"""TDD tests: B2 — Cancellation ownership check.

T8 (RED): execute_cancellation must reject when the requester's phone
does not match the appointment owner.

Tests:
  - test_cancel_rejects_wrong_owner
  - test_cancel_accepts_correct_owner
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

OWNER_PHONE = "+34611000031"
OTHER_PHONE = "+34611000032"
APPT_ID = uuid4()


def _make_appointment_mock(owner_phone=OWNER_PHONE):
    """Build a mock Appointment with a related Customer."""
    customer = MagicMock()
    customer.phone = owner_phone

    appt = MagicMock()
    appt.id = APPT_ID
    appt.customer = customer
    appt.status = MagicMock()
    appt.status.value = "pending"

    from unittest.mock import PropertyMock
    # Make status != CANCELLED comparison work
    from agent.services.cancellation_service import AppointmentStatus
    appt.status = AppointmentStatus.PENDING  # use real enum value

    return appt


def _make_session_ctx(appointment=None, not_found=False):
    """Build a mock DB session that returns the given appointment."""
    session = AsyncMock()
    scalars_mock = MagicMock()
    if not_found:
        scalars_mock.first.return_value = None
    else:
        scalars_mock.first.return_value = appointment
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    session.execute = AsyncMock(return_value=result_mock)
    session.commit = AsyncMock()

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.mark.asyncio
async def test_cancel_rejects_wrong_owner():
    """B2: execute_cancellation must return success=False when requester phone != owner phone."""
    from agent.services.cancellation_service import execute_cancellation

    appt = _make_appointment_mock(owner_phone=OWNER_PHONE)
    ctx = _make_session_ctx(appointment=appt)

    with patch("database.connection.get_async_session", return_value=ctx):
        result = await execute_cancellation(
            appointment_id=APPT_ID,
            customer_phone=OTHER_PHONE,  # wrong owner
            reason=None,
        )

    assert result.success is False, (
        f"Expected ownership rejection (success=False) when phone mismatch, got: {result}"
    )


@pytest.mark.asyncio
async def test_cancel_accepts_correct_owner():
    """B2: execute_cancellation is NOT blocked by ownership check when phone matches owner.

    We verify that the ownership check itself does not fire when phones match.
    The test proves the function proceeds past the ownership guard.
    We allow it to fail at deeper DB operations (no real DB needed for this test).
    """
    from agent.services.cancellation_service import execute_cancellation

    appt = _make_appointment_mock(owner_phone=OWNER_PHONE)
    ctx = _make_session_ctx(appointment=appt)

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch(
            "agent.services.cancellation_service.check_cancellation_allowed",
            new=AsyncMock(return_value=(True, 48.0)),
        ),
        patch(
            "agent.services.cancellation_service.delete_gcal_event",
            new=AsyncMock(),
        ),
        patch(
            "agent.services.cancellation_service._get_service_names",
            new=AsyncMock(return_value="Corte Dama"),
        ),
    ):
        result = await execute_cancellation(
            appointment_id=APPT_ID,
            customer_phone=OWNER_PHONE,  # correct owner
            reason=None,
        )

    # Should NOT be the ownership rejection. If it's any other kind of failure
    # (e.g. DB error after ownership check) that's ok — ownership guard passed.
    if not result.success:
        # Ownership rejection sentinel message check
        assert "No se encontró" not in (result.error_message or ""), (
            f"Ownership rejection fired for correct owner. error_message: {result.error_message}"
        )

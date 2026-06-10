"""Tests for Change J2: customer_id ownership guard in manage_appointments_tool.

REQ-J2: manage_appointments MUST reject appointment_id that doesn't belong to
the resolved customer (state.customer_id != appointments.customer_id).

Tests written BEFORE implementation (TDD RED phase).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

CUSTOMER_A_ID = uuid4()
CUSTOMER_B_ID = uuid4()
APPT_OWNED_BY_A = uuid4()
STATE_PHONE = "+34611000099"


# ---------------------------------------------------------------------------
# _cancel_appointment: IDOR guard via customer_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_own_appointment_passes_idor_guard():
    """Customer A can cancel their own appointment."""
    from agent.tools.manage_appointments_tool import _cancel_appointment

    with (
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(return_value=MagicMock(ok=True, error_code=None, error_message=None)),
        ),
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
        ) as mock_session_ctx,
    ):
        mock_session = AsyncMock()
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "agent.services.cancellation_service.execute_cancellation",
            new=AsyncMock(
                return_value=MagicMock(
                    success=True,
                    response_text="Tu cita ha sido cancelada.",
                    within_window=False,
                    hours_until_appointment=None,
                )
            ),
            create=True,
        ):
            result = await _cancel_appointment(
                customer_phone=STATE_PHONE,
                appointment_id=str(APPT_OWNED_BY_A),
                reason=None,
                customer_id=CUSTOMER_A_ID,
            )

    assert result["success"] is True


@pytest.mark.asyncio
async def test_cancel_other_customer_appointment_rejected():
    """Customer B CANNOT cancel customer A's appointment — IDOR guard fires."""
    from agent.tools._booking_validators import ERROR_APPOINTMENT_NOT_OWNED
    from agent.tools.manage_appointments_tool import _cancel_appointment

    with (
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(
                return_value=MagicMock(
                    ok=False,
                    error_code=ERROR_APPOINTMENT_NOT_OWNED,
                    error_message="No encontré esa cita asociada a tu cuenta.",
                )
            ),
        ),
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
        ) as mock_session_ctx,
        # Also patch cancellation_service to prevent it being imported via inner scope
        patch(
            "agent.services.cancellation_service.execute_cancellation",
            new=AsyncMock(),
            create=True,
        ),
    ):
        mock_session = AsyncMock()
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _cancel_appointment(
            customer_phone=STATE_PHONE,
            appointment_id=str(APPT_OWNED_BY_A),
            reason=None,
            customer_id=CUSTOMER_B_ID,  # Wrong customer
        )

    assert result["success"] is False
    assert "cita" in result["message"].lower()


@pytest.mark.asyncio
async def test_cancel_with_none_customer_id_rejected():
    """If customer_id is None (CustomerResolveMiddleware not run), tool rejects early."""
    from agent.tools.manage_appointments_tool import _cancel_appointment

    result = await _cancel_appointment(
        customer_phone=STATE_PHONE,
        appointment_id=str(APPT_OWNED_BY_A),
        reason=None,
        customer_id=None,
    )

    assert result["success"] is False
    assert result.get("error_code") is not None


# ---------------------------------------------------------------------------
# _reschedule_appointment: IDOR guard via customer_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reschedule_other_customer_appointment_rejected():
    """Customer B CANNOT reschedule customer A's appointment."""
    from agent.tools._booking_validators import ERROR_APPOINTMENT_NOT_OWNED
    from agent.tools.manage_appointments_tool import _reschedule_appointment

    with (
        patch(
            "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
            new=AsyncMock(
                return_value=MagicMock(
                    ok=False,
                    error_code=ERROR_APPOINTMENT_NOT_OWNED,
                    error_message="No encontré esa cita asociada a tu cuenta.",
                )
            ),
        ),
        patch(
            "agent.tools.manage_appointments_tool.get_async_session",
        ) as mock_session_ctx,
    ):
        mock_session = AsyncMock()
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _reschedule_appointment(
            customer_phone=STATE_PHONE,
            appointment_id=str(APPT_OWNED_BY_A),
            new_date="2026-07-01",
            new_time="10:00",
            reason=None,
            customer_id=CUSTOMER_B_ID,  # Wrong customer
        )

    assert result["success"] is False
    assert "cita" in result["message"].lower()

"""
Unit tests for PUT /api/admin/appointments/{id} transition guards.

Covers Slice 2 requirements:
- S2-R3: 409 when confirming a non-PENDING appointment
- S2-R4: 409 when cancelling a CANCELLED/COMPLETED appointment;
         cancelled_at + cancellation_reason set on valid cancel
- S2-A: 200 operator confirm PENDING → CONFIRMED (response includes id + status)
- S2-B: 200 operator cancel PENDING → CANCELLED with cancellation fields in response
- S2-D: GCal EVENT_COLORS regression guard (pending=="5", confirmed=="10")
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# =============================================================================
# Helpers
# =============================================================================


def _make_appointment_mock(status_value: str):
    """
    Create a MagicMock appointment with real AppointmentStatus enum value.
    Sets google_calendar_event_id=None so GCal branches are naturally skipped
    or controlled by the handler logic.
    """
    from database.models import AppointmentStatus

    appt = MagicMock()
    appt.id = uuid4()
    appt.customer_id = uuid4()
    appt.stylist_id = uuid4()
    appt.service_ids = []
    appt.start_time = datetime(2026, 7, 15, 10, 0, 0, tzinfo=UTC)
    appt.duration_minutes = 60
    appt.status = AppointmentStatus(status_value)
    appt.first_name = "Ana"
    appt.last_name = "López"
    appt.notes = None
    appt.google_calendar_event_id = None
    appt.created_at = datetime(2026, 7, 1, 9, 0, 0, tzinfo=UTC)
    appt.updated_at = datetime(2026, 7, 1, 9, 0, 0, tzinfo=UTC)
    appt.cancelled_at = None
    appt.cancellation_reason = None
    appt.confirmation_sent_at = None
    return appt


def _build_single_execute_session(appointment):
    """
    Session mock for 409 tests — only one execute needed before exception is raised.
    """
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = appointment
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


def _build_200_session(appointment):
    """
    Session mock for 200 tests.

    Two execute calls:
      1. Fetch appointment by id (scalar_one_or_none)
      2. Fetch services for GCal summary (scalars().all())

    commit() and refresh() are no-op AsyncMocks.
    """
    appt_result = MagicMock()
    appt_result.scalar_one_or_none.return_value = appointment

    services_result = MagicMock()
    services_result.scalars.return_value.all.return_value = []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[appt_result, services_result])
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


# =============================================================================
# 409 guard tests — RED before impl, GREEN after Phase 2
# =============================================================================


@pytest.mark.asyncio
async def test_confirm_already_confirmed_returns_200():
    """
    CONFIRMED→CONFIRMED (idempotent form-save) must return 200, not 409.

    The admin frontend always includes status in the PUT body, so editing
    notes/time/stylist on an already-CONFIRMED appointment sends
    {status:"confirmed"} → {status:"confirmed"}.  The guard must allow this
    idempotent transition.
    """
    from api.routes.admin import UpdateAppointmentRequest, update_appointment

    appt = _make_appointment_mock("confirmed")
    mock_ctx = _build_200_session(appt)
    mock_user = MagicMock()

    with (
        patch("api.routes.admin.get_async_session", return_value=mock_ctx),
        patch("api.routes.admin.create_notification", new=AsyncMock()),
    ):
        result = await update_appointment(
            appointment_id=appt.id,
            request=UpdateAppointmentRequest(status="confirmed"),
            current_user=mock_user,
        )

    assert result["status"] == "confirmed"


@pytest.mark.asyncio
async def test_confirm_from_cancelled_returns_409():
    """
    CANCELLED→CONFIRMED is a terminal transition and must return 409.
    """
    from fastapi import HTTPException

    from api.routes.admin import UpdateAppointmentRequest, update_appointment

    appt = _make_appointment_mock("cancelled")
    mock_ctx = _build_single_execute_session(appt)
    mock_user = MagicMock()

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        with pytest.raises(HTTPException) as exc_info:
            await update_appointment(
                appointment_id=appt.id,
                request=UpdateAppointmentRequest(status="confirmed"),
                current_user=mock_user,
            )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_confirm_completed_returns_409():
    """
    S2-R3: PUT {status:"confirmed"} on COMPLETED appointment → 409.
    """
    from fastapi import HTTPException

    from api.routes.admin import UpdateAppointmentRequest, update_appointment

    appt = _make_appointment_mock("completed")
    mock_ctx = _build_single_execute_session(appt)
    mock_user = MagicMock()

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        with pytest.raises(HTTPException) as exc_info:
            await update_appointment(
                appointment_id=appt.id,
                request=UpdateAppointmentRequest(status="confirmed"),
                current_user=mock_user,
            )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_cancel_already_cancelled_returns_409():
    """
    S2-R4: PUT {status:"cancelled"} on CANCELLED appointment → 409.
    """
    from fastapi import HTTPException

    from api.routes.admin import UpdateAppointmentRequest, update_appointment

    appt = _make_appointment_mock("cancelled")
    mock_ctx = _build_single_execute_session(appt)
    mock_user = MagicMock()

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        with pytest.raises(HTTPException) as exc_info:
            await update_appointment(
                appointment_id=appt.id,
                request=UpdateAppointmentRequest(status="cancelled"),
                current_user=mock_user,
            )

    assert exc_info.value.status_code == 409
    assert "terminal state" in exc_info.value.detail


@pytest.mark.asyncio
async def test_operator_confirm_pending_returns_200():
    """
    S2-A: PUT {status:"confirmed"} on PENDING appointment → 200.
    Response must include id and status=="confirmed".
    """
    from api.routes.admin import UpdateAppointmentRequest, update_appointment

    appt = _make_appointment_mock("pending")
    mock_ctx = _build_200_session(appt)
    mock_user = MagicMock()

    with (
        patch("api.routes.admin.get_async_session", return_value=mock_ctx),
        patch("api.routes.admin.create_notification", new=AsyncMock()),
        patch(
            "shared.gcal_push_service.push_appointment_to_gcal",
            new=AsyncMock(return_value=None),
        ),
    ):
        result = await update_appointment(
            appointment_id=appt.id,
            request=UpdateAppointmentRequest(status="confirmed"),
            current_user=mock_user,
        )

    assert result["id"] == str(appt.id)
    assert result["status"] == "confirmed"


@pytest.mark.asyncio
async def test_operator_cancel_sets_fields():
    """
    S2-B: PUT {status:"cancelled"} on PENDING appointment → 200.
    Response must include:
    - status == "cancelled"
    - cancelled_at is not None (ISO datetime string)
    - cancellation_reason == "operator_cancelled"
    """
    from api.routes.admin import UpdateAppointmentRequest, update_appointment

    appt = _make_appointment_mock("pending")
    mock_ctx = _build_200_session(appt)
    mock_user = MagicMock()

    with (
        patch("api.routes.admin.get_async_session", return_value=mock_ctx),
        patch("api.routes.admin.create_notification", new=AsyncMock()),
    ):
        result = await update_appointment(
            appointment_id=appt.id,
            request=UpdateAppointmentRequest(status="cancelled"),
            current_user=mock_user,
        )

    assert result["status"] == "cancelled"
    assert result["cancelled_at"] is not None, (
        "cancelled_at must be set when operator cancels"
    )
    assert result["cancellation_reason"] == "operator_cancelled"


# =============================================================================
# GCal color regression guard (S2-D) — synchronous, no session needed
# =============================================================================


def test_gcal_event_colors_regression():
    """
    S2-D: EVENT_COLORS["pending"] must be "5" (Yellow) and
    EVENT_COLORS["confirmed"] must be "10" (Green). These values MUST NOT drift.
    """
    from agent.services.gcal_push_service import EVENT_COLORS

    assert EVENT_COLORS["pending"] == "5", (
        f"Expected EVENT_COLORS['pending']='5', got '{EVENT_COLORS['pending']}'"
    )
    assert EVENT_COLORS["confirmed"] == "10", (
        f"Expected EVENT_COLORS['confirmed']='10', got '{EVENT_COLORS['confirmed']}'"
    )

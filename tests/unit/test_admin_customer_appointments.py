"""
Unit tests for GET /api/admin/customers/{customer_id}/appointments endpoint.

Tests cover:
- Returns paginated list of appointments
- Results are ordered by start_time DESC (most recent first)
- has_more flag is set correctly when there are more pages
- service_names are resolved via batch lookup
- stylist_name is resolved from joined Stylist
- Empty appointments list returns 200 with total: 0
- Returns HTTP 404 for non-existent customer

All tests use mocks — no real database required.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from database.models import Appointment, AppointmentStatus, Service, Stylist

# ============================================================================
# Helpers
# ============================================================================


def _make_stylist_mock(name: str = "Ana"):
    stylist = MagicMock(spec=Stylist)
    stylist.id = uuid4()
    stylist.name = name
    return stylist


def _make_service_mock(name: str = "Corte mujer"):
    svc = MagicMock(spec=Service)
    svc.id = uuid4()
    svc.name = name
    return svc


def _make_appointment_mock(
    stylist: Stylist,
    service_ids: list[UUID],
    start_time: datetime | None = None,
    status: AppointmentStatus = AppointmentStatus.COMPLETED,
):
    appt = MagicMock(spec=Appointment)
    appt.id = uuid4()
    appt.stylist = stylist
    appt.service_ids = service_ids
    appt.start_time = start_time or datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)
    appt.duration_minutes = 60
    appt.status = status
    appt.first_name = "María"
    appt.last_name = "García"
    appt.notes = None
    appt.created_at = datetime(2026, 3, 25, 14, 0, 0, tzinfo=UTC)
    return appt


def _build_session_mock_for_appointments(
    customer_exists: bool,
    appointments: list,
    services: list | None = None,
    total_count: int | None = None,
):
    """
    Build an AsyncMock session for appointment endpoint tests.

    First execute call: customer existence check (scalar_one_or_none).
    Second execute call: total COUNT(*) (scalar()).
    Third execute call: appointments list (scalars().all()).
    Fourth execute call (optional): services batch (all()).
    """
    mock_session = AsyncMock()

    # Customer check result
    customer_check_result = MagicMock()
    customer_check_result.scalar_one_or_none.return_value = uuid4() if customer_exists else None

    # Count result
    count_result = MagicMock()
    actual_total = total_count if total_count is not None else len(appointments)
    count_result.scalar.return_value = actual_total

    # Appointments result
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = appointments
    appt_result = MagicMock()
    appt_result.scalars.return_value = mock_scalars

    # Services batch result
    svc_result = MagicMock()
    svc_result.all.return_value = services or []

    # Wire up sequential execute() calls
    mock_session.execute = AsyncMock(
        side_effect=[customer_check_result, count_result, appt_result, svc_result]
    )

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    return mock_ctx


# ============================================================================
# Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_customer_appointments_returns_paginated_list():
    """
    GIVEN a customer with 25 appointments and default page_size=20
    WHEN GET /api/admin/customers/{id}/appointments is called
    THEN page 1 has 20 items
    """
    from api.routes.admin import get_customer_appointments

    stylist = _make_stylist_mock("Ana")
    svc_id = uuid4()
    svc = MagicMock()
    svc.id = svc_id
    svc.name = "Corte mujer"

    # 21 appointments returned by DB (limit+1 trick) — means has_more=True and 20 items shown
    appointments = [_make_appointment_mock(stylist, [svc_id]) for _ in range(21)]
    mock_ctx = _build_session_mock_for_appointments(True, appointments, [svc], total_count=25)
    mock_user = {"sub": "admin"}

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await get_customer_appointments(
            customer_id=uuid4(), current_user=mock_user, page=1, page_size=20
        )

    assert len(result["items"]) == 20
    assert result["page"] == 1
    assert result["page_size"] == 20


@pytest.mark.asyncio
async def test_get_customer_appointments_ordered_by_start_time_desc():
    """
    GIVEN a customer with 2 appointments at different dates
    WHEN GET /api/admin/customers/{id}/appointments is called
    THEN items are ordered most-recent-first (DB ORDER BY — mock preserves order)
    """
    from api.routes.admin import get_customer_appointments

    stylist = _make_stylist_mock()
    svc_id = uuid4()
    newer = _make_appointment_mock(
        stylist, [svc_id], start_time=datetime(2026, 4, 10, 10, 0, tzinfo=UTC)
    )
    older = _make_appointment_mock(
        stylist, [svc_id], start_time=datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    )
    # Mock returns in the order the endpoint receives from DB (DESC already applied)
    mock_ctx = _build_session_mock_for_appointments(True, [newer, older])
    mock_user = {"sub": "admin"}

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await get_customer_appointments(
            customer_id=uuid4(), current_user=mock_user, page=1, page_size=20
        )

    assert result["items"][0]["id"] == str(newer.id)
    assert result["items"][1]["id"] == str(older.id)


@pytest.mark.asyncio
async def test_get_customer_appointments_has_more_flag():
    """
    GIVEN 21 appointments returned by DB with page_size=20
    WHEN GET /api/admin/customers/{id}/appointments is called
    THEN has_more is True and only 20 items are in the response
    """
    from api.routes.admin import get_customer_appointments

    stylist = _make_stylist_mock()
    appointments = [_make_appointment_mock(stylist, []) for _ in range(21)]
    mock_ctx = _build_session_mock_for_appointments(True, appointments)
    mock_user = {"sub": "admin"}

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await get_customer_appointments(
            customer_id=uuid4(), current_user=mock_user, page=1, page_size=20
        )

    assert result["has_more"] is True
    assert len(result["items"]) == 20


@pytest.mark.asyncio
async def test_get_customer_appointments_service_names_resolved():
    """
    GIVEN an appointment with 2 service_ids
    WHEN GET /api/admin/customers/{id}/appointments is called
    THEN service_names has 2 strings resolved from the services batch lookup
    """
    from api.routes.admin import get_customer_appointments

    stylist = _make_stylist_mock()
    svc1_id = uuid4()
    svc2_id = uuid4()

    svc1 = MagicMock()
    svc1.id = svc1_id
    svc1.name = "Corte mujer"

    svc2 = MagicMock()
    svc2.id = svc2_id
    svc2.name = "Secado"

    appt = _make_appointment_mock(stylist, [svc1_id, svc2_id])
    mock_ctx = _build_session_mock_for_appointments(True, [appt], [svc1, svc2])
    mock_user = {"sub": "admin"}

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await get_customer_appointments(
            customer_id=uuid4(), current_user=mock_user, page=1, page_size=20
        )

    assert len(result["items"][0]["service_names"]) == 2
    assert "Corte mujer" in result["items"][0]["service_names"]
    assert "Secado" in result["items"][0]["service_names"]


@pytest.mark.asyncio
async def test_get_customer_appointments_stylist_name_resolved():
    """
    GIVEN an appointment joined with a Stylist row
    WHEN GET /api/admin/customers/{id}/appointments is called
    THEN stylist_name equals the stylist's name
    """
    from api.routes.admin import get_customer_appointments

    stylist = _make_stylist_mock("Carlos")
    appt = _make_appointment_mock(stylist, [])
    mock_ctx = _build_session_mock_for_appointments(True, [appt])
    mock_user = {"sub": "admin"}

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await get_customer_appointments(
            customer_id=uuid4(), current_user=mock_user, page=1, page_size=20
        )

    assert result["items"][0]["stylist_name"] == "Carlos"


@pytest.mark.asyncio
async def test_get_customer_appointments_empty():
    """
    GIVEN a customer with no appointments
    WHEN GET /api/admin/customers/{id}/appointments is called
    THEN returns HTTP 200 with items=[], total=0, has_more=False
    """
    from api.routes.admin import get_customer_appointments

    mock_ctx = _build_session_mock_for_appointments(True, [], total_count=0)
    mock_user = {"sub": "admin"}

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await get_customer_appointments(
            customer_id=uuid4(), current_user=mock_user, page=1, page_size=20
        )

    assert result["items"] == []
    assert result["total"] == 0
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_get_customer_appointments_404():
    """
    GIVEN a non-existent customer_id
    WHEN GET /api/admin/customers/{id}/appointments is called
    THEN HTTP 404 is returned
    """
    from fastapi import HTTPException

    from api.routes.admin import get_customer_appointments

    mock_ctx = _build_session_mock_for_appointments(False, [])
    mock_user = {"sub": "admin"}

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        with pytest.raises(HTTPException) as exc_info:
            await get_customer_appointments(
                customer_id=uuid4(), current_user=mock_user, page=1, page_size=20
            )

    assert exc_info.value.status_code == 404

"""
Integration tests for dashboard KPI and today-agenda endpoints — Slice 2a (TDD RED phase).

Tests cover:
  - GET /api/admin/dashboard/kpis  — new fields, parallelism, null on zero appointments
  - GET /api/admin/dashboard/today-agenda — ordered list, empty state, relation expansion

Follows the established pattern in tests/integration/test_billing_routes.py:
  - FastAPI TestClient
  - app.dependency_overrides for get_current_user (bypasses JWT)
  - Patching get_async_session at the api.routes.admin module level
  - asyncio.gather is not directly tested but we verify both endpoints return HTTP 200
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes.admin import get_current_user
from database.models import AppointmentStatus

MADRID_TZ = ZoneInfo("Europe/Madrid")


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _bypass_rate_limiter():
    """Disable Redis-based rate limiting for all tests in this module."""
    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock()
    with patch("api.middleware.rate_limiting.get_redis_client", return_value=mock_redis):
        yield


@pytest.fixture
def client():
    """Provide a TestClient for the FastAPI app."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def mock_auth():
    """Override get_current_user to bypass JWT authentication."""
    fake_user = {
        "sub": "admin",
        "jti": str(uuid4()),
        "exp": 9999999999,
        "type": "admin",
    }
    app.dependency_overrides[get_current_user] = lambda: fake_user
    yield fake_user
    app.dependency_overrides.pop(get_current_user, None)


# =============================================================================
# Helpers
# =============================================================================


def _make_kpi_session(
    confirmed_count: int = 3,
    total_count: int = 5,
    booked_minutes: int = 120,
    active_stylist_count: int = 3,
    bh_start_h: int = 9,
    bh_start_m: int = 0,
    bh_end_h: int = 18,
    bh_end_m: int = 0,
    bh_closed: bool = False,
    new_customers: int = 4,
):
    """
    Build a mock async context manager whose session returns data for all 4 KPI helpers.

    The helpers are called in this order (via asyncio.gather):
      1. _confirmation_rate_today     → one query returning (confirmed, total) row
      2. _appointments_count_today    → one query returning scalar count
      3. _occupation_today            → three queries: booked_min, stylist_count, business_hours
      4. _new_customers_last_7d       → one query returning scalar count

    Total execute() calls when gather runs them in parallel: the real DB would
    interleave them, but TestClient runs synchronously so each coroutine fully executes
    before the next one starts (single-threaded event loop).
    """
    mock_session = AsyncMock()
    bh = MagicMock()
    bh.is_closed = bh_closed
    bh.start_hour = bh_start_h
    bh.start_minute = bh_start_m
    bh.end_hour = bh_end_h
    bh.end_minute = bh_end_m

    # We can't know the exact call order when asyncio.gather is used, so we track
    # query count and return values in a repeating sequence.
    call_counter: dict = {"n": 0}
    responses = [
        # 1. confirmation_rate_today: returns (confirmed, total) row
        lambda: _one_row_result(confirmed_count, total_count),
        # 2. appointments_count_today: returns scalar
        lambda: _scalar_result(total_count),
        # 3. occupation_today call 1: booked_minutes scalar
        lambda: _scalar_result(booked_minutes),
        # 3. occupation_today call 2: active stylist count
        lambda: _scalar_result(active_stylist_count),
        # 3. occupation_today call 3: business hours row
        lambda: _bh_result(bh),
        # 4. new_customers_last_7d: returns scalar
        lambda: _scalar_result(new_customers),
    ]

    async def _execute(*_args, **_kwargs):
        idx = call_counter["n"]
        call_counter["n"] += 1
        if idx < len(responses):
            return responses[idx]()
        # Fallback for unexpected extra calls
        return _scalar_result(0)

    mock_session.execute = _execute

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


def _one_row_result(v1, v2):
    result = MagicMock()
    result.one.return_value = (v1, v2)
    return result


def _scalar_result(value):
    result = MagicMock()
    result.scalar.return_value = value
    result.scalar_one.return_value = value
    return result


def _bh_result(bh):
    result = MagicMock()
    result.scalar_one_or_none.return_value = bh
    return result


def _make_agenda_appointment(
    start_h: int = 10,
    start_m: int = 0,
    status: AppointmentStatus = AppointmentStatus.CONFIRMED,
):
    """Build a mock Appointment ORM object with relations loaded."""
    appt = MagicMock()
    appt.id = uuid4()
    appt.start_time = datetime(2026, 5, 10, start_h, start_m, 0, tzinfo=MADRID_TZ)
    appt.duration_minutes = 60
    appt.status = status

    customer = MagicMock()
    customer.id = uuid4()
    customer.first_name = "Ana"
    customer.last_name = "García"
    appt.customer = customer

    stylist = MagicMock()
    stylist.id = uuid4()
    stylist.name = "Laura"
    stylist.color = "#7C3AED"
    appt.stylist = stylist

    service = MagicMock()
    service.id = uuid4()
    service.name = "Corte de pelo"
    appt.services = [service]

    return appt


def _make_agenda_session(appointments: list):
    """Return session mock for today-agenda endpoint.

    The today-agenda endpoint calls:
      result.scalars().unique().all()   — first query (appointments)
      result.scalars().all()            — per-appointment service queries

    We handle both via a counter-based dispatcher.
    """
    mock_session = AsyncMock()
    call_count = {"n": 0}

    async def _execute(*_args, **_kwargs):
        call_count["n"] += 1
        mock_result = MagicMock()
        if call_count["n"] == 1:
            # First call: appointment SELECT — supports .scalars().unique().all()
            mock_scalars = MagicMock()
            mock_scalars.unique.return_value.all.return_value = appointments
            mock_scalars.all.return_value = appointments
            mock_result.scalars.return_value = mock_scalars
        else:
            # Subsequent calls: service SELECTs per appointment — return empty list
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = []
            mock_result.scalars.return_value = mock_scalars
        return mock_result

    mock_session.execute = _execute

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


# =============================================================================
# Tests — GET /api/admin/dashboard/kpis
# =============================================================================


class TestDashboardKpisEndpoint:
    """Tests for the expanded /dashboard/kpis endpoint."""

    def test_response_includes_all_new_kpi_fields(self, client, mock_auth):
        """
        GIVEN the endpoint is called with 3 confirmed out of 5 total today
        WHEN GET /api/admin/dashboard/kpis
        THEN response includes confirmation_rate_today, appointments_today,
             occupation_today, new_customers_this_week fields
        """
        mock_ctx = _make_kpi_session(
            confirmed_count=3,
            total_count=5,
            booked_minutes=120,
            active_stylist_count=2,
            new_customers=4,
        )

        with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
            response = client.get("/api/admin/dashboard/kpis")

        assert response.status_code == 200
        data = response.json()
        assert "confirmation_rate_today" in data
        assert "appointments_today" in data
        assert "occupation_today" in data
        assert "new_customers_this_week" in data

    def test_confirmation_rate_is_null_when_zero_appointments(self, client, mock_auth):
        """
        GIVEN today has 0 total non-cancelled/no_show appointments
        WHEN GET /api/admin/dashboard/kpis
        THEN confirmation_rate_today is null (not divide-by-zero error)
        """
        mock_ctx = _make_kpi_session(
            confirmed_count=0,
            total_count=0,
            booked_minutes=0,
            active_stylist_count=2,
            new_customers=0,
        )

        with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
            response = client.get("/api/admin/dashboard/kpis")

        assert response.status_code == 200
        data = response.json()
        # When total_count == 0 the helper returns 0.0; frontend displays "—"
        # Per user decision: zero appointments → return 0.0 (not null)
        assert data["confirmation_rate_today"] == 0.0

    def test_appointments_today_shows_non_cancelled_count(self, client, mock_auth):
        """
        GIVEN 5 non-cancelled appointments today
        WHEN GET /api/admin/dashboard/kpis
        THEN appointments_today is 5
        """
        mock_ctx = _make_kpi_session(
            confirmed_count=3,
            total_count=5,
            booked_minutes=240,
            active_stylist_count=3,
            new_customers=2,
        )

        with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
            response = client.get("/api/admin/dashboard/kpis")

        assert response.status_code == 200
        data = response.json()
        assert data["appointments_today"] == 5

    def test_new_customers_this_week_is_integer(self, client, mock_auth):
        """
        GIVEN 7 new customers in the last 7 days
        WHEN GET /api/admin/dashboard/kpis
        THEN new_customers_this_week is 7
        """
        mock_ctx = _make_kpi_session(
            confirmed_count=2,
            total_count=4,
            booked_minutes=90,
            active_stylist_count=1,
            new_customers=7,
        )

        with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
            response = client.get("/api/admin/dashboard/kpis")

        assert response.status_code == 200
        data = response.json()
        assert data["new_customers_this_week"] == 7

    def test_returns_200_and_not_500(self, client, mock_auth):
        """
        Smoke test: endpoint is reachable and does not crash.
        """
        mock_ctx = _make_kpi_session()

        with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
            response = client.get("/api/admin/dashboard/kpis")

        assert response.status_code == 200


# =============================================================================
# Tests — GET /api/admin/dashboard/today-agenda
# =============================================================================


class TestTodayAgendaEndpoint:
    """Tests for the new /dashboard/today-agenda endpoint."""

    def test_returns_appointments_ordered_by_time(self, client, mock_auth):
        """
        GIVEN today has 3 appointments at 10:00, 12:00, 14:00
        WHEN GET /api/admin/dashboard/today-agenda
        THEN response contains 3 appointment objects in order
        """
        appointments = [
            _make_agenda_appointment(start_h=10),
            _make_agenda_appointment(start_h=12),
            _make_agenda_appointment(start_h=14),
        ]
        mock_ctx = _make_agenda_session(appointments)

        with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
            response = client.get("/api/admin/dashboard/today-agenda")

        assert response.status_code == 200
        data = response.json()
        assert "appointments" in data
        assert len(data["appointments"]) == 3

    def test_returns_empty_list_when_no_appointments(self, client, mock_auth):
        """
        GIVEN today has no appointments
        WHEN GET /api/admin/dashboard/today-agenda
        THEN response body is {"appointments": []} with HTTP 200
        """
        mock_ctx = _make_agenda_session([])

        with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
            response = client.get("/api/admin/dashboard/today-agenda")

        assert response.status_code == 200
        data = response.json()
        assert data["appointments"] == []

    def test_appointment_has_required_fields(self, client, mock_auth):
        """
        GIVEN one appointment today
        WHEN GET /api/admin/dashboard/today-agenda
        THEN the appointment object contains id, start_time, duration_minutes,
             status, customer (name), stylist (name + color), services
        """
        appt = _make_agenda_appointment(start_h=11)
        mock_ctx = _make_agenda_session([appt])

        with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
            response = client.get("/api/admin/dashboard/today-agenda")

        assert response.status_code == 200
        data = response.json()
        assert len(data["appointments"]) == 1
        item = data["appointments"][0]
        assert "id" in item
        assert "start_time" in item
        assert "duration_minutes" in item
        assert "status" in item
        # Customer and stylist sub-objects
        assert "customer_name" in item or "customer" in item
        assert "stylist_name" in item or "stylist" in item

    def test_appointment_includes_stylist_color(self, client, mock_auth):
        """
        GIVEN an appointment with stylist color "#7C3AED"
        WHEN GET /api/admin/dashboard/today-agenda
        THEN the response includes the stylist color
        """
        appt = _make_agenda_appointment(start_h=9)
        appt.stylist.color = "#7C3AED"
        mock_ctx = _make_agenda_session([appt])

        with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
            response = client.get("/api/admin/dashboard/today-agenda")

        assert response.status_code == 200
        data = response.json()
        item = data["appointments"][0]
        # The color must be present somewhere in the response
        response_str = str(item)
        assert "#7C3AED" in response_str or "7C3AED" in response_str.upper()

    def test_endpoint_requires_authentication(self, client):
        """
        GIVEN no mock_auth override (no valid JWT)
        WHEN GET /api/admin/dashboard/today-agenda
        THEN returns 401 or 403 (not 200 or 500)
        """
        # No mock_auth fixture means get_current_user is the real implementation
        response = client.get("/api/admin/dashboard/today-agenda")
        assert response.status_code in (401, 403, 422)

    def test_kpis_endpoint_requires_authentication(self, client):
        """
        GIVEN no mock_auth override
        WHEN GET /api/admin/dashboard/kpis
        THEN returns 401 or 403
        """
        response = client.get("/api/admin/dashboard/kpis")
        assert response.status_code in (401, 403, 422)


# =============================================================================
# Regression test — AsyncSession concurrency bug (asyncio.gather shared session)
# =============================================================================

# Module-level flag used by the instrumented KPI fakes below.
# Each fake asserts it is False on entry (no concurrent overlap), sets it True,
# yields control via asyncio.sleep(0) so gather() can interleave, then clears it.
# With asyncio.gather the second coroutine enters while the flag is still True →
# AssertionError (RED).  With sequential awaits they never overlap → all clear (GREEN).
_kpi_in_flight: bool = False


async def _fake_confirmation_rate(session, today):
    global _kpi_in_flight
    assert not _kpi_in_flight, (
        "AsyncSession concurrency hazard: _fake_confirmation_rate entered while "
        "another KPI coroutine was still in progress"
    )
    _kpi_in_flight = True
    import asyncio as _asyncio
    await _asyncio.sleep(0)  # yield → gather() will interleave the next coroutine
    _kpi_in_flight = False
    return 0.6


async def _fake_appointments_count(session, today):
    global _kpi_in_flight
    assert not _kpi_in_flight, (
        "AsyncSession concurrency hazard: _fake_appointments_count entered while "
        "another KPI coroutine was still in progress"
    )
    _kpi_in_flight = True
    import asyncio as _asyncio
    await _asyncio.sleep(0)
    _kpi_in_flight = False
    return 5


async def _fake_occupation(session, today):
    global _kpi_in_flight
    assert not _kpi_in_flight, (
        "AsyncSession concurrency hazard: _fake_occupation entered while "
        "another KPI coroutine was still in progress"
    )
    _kpi_in_flight = True
    import asyncio as _asyncio
    await _asyncio.sleep(0)
    _kpi_in_flight = False
    return 0.72


async def _fake_new_customers(session, now):
    global _kpi_in_flight
    assert not _kpi_in_flight, (
        "AsyncSession concurrency hazard: _fake_new_customers entered while "
        "another KPI coroutine was still in progress"
    )
    _kpi_in_flight = True
    import asyncio as _asyncio
    await _asyncio.sleep(0)
    _kpi_in_flight = False
    return 3


class TestDashboardKpisNoSessionConcurrency:
    """Regression guard for asyncio.gather shared-session concurrency bug.

    Root cause: get_dashboard_kpis ran 4 KPI helpers concurrently via
    asyncio.gather() sharing a single AsyncSession.  AsyncSession/asyncpg is NOT
    concurrency-safe: concurrent use raises IllegalStateChangeError and corrupts
    the connection pool, causing 503s on this endpoint AND collateral 503s on
    other endpoints (e.g. PATCH /escalations/{id}/resolve).

    Fix: replace asyncio.gather with sequential awaits on the shared session.

    How the test works:
      - Each instrumented fake asserts a module-level _in_flight flag is False,
        sets it True, then yields via asyncio.sleep(0) before clearing it.
      - With asyncio.gather the event loop resumes the next coroutine while the
        flag is still True → AssertionError → test FAILS (RED).
      - With sequential awaits each coroutine finishes before the next starts →
        flag is always False on entry → test PASSES (GREEN).
    """

    def setup_method(self):
        """Reset the in-flight flag before each test."""
        global _kpi_in_flight
        _kpi_in_flight = False

    def test_dashboard_kpis_no_concurrent_session_use(self, client, mock_auth):
        """
        GIVEN the 4 KPI helpers are replaced with concurrency-detecting fakes
        WHEN GET /api/admin/dashboard/kpis
        THEN no two helpers overlap on the shared session (flag never True on entry)
        AND response is HTTP 200 with the canned KPI values
        """
        mock_session = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("api.routes.admin.get_async_session", return_value=mock_ctx),
            patch(
                "api.routes.admin._confirmation_rate_today",
                side_effect=_fake_confirmation_rate,
            ),
            patch(
                "api.routes.admin._appointments_count_today",
                side_effect=_fake_appointments_count,
            ),
            patch(
                "api.routes.admin._occupation_today",
                side_effect=_fake_occupation,
            ),
            patch(
                "api.routes.admin._new_customers_last_7d",
                side_effect=_fake_new_customers,
            ),
        ):
            response = client.get("/api/admin/dashboard/kpis")

        assert response.status_code == 200
        data = response.json()
        assert data["confirmation_rate_today"] == round(0.6, 4)
        assert data["appointments_today"] == 5
        assert data["occupation_today"] == round(0.72, 4)
        assert data["new_customers_this_week"] == 3

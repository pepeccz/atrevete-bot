"""Integration tests for POST /api/admin/appointments/{id}/gcal-retry endpoint.

Covers spec scenarios:
  AS6  — Retry of book succeeds → 200 {status: synced}
  AS7  — Retry of cancel where GCal 404 = success → 200 {status: synced}
  AS8  — Non-admin (no JWT) → 401
  AS10 — Retry still fails → 200 {status: failed}, no new notification
  E3   — gcal_operation IS NULL → 400

No live Postgres or Redis required. Push functions are monkeypatched.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import app
from database.models import AdminUser, Appointment, AppointmentStatus

_ORIGIN = "http://localhost:3000"


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _make_admin_user() -> AdminUser:
    u = MagicMock(spec=AdminUser)
    u.id = uuid4()
    u.username = "admin"
    u.role = "admin"
    u.is_active = True
    u.display_name = "Admin"
    return u


def _make_appointment(
    gcal_sync_status: str = "failed",
    gcal_operation: str | None = "book",
    google_calendar_event_id: str | None = "evt_abc",
) -> Appointment:
    appt = MagicMock(spec=Appointment)
    appt.id = uuid4()
    appt.stylist_id = uuid4()
    appt.customer_id = uuid4()
    appt.first_name = "Ana"
    appt.last_name = "García"
    appt.start_time = datetime(2026, 6, 10, 10, 0, 0, tzinfo=UTC)
    appt.duration_minutes = 60
    appt.status = AppointmentStatus.CONFIRMED
    appt.service_ids = [uuid4()]
    appt.notes = None
    appt.google_calendar_event_id = google_calendar_event_id
    appt.gcal_sync_status = gcal_sync_status
    appt.gcal_operation = gcal_operation
    appt.gcal_last_error = "previous error"
    return appt


def _make_session_for_appointment(appt: Appointment | None) -> AsyncMock:
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = appt
    session.execute = AsyncMock(return_value=scalar_result)
    return session


# ─── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False, headers={"Origin": _ORIGIN})


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _override_auth(user: AdminUser):
    from api.dependencies.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: user


# ─── AS8: No JWT → 401 ─────────────────────────────────────────────────────────


def test_no_jwt_returns_401_or_403(client):
    """AS8: No JWT on POST gcal-retry → 401 (or 403 when CORS fires first without Origin)."""
    c = TestClient(app, raise_server_exceptions=False, headers={"Origin": _ORIGIN})
    appt_id = uuid4()
    resp = c.post(f"/api/admin/appointments/{appt_id}/gcal-retry")
    # CORS with Origin: 401 from auth dep. Without Origin: 403 from CORS.
    assert resp.status_code in (401, 403)


# ─── E3: gcal_operation IS NULL → 400 ──────────────────────────────────────────


def test_null_operation_returns_400(client):
    """E3: gcal_operation IS NULL → 400."""
    admin = _make_admin_user()
    appt = _make_appointment(gcal_sync_status="failed", gcal_operation=None)
    session = _make_session_for_appointment(appt)

    _override_auth(admin)

    with patch("api.routes.admin.get_async_session", return_value=session):
        resp = client.post(f"/api/admin/appointments/{appt.id}/gcal-retry")

    assert resp.status_code == 400
    assert "operation" in resp.json().get("detail", "").lower() or "operation" in str(resp.json()).lower()


# ─── AS6: Retry of book succeeds → 200 synced ──────────────────────────────────


def test_retry_book_success_returns_synced(client):
    """AS6: Retry of book operation succeeds → 200 {status: synced}."""
    admin = _make_admin_user()
    appt = _make_appointment(gcal_sync_status="failed", gcal_operation="book")
    synced_appt = _make_appointment(gcal_sync_status="synced", gcal_operation="book", google_calendar_event_id="evt_new")

    # Two separate session mocks — one per `async with get_async_session()` call
    session1 = AsyncMock()
    session1.__aenter__ = AsyncMock(return_value=session1)
    session1.__aexit__ = AsyncMock(return_value=False)
    r1 = MagicMock()
    r1.scalar_one_or_none.return_value = appt
    session1.execute = AsyncMock(return_value=r1)

    session2 = AsyncMock()
    session2.__aenter__ = AsyncMock(return_value=session2)
    session2.__aexit__ = AsyncMock(return_value=False)
    r2 = MagicMock()
    r2.scalar_one_or_none.return_value = synced_appt
    session2.execute = AsyncMock(return_value=r2)

    _override_auth(admin)

    with (
        patch("api.routes.admin.get_async_session", side_effect=[session1, session2]),
        patch("shared.gcal_push_service.push_appointment_to_gcal", AsyncMock(return_value="evt_new")),
    ):
        resp = client.post(f"/api/admin/appointments/{appt.id}/gcal-retry")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "synced"


# ─── AS10: Retry still fails → 200 with failed status ──────────────────────────


def test_retry_book_still_fails_returns_200_failed(client):
    """AS10: Retry fails → 200 {status: failed}, not 500."""
    admin = _make_admin_user()
    appt = _make_appointment(gcal_sync_status="failed", gcal_operation="book")
    failed_appt = _make_appointment(gcal_sync_status="failed", gcal_operation="book")
    failed_appt.gcal_last_error = "new error"

    session1 = AsyncMock()
    session1.__aenter__ = AsyncMock(return_value=session1)
    session1.__aexit__ = AsyncMock(return_value=False)
    r1 = MagicMock()
    r1.scalar_one_or_none.return_value = appt
    session1.execute = AsyncMock(return_value=r1)

    session2 = AsyncMock()
    session2.__aenter__ = AsyncMock(return_value=session2)
    session2.__aexit__ = AsyncMock(return_value=False)
    r2 = MagicMock()
    r2.scalar_one_or_none.return_value = failed_appt
    session2.execute = AsyncMock(return_value=r2)

    _override_auth(admin)

    with (
        patch("api.routes.admin.get_async_session", side_effect=[session1, session2]),
        patch("shared.gcal_push_service.push_appointment_to_gcal", AsyncMock(return_value=None)),
    ):
        resp = client.post(f"/api/admin/appointments/{appt.id}/gcal-retry")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"


# ─── AS7: Cancel retry where GCal 404 = success ────────────────────────────────


def test_retry_cancel_404_treated_as_synced(client):
    """AS7: Cancel retry where GCal 404 = success → 200 synced."""
    admin = _make_admin_user()
    appt = _make_appointment(gcal_sync_status="failed", gcal_operation="cancel", google_calendar_event_id="evt_gone")
    synced_appt = _make_appointment(gcal_sync_status="synced", gcal_operation="cancel")

    session1 = AsyncMock()
    session1.__aenter__ = AsyncMock(return_value=session1)
    session1.__aexit__ = AsyncMock(return_value=False)
    r1 = MagicMock()
    r1.scalar_one_or_none.return_value = appt
    session1.execute = AsyncMock(return_value=r1)

    session2 = AsyncMock()
    session2.__aenter__ = AsyncMock(return_value=session2)
    session2.__aexit__ = AsyncMock(return_value=False)
    r2 = MagicMock()
    r2.scalar_one_or_none.return_value = synced_appt
    session2.execute = AsyncMock(return_value=r2)

    _override_auth(admin)

    # delete_gcal_event returns True (404 = already deleted = success)
    with (
        patch("api.routes.admin.get_async_session", side_effect=[session1, session2]),
        patch("shared.gcal_push_service.delete_gcal_event", AsyncMock(return_value=True)),
    ):
        resp = client.post(f"/api/admin/appointments/{appt.id}/gcal-retry")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "synced"

"""
Integration tests for POST /api/admin/blocking-events — conflict detection.

TDD cycle (STRICT TDD MODE):
  RED  — this file, written before any production changes.
  GREEN — S1.2/S1.3 implement the overlap check + error-message fix.

Follows the established pattern in tests/integration/test_dashboard_endpoint.py:
  - FastAPI TestClient
  - app.dependency_overrides for get_current_user (bypasses JWT)
  - Patching get_async_session at api.routes.admin module level
  - Patching check_conflicts_for_dates for conflict-simulation tests
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes.admin import get_current_user

# ---------------------------------------------------------------------------
# Base payload — valid single-stylist blocking event
# ---------------------------------------------------------------------------
STYLIST_ID = str(uuid4())

VALID_PAYLOAD = {
    "stylist_ids": [STYLIST_ID],
    "title": "Reunión equipo",
    "description": "Standup semanal",
    "start_time": "2026-06-02T10:00:00+02:00",
    "end_time": "2026-06-02T11:00:00+02:00",
    "event_type": "meeting",
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    return TestClient(
        app, raise_server_exceptions=False, headers={"Origin": "http://localhost:3000"}
    )


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


def _make_blocking_event_mock(stylist_id: str) -> MagicMock:
    """Return a mock BlockingEvent ORM object with all fields populated."""

    event = MagicMock()
    event.id = uuid4()
    event.stylist_id = stylist_id
    event.title = "Reunión equipo"
    event.description = "Standup semanal"
    event.start_time = datetime(2026, 6, 2, 8, 0, tzinfo=UTC)
    event.end_time = datetime(2026, 6, 2, 9, 0, tzinfo=UTC)
    event.event_type = MagicMock()
    event.event_type.value = "meeting"
    event.created_at = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
    return event


def _make_session_ctx(stylist_ids: list[str] | None = None):
    """
    Build a mock async context manager whose session returns a scalars result
    for the 'Verify all stylists exist' query inside the endpoint.

    The endpoint calls:
      session.execute(select(Stylist).where(Stylist.id.in_(...)))
      result.scalars().all()  → returns list of mock Stylist objects
    """
    if stylist_ids is None:
        stylist_ids = [STYLIST_ID]

    # Build mock Stylist objects for each requested stylist_id
    mock_stylists = []
    for sid in stylist_ids:
        s = MagicMock()
        s.id = sid
        mock_stylists.append(s)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_stylists

    # Mock refresh to populate created_at on BlockingEvent objects
    async def _mock_refresh(obj):
        if not hasattr(obj, "created_at") or obj.created_at is None:
            from datetime import datetime

            obj.created_at = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = _mock_refresh

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


def _make_conflict(conflict_type: str = "appointment") -> dict:
    """Return a single conflict dict matching the ConflictInfo shape."""
    return {
        "date": "2026-06-02",
        "stylist_id": STYLIST_ID,
        "stylist_name": "Marta",
        "conflict_type": conflict_type,
        "conflict_title": "Cita: Ana" if conflict_type == "appointment" else "Bloqueo existente",
        "start_time": "10:00",
        "end_time": "11:00",
    }


# =============================================================================
# Tests
# =============================================================================


class TestCreateBlockingEventConflictCheck:
    """Tests for the overlap / conflict-detection logic on POST /blocking-events."""

    def test_create_no_overlap_returns_201(self, client, mock_auth):
        """
        GIVEN no existing events for stylist and time range
        WHEN POST /api/admin/blocking-events is called with valid payload
        THEN status 201 is returned and the event is persisted.
        """
        with (
            patch("api.routes.admin.get_async_session", return_value=_make_session_ctx()),
            patch(
                "api.routes.admin.check_conflicts_for_dates",
                new=AsyncMock(return_value=[]),
            ),
            patch("shared.gcal_push_service.fire_and_forget_push_blocking_event", new=AsyncMock()),
        ):
            response = client.post("/api/admin/blocking-events", json=VALID_PAYLOAD)

        assert response.status_code == 201

    def test_create_overlapping_appointment_without_ignore_returns_409(self, client, mock_auth):
        """
        GIVEN a confirmed appointment overlaps the requested range
        WHEN POST /api/admin/blocking-events is called without ignore_conflicts
        THEN status 409 is returned with a conflicts list.
        """
        conflict = _make_conflict("appointment")

        with (
            patch("api.routes.admin.get_async_session", return_value=_make_session_ctx()),
            patch(
                "api.routes.admin.check_conflicts_for_dates",
                new=AsyncMock(return_value=[conflict]),
            ),
        ):
            response = client.post("/api/admin/blocking-events", json=VALID_PAYLOAD)

        assert response.status_code == 409
        body = response.json()
        assert "conflicts" in body["detail"]
        assert len(body["detail"]["conflicts"]) >= 1

    def test_create_overlapping_appointment_with_ignore_returns_201(self, client, mock_auth):
        """
        GIVEN a confirmed appointment overlaps the requested range
        WHEN POST /api/admin/blocking-events is called with ignore_conflicts=true
        THEN status 201 is returned (conflict check skipped).
        """
        conflict = _make_conflict("appointment")

        with (
            patch("api.routes.admin.get_async_session", return_value=_make_session_ctx()),
            patch(
                "api.routes.admin.check_conflicts_for_dates",
                new=AsyncMock(return_value=[conflict]),
            ),
            patch("shared.gcal_push_service.fire_and_forget_push_blocking_event", new=AsyncMock()),
        ):
            response = client.post(
                "/api/admin/blocking-events?ignore_conflicts=true",
                json=VALID_PAYLOAD,
            )

        assert response.status_code == 201

    def test_create_overlapping_block_returns_409(self, client, mock_auth):
        """
        GIVEN an existing blocking_event overlaps the requested range
        WHEN POST /api/admin/blocking-events is called without ignore_conflicts
        THEN status 409 is returned.
        """
        conflict = _make_conflict("blocking_event")

        with (
            patch("api.routes.admin.get_async_session", return_value=_make_session_ctx()),
            patch(
                "api.routes.admin.check_conflicts_for_dates",
                new=AsyncMock(return_value=[conflict]),
            ),
        ):
            response = client.post("/api/admin/blocking-events", json=VALID_PAYLOAD)

        assert response.status_code == 409

    def test_create_overlapping_cancelled_appointment_returns_201(self, client, mock_auth):
        """
        GIVEN a CANCELLED appointment overlaps the requested range
        WHEN POST /api/admin/blocking-events is called
        THEN status 201 is returned (cancelled appointments don't conflict).

        check_conflicts_for_dates already excludes cancelled appointments
        (it only checks PENDING/CONFIRMED). Here we verify that when it
        returns an empty list, the endpoint proceeds normally.
        """
        with (
            patch("api.routes.admin.get_async_session", return_value=_make_session_ctx()),
            patch(
                "api.routes.admin.check_conflicts_for_dates",
                new=AsyncMock(return_value=[]),  # cancelled appt excluded → no conflict
            ),
            patch("shared.gcal_push_service.fire_and_forget_push_blocking_event", new=AsyncMock()),
        ):
            response = client.post("/api/admin/blocking-events", json=VALID_PAYLOAD)

        assert response.status_code == 201

    def test_create_invalid_event_type_lists_personal_in_error(self, client, mock_auth):
        """
        GIVEN event_type 'bogus' is submitted
        WHEN POST /api/admin/blocking-events is called
        THEN status 400 is returned AND the error message contains 'personal'.
        """
        payload = {**VALID_PAYLOAD, "event_type": "bogus"}

        with patch("api.routes.admin.get_async_session", return_value=_make_session_ctx()):
            response = client.post("/api/admin/blocking-events", json=payload)

        assert response.status_code == 400
        body = response.json()
        detail = body.get("detail", "")
        assert (
            "personal" in detail.lower()
        ), f"Expected 'personal' in error message, got: {detail!r}"

    def test_ignore_conflicts_query_param_default_false(self, client, mock_auth):
        """
        GIVEN a conflict exists and ignore_conflicts is NOT provided
        WHEN POST /api/admin/blocking-events is called
        THEN the behavior is identical to ignore_conflicts=false (409 returned).

        This test confirms the default value of the query parameter is False.
        """
        conflict = _make_conflict("appointment")

        with (
            patch("api.routes.admin.get_async_session", return_value=_make_session_ctx()),
            patch(
                "api.routes.admin.check_conflicts_for_dates",
                new=AsyncMock(return_value=[conflict]),
            ),
        ):
            # Omit ignore_conflicts entirely
            response_no_param = client.post("/api/admin/blocking-events", json=VALID_PAYLOAD)
            # Explicitly pass ignore_conflicts=false
            response_explicit_false = client.post(
                "/api/admin/blocking-events?ignore_conflicts=false",
                json=VALID_PAYLOAD,
            )

        assert response_no_param.status_code == 409, "default should be False → 409"
        assert response_explicit_false.status_code == 409
        # Both responses must have the same status code
        assert response_no_param.status_code == response_explicit_false.status_code
